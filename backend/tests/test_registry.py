"""U4 tests: DataSourceRegistry 主备调度 + 熔断.

不依赖网络. 用 fake source 验证:
- 主源命中 → 返回主源, 不试备用
- 主源异常/空 → fallback 到备用源
- NotImplementedMarker → 跳过该源试下一个
- 连续失败触达阈值 → 熔断 (后续跳过, 冷却后半开重试)
- 全部源都空 → 返回 (空 df, source="")
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.services.data.base import DataSource, FetchResult
from app.services.data.guosen_source import NotImplementedMarker
from app.services.data.registry import DataSourceRegistry


class FakeSource(DataSource):
    """可控行为的数据源桩: 记录被调用次数 + 可注入返回/异常/不支持."""

    def __init__(
        self,
        name: str,
        df: pd.DataFrame | None = None,
        raise_exc: Exception | None = None,
        not_supported: bool = False,
    ):
        self.name = name
        self._df = df
        self._exc = raise_exc
        self._not_supported = not_supported
        self.call_count = 0

    def fetch_index_daily(self, code, start=None, end=None):
        self.call_count += 1
        if self._not_supported:
            raise NotImplementedMarker(f"{self.name} not supported")
        if self._exc:
            raise self._exc
        return self._df if self._df is not None else pd.DataFrame()

    def fetch_etf_daily(self, code, start=None, end=None):
        return self.fetch_index_daily(code, start, end)

    def fetch_stock_daily(self, code, market="A", start=None, end=None):
        return self.fetch_index_daily(code, start, end)

    def fetch_macro_proxy(self, name, start=None, end=None):
        self.call_count += 1
        if self._not_supported:
            raise NotImplementedMarker(f"{self.name} not supported")
        if self._exc:
            raise self._exc
        return self._df if self._df is not None else pd.DataFrame()


def _df_with(n: int = 2):
    return pd.DataFrame({
        "trade_date": [date(2026, 6, 18), date(2026, 6, 19)][:n],
        "close": [10.0, 11.0][:n],
    })


def test_primary_hit_returns_primary_and_skips_fallback():
    primary = FakeSource("primary", df=_df_with())
    fallback = FakeSource("fallback", df=_df_with())
    reg = DataSourceRegistry([primary, fallback])
    result = reg.fetch_index_daily("000300")
    assert result.source == "primary"
    assert not result.df.empty
    assert fallback.call_count == 0  # 没试备用


def test_primary_empty_falls_back_to_secondary():
    primary = FakeSource("primary", df=pd.DataFrame())
    fallback = FakeSource("fallback", df=_df_with())
    reg = DataSourceRegistry([primary, fallback])
    result = reg.fetch_index_daily("000300")
    assert result.source == "fallback"
    assert len(result.df) == 2


def test_primary_exception_falls_back_to_secondary():
    primary = FakeSource("primary", raise_exc=ConnectionError("down"))
    fallback = FakeSource("fallback", df=_df_with())
    reg = DataSourceRegistry([primary, fallback])
    result = reg.fetch_index_daily("000300")
    assert result.source == "fallback"
    # 异常计入了 primary 健康计数
    assert reg.health_snapshot()["primary"]["failures"] == 1


def test_not_implemented_marker_skips_source():
    """备用源不支持个股 → 不计入熔断, 直接跳过."""
    ak = FakeSource("ak", df=_df_with())
    guosen = FakeSource("guosen", not_supported=True)
    reg = DataSourceRegistry([ak, guosen])
    result = reg.fetch_stock_daily("600519")
    assert result.source == "ak"
    # guosen 不支持没记失败
    assert reg.health_snapshot()["guosen"]["failures"] == 0


def test_all_sources_empty_returns_empty_no_source():
    primary = FakeSource("primary", df=pd.DataFrame())
    fallback = FakeSource("fallback", df=pd.DataFrame())
    reg = DataSourceRegistry([primary, fallback])
    result = reg.fetch_index_daily("000300")
    assert result.df.empty
    assert result.source == ""


def test_circuit_opens_after_threshold_failures(monkeypatch):
    """连续失败触达阈值 → 熔断打开, 后续调用直接跳过该源."""
    monkeypatch.setattr("app.services.data.registry.settings.import_circuit_threshold", 3)
    monkeypatch.setattr("app.services.data.registry.settings.import_circuit_cooldown", 9999.0)
    primary = FakeSource("primary", raise_exc=ConnectionError("down"))
    fallback = FakeSource("fallback", df=_df_with())
    reg = DataSourceRegistry([primary, fallback])

    for _ in range(3):
        reg.fetch_index_daily("000300")

    snap = reg.health_snapshot()["primary"]
    assert snap["open"] is True  # 熔断打开
    # primary 已被调用 3 次 (阈值 3)
    assert primary.call_count == 3

    # 再调一次: primary 被熔断跳过, 不增加调用
    reg.fetch_index_daily("000300")
    assert primary.call_count == 3
    # fallback 仍然命中
    assert reg.fetch_index_daily("000300").source == "fallback"


def test_circuit_half_opens_after_cooldown(monkeypatch):
    """熔断冷却后半开: 允许再试, 成功则恢复."""
    monkeypatch.setattr("app.services.data.registry.settings.import_circuit_threshold", 2)
    monkeypatch.setattr("app.services.data.registry.settings.import_circuit_cooldown", 0.0)
    primary = FakeSource("primary", raise_exc=ConnectionError("down"))
    fallback = FakeSource("fallback", df=_df_with())
    reg = DataSourceRegistry([primary, fallback])

    # 触发熔断
    reg.fetch_index_daily("000300")
    reg.fetch_index_daily("000300")
    assert reg.health_snapshot()["primary"]["open"] is True

    # 冷却窗口 0 → 半开; 把 primary 改成成功, 下次应恢复并命中 primary
    primary._exc = None
    primary._df = _df_with()
    result = reg.fetch_index_daily("000300")
    assert result.source == "primary"
    assert reg.health_snapshot()["primary"]["open"] is False


def test_fetch_result_carries_source_name():
    primary = FakeSource("primary", df=_df_with())
    reg = DataSourceRegistry([primary])
    result: FetchResult = reg.fetch_macro_proxy("us_treasury_10y")
    assert result.source == "primary"
    assert isinstance(result, FetchResult)
