"""GuosenDataSource — 国信备用源,实现 DataSource 契约.

定位 (per plan KTD7): 优先指数/ETF/宏观代理 fetch;个股 fetch 返回 NotImplementedMarker
让 registry 跳过它直接用 akshare (沪深300个股由 akshare 主导).

注意: 国信 queryPastHQInfo 只能取"近N个交易日",无法指定日期范围或全量历史.
所以这里把 start/end 当作"取近端N天"的近似 —— 用 want_nums 大值(如 5000)尽量覆盖,
再按 start/end 裁剪. 全量历史回填仍由 akshare 负责.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.services.data import guosen_client
from app.services.data.base import DataSource
from app.services.data.guosen_client import SET_CODE, GuosenError


class NotImplementedMarker(Exception):
    """该源不支持此品类/方法,registry 应跳过它用下一个源."""


# 国信行情返回字段名 → 归一化名 (宽松匹配,实际字段以响应为准).
_FIELD_ALIASES = {
    "date": "trade_date", "日期": "trade_date", "f1": "trade_date", "time": "trade_date",
    "open": "open", "开盘": "open", "f2": "open",
    "close": "close", "收盘": "close", "f3": "close",
    "high": "high", "最高": "high", "f4": "high",
    "low": "low", "最低": "low", "f5": "low",
    "volume": "volume", "成交量": "volume", "f6": "volume",
    "amount": "amount", "成交额": "amount", "f7": "amount",
}


def _parse_past_hq(resp: dict) -> pd.DataFrame:
    """把国信 queryPastHQInfo 响应解析为归一化 DataFrame.

    响应结构以国信实际返回为准,这里宽松处理: 在 resp 里找包含 dict 记录的列表.
    """
    # 常见结构: {"data": [...], ...} 或直接是 list, 或 {"data": {"data": [...]}}
    rows = resp
    if isinstance(resp, dict):
        for key in ("data", "result", "list"):
            if key in resp:
                rows = resp[key]
                break
    if isinstance(rows, dict):
        # 再挖一层
        for key in ("data", "result", "list"):
            if key in rows:
                rows = rows[key]
                break
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # 列名归一化
    rename = {c: _FIELD_ALIASES.get(str(c).lower(), _FIELD_ALIASES.get(str(c)))
              for c in df.columns}
    df = df.rename(columns=rename)

    if "trade_date" not in df.columns:
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    for col in ("open", "close", "high", "low", "amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.dropna(subset=["trade_date"])
    keep = [c for c in ["trade_date", "open", "close", "high", "low", "volume", "amount"] if c in df.columns]
    return df[keep].sort_values("trade_date").reset_index(drop=True)


def _market_to_setcode(market: str) -> int:
    m = market.upper()
    if m in ("A", "SH", "SZ", "BJ"):
        return SET_CODE["SH"]  # 个股由 code 前缀决定, 这里用上海作默认; 指数走 queryPastHQInfo 用 setCode=1
    if m == "HK":
        return SET_CODE["HK"]
    if m == "US":
        return SET_CODE["US"]
    return SET_CODE["SH"]


class GuosenDataSource(DataSource):
    name = "guosen"

    def fetch_index_daily(self, code: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        resp = guosen_client.query_past_hq(code, set_code=SET_CODE["SH"], want_nums=5000)
        df = _parse_past_hq(resp)
        return _clip(df, start, end)

    def fetch_etf_daily(self, code: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        resp = guosen_client.query_past_hq(code, set_code=SET_CODE["SH"], want_nums=5000)
        df = _parse_past_hq(resp)
        return _clip(df, start, end)

    def fetch_stock_daily(self, code: str, market: str = "A", start: date | None = None, end: date | None = None) -> pd.DataFrame:
        """个股由 akshare 主导,国信标记不支持 → registry 跳过."""
        raise NotImplementedMarker("国信不作为个股主源 (沪深300个股由 akshare 负责)")

    def fetch_macro_proxy(self, name: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        """国信不支持宏观代理 (国债ETF/美债10Y),标记不支持."""
        raise NotImplementedMarker(f"国信不支持宏观代理 {name}")


def _clip(df: pd.DataFrame, start: date | None, end: date | None) -> pd.DataFrame:
    if df.empty:
        return df
    if start:
        df = df[df["trade_date"] >= start]
    if end:
        df = df[df["trade_date"] <= end]
    return df.reset_index(drop=True)


__all__ = ["GuosenDataSource", "NotImplementedMarker", "GuosenError"]
