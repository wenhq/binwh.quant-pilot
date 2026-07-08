"""U7 tests: 状态落库 (regime_runs / regime_states)."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from app.models import RegimeRun, RegimeState
from app.services.market_regime.persist import _to_jsonable, save_run, save_states


def _make_factory(engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def sqlite_db():
    from sqlalchemy.ext.asyncio import create_async_engine

    from app import models  # noqa: F401  register metadata
    from app.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


def _overlay(n: int = 5):
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "trade_date": dates,
            "close": np.linspace(100, 105, n),
            "state_label": [0, 0, 1, 1, 0][:n],
            "state_prob": [0.1, 0.2, 0.8, 0.7, 0.2][:n],
        }
    )


def test_to_jsonable_numpy_and_nan():
    out = _to_jsonable(
        {"a": np.float64(1.5), "b": np.int64(2), "c": np.array([1, 2]), "nan": np.float64(np.nan)}
    )
    assert out == {"a": 1.5, "b": 2, "c": [1, 2], "nan": None}


@pytest.mark.asyncio
async def test_save_run_creates_row_with_metrics(sqlite_db):
    factory = _make_factory(sqlite_db)
    async with factory() as s:
        run = await save_run(s, "A", metrics={"ks": np.float64(0.9), "silhouette": 0.2})
        await s.commit()
        assert run.id is not None
    async with factory() as s:
        rows = (await s.execute(select(RegimeRun))).scalars().all()
        assert len(rows) == 1
        assert rows[0].market == "A"
        assert rows[0].algorithm == "hmm"
        assert rows[0].classifier == "logistic"
        # numpy 已转原生
        assert rows[0].metrics == {"ks": 0.9, "silhouette": 0.2}


@pytest.mark.asyncio
async def test_save_states_writes_rows(sqlite_db):
    factory = _make_factory(sqlite_db)
    async with factory() as s:
        run = await save_run(s, "A")
        n = await save_states(s, run.id, _overlay(5))
        await s.commit()
        assert n == 5
    async with factory() as s:
        states = (
            await s.execute(select(RegimeState).where(RegimeState.run_id == run.id))
        ).scalars().all()
        assert len(states) == 5
        assert states[0].state_label == 0
        assert states[2].state_label == 1
        assert states[2].state_prob == 0.8
        assert isinstance(states[0].trade_date, date)


@pytest.mark.asyncio
async def test_save_states_idempotent(sqlite_db):
    """同 run_id 重写 → 行数不翻倍 (覆盖式 delete-then-insert)."""
    factory = _make_factory(sqlite_db)
    ov = _overlay(5)
    async with factory() as s:
        run = await save_run(s, "A")
        await save_states(s, run.id, ov)
        await save_states(s, run.id, ov)  # 再写一次
        await s.commit()
    async with factory() as s:
        states = (
            await s.execute(select(RegimeState).where(RegimeState.run_id == run.id))
        ).scalars().all()
        assert len(states) == 5


@pytest.mark.asyncio
async def test_save_states_with_features_snapshot(sqlite_db):
    factory = _make_factory(sqlite_db)
    async with factory() as s:
        run = await save_run(s, "A")
        ov = _overlay(3)
        feats = pd.DataFrame(
            {"pc1": [0.1, 0.2, 0.3], "pc2": [1.0, 1.1, 1.2]},
            index=pd.date_range("2024-01-01", periods=3, freq="B"),
        )
        await save_states(s, run.id, ov, features_snapshot=feats)
        await s.commit()
    async with factory() as s:
        states = (
            await s.execute(select(RegimeState).where(RegimeState.run_id == run.id))
        ).scalars().all()
        assert states[0].features_snapshot == {"pc1": 0.1, "pc2": 1.0}
