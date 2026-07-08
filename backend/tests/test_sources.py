"""U2 tests: DataSource 抽象 + akshare 实现 (mock).

不依赖网络. mock akshare 各接口返回,验证归一化契约:
- 各品类 fetch 返回归一化列 (trade_date/open/...),日期升序
- 空返回 → 空 DataFrame (不抛异常)
- 源端异常 → 向上抛 (供 registry 切源)
"""
from datetime import date

import pandas as pd
import pytest

from app.services.data import akshare_source
from app.services.data.akshare_source import AkshareDataSource
from app.services.data import guosen_client, guosen_source
from app.services.data.guosen_source import GuosenDataSource, NotImplementedMarker


def _cn_df():
    """akshare 中文列名样本 (东方财富系列: 个股/指数/ETF)."""
    return pd.DataFrame({
        "日期": ["2026-06-18", "2026-06-19", "2026-06-20"],
        "开盘": [10.0, 10.5, 10.8],
        "收盘": [10.5, 10.8, 11.0],
        "最高": [10.8, 11.0, 11.2],
        "最低": [9.9, 10.4, 10.7],
        "成交量": [100000, 120000, 90000],
        "成交额": [1.05e6, 1.3e6, 9.9e5],
    })


def _en_df():
    """akshare 港股 stock_hk_daily 英文列名样本."""
    return pd.DataFrame({
        "date": ["2026-06-18", "2026-06-19"],
        "open": [440.0, 441.0],
        "high": [446.0, 442.0],
        "low": [435.0, 438.0],
        "close": [440.2, 441.5],
        "volume": [3.0e7, 2.8e7],
        "amount": [1.3e10, 1.2e10],
    })


def test_fetch_index_daily_normalizes(monkeypatch):
    # 东财经 mini_racer 线程不安全已跳过, 指数走腾讯 stock_zh_index_daily_tx.
    monkeypatch.setattr(akshare_source.ak, "stock_zh_index_daily_tx", lambda **kw: _cn_df())
    df = AkshareDataSource().fetch_index_daily("000300")
    assert list(df.columns)[:7] == ["trade_date", "open", "close", "high", "low", "volume", "amount"]
    assert df["trade_date"].is_monotonic_increasing
    assert df["trade_date"].iloc[0] == date(2026, 6, 18)


def test_fetch_etf_daily_normalizes(monkeypatch):
    # ETF 同样走腾讯 stock_zh_index_daily_tx (与指数同前缀规则).
    monkeypatch.setattr(akshare_source.ak, "stock_zh_index_daily_tx", lambda **kw: _cn_df())
    df = AkshareDataSource().fetch_etf_daily("511260")
    assert len(df) == 3
    assert df["close"].iloc[-1] == 11.0


def test_fetch_stock_daily_a_share(monkeypatch):
    monkeypatch.setattr(akshare_source.ak, "stock_zh_a_daily", lambda **kw: _cn_df())
    df = AkshareDataSource().fetch_stock_daily("600519", market="A")
    assert df["volume"].dtype.kind in "iu"
    assert len(df) == 3


def test_fetch_stock_daily_hk_filters_by_date(monkeypatch):
    monkeypatch.setattr(akshare_source.ak, "stock_hk_daily", lambda **kw: _en_df())
    df = AkshareDataSource().fetch_stock_daily(
        "00700", market="HK", start=date(2026, 6, 19), end=date(2026, 6, 20)
    )
    assert len(df) == 1
    assert df["trade_date"].iloc[0] == date(2026, 6, 19)


def test_empty_return_is_empty_df_not_exception(monkeypatch):
    """所有指数源都返回空 → 最终返回空 DataFrame (让 registry 决定 fallback)."""
    monkeypatch.setattr(akshare_source.ak, "stock_zh_index_daily_tx", lambda **kw: pd.DataFrame())
    monkeypatch.setattr(akshare_source.ak, "stock_zh_index_daily", lambda **kw: pd.DataFrame())
    df = AkshareDataSource().fetch_index_daily("000300")
    assert df.empty


def test_source_exception_propagates(monkeypatch):
    """主源(腾讯)异常被吞后 fallback; 最终兜底源(新浪)异常 → 向上抛 (供 registry 切源)."""
    def boom(*a, **kw):
        raise ConnectionError("source down")
    monkeypatch.setattr(akshare_source.ak, "stock_zh_index_daily_tx", boom)
    monkeypatch.setattr(akshare_source.ak, "stock_zh_index_daily", boom)
    with pytest.raises(ConnectionError):
        AkshareDataSource().fetch_index_daily("000300")


def test_macro_proxy_us_treasury(monkeypatch):
    raw = pd.DataFrame({
        "日期": ["2026-06-18", "2026-06-19"],
        "中国国债收益率10年": [2.3, 2.31],
        "美国国债收益率10年": [4.25, 4.27],
    })
    monkeypatch.setattr(akshare_source.ak, "bond_zh_us_rate", lambda **kw: raw)
    df = AkshareDataSource().fetch_macro_proxy("us_treasury_10y")
    assert list(df.columns) == ["trade_date", "close"]
    assert df["close"].iloc[0] == 4.25


def test_macro_proxy_unknown_returns_empty():
    assert AkshareDataSource().fetch_macro_proxy("nonexistent_proxy").empty


# ----- U3: GuosenDataSource (mock HTTP) -----


def _guosen_past_hq_resp():
    """国信 queryPastHQInfo 典型响应 (data 列表 + 中文字段)."""
    return {
        "code": 0,
        "data": [
            {"日期": "2026-06-18", "开盘": 4000.0, "收盘": 4010.0, "最高": 4020.0, "最低": 3990.0, "成交量": 0, "成交额": 0},
            {"日期": "2026-06-19", "开盘": 4010.0, "收盘": 4025.0, "最高": 4030.0, "最低": 4005.0, "成交量": 0, "成交额": 0},
        ],
    }


def test_guosen_fetch_index_normalizes(monkeypatch):
    monkeypatch.setattr(guosen_client, "query_past_hq", lambda *a, **kw: _guosen_past_hq_resp())
    df = GuosenDataSource().fetch_index_daily("000300")
    assert not df.empty
    assert "trade_date" in df.columns and "close" in df.columns
    assert df["trade_date"].is_monotonic_increasing
    assert df["close"].iloc[-1] == 4025.0


def test_guosen_fetch_index_clips_by_date(monkeypatch):
    monkeypatch.setattr(guosen_client, "query_past_hq", lambda *a, **kw: _guosen_past_hq_resp())
    df = GuosenDataSource().fetch_index_daily("000300", start=date(2026, 6, 19), end=date(2026, 6, 20))
    assert len(df) == 1
    assert df["trade_date"].iloc[0] == date(2026, 6, 19)


def test_guosen_stock_not_supported(monkeypatch):
    """个股由 akshare 主导,国信标记不支持 → NotImplementedMarker."""
    with pytest.raises(NotImplementedMarker):
        GuosenDataSource().fetch_stock_daily("600519", market="A")


def test_guosen_macro_not_supported():
    with pytest.raises(NotImplementedMarker):
        GuosenDataSource().fetch_macro_proxy("us_treasury_10y")


def test_guosen_empty_response(monkeypatch):
    monkeypatch.setattr(guosen_client, "query_past_hq", lambda *a, **kw: {"data": []})
    assert GuosenDataSource().fetch_index_daily("000300").empty


def test_guosen_auth_failure_raises(monkeypatch):
    """鉴权失败/限免过期 → GuosenError (供 registry 切回主源)."""
    def boom(*a, **kw):
        raise guosen_client.GuosenError("HTTP 401: 鉴权失效")
    monkeypatch.setattr(guosen_client, "query_past_hq", boom)
    with pytest.raises(guosen_client.GuosenError):
        GuosenDataSource().fetch_index_daily("000300")


def test_guosen_missing_api_key_raises(monkeypatch):
    """GS_API_KEY 缺失 → GuosenError (启动期可发现)."""
    monkeypatch.setattr(guosen_client.settings, "gs_api_key", None)
    with pytest.raises(guosen_client.GuosenError):
        GuosenDataSource().fetch_index_daily("000300")
