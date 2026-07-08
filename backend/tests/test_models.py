"""U1 tests: 四类资产分表 schema + 状态/错误表 schema.

Uses SQLite (in-memory) to validate table creation + unique constraints,
decoupled from the MySQL connectivity required at runtime.
"""
from datetime import date

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import (
    Etf,
    EtfDailyKline,
    Fund,
    FundDailyKline,
    ImportError,
    Index,
    IndexDailyKline,
    RegimeRun,
    RegimeState,
    Stock,
    StockDailyKline,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


async def test_all_tables_created(session):
    """Happy: init_db 建出全部 8+ 张表."""
    engine = session.bind

    def _names(sync_conn):
        return inspect(sync_conn).get_table_names()

    async with engine.connect() as conn:
        tables = await conn.run_sync(_names)
    for expected in [
        "stocks",
        "indices",
        "etfs",
        "funds",
        "stock_daily_klines",
        "index_daily_klines",
        "etf_daily_klines",
        "fund_daily_klines",
        "regime_runs",
        "regime_states",
        "import_errors",
    ]:
        assert expected in tables, f"missing table: {expected}"


async def test_stock_kline_unique_constraint(session):
    """Edge: (stock_id, trade_date) 唯一约束生效."""
    stock = Stock(code="600519", name="贵州茅台", market="A")
    session.add(stock)
    await session.commit()
    await session.refresh(stock)

    kline = StockDailyKline(
        stock_id=stock.id,
        trade_date=date(2026, 6, 20),
        open=1500.0,
        close=1510.0,
        high=1520.0,
        low=1490.0,
        volume=100000,
    )
    session.add(kline)
    await session.commit()

    dup = StockDailyKline(
        stock_id=stock.id,
        trade_date=date(2026, 6, 20),
        open=1500.0,
        close=1520.0,
        high=1530.0,
        low=1500.0,
        volume=200000,
    )
    session.add(dup)
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_index_and_etf_klines_roundtrip(session):
    """Happy: 指数/ETF 行情表可读写."""
    idx = Index(code="000300", name="沪深300", market="A")
    etf = Etf(code="511260", name="国债ETF", tracks="国债指数")
    session.add_all([idx, etf])
    await session.commit()
    await session.refresh(idx)
    await session.refresh(etf)

    session.add(IndexDailyKline(
        index_id=idx.id, trade_date=date(2026, 6, 20),
        open=4000.0, close=4010.0, high=4020.0, low=3990.0, volume=0,
    ))
    session.add(EtfDailyKline(
        etf_id=etf.id, trade_date=date(2026, 6, 20),
        open=100.0, close=100.5, high=100.8, low=99.9, volume=5000,
    ))
    await session.commit()

    assert (await session.execute(select(IndexDailyKline))).scalars().all().__len__() == 1
    assert (await session.execute(select(EtfDailyKline))).scalars().all().__len__() == 1


async def test_fund_nav_fields(session):
    """Happy: 基金净值表 unit_nav / acc_nav 字段正确."""
    fund = Fund(code="110011", name="易方达中小盘", fund_type="混合型")
    session.add(fund)
    await session.commit()
    await session.refresh(fund)

    session.add(FundDailyKline(
        fund_id=fund.id, trade_date=date(2026, 6, 20), unit_nav=3.521, acc_nav=4.102,
    ))
    await session.commit()
    row = (await session.execute(select(FundDailyKline))).scalar_one()
    assert float(row.unit_nav) == 3.521
    assert float(row.acc_nav) == 4.102


async def test_hk_stock_coexists_with_a_share(session):
    """Edge: 港股与 A 股共存于同一张表,market 字段区分,主键不冲突."""
    a_stock = Stock(code="600519", name="贵州茅台", market="A")
    hk_stock = Stock(code="00700", name="腾讯控股", market="HK")
    session.add_all([a_stock, hk_stock])
    await session.commit()

    stocks = {s.code: s.market for s in (await session.execute(select(Stock))).scalars().all()}
    assert stocks == {"600519": "A", "00700": "HK"}


async def test_regime_tables_schema(session):
    """Happy: RegimeRun / RegimeState 表可创建且写入正确(为后续 ML 留位)."""
    run = RegimeRun(market="A", algorithm="hmm", classifier="logistic",
                    params={"k": 2}, metrics={"ks": 0.97})
    session.add(run)
    await session.commit()
    await session.refresh(run)

    session.add(RegimeState(
        run_id=run.id, trade_date=date(2026, 6, 20), state_label=1, state_prob=0.83,
    ))
    await session.commit()

    state = (await session.execute(select(RegimeState))).scalar_one()
    assert state.state_label == 1
    assert float(state.state_prob) == 0.83


async def test_import_error_table(session):
    """Happy: ImportError 错误表可记录失败标的."""
    session.add(ImportError(asset_type="stock", code="600519", source="akshare",
                            error_msg="timeout"))
    await session.commit()
    row = (await session.execute(select(ImportError))).scalar_one()
    assert row.retried_at is None
    assert row.error_msg == "timeout"
