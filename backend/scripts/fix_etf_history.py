"""Quick fix: re-import only ETFs with full history via merged baostock+akshare."""
import asyncio
import logging

from sqlalchemy import select, func

from app.database import AsyncSessionLocal, init_db
from app.models.etf import Etf, EtfDailyKline
from app.services.data.importer import _import_one, _upsert_instrument
from app.services.data.registry import default_registry
from app.services.data.universe import CORE_ETF, SECTOR_ETF

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main():
    await init_db()
    registry = default_registry()
    etfs = CORE_ETF + SECTOR_ETF

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Etf.code, Etf.id, func.count(EtfDailyKline.id))
            .outerjoin(EtfDailyKline, Etf.id == EtfDailyKline.etf_id)
            .group_by(Etf.id)
        )
        db_counts = {row[0]: (row[1], row[2]) for row in result.all()}

    succeeded = 0
    failed = 0
    skipped = 0

    for etf in etfs:
        code = etf["code"]
        name = etf.get("name")
        tracks = etf.get("tracks")
        category = etf.get("category")
        data_source = etf.get("data_source")

        async with AsyncSessionLocal() as session:
            try:
                source, n = await _import_one(
                    session, registry, "etf", code,
                    market=None, name=name, tracks=tracks,
                )
                await _upsert_instrument(session, {
                    "code": code, "name": name, "asset_type": "etf",
                    "market": None, "category": category,
                    "data_source": data_source, "tracks": tracks,
                }, source)
                await session.commit()
                if n > 0:
                    logger.info(f"OK {code}: {n} rows from {source}")
                    succeeded += 1
                else:
                    logger.warning(f"SKIP {code}: empty df")
                    skipped += 1
            except Exception as e:
                logger.error(f"FAIL {code}: {e}")
                failed += 1

    logger.info(f"Done: succeeded={succeeded}, skipped={skipped}, failed={failed}")


if __name__ == "__main__":
    asyncio.run(main())
