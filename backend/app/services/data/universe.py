"""Universe 构建 — 标的池优先级.

按用户要求: 标的池优先看沪深300成分股, 从大市值开始.
- 个股: akshare index_stock_cons_csindex('000300') 取成分股,
        叠加 stock_zh_a_spot_em 的总市值, 按市值降序.
- 指数: 硬编码核心宽基 (沪深300/上证50/中证500/中证1000/恒生指数/恒生科技).
- ETF: 硬编码核心宽基ETF (510300/510050/510500/512100/513180/510310).
- 宏观代理: 美债10Y (us_treasury_10y).

设计: 这些函数返回纯数据结构 (list[dict]), 不写库 —— 写库由 U6 导入器负责,
这样 universe 可独立测试且复用.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import akshare as ak
import pandas as pd


CORE_INDICES = [
    {"code": "000001", "name": "上证综指", "market": "SH", "category": "宽基", "data_source": "东财/腾讯/新浪"},
    {"code": "399001", "name": "深证成指", "market": "SZ", "category": "宽基", "data_source": "东财/腾讯/新浪"},
    {"code": "399006", "name": "创业板指", "market": "SZ", "category": "成长", "data_source": "东财/腾讯/新浪"},
    {"code": "000688", "name": "科创50", "market": "SH", "category": "成长", "data_source": "东财/腾讯/新浪"},
    {"code": "000300", "name": "沪深300", "market": "SH", "category": "宽基", "data_source": "东财/腾讯/新浪"},
    {"code": "000016", "name": "上证50", "market": "SH", "category": "宽基", "data_source": "东财/腾讯/新浪"},
    {"code": "000905", "name": "中证500", "market": "SH", "category": "宽基", "data_source": "东财/腾讯/新浪"},
    {"code": "000852", "name": "中证1000", "market": "SH", "category": "宽基", "data_source": "东财/腾讯/新浪"},
    {"code": "HSI", "name": "恒生指数", "market": "HK", "category": "港股宽基", "data_source": "新浪港股指数"},
    {"code": "HSTECH", "name": "恒生科技", "market": "HK", "category": "港股科技", "data_source": "新浪港股指数"},
    {"code": "CN10Y", "name": "中国10年期国债收益率", "market": "CN", "category": "国债", "data_source": "新浪中国国债 bond_gb_zh_sina"},
    {"code": "US10Y", "name": "美国10年期国债收益率", "market": "US", "category": "国债", "data_source": "新浪美国国债 bond_gb_us_sina"},
    {"code": "USDCNY", "name": "美元兑人民币(央行中间价)", "market": "FX", "category": "汇率", "data_source": "新浪中行外汇 currency_boc_sina"},
]

CORE_ETF = [
    {"code": "510300", "name": "沪深300ETF", "tracks": "000300", "category": "宽基", "data_source": "东财/腾讯/新浪"},
    {"code": "510050", "name": "上证50ETF", "tracks": "000016", "category": "宽基", "data_source": "东财/腾讯/新浪"},
    {"code": "510500", "name": "中证500ETF", "tracks": "000905", "category": "宽基", "data_source": "东财/腾讯/新浪"},
    {"code": "512100", "name": "中证1000ETF", "tracks": "000852", "category": "宽基", "data_source": "东财/腾讯/新浪"},
    {"code": "513180", "name": "恒生科技ETF", "tracks": "HSTECH", "category": "港股科技", "data_source": "东财/腾讯/新浪"},
    {"code": "510310", "name": "沪深300ETF易方达", "tracks": "000300", "category": "宽基", "data_source": "东财/腾讯/新浪"},
]

# 行业/板块 ETF — 结构分化信号 (成长vs价值、进攻vs防御、周期vs非周期).
SECTOR_ETF = [
    {"code": "512800", "name": "银行ETF", "category": "金融", "data_source": "东财/腾讯/新浪"},
    {"code": "510230", "name": "金融ETF", "category": "金融", "data_source": "东财/腾讯/新浪"},
    {"code": "159928", "name": "消费ETF", "category": "消费", "data_source": "东财/腾讯/新浪"},
    {"code": "512010", "name": "医药ETF", "category": "医药", "data_source": "东财/腾讯/新浪"},
    {"code": "512400", "name": "有色ETF", "category": "周期资源", "data_source": "东财/腾讯/新浪"},
    {"code": "515220", "name": "煤炭ETF", "category": "周期资源", "data_source": "东财/腾讯/新浪"},
    {"code": "512480", "name": "半导体ETF", "category": "科技成长", "data_source": "东财/腾讯/新浪"},
    {"code": "512660", "name": "军工ETF", "category": "科技成长", "data_source": "东财/腾讯/新浪"},
    {"code": "510880", "name": "红利ETF", "category": "红利防御", "data_source": "东财/腾讯/新浪"},
    {"code": "515030", "name": "新能源车ETF", "category": "新能源", "data_source": "东财/腾讯/新浪"},
    {"code": "515790", "name": "光伏ETF", "category": "新能源", "data_source": "东财/腾讯/新浪"},
    {"code": "159819", "name": "人工智能ETF", "category": "AI主题", "data_source": "东财/腾讯/新浪"},
    {"code": "512880", "name": "证券ETF", "category": "金融", "data_source": "东财/腾讯/新浪"},
    {"code": "159805", "name": "传媒ETF", "category": "TMT", "data_source": "东财/腾讯/新浪"},
]

# 宏观代理当前已并入 CORE_INDICES (US10Y 当作伪指数入库). 保留列表供未来非指数类代理扩展.
MACRO_PROXIES = []


@dataclass
class Universe:
    stocks: list[dict] = field(default_factory=list)  # {code,name,market,market_cap}
    indices: list[dict] = field(default_factory=list)
    etfs: list[dict] = field(default_factory=list)
    macro_proxies: list[str] = field(default_factory=list)

    def total(self) -> int:
        return len(self.stocks) + len(self.indices) + len(self.etfs) + len(self.macro_proxies)


def _merge_market_cap(cons_df: pd.DataFrame) -> pd.DataFrame:
    """成分股表 + 实时行情总市值 → 合并, 返回带 market_cap 列的 DataFrame.

    akshare index_stock_cons_csindex 返回列顺序固定:
    日期 / 指数代码 / 指数名称 / 指数英文名称 / 成分券代码 / 成分券名称 / ...
    按位置取第 5 列 (成分券代码) 和第 6 列 (成分券名称), 避免被'指数代码'等干扰.
    """
    if cons_df is None or cons_df.empty:
        return pd.DataFrame()
    cols = list(cons_df.columns)
    if len(cols) < 6:
        return pd.DataFrame()

    cons = cons_df.rename(columns={cols[4]: "code", cols[5]: "name"})
    cons["code"] = cons["code"].astype(str).str.zfill(6)
    cons["name"] = cons["name"].astype(str)

    # 取 A 股实时行情的总市值用于排序. 失败则按成分股原顺序 (无市值降序).
    try:
        spot = ak.stock_zh_a_spot_em()
        cap_col = next((c for c in spot.columns if "总市值" in str(c)), None)
        sym_col = next((c for c in spot.columns if "代码" in str(c)), None)
        if spot is not None and not spot.empty and cap_col and sym_col:
            caps = spot.rename(columns={sym_col: "code", cap_col: "market_cap"})[["code", "market_cap"]]
            caps["code"] = caps["code"].astype(str).str.zfill(6)
            cons = cons.merge(caps, on="code", how="left")
            cons["market_cap"] = pd.to_numeric(cons["market_cap"], errors="coerce")
    except Exception:
        cons["market_cap"] = pd.NA
    if "market_cap" not in cons.columns:
        cons["market_cap"] = pd.NA
    return cons


def build_stock_universe(index_code: str = "000300") -> list[dict]:
    """沪深300成分股, 按总市值降序. market_cap 取不到时维持成分股原序.

    每项: {code, name, market, market_cap}.
    """
    cons = ak.index_stock_cons_csindex(symbol=index_code)
    merged = _merge_market_cap(cons)
    if merged.empty:
        return []
    merged = merged.sort_values("market_cap", ascending=False, na_position="last")
    out: list[dict] = []
    for _, row in merged.iterrows():
        code = str(row["code"]).zfill(6)
        name = row.get("name")
        out.append({
            "code": code,
            "name": str(name) if name is not None else None,
            "market": _infer_market(code),
            "market_cap": float(row["market_cap"]) if pd.notna(row.get("market_cap")) else None,
        })
    return out


def _infer_market(code: str) -> str:
    """A 股代码 → 市场归属 (SH/SZ/BJ)."""
    c = code.zfill(6)
    if c.startswith(("60", "68", "90", "11", "13")):
        return "SH"
    if c.startswith(("00", "30", "12", "15", "18")):
        return "SZ"
    if c.startswith(("43", "83", "87", "88", "92")):
        return "BJ"
    return "SH"


def build_universe(index_code: str = "000300") -> Universe:
    """构建完整标的池: 沪深300个股(市值降序) + 核心指数 + 宽基ETF + 行业ETF + 宏观代理."""
    return Universe(
        stocks=build_stock_universe(index_code),
        indices=list(CORE_INDICES),
        etfs=list(CORE_ETF) + list(SECTOR_ETF),
        macro_proxies=list(MACRO_PROXIES),
    )


__all__ = [
    "Universe",
    "build_universe",
    "build_stock_universe",
    "CORE_INDICES",
    "CORE_ETF",
    "SECTOR_ETF",
    "MACRO_PROXIES",
]
