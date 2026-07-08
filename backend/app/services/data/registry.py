"""DataSourceRegistry — 多源调度 + 熔断.

策略 (per plan KTD2/KTD3):
- 按注册顺序逐源尝试; 某源抛 NotImplementedMarker → 跳过该源试下一个;
  抛异常 → 计入该源失败计数, 触达阈值则熔断 (open 状态, 冷却时间跳过);
  返回空 df → 视为"没拿到"继续尝试下一个源.
- 命中第一个有数据的源即返回 (df, source_hit).
- 全部源都没拿到数据 → 返回 (空 df, source_hit=None).

熔断状态进程内维护 (单导入任务生命周期足够), 不持久化.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import pandas as pd

from app.config import settings
from app.services.data.base import DataSource, FetchResult
from app.services.data.guosen_source import NotImplementedMarker


@dataclass
class _SourceHealth:
    """单源健康状态: 连续失败计数 + 熔断打开时刻."""

    consecutive_failures: int = 0
    opened_at: float | None = None  # epoch 秒; None=未熔断

    @property
    def is_open(self) -> bool:
        return self.opened_at is not None

    def trip(self, now: float) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= settings.import_circuit_threshold:
            self.opened_at = now

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None

    def cooled_down(self, now: float) -> bool:
        """熔断后过冷却窗口 → 半开 (允许再试, 失败则重新熔断)."""
        if self.opened_at is None:
            return True
        return (now - self.opened_at) >= settings.import_circuit_cooldown


class DataSourceRegistry:
    """按优先级调度多个数据源, 带熔断."""

    def __init__(self, sources: list[DataSource] | None = None):
        self._sources: list[DataSource] = []
        self._health: dict[str, _SourceHealth] = {}
        for source in sources or []:
            self.register(source)

    def register(self, source: DataSource) -> None:
        self._sources.append(source)
        self._health[source.name] = _SourceHealth()

    def _try(
        self,
        source: DataSource,
        fn: Callable[[DataSource], pd.DataFrame],
        now: float,
    ) -> tuple[bool, pd.DataFrame]:
        """对单源执行 fn. 返回 (是否拿到数据, df).

        - NotImplementedMarker → 该源不支持, 返回 (False, 空)
        - 抛其他异常 → 计入熔断, 返回 (False, 空)
        - 返回空 df → (False, 空) 让 registry 试下一源
        - 返回非空 df → 成功, 重置健康计数
        """
        health = self._health[source.name]
        if health.is_open and not health.cooled_down(now):
            return False, pd.DataFrame()
        try:
            df = fn(source)
        except NotImplementedMarker:
            return False, pd.DataFrame()
        except Exception:
            health.trip(now)
            return False, pd.DataFrame()
        if df is None or df.empty:
            return False, pd.DataFrame()
        health.record_success()
        return True, df

    def _dispatch(self, fn: Callable[[DataSource], pd.DataFrame]) -> FetchResult:
        now = time.monotonic()
        for source in self._sources:
            got, df = self._try(source, fn, now)
            if got:
                return FetchResult(df=df, source=source.name)
        return FetchResult(df=pd.DataFrame(), source="")

    # ----- 对外 API: 与 DataSource 同名方法, 返回 FetchResult -----

    def fetch_index_daily(
        self, code: str, start: date | None = None, end: date | None = None
    ) -> FetchResult:
        return self._dispatch(lambda s: s.fetch_index_daily(code, start, end))

    def fetch_etf_daily(
        self, code: str, start: date | None = None, end: date | None = None
    ) -> FetchResult:
        """ETF 取数: 合并所有有数据的源, 取最长历史.
        
        baostock 只返回近期 (~6个月), akshare/guosen 有完整历史.
        拼接后按 trade_date 去重 (保留全部日期, 避免覆盖).
        """
        now = time.monotonic()
        frames: list[pd.DataFrame] = []
        hit_sources: list[str] = []
        for source in self._sources:
            ok, df = self._try(source, lambda s: s.fetch_etf_daily(code, start, end), now)
            if ok and df is not None and not df.empty:
                frames.append(df)
                hit_sources.append(source.name)
        if not frames:
            return FetchResult(df=pd.DataFrame(), source="")
        merged = pd.concat(frames, ignore_index=True)
        if "trade_date" in merged.columns:
            merged = merged.drop_duplicates(subset=["trade_date"], keep="first")
            merged = merged.sort_values("trade_date").reset_index(drop=True)
        return FetchResult(df=merged, source="+".join(hit_sources))

    def fetch_stock_daily(
        self, code: str, market: str = "A", start: date | None = None, end: date | None = None
    ) -> FetchResult:
        return self._dispatch(lambda s: s.fetch_stock_daily(code, market, start, end))

    def fetch_macro_proxy(
        self, name: str, start: date | None = None, end: date | None = None
    ) -> FetchResult:
        return self._dispatch(lambda s: s.fetch_macro_proxy(name, start, end))

    @property
    def sources(self) -> list[DataSource]:
        return list(self._sources)

    def health_snapshot(self) -> dict[str, dict]:
        """可观测: 各源连续失败数 + 是否熔断."""
        return {
            name: {"failures": h.consecutive_failures, "open": h.is_open}
            for name, h in self._health.items()
        }


def default_registry() -> DataSourceRegistry:
    """主源 baostock (A股, 稳定纯HTTP) → 备用 akshare (港股/国债/外汇) → guosen.

    baostock 不支持港股指数/国债/外汇 → NotImplementedMarker → 回退 akshare 新浪源.
    """
    from app.services.data.akshare_source import AkshareDataSource
    from app.services.data.baostock_source import BaostockDataSource
    from app.services.data.guosen_source import GuosenDataSource

    reg = DataSourceRegistry()
    reg.register(BaostockDataSource())  # A股主源 (无 V8, 稳定)
    reg.register(AkshareDataSource())   # 港股/国债/外汇 回退源
    reg.register(GuosenDataSource())    # 兜底
    return reg


__all__ = ["DataSourceRegistry", "default_registry"]
