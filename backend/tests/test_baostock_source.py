"""Baostock 数据源单元测试 (mock baostock 库, 不依赖网络).

验证:
- _to_baostock_code 沪深代码映射 (sh./sz. 前缀)
- fetch_index_daily/etf_daily 归一化列 + 数值类型
- 港股/国债/外汇/宏观代理抛 NotImplementedMarker (留给 registry 回退 akshare)
- _ensure_login 进程级单例幂等 (login 只调一次)
- query 失败 → 空 DataFrame (不抛异常)
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.services.data import baostock_source as bsrc
from app.services.data.baostock_source import (
    BaostockDataSource,
    _ensure_login,
    _to_baostock_code,
)
from app.services.data.guosen_source import NotImplementedMarker


class _FakeResult:
    """模拟 baostock query_history_k_data_plus 返回的 ResultSet."""

    def __init__(self, error_code: str = "0", rows: list[list[str]] | None = None,
                 error_msg: str = "success"):
        self.error_code = error_code
        self.error_msg = error_msg
        self._rows = rows or []
        self._idx = 0

    def next(self) -> bool:
        if self._idx < len(self._rows):
            self._idx += 1
            return True
        return False

    def get_row_data(self) -> list[str]:
        return self._rows[self._idx - 1]


def _kline_rows():
    # baostock 返回字符串字段: date,open,high,low,close,volume,amount
    return [
        ["2026-06-18", "10.00", "10.80", "9.90", "10.50", "100000", "1050000.00"],
        ["2026-06-19", "10.50", "11.00", "10.40", "11.00", "120000", "1320000.00"],
    ]


@pytest.fixture(autouse=True)
def _reset_login(monkeypatch):
    """每个测试前重置 login 标志 + mock bs.login, 避免进程状态污染."""
    bsrc._logged_in = False
    fake_bs = MagicMock()
    fake_bs.login.return_value = SimpleNamespace(error_code="0", error_msg="success")
    monkeypatch.setattr(bsrc, "_ensure_login", lambda: None)
    # 仍提供 bs 模块供 _query 内 import (虽然 _ensure_login 被 mock 掉, query 内还要 import bs)
    import sys
    sys.modules["baostock"] = fake_bs
    yield
    bsrc._logged_in = False


def test_to_baostock_code_sh():
    assert _to_baostock_code("600519", "stock") == "sh.600519"  # 沪市个股
    assert _to_baostock_code("688981", "stock") == "sh.688981"  # 科创板
    assert _to_baostock_code("510300", "etf") == "sh.510300"    # 沪市ETF
    # 指数必须靠 market 区分: 000300 带 SH → sh.000300
    assert _to_baostock_code("000300", "index", "SH") == "sh.000300"


def test_to_baostock_code_sz():
    assert _to_baostock_code("000001", "stock") == "sz.000001"  # 深市个股 (无market按前缀)
    assert _to_baostock_code("300750", "stock") == "sz.300750"  # 创业板
    assert _to_baostock_code("159928", "etf") == "sz.159928"    # 深市ETF
    assert _to_baostock_code("399001", "index", "SZ") == "sz.399001"  # 深证成指


def test_to_baostock_code_non_digit_returns_none():
    assert _to_baostock_code("HSI", "index") is None
    assert _to_baostock_code("US10Y", "index") is None


def test_fetch_index_daily_normalizes(monkeypatch):
    fake_bs = __import__("sys").modules["baostock"]
    fake_bs.query_history_k_data_plus.return_value = _FakeResult(rows=_kline_rows())
    df = BaostockDataSource().fetch_index_daily("000300")
    assert list(df.columns)[:7] == ["trade_date", "open", "close", "high", "low", "volume", "amount"]
    assert len(df) == 2
    assert df["trade_date"].is_monotonic_increasing
    assert df["trade_date"].iloc[0] == date(2026, 6, 18)
    assert df["close"].iloc[-1] == 11.0
    assert df["volume"].dtype.kind in "iu"  # volume 转 int


def test_fetch_etf_daily_normalizes(monkeypatch):
    fake_bs = __import__("sys").modules["baostock"]
    fake_bs.query_history_k_data_plus.return_value = _FakeResult(rows=_kline_rows())
    df = BaostockDataSource().fetch_etf_daily("510300")
    assert len(df) == 2
    assert df["close"].iloc[0] == 10.5


def test_query_error_returns_empty(monkeypatch):
    """query 返回 error_code != '0' → 空 DataFrame, 不抛异常."""
    fake_bs = __import__("sys").modules["baostock"]
    fake_bs.query_history_k_data_plus.return_value = _FakeResult(error_code="1", error_msg="no data")
    df = BaostockDataSource().fetch_index_daily("000300")
    assert df.empty


def test_empty_rows_returns_empty(monkeypatch):
    fake_bs = __import__("sys").modules["baostock"]
    fake_bs.query_history_k_data_plus.return_value = _FakeResult(rows=[])
    df = BaostockDataSource().fetch_index_daily("000300")
    assert df.empty


def test_hk_index_not_implemented():
    with pytest.raises(NotImplementedMarker):
        BaostockDataSource().fetch_index_daily("HSI")


def test_bond_not_implemented():
    with pytest.raises(NotImplementedMarker):
        BaostockDataSource().fetch_index_daily("US10Y")


def test_forex_not_implemented():
    with pytest.raises(NotImplementedMarker):
        BaostockDataSource().fetch_index_daily("USDCNY")


def test_macro_proxy_not_implemented():
    with pytest.raises(NotImplementedMarker):
        BaostockDataSource().fetch_macro_proxy("us_treasury_10y")


def test_hk_stock_not_implemented():
    with pytest.raises(NotImplementedMarker):
        BaostockDataSource().fetch_stock_daily("00700", market="HK")


def test_ensure_login_idempotent(monkeypatch):
    """_ensure_login 只调用 bs.login 一次 (进程级单例)."""
    bsrc._logged_in = False
    call_count = {"n": 0}
    import sys

    class _FakeBS:
        @staticmethod
        def login():
            call_count["n"] += 1
            return SimpleNamespace(error_code="0", error_msg="success")

    # 恢复真实的 _ensure_login (本测试专测它)
    monkeypatch.setattr(bsrc, "_ensure_login", _ensure_login)
    sys.modules["baostock"] = _FakeBS
    _ensure_login()
    _ensure_login()
    _ensure_login()
    assert call_count["n"] == 1


def test_login_failure_raises(monkeypatch):
    """bs.login 返回非 0 → _ensure_login 抛 RuntimeError."""
    bsrc._logged_in = False
    import sys
    monkeypatch.setattr(bsrc, "_ensure_login", _ensure_login)

    class _FakeBS:
        @staticmethod
        def login():
            return SimpleNamespace(error_code="1001", error_msg="auth failed")

    sys.modules["baostock"] = _FakeBS
    with pytest.raises(RuntimeError, match="baostock login failed"):
        _ensure_login()
