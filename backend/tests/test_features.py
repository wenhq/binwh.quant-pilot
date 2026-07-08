"""U2 tests: 特征工程 (expanding 防泄漏)."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.models import Etf, EtfDailyKline, Index, IndexDailyKline
from app.services.market_regime.config import MARKET_CONFIGS
from app.services.market_regime.features import (
    _cross_spread_features,
    build_feature_matrix,
    build_raw_features,
    macro_diff,
    multi_period_returns,
    realized_volatility,
    standardize_expanding,
)


def _make_session_factory(engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def sqlite_db():
    from sqlalchemy.ext.asyncio import create_async_engine
    from app import models  # noqa: F401
    from app.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


def _dates(n: int, start: str = "2024-01-01") -> list[date]:
    base = date.fromisoformat(start)
    return [base + timedelta(days=i) for i in range(n)]


# ---------- 纯函数 ----------


def test_multi_period_returns_windows():
    close = pd.Series(np.linspace(100, 130, 100), index=_dates(100), name="P")
    df = multi_period_returns(close, (5, 21, 63))
    assert list(df.columns) == ["ret_5d", "ret_21d", "ret_63d"]
    expected = (close.iloc[5] - close.iloc[0]) / close.iloc[0]
    assert df["ret_5d"].iloc[5] == pytest.approx(expected)
    assert np.isnan(df["ret_5d"].iloc[3])


def test_realized_volatility_positive_and_annualized():
    rng = np.random.default_rng(0)
    close = pd.Series(100 + rng.normal(0, 1, 300).cumsum(), index=_dates(300), name="P")
    vol = realized_volatility(close, span=21)
    assert vol.name == "realvol_21d"
    valid = vol.dropna()
    assert (valid > 0).all()
    assert valid.median() < 1.0


# ---------- 防泄漏核心 (R2) ----------


def test_standardize_expanding_no_future_leak():
    idx = pd.DatetimeIndex(_dates(200))
    rng = np.random.default_rng(42)
    X = pd.DataFrame({"f": rng.normal(0, 1, 200)}, index=idx)
    scaled_full = standardize_expanding(X, min_periods=60)
    X_perturbed = X.copy()
    X_perturbed.iloc[159, 0] = 1e6
    scaled_perturbed = standardize_expanding(X_perturbed, min_periods=60)
    d100 = idx[100]
    assert scaled_full.loc[d100, "f"] == pytest.approx(scaled_perturbed.loc[d100, "f"])
    upto = idx[158]
    assert np.allclose(
        scaled_full.loc[:upto, "f"].values,
        scaled_perturbed.loc[:upto, "f"].values,
    )


def test_standardize_expanding_drops_warmup():
    idx = pd.DatetimeIndex(_dates(100))
    X = pd.DataFrame({"f": np.linspace(1, 2, 100)}, index=idx)
    scaled = standardize_expanding(X, min_periods=60)
    assert len(scaled) == 41
    assert scaled.index.min() == idx[59]


# ---------- build_raw_features ----------


def test_build_raw_features_adds_suffix():
    primary = pd.Series(np.linspace(100, 110, 100), index=_dates(100), name="000300")
    cfg = {"primary": "000300"}
    feats = build_raw_features(primary, cfg, {})
    assert "ret_5d_000300" in feats.columns
    assert "realvol_21d_000300" in feats.columns


def test_macro_diff_first_difference():
    s = pd.Series([1.0, 1.5, 2.0, 2.4], index=_dates(4))
    d = macro_diff(s)
    assert np.isnan(d.iloc[0])
    assert d.iloc[1] == pytest.approx(0.5)
    assert d.iloc[3] == pytest.approx(0.4)


# ---------- 交叉价差 ----------


def test_cross_spread_features():
    rng = np.random.default_rng(0)
    idx = pd.DatetimeIndex(_dates(100))
    sa = pd.Series(100 + rng.normal(0, 1, 100).cumsum(), index=idx)
    sb = pd.Series(100 + rng.normal(0, 1.5, 100).cumsum(), index=idx)
    closes = {"000300": sa, "000905": sb}
    feats = _cross_spread_features(closes, [("000300", "000905")], idx)
    assert "cross_000300_000905" in feats.columns
    assert len(feats) == len(idx)


def test_cross_spread_missing_pair_skipped():
    rng = np.random.default_rng(0)
    idx = pd.DatetimeIndex(_dates(50))
    sa = pd.Series(100 + rng.normal(0, 1, 50).cumsum(), index=idx)
    closes = {"000300": sa}
    feats = _cross_spread_features(closes, [("000300", "000905")], idx)
    assert feats.empty


# ---------- 端到端 integration (sqlite) ----------


async def _seed_index(session, code, name, market, closes):
    idx = Index(code=code, name=name, market=market)
    session.add(idx)
    await session.flush()
    for d, c in closes:
        session.add(
            IndexDailyKline(
                index_id=idx.id, trade_date=d, open=c, close=c, high=c, low=c, volume=1000
            )
        )
    return idx


async def _seed_etf(session, code, name, closes):
    e = Etf(code=code, name=name)
    session.add(e)
    await session.flush()
    for d, c in closes:
        session.add(
            EtfDailyKline(
                etf_id=e.id, trade_date=d, open=c, close=c, high=c, low=c, volume=1000
            )
        )
    return e


@pytest.mark.asyncio
async def test_build_feature_matrix_end_to_end(sqlite_db):
    """composite primary (000001+399001) + 交叉价差 + 宏观 + 行业ETF."""
    factory = _make_session_factory(sqlite_db)
    rng = np.random.default_rng(7)
    dates = _dates(200)

    async with factory() as s:
        await _seed_index(s, "000001", "上证综指", "A", list(zip(dates, 100 + rng.normal(0, 1, 200).cumsum())))
        await _seed_index(s, "399001", "深证成指", "A", list(zip(dates, 100 + rng.normal(0, 1.2, 200).cumsum())))
        await _seed_etf(s, "512480", "半导体ETF", list(zip(dates, np.linspace(1.0, 1.3, 200))))
        await _seed_etf(s, "510880", "红利ETF", list(zip(dates, np.linspace(2.0, 2.4, 200))))
        await s.commit()

    async with factory() as s:
        mat = await build_feature_matrix(s, "A")

    assert not mat.empty
    assert "ret_5d_composite" in mat.columns
    assert "realvol_21d_composite" in mat.columns
    assert any(c.startswith("spread_") for c in mat.columns)
    assert not mat.isna().any().any()


@pytest.mark.asyncio
async def test_build_feature_matrix_missing_primary_raises(sqlite_db):
    factory = _make_session_factory(sqlite_db)
    async with factory() as s:
        with pytest.raises(ValueError, match="无数据"):
            await build_feature_matrix(s, "A")
