"""U6: 限速分批导入器 + 断点续传.

流程:
1. 从 universe 拿标的 (沪深300个股 + 核心指数/ETF + 宏观代理).
2. 对每个标的: registry 取数 → upsert 元数据行 → upsert 日线 (UNIQUE 防重).
3. asyncio.Semaphore(concurrency) 控并发 + 每次取数后 sleep(rate) 避免封 IP.
4. 取数失败/空 → 写 import_errors (code+asset_type+source+msg), retried_at IS NULL 供重试.
5. 进度通过 progress dict + 日志暴露 (供 status 端点轮询).

akshare/guosen 是同步阻塞库 → run_in_executor 包装.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.etf import Etf, EtfDailyKline
from app.models.import_log import ImportError
from app.models.index import Index, IndexDailyKline
from app.models.instrument import Instrument
from app.models.stock import Stock, StockDailyKline
from app.services.data.registry import DataSourceRegistry, default_registry
from app.services.data.universe import Universe, build_universe

logger = logging.getLogger(__name__)


@dataclass
class ImportProgress:
    """导入进度 (供 status 端点). 进程内单例, 不持久化."""

    total: int = 0
    done: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0  # 取到空 df 但没报错
    last_code: str | None = None
    last_source: str | None = None
    running: bool = False
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "done": self.done,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "last_code": self.last_code,
            "last_source": self.last_source,
            "running": self.running,
            "recent_errors": self.errors[-20:],
        }


# 进程级单例进度 (单导入任务场景足够).
_progress = ImportProgress()


def get_progress() -> ImportProgress:
    return _progress


def reset_progress() -> None:
    global _progress
    _progress = ImportProgress()


# ----- 元数据 upsert (按 code) -----


async def _upsert_stock(session: AsyncSession, code: str, name: str | None, market: str | None) -> Stock:
    row = (await session.execute(select(Stock).where(Stock.code == code))).scalar_one_or_none()
    if row:
        if name and row.name != name:
            row.name = name
        if market and row.market != market:
            row.market = market
        return row
    stock = Stock(code=code, name=name, market=market)
    session.add(stock)
    await session.flush()
    return stock


async def _upsert_index(session: AsyncSession, code: str, name: str | None, market: str | None) -> Index:
    row = (await session.execute(select(Index).where(Index.code == code))).scalar_one_or_none()
    if row:
        return row
    obj = Index(code=code, name=name, market=market)
    session.add(obj)
    await session.flush()
    return obj


async def _upsert_etf(session: AsyncSession, code: str, name: str | None, tracks: str | None) -> Etf:
    row = (await session.execute(select(Etf).where(Etf.code == code))).scalar_one_or_none()
    if row:
        return row
    obj = Etf(code=code, name=name, tracks=tracks)
    session.add(obj)
    await session.flush()
    return obj


async def _upsert_instrument(session: AsyncSession, task: dict, source_hit: str) -> None:
    """把标的字典元数据 upsert 进 instruments (统一代码目录).

    code 为主键: 已存在则更新分类/源/跟踪关系; 不存在则插入.
    MySQL 走 INSERT ... ON DUPLICATE KEY; SQLite (测试) 走 select+update/insert.
    data_source 优先用 universe 配置, 没有时回填实际命中源.
    """
    code = task["code"]
    if getattr(session, "bind", None) is None:
        return  # 无真实 engine 绑定 (编排测试用 null session) — 字典写入跳过
    data_source = task.get("data_source") or source_hit or ""
    values = dict(
        code=code,
        name=task.get("name"),
        asset_type=task["asset_type"],
        market=task.get("market"),
        category=task.get("category"),
        data_source=data_source,
        tracks_index=task.get("tracks"),
    )
    dialect = session.bind.dialect.name if session.bind else "sqlite"
    if dialect == "mysql":
        from sqlalchemy.dialects.mysql import insert as mysql_insert
        stmt = mysql_insert(Instrument).values(values)
        stmt = stmt.on_duplicate_key_update({
            "name": stmt.inserted.name,
            "asset_type": stmt.inserted.asset_type,
            "market": stmt.inserted.market,
            "category": stmt.inserted.category,
            "data_source": stmt.inserted.data_source,
            "tracks_index": stmt.inserted.tracks_index,
        })
        await session.execute(stmt)
    else:
        # SQLite (测试): select + update/insert
        row = (await session.execute(select(Instrument).where(Instrument.code == code))).scalar_one_or_none()
        if row:
            for k, v in values.items():
                if k != "code":
                    setattr(row, k, v)
        else:
            session.add(Instrument(**values))


# ----- 日线批量 upsert (MySQL ON DUPLICATE KEY UPDATE) -----


async def _bulk_upsert_klines(
    session: AsyncSession,
    table,
    asset_id_col: str,
    asset_id: int,
    df: pd.DataFrame,
) -> int:
    """把归一化 df upsert 进对应日线表. 返回写入行数.

    table 为模型类 (StockDailyKline 等), 取其 .__table__. 只写 table 实际拥有的列
    (indices 无 adj_factor, funds 无 OHLCV 走单独路径).
    """
    if df is None or df.empty:
        return 0
    table_obj = table.__table__ if hasattr(table, "__table__") else table
    col_names = [c.name for c in table_obj.c]
    valid_cols = {c for c in col_names if c in (asset_id_col, "trade_date", "open", "close", "high",
                              "low", "volume", "amount", "adj_factor")}
    rows = []
    insert_col_set: set[str] = set()
    for _, r in df.iterrows():
        trade_date = r.get("trade_date")
        if isinstance(trade_date, str):
            trade_date = pd.to_datetime(trade_date).date()
        row = {asset_id_col: asset_id, "trade_date": trade_date}
        insert_col_set.update({asset_id_col, "trade_date"})
        for c in ("open", "close", "high", "low"):
            if c in valid_cols:
                row[c] = float(r[c])
                insert_col_set.add(c)
        if "volume" in valid_cols:
            row["volume"] = int(r.get("volume") or 0)
            insert_col_set.add("volume")
        if "amount" in valid_cols:
            val = r.get("amount")
            row["amount"] = float(val) if pd.notna(val) else None
            insert_col_set.add("amount")
        if "adj_factor" in valid_cols:
            val = r.get("adj_factor")
            row["adj_factor"] = float(val) if pd.notna(val) else None
            insert_col_set.add("adj_factor")
        rows.append(row)
    if not rows:
        return 0
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Bulk upsert: table=%s, rows=%d, valid_cols=%s", table_obj.name, len(rows), sorted(valid_cols))
    if rows:
        logger.info("Sample row keys: %s", sorted(rows[0].keys()))
    
    stmt = mysql_insert(table_obj).values(rows)
    update_cols = {c: stmt.inserted[c] for c in insert_col_set
                   if c not in (asset_id_col, "trade_date")}
    stmt = stmt.on_duplicate_key_update(update_cols)
    try:
        result = await session.execute(stmt)
        logger.info("Insert executed: rowcount=%s", result.rowcount)
    except Exception as e:
        logger.error("Insert failed: %s", e, exc_info=True)
        raise
    return len(rows)


# ----- 单标的取数 (线程池执行同步 fetch) -----


async def _fetch_async(loop, registry: DataSourceRegistry, method: str, *args, **kwargs):
    """在线程池跑 registry 的同步方法 (akshare/guosen 阻塞)."""
    fn = getattr(registry, method)
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


async def _import_one(
    session: AsyncSession,
    registry: DataSourceRegistry,
    asset_type: str,
    code: str,
    *,
    market: str | None = None,
    name: str | None = None,
    tracks: str | None = None,
) -> tuple[str, int]:
    """导入单个标的. 返回 (命中的 source, 写入行数). 失败抛异常由调用方记 import_errors."""
    loop = asyncio.get_running_loop()
    if asset_type == "stock":
        result = await _fetch_async(loop, registry, "fetch_stock_daily", code, market or "A")
        stock = await _upsert_stock(session, code, name, market)
        n = await _bulk_upsert_klines(session, StockDailyKline, "stock_id", stock.id, result.df)
    elif asset_type == "index":
        result = await _fetch_async(loop, registry, "fetch_index_daily", code)
        idx = await _upsert_index(session, code, name, market)
        n = await _bulk_upsert_klines(session, IndexDailyKline, "index_id", idx.id, result.df)
    elif asset_type == "etf":
        result = await _fetch_async(loop, registry, "fetch_etf_daily", code)
        etf = await _upsert_etf(session, code, name, tracks)
        n = await _bulk_upsert_klines(session, EtfDailyKline, "etf_id", etf.id, result.df)
    else:
        raise ValueError(f"unknown asset_type {asset_type}")
    return result.source, n


# ----- 主导入流程 -----


async def run_import(
    session_factory,
    universe: Universe | None = None,
    *,
    registry: DataSourceRegistry | None = None,
    concurrency: int | None = None,
    rate_seconds: float | None = None,
) -> ImportProgress:
    """限速并发导入整个 universe. session_factory: async callable → AsyncSession."""
    from app.config import settings

    universe = universe or build_universe()
    registry = registry or default_registry()
    concurrency = concurrency or settings.import_concurrency
    rate = rate_seconds if rate_seconds is not None else settings.import_rate_seconds

    reset_progress()
    prog = get_progress()
    prog.running = True

    # 展平成统一任务列表.
    tasks: list[dict] = []
    for s in universe.stocks:
        tasks.append({"asset_type": "stock", "code": s["code"], "market": s["market"], "name": s.get("name")})
    for i in universe.indices:
        tasks.append({"asset_type": "index", "code": i["code"], "market": i.get("market"), "name": i.get("name"),
                       "category": i.get("category"), "data_source": i.get("data_source")})
    for e in universe.etfs:
        tasks.append({"asset_type": "etf", "code": e["code"], "name": e.get("name"), "tracks": e.get("tracks"),
                       "category": e.get("category"), "data_source": e.get("data_source")})
    prog.total = len(tasks)

    sem = asyncio.Semaphore(concurrency)

    async def handle(task: dict) -> None:
        async with sem:
            await _import_task(session_factory, registry, task, rate)

    await asyncio.gather(*(handle(t) for t in tasks))
    prog.running = False
    return prog


async def _import_task(session_factory, registry: DataSourceRegistry, task: dict, rate: float) -> None:
    """单个标的导入任务: 取数 → 写库 → 记错误 → 更新进度 → sleep 限速."""
    prog = get_progress()
    loop = asyncio.get_running_loop()
    asset_type = task["asset_type"]
    code = task["code"]
    try:
        async with session_factory() as session:
            source, n = await _import_one(
                session, registry, asset_type, code,
                market=task.get("market"),
                name=task.get("name"),
                tracks=task.get("tracks"),
            )
            await _upsert_instrument(session, task, source)
            await session.commit()
        prog.done += 1
        prog.last_code = code
        prog.last_source = source
        if n > 0:
            prog.succeeded += 1
        else:
            prog.skipped += 1  # 取到空 df (可能源端无该标的), 不算失败
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"[:500]
        logger.warning("import failed %s %s: %s", asset_type, code, msg)
        prog.done += 1
        prog.failed += 1
        prog.errors.append({"asset_type": asset_type, "code": code, "error": msg})
        async with session_factory() as session:
            session.add(ImportError(
                asset_type=asset_type, code=code, source=task.get("source"), error_msg=msg,
            ))
            await session.commit()
    finally:
        # 限速: 每次取数后 sleep, 避免高频触发反爬封 IP.
        if rate > 0:
            await asyncio.sleep(rate)


async def retry_errors(session_factory, registry: DataSourceRegistry | None = None) -> ImportProgress:
    """重试 import_errors 中 retried_at IS NULL 的标的."""
    registry = registry or default_registry()
    reset_progress()
    prog = get_progress()
    prog.running = True

    async with session_factory() as session:
        rows = (await session.execute(
            select(ImportError).where(ImportError.retried_at.is_(None))
        )).scalars().all()

    tasks = [{"asset_type": r.asset_type, "code": r.code, "source": r.source,
              "market": None, "name": None, "tracks": None, "_err_id": r.id} for r in rows]
    prog.total = len(tasks)

    sem = asyncio.Semaphore(2)
    from app.config import settings

    async def handle(task: dict) -> None:
        async with sem:
            await _import_task(session_factory, registry, task, settings.import_rate_seconds)
            # 标记该错误已重试.
            async with session_factory() as s:
                err = await s.get(ImportError, task["_err_id"])
                if err:
                    err.retried_at = datetime.now()
                    await s.commit()

    await asyncio.gather(*(handle(t) for t in tasks))
    prog.running = False
    return prog


__all__ = ["ImportProgress", "run_import", "retry_errors", "get_progress", "reset_progress"]
