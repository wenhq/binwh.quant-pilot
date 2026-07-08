"""技术指标 API — 优先读 indicator_values 表, 回退实时计算."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import delete, func, select

from app.database import AsyncSessionLocal
from app.models import (
    Etf,
    EtfDailyKline,
    Index,
    IndexDailyKline,
    IndicatorValue,
    Stock,
    StockDailyKline,
)
from app.services.indicators import adjust, macd, rsi, bollinger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/indicators", tags=["indicators"])


async def _load_klines(
    asset_type: str, code: str, limit: int = 120, adjust_mode: str = "forward"
) -> pd.DataFrame:
    """Load klines from DB into a DataFrame with OHLCV + adj_factor."""
    async with AsyncSessionLocal() as session:
        if asset_type == "etf":
            entity = (await session.execute(select(Etf).where(Etf.code == code))).scalar_one_or_none()
            if not entity:
                raise HTTPException(status_code=404, detail="ETF not found")
            rows = (
                await session.execute(
                    select(EtfDailyKline)
                    .where(EtfDailyKline.etf_id == entity.id)
                    .order_by(EtfDailyKline.trade_date.desc())
                    .limit(limit)
                )
            ).scalars().all()
        elif asset_type == "index":
            entity = (await session.execute(select(Index).where(Index.code == code))).scalar_one_or_none()
            if not entity:
                raise HTTPException(status_code=404, detail="Index not found")
            rows = (
                await session.execute(
                    select(IndexDailyKline)
                    .where(IndexDailyKline.index_id == entity.id)
                    .order_by(IndexDailyKline.trade_date.desc())
                    .limit(limit)
                )
            ).scalars().all()
        elif asset_type == "stock":
            entity = (await session.execute(select(Stock).where(Stock.code == code))).scalar_one_or_none()
            if not entity:
                raise HTTPException(status_code=404, detail="Stock not found")
            rows = (
                await session.execute(
                    select(StockDailyKline)
                    .where(StockDailyKline.stock_id == entity.id)
                    .order_by(StockDailyKline.trade_date.desc())
                    .limit(limit)
                )
            ).scalars().all()
        else:
            raise HTTPException(status_code=400, detail="asset_type must be etf/index/stock")

        if not rows:
            raise HTTPException(status_code=404, detail="No kline data")

        df = pd.DataFrame([{
            "trade_date": str(r.trade_date),
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": int(r.volume),
            "amount": float(r.amount) if r.amount else None,
            "adj_factor": float(r.adj_factor) if hasattr(r, "adj_factor") and r.adj_factor else None,
        } for r in rows])
        df = df.iloc[::-1].reset_index(drop=True)

    if adjust_mode != "none" and "adj_factor" in df.columns and df["adj_factor"].notna().any():
        df = adjust(df, adjust_mode)

    return df


async def _load_indicators(
    asset_type: str, code: str, limit: int = 120
) -> list[dict[str, Any]] | None:
    """Try loading indicators from indicator_values table. Returns None if empty."""
    async with AsyncSessionLocal() as session:
        q = (
            select(IndicatorValue)
            .where(
                IndicatorValue.asset_type == asset_type,
                IndicatorValue.code == code,
            )
            .order_by(IndicatorValue.trade_date.desc())
            .limit(limit)
        )
        rows = (await session.execute(q)).scalars().all()

    if not rows:
        return None

    return [
        {
            "trade_date": r.trade_date.isoformat(),
            "macd_dif": r.macd_dif,
            "macd_dea": r.macd_dea,
            "macd_hist": r.macd_hist,
            "rsi": r.rsi,
            "boll_upper": r.boll_upper,
            "boll_mid": r.boll_mid,
            "boll_lower": r.boll_lower,
            "keltner_upper": r.keltner_upper,
            "keltner_mid": r.keltner_mid,
            "keltner_lower": r.keltner_lower,
            "atr": r.atr,
        }
        for r in reversed(rows)
    ]


@router.get("/{asset_type}/{code}/macd")
async def get_macd(
    asset_type: str,
    code: str,
    limit: int = 120,
    adjust_mode: str = "forward",
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
):
    """Return MACD indicator (DIF/DEA/HIST) for the given asset."""
    ind = await _load_indicators(asset_type, code, limit)
    if ind:
        data = [
            {"trade_date": r["trade_date"], "dif": r["macd_dif"], "dea": r["macd_dea"], "hist": r["macd_hist"]}
            for r in ind
        ]
        return {"code": code, "indicator": "macd", "params": {"fast": fast, "slow": slow, "signal": signal}, "data": data, "source": "db"}

    df = await _load_klines(asset_type, code, limit, adjust_mode)
    m = macd(df["close"], fast=fast, slow=slow, signal=signal)
    data = [
        {"trade_date": df.loc[i, "trade_date"], "dif": round(m.loc[i, "dif"], 4), "dea": round(m.loc[i, "dea"], 4), "hist": round(m.loc[i, "hist"], 4)}
        for i in range(len(df))
    ]
    return {"code": code, "indicator": "macd", "params": {"fast": fast, "slow": slow, "signal": signal}, "data": data, "source": "realtime"}


@router.get("/{asset_type}/{code}/rsi")
async def get_rsi(
    asset_type: str,
    code: str,
    limit: int = 120,
    adjust_mode: str = "forward",
    period: int = 14,
):
    """Return RSI indicator for the given asset."""
    ind = await _load_indicators(asset_type, code, limit)
    if ind:
        data = [
            {"trade_date": r["trade_date"], "rsi": r["rsi"]}
            for r in ind
        ]
        return {"code": code, "indicator": "rsi", "params": {"period": period}, "data": data, "source": "db"}

    df = await _load_klines(asset_type, code, limit, adjust_mode)
    r = rsi(df["close"], period=period)
    data = [
        {"trade_date": df.loc[i, "trade_date"], "rsi": round(r.iloc[i], 2) if pd.notna(r.iloc[i]) else None}
        for i in range(len(df))
    ]
    return {"code": code, "indicator": "rsi", "params": {"period": period}, "data": data, "source": "realtime"}


@router.get("/{asset_type}/{code}/boll")
async def get_boll(
    asset_type: str,
    code: str,
    limit: int = 120,
    adjust_mode: str = "forward",
    period: int = 20,
    std_dev: float = 2.0,
):
    """Return Bollinger Bands for the given asset."""
    ind = await _load_indicators(asset_type, code, limit)
    if ind:
        data = [
            {
                "trade_date": r["trade_date"],
                "upper": r["boll_upper"],
                "mid": r["boll_mid"],
                "lower": r["boll_lower"],
            }
            for r in ind
        ]
        return {"code": code, "indicator": "boll", "params": {"period": period, "std_dev": std_dev}, "data": data, "source": "db"}

    df = await _load_klines(asset_type, code, limit, adjust_mode)
    b = bollinger(df["close"], period=period, std_dev=std_dev)
    data = [
        {
            "trade_date": df.loc[i, "trade_date"],
            "upper": round(b.loc[i, "upper"], 4) if pd.notna(b.loc[i, "upper"]) else None,
            "mid": round(b.loc[i, "mid"], 4) if pd.notna(b.loc[i, "mid"]) else None,
            "lower": round(b.loc[i, "lower"], 4) if pd.notna(b.loc[i, "lower"]) else None,
        }
        for i in range(len(df))
    ]
    return {"code": code, "indicator": "boll", "params": {"period": period, "std_dev": std_dev}, "data": data, "source": "realtime"}


@router.get("/{asset_type}/{code}/all")
async def get_all_indicators(
    asset_type: str,
    code: str,
    limit: int = 120,
    adjust_mode: str = "forward",
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    rsi_period: int = 14,
    boll_period: int = 20,
    boll_std: float = 2.0,
):
    """Return klines + all indicators in one call (for frontend chart rendering)."""
    ind = await _load_indicators(asset_type, code, limit)
    df = await _load_klines(asset_type, code, limit, adjust_mode)

    if ind:
        df_map = {r["trade_date"]: r for r in ind}
        data = []
        for i in range(len(df)):
            td = df.loc[i, "trade_date"]
            iv = df_map.get(td)
            data.append({
                "trade_date": td,
                "open": round(df.loc[i, "open"], 4),
                "high": round(df.loc[i, "high"], 4),
                "low": round(df.loc[i, "low"], 4),
                "close": round(df.loc[i, "close"], 4),
                "volume": int(df.loc[i, "volume"]),
                "macd_dif": iv["macd_dif"] if iv else None,
                "macd_dea": iv["macd_dea"] if iv else None,
                "macd_hist": iv["macd_hist"] if iv else None,
                "rsi": iv["rsi"] if iv else None,
                "boll_upper": iv["boll_upper"] if iv else None,
                "boll_mid": iv["boll_mid"] if iv else None,
                "boll_lower": iv["boll_lower"] if iv else None,
                "keltner_upper": iv["keltner_upper"] if iv else None,
                "keltner_mid": iv["keltner_mid"] if iv else None,
                "keltner_lower": iv["keltner_lower"] if iv else None,
                "atr": iv["atr"] if iv else None,
            })
        return {"code": code, "adjust_mode": adjust_mode, "data": data, "source": "db"}

    m = macd(df["close"], fast=macd_fast, slow=macd_slow, signal=macd_signal)
    r = rsi(df["close"], period=rsi_period)
    b = bollinger(df["close"], period=boll_period, std_dev=boll_std)
    k = keltner(df["close"], df["high"], df["low"])
    a = atr(df["high"], df["low"], df["close"])

    data = []
    for i in range(len(df)):
        data.append({
            "trade_date": df.loc[i, "trade_date"],
            "open": round(df.loc[i, "open"], 4),
            "high": round(df.loc[i, "high"], 4),
            "low": round(df.loc[i, "low"], 4),
            "close": round(df.loc[i, "close"], 4),
            "volume": int(df.loc[i, "volume"]),
            "macd_dif": round(m.loc[i, "dif"], 4) if pd.notna(m.loc[i, "dif"]) else None,
            "macd_dea": round(m.loc[i, "dea"], 4) if pd.notna(m.loc[i, "dea"]) else None,
            "macd_hist": round(m.loc[i, "hist"], 4) if pd.notna(m.loc[i, "hist"]) else None,
            "rsi": round(r.iloc[i], 2) if pd.notna(r.iloc[i]) else None,
            "boll_upper": round(b.loc[i, "upper"], 4) if pd.notna(b.loc[i, "upper"]) else None,
            "boll_mid": round(b.loc[i, "mid"], 4) if pd.notna(b.loc[i, "mid"]) else None,
            "boll_lower": round(b.loc[i, "lower"], 4) if pd.notna(b.loc[i, "lower"]) else None,
            "keltner_upper": round(k.loc[i, "upper"], 4) if pd.notna(k.loc[i, "upper"]) else None,
            "keltner_mid": round(k.loc[i, "mid"], 4) if pd.notna(k.loc[i, "mid"]) else None,
            "keltner_lower": round(k.loc[i, "lower"], 4) if pd.notna(k.loc[i, "lower"]) else None,
            "atr": round(a.iloc[i], 4) if pd.notna(a.iloc[i]) else None,
        })

    return {
        "code": code,
        "adjust_mode": adjust_mode,
        "data": data,
        "source": "realtime",
    }
