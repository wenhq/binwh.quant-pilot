"""定时任务 — 每个交易日 15:05 CST 自动增量同步行情 + 重算指标."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import delete, func, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Etf, EtfDailyKline, Index, IndexDailyKline, IndicatorValue
from app.services.data.universe import CORE_ETF, SECTOR_ETF, CORE_INDICES
from app.services.indicators import adjust, macd, rsi, bollinger, keltner, atr

logger = logging.getLogger(__name__)

# 上海时区偏移 (UTC+8)
_SH_TZ_OFFSET = timedelta(hours=8)
_SYNC_HOUR = 15
_SYNC_MINUTE = 5
_RETRY_INTERVAL = timedelta(minutes=30)


def _next_sync_shanghai(now: datetime) -> datetime:
    """计算下一个同步时间 (上海时间 15:05)."""
    sh_now = now + _SH_TZ_OFFSET
    target = datetime.combine(sh_now.date(), time(_SYNC_HOUR, _SYNC_MINUTE))
    if sh_now.time() >= time(_SYNC_HOUR, _SYNC_MINUTE):
        target += timedelta(days=1)
    # 跳过周末
    while target.weekday() >= 5:
        target += timedelta(days=1)
    return target - _SH_TZ_OFFSET


# ----- 指标计算 -----


def _calc_indicators(df: pd.DataFrame, adjust_mode: str) -> pd.DataFrame:
    """Apply adjustment + compute all indicators."""
    if adjust_mode != "none" and "adj_factor" in df.columns and df["adj_factor"].notna().any():
        df = adjust(df, adjust_mode)

    m = macd(df["close"])
    r = rsi(df["close"])
    b = bollinger(df["close"])
    k = keltner(df["close"], df["high"], df["low"])

    df["macd_dif"] = m["dif"]
    df["macd_dea"] = m["dea"]
    df["macd_hist"] = m["hist"]
    df["rsi"] = r
    df["boll_upper"] = b["upper"]
    df["boll_mid"] = b["mid"]
    df["boll_lower"] = b["lower"]
    df["keltner_upper"] = k["upper"]
    df["keltner_mid"] = k["mid"]
    df["keltner_lower"] = k["lower"]
    df["atr"] = atr(df["high"], df["low"], df["close"])
    return df


# ----- 增量辅助函数 -----


async def _get_last_trade_date(session, asset_type: str, entity_id: int) -> date | None:
    """取 kline 表最新 trade_date."""
    if asset_type == "etf":
        row = await session.execute(
            select(func.max(EtfDailyKline.trade_date)).where(EtfDailyKline.etf_id == entity_id)
        )
    elif asset_type == "index":
        row = await session.execute(
            select(func.max(IndexDailyKline.trade_date)).where(IndexDailyKline.index_id == entity_id)
        )
    else:
        return None
    return row.scalar_one_or_none()


async def _filter_new_rows(session, df: pd.DataFrame, asset_type: str, entity_id: int) -> pd.DataFrame:
    """过滤掉已在库中的 trade_date, 只保留增量."""
    if df.empty:
        return df
    last_date = await _get_last_trade_date(session, asset_type, entity_id)
    if last_date is None:
        return df
    return df[df["trade_date"] > last_date].reset_index(drop=True)


# ----- 增量同步核心逻辑 -----


async def _fetch_latest_klines(asset_type: str, code: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """从数据源拉取 kline 数据 (支持增量 start)."""
    from app.services.data.registry import default_registry

    registry = default_registry()
    loop = asyncio.get_running_loop()
    try:
        if asset_type == "etf":
            result = await loop.run_in_executor(None, lambda: registry.fetch_etf_daily(code, start, end))
        elif asset_type == "index":
            result = await loop.run_in_executor(None, lambda: registry.fetch_index_daily(code, start, end))
        else:
            return pd.DataFrame()
    except Exception as e:
        logger.warning("fetch failed %s %s: %s", asset_type, code, e)
        return pd.DataFrame()

    if result.df is None or result.df.empty:
        return pd.DataFrame()

    df = result.df.copy()
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df


async def _upsert_klines(session, asset_type: str, entity_id: int, df: pd.DataFrame) -> int:
    """Upsert klines into appropriate table. Returns rows written."""
    from sqlalchemy.dialects.mysql import insert as mysql_insert

    if df.empty:
        return 0

    if asset_type == "etf":
        table = EtfDailyKline.__table__
        asset_col = "etf_id"
    elif asset_type == "index":
        table = IndexDailyKline.__table__
        asset_col = "index_id"
    else:
        return 0

    valid_cols = {c for c in (asset_col, "trade_date", "open", "close", "high",
                              "low", "volume", "amount", "adj_factor") if c in table.c}
    rows = []
    insert_col_set: set[str] = set()
    for _, r in df.iterrows():
        trade_date = r.get("trade_date")
        if isinstance(trade_date, str):
            trade_date = pd.to_datetime(trade_date).date()
        row = {asset_col: entity_id, "trade_date": trade_date}
        insert_col_set.update({asset_col, "trade_date"})
        for c in ("open", "close", "high", "low"):
            if c in valid_cols:
                row[c] = float(r[c])
                insert_col_set.add(c)
        if "volume" in valid_cols:
            row["volume"] = int(r.get("volume") or 0)
            insert_col_set.add("volume")
        if "amount" in valid_cols and pd.notna(r.get("amount")):
            row["amount"] = float(r["amount"])
            insert_col_set.add("amount")
        if "adj_factor" in valid_cols and pd.notna(r.get("adj_factor")):
            row["adj_factor"] = float(r["adj_factor"])
            insert_col_set.add("adj_factor")
        rows.append(row)

    if not rows:
        return 0

    stmt = mysql_insert(table).values(rows)
    update_cols = {c: stmt.inserted[c] for c in insert_col_set if c not in (asset_col, "trade_date")}
    stmt = stmt.on_duplicate_key_update(update_cols)
    await session.execute(stmt)
    return len(rows)


async def _recalc_indicators(session, asset_type: str, entity_id: int, code: str, adjust_mode: str) -> int:
    """Query all klines for entity, recalc all indicators, upsert into indicator_values."""
    if asset_type == "etf":
        rows = (
            await session.execute(
                select(EtfDailyKline)
                .where(EtfDailyKline.etf_id == entity_id)
                .order_by(EtfDailyKline.trade_date.asc())
            )
        ).scalars().all()
    elif asset_type == "index":
        rows = (
            await session.execute(
                select(IndexDailyKline)
                .where(IndexDailyKline.index_id == entity_id)
                .order_by(IndexDailyKline.trade_date.asc())
            )
        ).scalars().all()
    else:
        return 0

    if not rows:
        return 0

    df = pd.DataFrame([{
        "trade_date": row.trade_date,
        "open": float(row.open),
        "high": float(row.high),
        "low": float(row.low),
        "close": float(row.close),
        "volume": int(row.volume),
        "amount": float(row.amount) if row.amount else None,
        "adj_factor": float(row.adj_factor) if getattr(row, "adj_factor", None) else None,
    } for row in rows])

    df = _calc_indicators(df, adjust_mode)
    df = df.dropna(subset=["macd_dif", "rsi", "boll_upper", "keltner_upper", "atr"], how="all")
    if df.empty:
        return 0

    await session.execute(delete(IndicatorValue).where(
        IndicatorValue.asset_type == asset_type,
        IndicatorValue.code == code,
    ))

    records = []
    for _, row in df.iterrows():
        records.append({
            "asset_type": asset_type,
            "code": code,
            "trade_date": row["trade_date"],
            "macd_dif": round(row["macd_dif"], 6) if pd.notna(row.get("macd_dif")) else None,
            "macd_dea": round(row["macd_dea"], 6) if pd.notna(row.get("macd_dea")) else None,
            "macd_hist": round(row["macd_hist"], 6) if pd.notna(row.get("macd_hist")) else None,
            "rsi": round(row["rsi"], 4) if pd.notna(row.get("rsi")) else None,
            "boll_upper": round(row["boll_upper"], 6) if pd.notna(row.get("boll_upper")) else None,
            "boll_mid": round(row["boll_mid"], 6) if pd.notna(row.get("boll_mid")) else None,
            "boll_lower": round(row["boll_lower"], 6) if pd.notna(row.get("boll_lower")) else None,
            "keltner_upper": round(row["keltner_upper"], 6) if pd.notna(row.get("keltner_upper")) else None,
            "keltner_mid": round(row["keltner_mid"], 6) if pd.notna(row.get("keltner_mid")) else None,
            "keltner_lower": round(row["keltner_lower"], 6) if pd.notna(row.get("keltner_lower")) else None,
            "atr": round(row["atr"], 6) if pd.notna(row.get("atr")) else None,
        })

    session.add_all([IndicatorValue(**r) for r in records])
    return len(records)


# ----- 每日同步任务 -----


async def _run_daily_sync() -> None:
    """执行一次完整同步: ETF + Index 增量更新 + 指标重算."""
    logger.info("Daily sync started at %s", datetime.now())

    etf_codes = [e["code"] for e in CORE_ETF + SECTOR_ETF]
    index_codes = [i["code"] for i in CORE_INDICES]

    async with AsyncSessionLocal() as session:
        etf_map = {row[0]: row[1] for row in (await session.execute(select(Etf.code, Etf.id))).all()}
        idx_map = {row[0]: row[1] for row in (await session.execute(select(Index.code, Index.id))).all()}

    etf_done = 0
    for code in etf_codes:
        if code not in etf_map:
            continue
        etf_id = etf_map[code]
        async with AsyncSessionLocal() as session:
            last_date = await _get_last_trade_date(session, "etf", etf_id)
            start = last_date + timedelta(days=1) if last_date else None
            df = await _fetch_latest_klines("etf", code, start, None)
            if df.empty:
                continue
            # 过滤掉已有日期 (防止 registry 返回历史数据覆盖)
            df = await _filter_new_rows(session, df, "etf", etf_id)
            if df.empty:
                continue
            n_k = await _upsert_klines(session, "etf", etf_id, df)
            if n_k > 0:
                n_i = await _recalc_indicators(session, "etf", etf_id, code, "forward")
                await session.commit()
                logger.info("ETF %s: %d klines upserted, %d indicators recalculated", code, n_k, n_i)
                etf_done += 1

    index_done = 0
    for code in index_codes:
        if code not in idx_map:
            continue
        idx_id = idx_map[code]
        async with AsyncSessionLocal() as session:
            last_date = await _get_last_trade_date(session, "index", idx_id)
            start = last_date + timedelta(days=1) if last_date else None
            df = await _fetch_latest_klines("index", code, start, None)
            if df.empty:
                continue
            df = await _filter_new_rows(session, df, "index", idx_id)
            if df.empty:
                continue
            n_k = await _upsert_klines(session, "index", idx_id, df)
            if n_k > 0:
                n_i = await _recalc_indicators(session, "index", idx_id, code, "none")
                await session.commit()
                logger.info("Index %s: %d klines upserted, %d indicators recalculated", code, n_k, n_i)
                index_done += 1

    logger.info("Daily sync completed: %d ETFs, %d indices updated", etf_done, index_done)


# ----- 后台调度循环 -----


async def _scheduler_loop() -> None:
    """后台任务: 每个交易日上海时间 15:05 执行同步."""
    logger.info("Scheduler loop started")
    while True:
        now = datetime.now()
        next_sync = _next_sync_shanghai(now)
        wait_seconds = (next_sync - now).total_seconds()
        logger.info("Next sync scheduled at %s (in %.1f hours)", next_sync, wait_seconds / 3600)

        try:
            await asyncio.sleep(wait_seconds)
            await _run_daily_sync()
        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled")
            break
        except Exception as e:
            logger.error("Sync failed: %s. Retrying in %s", e, _RETRY_INTERVAL)
            await asyncio.sleep(_RETRY_INTERVAL.total_seconds())


_scheduler_task: asyncio.Task | None = None


def start_scheduler() -> None:
    """在 FastAPI startup 事件中调用."""
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_scheduler_loop())
        logger.info("Market sync scheduler started")


def stop_scheduler() -> None:
    """在 FastAPI shutdown 事件中调用."""
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        logger.info("Market sync scheduler stopped")
