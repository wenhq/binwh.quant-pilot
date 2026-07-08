"""Backfill indicator_values from kline data for all ETFs + indices."""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Sequence

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.database import AsyncSessionLocal, init_db
from app.models import Etf, EtfDailyKline, Index, IndexDailyKline, IndicatorValue
from app.services.data.universe import CORE_ETF, SECTOR_ETF, CORE_INDICES
from app.services.indicators import adjust, macd, rsi, bollinger, keltner, atr

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _calc_indicators(df: pd.DataFrame, adjust_mode: str) -> pd.DataFrame:
    """Apply adjustment + compute all indicators, return df with indicator columns."""
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


def _build_row(code: str, asset_type: str, row: pd.Series) -> dict:
    """Build a dict for bulk insert from a DataFrame row."""
    return {
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
    }


async def backfill_etf(adjust_mode: str = "forward") -> None:
    """Backfill indicator_values for all ETFs in universe."""
    etf_codes = [e["code"] for e in CORE_ETF + SECTOR_ETF]
    async with AsyncSessionLocal() as session:
        etf_map = {
            row[0]: row[1]
            for row in (await session.execute(select(Etf.code, Etf.id))).all()
        }

    for code in etf_codes:
        if code not in etf_map:
            logger.warning(f"ETF {code} not in DB, skip")
            continue
        etf_id = etf_map[code]
        await _backfill_one("etf", etf_id, code, adjust_mode)


async def backfill_index(adjust_mode: str = "none") -> None:
    """Backfill indicator_values for all indices in universe."""
    index_codes = [i["code"] for i in CORE_INDICES]
    async with AsyncSessionLocal() as session:
        idx_map = {
            row[0]: row[1]
            for row in (await session.execute(select(Index.code, Index.id))).all()
        }

    for code in index_codes:
        if code not in idx_map:
            logger.warning(f"Index {code} not in DB, skip")
            continue
        idx_id = idx_map[code]
        await _backfill_one("index", idx_id, code, adjust_mode)


async def _backfill_one(
    asset_type: str,
    entity_id: int,
    code: str,
    adjust_mode: str = "forward",
) -> None:
    """Query klines, compute indicators, upsert into indicator_values."""
    async with AsyncSessionLocal() as session:
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
            logger.warning(f"Unsupported asset_type: {asset_type}")
            return

        if not rows:
            logger.warning(f"No klines for {asset_type} {code}")
            return

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

        records = [_build_row(code, asset_type, row) for _, row in df.iterrows()]
        if not records:
            logger.warning(f"No valid indicator rows for {asset_type} {code}")
            return

        await session.execute(delete(IndicatorValue).where(
            IndicatorValue.asset_type == asset_type,
            IndicatorValue.code == code,
        ))
        session.add_all([IndicatorValue(**r) for r in records])
        await session.commit()
        logger.info(f"OK {asset_type} {code}: {len(records)} indicator rows")


async def main(asset: str = "all", adjust_mode: str = "forward") -> None:
    await init_db()
    if asset in ("etf", "all"):
        logger.info("Backfilling ETFs...")
        await backfill_etf(adjust_mode)
    if asset in ("index", "all"):
        logger.info("Backfilling indices...")
        await backfill_index(adjust_mode)


if __name__ == "__main__":
    import sys
    asset_arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    asyncio.run(main(asset_arg))
