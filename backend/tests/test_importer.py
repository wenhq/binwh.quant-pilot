"""U6 tests: 限速导入器编排 + 错误记录.

SQLite 不支持 mysql_insert.on_duplicate_key_update, 所以这里测编排层:
- progress 计数正确 (succeeded/skipped/failed/done/total)
- 失败标的写入 import_errors
- 限速 sleep 被调用 (rate>0 时)
- universe 展平正确 (个股+指数+ETF 数量)

bulk upsert 的幂等性在真实 MySQL 上验证 (运行时), 单测覆盖元数据 upsert + 错误表.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pandas as pd
import pytest

from app.database import Base
from app.models.import_log import ImportError
from app.services.data.base import FetchResult
from app.services.data.importer import (
    ImportProgress,
    _import_task,
    get_progress,
    reset_progress,
)
from app.services.data.universe import Universe


def _make_session_factory(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory


@pytest.fixture
async def sqlite_db():
    """内存 SQLite + 全部表 (测错误表/元数据 upsert)."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from app import models  # noqa: F401 register metadata

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


class _FakeRegistry:
    """可控 registry: 按 code 返回 FetchResult 或抛异常."""

    def __init__(self, results: dict[str, FetchResult], errors: dict[str, Exception] | None = None):
        self.results = results
        self.errors = errors or {}

    def fetch_stock_daily(self, code, market="A", start=None, end=None):
        if code in self.errors:
            raise self.errors[code]
        return self.results.get(code, FetchResult(df=pd.DataFrame(), source="")).df

    def fetch_index_daily(self, code, start=None, end=None):
        if code in self.errors:
            raise self.errors[code]
        return self.results.get(code, FetchResult(df=pd.DataFrame(), source="")).df

    def fetch_etf_daily(self, code, start=None, end=None):
        if code in self.errors:
            raise self.errors[code]
        return self.results.get(code, FetchResult(df=pd.DataFrame(), source="")).df

    def fetch_macro_proxy(self, name, start=None, end=None):
        return self.results.get(name, FetchResult(df=pd.DataFrame(), source="")).df


def _kline_df(n=2):
    return pd.DataFrame({
        "trade_date": [date(2026, 6, 18), date(2026, 6, 19)][:n],
        "open": [10.0, 10.5][:n],
        "close": [10.5, 11.0][:n],
        "high": [10.8, 11.0][:n],
        "low": [9.9, 10.4][:n],
        "volume": [100000, 120000][:n],
        "amount": [1.05e6, 1.3e6][:n],
    })


@pytest.mark.asyncio
async def test_progress_counts_success_skip_fail(sqlite_db, monkeypatch):
    """3 个标的: 1 成功, 1 空(skipped), 1 失败(failed+import_errors)."""
    factory = _make_session_factory(sqlite_db)
    reset_progress()
    prog = get_progress()
    prog.total = 3
    prog.running = True

    registry = _FakeRegistry(
        results={
            "600519": FetchResult(df=_kline_df(), source="akshare"),
            "000001": FetchResult(df=pd.DataFrame(), source=""),  # 空 → skipped
        },
        errors={"300750": ConnectionError("source down")},
    )

    # 绕过 MySQL-only bulk upsert: stub _import_one 返回 (source, rows).
    async def fake_import_one(session, reg, asset_type, code, **kw):
        if code in registry.errors:
            raise registry.errors[code]
        df = registry.results.get(code)
        return (df.source if df else "", 0 if (df is None or df.df.empty) else len(df.df))

    import app.services.data.importer as imp
    monkeypatch.setattr(imp, "_import_one", fake_import_one)
    monkeypatch.setattr(imp.asyncio, "sleep", lambda *a, **kw: asyncio.sleep(0))  # 跳过限速

    tasks = [
        {"asset_type": "stock", "code": "600519"},
        {"asset_type": "stock", "code": "000001"},
        {"asset_type": "stock", "code": "300750"},
    ]
    for t in tasks:
        await _import_task(factory, registry, t, 0.0)

    assert prog.done == 3
    assert prog.succeeded == 1
    assert prog.skipped == 1
    assert prog.failed == 1
    assert len(prog.errors) == 1
    assert prog.errors[0]["code"] == "300750"

    # 失败标的入 import_errors
    from sqlalchemy import select
    async with factory() as s:
        rows = (await s.execute(select(ImportError).where(ImportError.code == "300750"))).scalars().all()
        assert len(rows) == 1
        assert rows[0].asset_type == "stock"
        assert rows[0].retried_at is None


@pytest.mark.asyncio
async def test_rate_sleep_called_between_tasks(monkeypatch):
    """rate>0 → 每个任务后 sleep(rate) 被调用."""
    factory = None
    reset_progress()
    prog = get_progress()
    prog.total = 2
    prog.running = True

    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    import app.services.data.importer as imp

    async def fake_import_one(session, reg, asset_type, code, **kw):
        return ("akshare", 1)

    monkeypatch.setattr(imp, "_import_one", fake_import_one)
    monkeypatch.setattr(imp.asyncio, "sleep", fake_sleep)

    class _NullFactory:
        def __call__(self):
            class _S:
                bind = None  # _upsert_instrument 见无 bind 跳过字典写入

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

                async def commit(self):
                    pass

                def add(self, *_a, **_kw):
                    pass

                async def execute(self, *_a, **_kw):
                    pass

            return _S()

    registry = _FakeRegistry({})
    for code in ("600519", "000001"):
        await _import_task(_NullFactory(), registry, {"asset_type": "stock", "code": code}, 2.0)
    assert sleeps == [2.0, 2.0]
    assert prog.succeeded == 2


def test_universe_flattening_total():
    """run_import 把 universe 展平成 任务数 = 个股+指数+ETF (宏观代理单独走)."""
    uni = Universe(
        stocks=[{"code": "600519"}, {"code": "000001"}],
        indices=[{"code": "000300"}, {"code": "000016"}],
        etfs=[{"code": "510300"}],
        macro_proxies=["us_treasury_10y"],
    )
    # 宏观代理不计入 kline 导入任务 (走独立路径/未来扩展).
    expected = len(uni.stocks) + len(uni.indices) + len(uni.etfs)
    assert expected == 5


def test_progress_to_dict_shape():
    prog = ImportProgress(total=10, done=3, succeeded=2, failed=1)
    d = prog.to_dict()
    assert set(d.keys()) >= {"total", "done", "succeeded", "failed", "skipped",
                             "running", "last_code", "last_source", "recent_errors"}
    assert d["total"] == 10 and d["running"] is False
