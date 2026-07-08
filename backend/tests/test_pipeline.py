"""U8 tests: 端到端编排 + 两市场独立."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import models  # noqa: F401  register metadata
from app.database import Base
from app.models import Etf, EtfDailyKline, Index, IndexDailyKline, RegimeState
from app.services.market_regime.pipeline import run_all_markets, run_pipeline


def _factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def sqlite_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def _seed_index(s, code, name, market, closes):
    idx = Index(code=code, name=name, market=market)
    s.add(idx)
    await s.flush()
    for d, c in closes:
        s.add(
            IndexDailyKline(
                index_id=idx.id, trade_date=d, open=c, close=c, high=c, low=c, volume=1000
            )
        )


async def _seed_etf(s, code, name, closes):
    e = Etf(code=code, name=name)
    s.add(e)
    await s.flush()
    for d, c in closes:
        s.add(
            EtfDailyKline(
                etf_id=e.id, trade_date=d, open=c, close=c, high=c, low=c, volume=1000
            )
        )


def _dates(n: int) -> list[date]:
    return [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]


async def _seed_market_a(s, n=300):
    """主标的构造两态结构 (前半低波动, 后半高波动) 以便 HMM 识别."""
    rng = np.random.default_rng(7)
    dates = _dates(n)
    half = n // 2
    low = 100 + rng.normal(0, 0.5, half).cumsum()
    high = 100 + rng.normal(0, 3.0, n - half).cumsum() + 50
    closes_300 = np.concatenate([low, high])
    closes_001 = closes_300 * 0.95 + rng.normal(0, 0.3, n).cumsum()  # 上证综指
    closes_399 = closes_300 * 1.02 + rng.normal(0, 0.4, n).cumsum()  # 深证成指
    await _seed_index(s, "000001", "上证综指", "A", list(zip(dates, closes_001)))
    await _seed_index(s, "399001", "深证成指", "A", list(zip(dates, closes_399)))
    await _seed_index(s, "000300", "沪深300", "A", list(zip(dates, closes_300)))
    await _seed_index(s, "CN10Y", "中国10年国债", "CN", list(zip(dates, np.linspace(2.5, 2.8, n))))
    await _seed_index(s, "USDCNY", "美元人民币", "FX", list(zip(dates, np.linspace(7.1, 7.2, n))))
    await _seed_etf(s, "512480", "半导体ETF", list(zip(dates, np.linspace(1.0, 1.3, n))))
    await _seed_etf(s, "510880", "红利ETF", list(zip(dates, np.linspace(2.0, 2.4, n))))


@pytest.mark.asyncio
async def test_run_pipeline_end_to_end(sqlite_db):
    factory = _factory(sqlite_db)
    async with factory() as s:
        await _seed_market_a(s, 300)
        await s.commit()
    async with factory() as s:
        res = await run_pipeline(s, "A")
    assert res.success, f"pipeline 失败: {res.error}"
    assert res.run_id > 0
    assert res.n_rows > 0
    # 落库验证
    async with factory() as s:
        states = (
            await s.execute(select(RegimeState).where(RegimeState.run_id == res.run_id))
        ).scalars().all()
        assert len(states) == res.n_rows


@pytest.mark.asyncio
async def test_run_pipeline_missing_data_fails_gracefully(sqlite_db):
    """空库 → A 失败, 返回 success=False + error (不抛异常)."""
    factory = _factory(sqlite_db)
    async with factory() as s:
        res = await run_pipeline(s, "A")
    assert not res.success
    assert res.error is not None


@pytest.mark.asyncio
async def test_run_all_markets_isolation(sqlite_db):
    """A 有数据, HK 无 → A 成功, HK 失败, 互不影响."""
    factory = _factory(sqlite_db)
    async with factory() as s:
        await _seed_market_a(s, 300)
        await s.commit()
    results = await run_all_markets(factory)
    assert len(results) == 2
    a_res = next(r for r in results if r.market == "A")
    hk_res = next(r for r in results if r.market == "HK")
    assert a_res.success
    assert not hk_res.success  # HK 无数据, 失败
