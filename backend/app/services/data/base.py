"""DataSource 抽象接口 (契约).

每个数据源实现该接口,提供指数/ETF/个股/宏观代理的日线拉取能力.
方法返回归一化后的 DataFrame (列: trade_date/open/close/high/low/volume/amount),
空数据返回空 DataFrame (让 registry 决定是否 fallback),源端异常向上抛.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class FetchResult:
    """一次取数的结果 + 命中的源名 (registry/导入器用于可观测)."""

    df: pd.DataFrame
    source: str


class DataSource(ABC):
    """多源数据层统一契约. name 标识源 (akshare | guosen | ...)."""

    name: str = "base"

    @abstractmethod
    def fetch_index_daily(
        self, code: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame: ...

    @abstractmethod
    def fetch_etf_daily(
        self, code: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame: ...

    @abstractmethod
    def fetch_stock_daily(
        self, code: str, market: str = "A", start: date | None = None, end: date | None = None
    ) -> pd.DataFrame: ...

    @abstractmethod
    def fetch_macro_proxy(
        self, name: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        """宏观代理 (国债ETF/美债10Y 等). name 为逻辑代理名 (如 'us_treasury_10y')."""
