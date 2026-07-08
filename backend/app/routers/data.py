import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, AsyncSessionLocal
from app.models import Stock, StockDailyKline, Index, IndexDailyKline, Etf, EtfDailyKline
from app.services.data.akshare_client import fetch_stock_daily, fetch_stock_info
from app.services.data.normalizer import normalize_daily

router = APIRouter(prefix="/data", tags=["data"])
_executor = ThreadPoolExecutor(max_workers=2)


@router.post("/sync/{stock_code:str}")
async def sync_stock(stock_code: str):
    """
    Fetch daily kline from akshare and persist to MySQL.
    If stock not in DB, auto-register with basic info.
    """
    async with AsyncSessionLocal() as session:
        # Ensure stock exists
        result = await session.execute(select(Stock).where(Stock.code == stock_code))
        stock = result.scalar_one_or_none()
        if not stock:
            info = await asyncio.get_event_loop().run_in_executor(
                _executor, fetch_stock_info, stock_code
            )
            stock = Stock(code=stock_code, name=info.get("name"), market=info.get("market"))
            session.add(stock)
            await session.commit()
            await session.refresh(stock)

        # Fetch kline data in thread pool (akshare is synchronous)
        raw_df = await asyncio.get_event_loop().run_in_executor(
            _executor, fetch_stock_daily, stock_code
        )
        if raw_df.empty:
            return {"stock_code": stock_code, "synced": 0, "message": "No data returned"}

        df = normalize_daily(raw_df)

        # Upsert klines
        for _, row in df.iterrows():
            kline = StockDailyKline(
                stock_id=stock.id,
                trade_date=row["trade_date"],
                open=row["open"],
                close=row["close"],
                high=row["high"],
                low=row["low"],
                volume=int(row["volume"]),
                amount=row.get("amount"),
                adj_factor=None,  # original unadjusted
            )
            await session.merge(kline)

        await session.commit()

    return {"stock_code": stock_code, "synced": len(df)}


@router.get("/stock/{stock_code:str}/daily")
async def get_daily_klines(stock_code: str, limit: int = 100):
    """Return daily klines for a stock from MySQL."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Stock).where(Stock.code == stock_code))
        stock = result.scalar_one_or_none()
        if not stock:
            raise HTTPException(status_code=404, detail="Stock not found")

        klines = await session.execute(
            select(StockDailyKline)
            .where(StockDailyKline.stock_id == stock.id)
            .order_by(StockDailyKline.trade_date.desc())
            .limit(limit)
        )
        data = [
            {
                "trade_date": str(k.trade_date),
                "open": float(k.open),
                "close": float(k.close),
                "high": float(k.high),
                "low": float(k.low),
                "volume": k.volume,
                "amount": float(k.amount) if k.amount else None,
            }
            for k in klines.scalars().all()
        ]
        return {"stock_code": stock.code, "name": stock.name, "data": data[::-1]}


# ----- U6: 批量导入 / 重试 / 进度 -----

_bg_tasks: dict[str, asyncio.Task] = {}


@router.post("/import/batch")
async def import_batch(background: bool = True):
    """限速并发导入整个 universe (沪深300个股 + 核心指数/ETF). 默认后台跑."""
    from app.services.data.importer import run_import
    if background:
        task = asyncio.create_task(run_import(AsyncSessionLocal))
        _bg_tasks["batch"] = task
        return {"status": "started", "background": True, "hint": "GET /data/import/progress"}
    prog = await run_import(AsyncSessionLocal)
    return prog.to_dict()


@router.post("/import/retry")
async def import_retry(background: bool = True):
    """重试 import_errors 中 retried_at IS NULL 的标的."""
    from app.services.data.importer import retry_errors
    if background:
        task = asyncio.create_task(retry_errors(AsyncSessionLocal))
        _bg_tasks["retry"] = task
        return {"status": "started", "background": True}
    prog = await retry_errors(AsyncSessionLocal)
    return prog.to_dict()


@router.get("/import/progress")
async def import_progress():
    """轮询导入进度 (含最近失败列表)."""
    from app.services.data.importer import get_progress
    return get_progress().to_dict()


# ----- U7: 指数 / ETF 查询接口 -----


@router.get("/index/{index_code:str}/daily")
async def get_index_klines(index_code: str, limit: int = 120):
    """Return daily klines for an index from MySQL."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Index).where(Index.code == index_code))
        index = result.scalar_one_or_none()
        if not index:
            raise HTTPException(status_code=404, detail="Index not found")
        klines = await session.execute(
            select(IndexDailyKline)
            .where(IndexDailyKline.index_id == index.id)
            .order_by(IndexDailyKline.trade_date.desc())
            .limit(limit)
        )
        data = [
            {
                "trade_date": str(k.trade_date),
                "open": float(k.open),
                "close": float(k.close),
                "high": float(k.high),
                "low": float(k.low),
                "volume": k.volume,
                "amount": float(k.amount) if k.amount else None,
            }
            for k in klines.scalars().all()
        ]
        return {"index_code": index.code, "name": index.name, "data": data[::-1]}


@router.get("/etf/{etf_code:str}/daily")
async def get_etf_klines(etf_code: str, limit: int = 120):
    """Return daily klines for an ETF from MySQL."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Etf).where(Etf.code == etf_code))
        etf = result.scalar_one_or_none()
        if not etf:
            raise HTTPException(status_code=404, detail="ETF not found")
        klines = await session.execute(
            select(EtfDailyKline)
            .where(EtfDailyKline.etf_id == etf.id)
            .order_by(EtfDailyKline.trade_date.desc())
            .limit(limit)
        )
        data = [
            {
                "trade_date": str(k.trade_date),
                "open": float(k.open),
                "close": float(k.close),
                "high": float(k.high),
                "low": float(k.low),
                "volume": k.volume,
                "amount": float(k.amount) if k.amount else None,
                "adj_factor": float(k.adj_factor) if k.adj_factor else None,
            }
            for k in klines.scalars().all()
        ]
        return {"etf_code": etf.code, "name": etf.name, "tracks": etf.tracks, "data": data[::-1]}


@router.get("/etfs")
async def list_etfs():
    """List all ETFs with latest close and change."""
    async with AsyncSessionLocal() as session:
        etfs = (await session.execute(select(Etf))).scalars().all()
        result = []
        for etf in etfs:
            latest = (
                await session.execute(
                    select(EtfDailyKline)
                    .where(EtfDailyKline.etf_id == etf.id)
                    .order_by(EtfDailyKline.trade_date.desc())
                    .limit(2)
                )
            ).scalars().all()
            if not latest:
                continue
            close = float(latest[0].close)
            prev = float(latest[1].close) if len(latest) > 1 else close
            change_pct = ((close - prev) / prev * 100) if prev else 0
            result.append({
                "code": etf.code,
                "name": etf.name,
                "tracks": etf.tracks,
                "latest_close": close,
                "change_pct": round(change_pct, 2),
            })
        return {"etfs": result}
