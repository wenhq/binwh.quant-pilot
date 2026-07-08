"""U5 tests: 标的池构建 (mock akshare).

验证:
- 沪深300成分股解析 + 总市值合并 + 市值降序
- 市值取不到时维持成分股原序 (na_position=last)
- _infer_market 代码归属
- build_universe 聚合 个股+指数+ETF+宏观
- 核心指数/ETF/宏观列表非空
"""
from __future__ import annotations

import pandas as pd

from app.services.data import universe as U


def _cons_df():
    return pd.DataFrame({
        "成分券代码": ["600519", "000001", "300750"],
        "成分券名称": ["贵州茅台", "平安银行", "宁德时代"],
    })


def _spot_df():
    return pd.DataFrame({
        "代码": ["000001", "600519", "300750"],
        "名称": ["平安银行", "贵州茅台", "宁德时代"],
        "总市值": [2.5e11, 2.0e12, 8.0e11],
    })


def test_build_stock_universe_sorts_by_market_cap_desc(monkeypatch):
    monkeypatch.setattr(U.ak, "index_stock_cons_csindex", lambda **kw: _cons_df())
    monkeypatch.setattr(U.ak, "stock_zh_a_spot_em", lambda *a, **kw: _spot_df())
    stocks = U.build_stock_universe("000300")
    codes = [s["code"] for s in stocks]
    # 总市值: 茅台2e12 > 宁德8e11 > 平安2.5e11 → 降序
    assert codes == ["600519", "300750", "000001"]
    assert stocks[0]["market_cap"] == 2.0e12
    assert stocks[0]["name"] == "贵州茅台"
    assert stocks[0]["market"] == "SH"


def test_market_cap_unavailable_preserves_constituent_order(monkeypatch):
    """spot_em 失败 → 无市值, 维持成分股原序 (na_position=last)."""
    monkeypatch.setattr(U.ak, "index_stock_cons_csindex", lambda **kw: _cons_df())

    def boom(*a, **kw):
        raise ConnectionError("spot down")
    monkeypatch.setattr(U.ak, "stock_zh_a_spot_em", boom)
    stocks = U.build_stock_universe("000300")
    codes = [s["code"] for s in stocks]
    assert codes == ["600519", "000001", "300750"]  # 成分股原序
    assert all(s["market_cap"] is None for s in stocks)


def test_empty_constituents_returns_empty(monkeypatch):
    monkeypatch.setattr(U.ak, "index_stock_cons_csindex", lambda **kw: pd.DataFrame())
    assert U.build_stock_universe("000300") == []


def test_infer_market():
    assert U._infer_market("600519") == "SH"
    assert U._infer_market("000001") == "SZ"
    assert U._infer_market("300750") == "SZ"
    assert U._infer_market("688981") == "SH"
    assert U._infer_market("830799") == "BJ"


def test_core_lists_non_empty():
    assert len(U.CORE_INDICES) >= 4
    assert any(i["code"] == "000300" for i in U.CORE_INDICES)
    assert any(i["market"] == "HK" for i in U.CORE_INDICES)
    # 美债10Y 作为伪指数并入 CORE_INDICES
    assert any(i["code"] == "US10Y" for i in U.CORE_INDICES)
    assert len(U.CORE_ETF) >= 4


def test_build_universe_aggregates_all(monkeypatch):
    monkeypatch.setattr(U.ak, "index_stock_cons_csindex", lambda **kw: _cons_df())
    monkeypatch.setattr(U.ak, "stock_zh_a_spot_em", lambda *a, **kw: _spot_df())
    uni = U.build_universe("000300")
    assert len(uni.stocks) == 3
    assert len(uni.indices) == len(U.CORE_INDICES)
    assert len(uni.etfs) == len(U.CORE_ETF) + len(U.SECTOR_ETF)
    assert uni.macro_proxies == []
    assert uni.total() == len(uni.stocks) + len(uni.indices) + len(uni.etfs)
