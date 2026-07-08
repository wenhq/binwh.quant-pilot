"""AkshareDataSource — 主数据源,实现 DataSource 契约.

封装 akshare 同步调用 (akshare 是同步阻塞库,调用方应在线程池中执行).
各品类接口映射:
- A股指数: index_zh_a_hist (东方财富), 失败 fallback 到 stock_zh_index_daily (新浪, 全量+裁剪)
- ETF: fund_etf_hist_em
- A股个股: stock_zh_a_daily
- 港股: stock_hk_daily
- 美债10Y代理: bond_zh_us_rate

空数据返回空 DataFrame (不抛异常),源端异常向上抛供 registry 切源.
"""
from __future__ import annotations

from datetime import date

import akshare as ak
import pandas as pd

from app.services.data.base import DataSource
from app.services.data.normalizer import normalize_daily


def _fmt(d: date | None) -> str | None:
    return d.strftime("%Y%m%d") if d else None


def _to_sina_symbol(code: str) -> str | None:
    """裸指数/ETF 代码 → 新浪/腾讯 symbol (带交易所前缀).
    指数: 000/950 系沪, 399 系深. ETF: 5xx 系沪, 1xx(159) 系深.
    """
    c = code.strip().upper()
    if c.startswith(("SH", "SZ")) and len(c) >= 8:
        return c.lower()
    digits = "".join(ch for ch in c if ch.isdigit())
    if len(digits) != 6:
        return None
    if digits.startswith(("000", "950")):  # 沪深300/上证50/中证系列多在沪
        return "sh" + digits
    if digits.startswith("399"):  # 深证系列指数
        return "sz" + digits
    if digits.startswith("15") or digits.startswith("16") or digits.startswith("18"):  # 深市 ETF
        return "sz" + digits
    if digits.startswith(("50", "51", "52", "56", "58")):  # 沪市 ETF/基金
        return "sh" + digits
    return "sh" + digits  # 默认沪


def _clip_by_date(df: pd.DataFrame, start: date | None, end: date | None) -> pd.DataFrame:
    if df.empty:
        return df
    if start:
        df = df[df["trade_date"] >= start]
    if end:
        df = df[df["trade_date"] <= end]
    return df.reset_index(drop=True)


def _tencent_sina_fallback(code: str, start: date | None, end: date | None) -> pd.DataFrame:
    sina = _to_sina_symbol(code)
    if not sina:
        return pd.DataFrame()
    # 腾讯 (有 amount, 列: date/open/close/high/low/amount; 无 volume)
    try:
        df = ak.stock_zh_index_daily_tx(
            symbol=sina, start_date=_fmt(start) or "19900101", end_date=_fmt(end) or "20991231",
        )
        if df is not None and not df.empty:
            df = df.copy()
            if "volume" not in df.columns:
                df["volume"] = 0  # 腾讯无 volume, 填 0 (amount 已保留成交信息)
            norm = normalize_daily(df)
            if not norm.empty:
                return norm
    except Exception:
        pass
    # 新浪 (有 volume, 无 amount; 全量返回需裁剪)
    df = ak.stock_zh_index_daily(symbol=sina)
    norm = normalize_daily(df)
    return _clip_by_date(norm, start, end)


# 非纯数字指数代码 → 对应新浪源 (港股指数 / 国债收益率 / 外汇).
_HK_INDEX_SYMBOLS = {"HSI", "HSTECH", "HSCEI", "CES100"}
# 国债代码 → (新浪接口函数名, 标的名称). 美债走 bond_gb_us_sina, 中国国债走 bond_gb_zh_sina.
_BOND_MAP = {
    "US10Y": ("bond_gb_us_sina", "美国10年期国债"),
    "US2Y": ("bond_gb_us_sina", "美国2年期国债"),
    "US30Y": ("bond_gb_us_sina", "美国30年期国债"),
    "CN10Y": ("bond_gb_zh_sina", "中国10年期国债"),
    "CN2Y": ("bond_gb_zh_sina", "中国2年期国债"),
    "CN30Y": ("bond_gb_zh_sina", "中国30年期国债"),
}
# 外汇代码 → 新浪中行外汇牌价标的. 取央行中间价作为 close (单值序列当伪指数).
_FX_MAP = {"USDCNY": "美元"}


def _fx_to_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """中行外汇牌价 → OHLC 伪指数: 日期→trade_date, 央行中间价填 OHLC, volume=0."""
    if df is None or df.empty:
        return pd.DataFrame()
    date_col = next((c for c in df.columns if "日期" in str(c)), None)
    mid_col = next((c for c in df.columns if "中间价" in str(c)), None)
    if date_col is None or mid_col is None:
        return pd.DataFrame()
    out = pd.DataFrame({
        "trade_date": pd.to_datetime(df[date_col], errors="coerce").dt.date,
        "close": pd.to_numeric(df[mid_col], errors="coerce"),
    }).dropna(subset=["trade_date", "close"])
    out["open"] = out["high"] = out["low"] = out["close"]
    out["volume"] = 0
    return out.sort_values("trade_date").reset_index(drop=True)


def _special_index_fallback(code: str, start: date | None, end: date | None) -> pd.DataFrame:
    """非纯数字指数代码取数: 港股指数 → 新浪港股指数; 国债 → 新浪国债; 外汇 → 新浪中行牌价 (央行中间价)."""
    if code in _BOND_MAP:
        fn_name, symbol = _BOND_MAP[code]
        try:
            df = getattr(ak, fn_name)(symbol=symbol)
            norm = normalize_daily(df)
            return _clip_by_date(norm, start, end)
        except Exception:
            return pd.DataFrame()
    if code in _FX_MAP:
        try:
            df = ak.currency_boc_sina(symbol=_FX_MAP[code], start_date=_fmt(start) or "19900101",
                                      end_date=_fmt(end) or "20991231")
            norm = _fx_to_ohlc(df)
            return _clip_by_date(norm, start, end)
        except Exception:
            return pd.DataFrame()
    if code in _HK_INDEX_SYMBOLS:
        try:
            df = ak.stock_hk_index_daily_sina(symbol=code)
            norm = normalize_daily(df)
            return _clip_by_date(norm, start, end)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


class AkshareDataSource(DataSource):
    name = "akshare"

    def fetch_index_daily(self, code: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        """非纯数字代码 → 特殊源: 港股指数(HSI/HSTECH)走新浪港股指数, 美债(US10Y)走新浪美债.
        A股数字指数: 腾讯 (amount) → 新浪 (volume) 两级回退.

        注: 东方财富 index_zh_a_hist 经 mini_racer 跑反爬 JS, V8 isolate 非线程安全,
        在 run_in_executor 工作线程里会 FATAL 崩进程; 且该端点本就被反爬限制, 故跳过东财直接走腾讯/新浪.
        """
        sym = code.strip()
        if not sym.isdigit():
            return _special_index_fallback(sym.upper(), start, end)
        return _tencent_sina_fallback(code, start, end)

    def fetch_etf_daily(self, code: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        """两级回退: 腾讯 (amount) → 新浪 (volume).

        东财 fund_etf_hist_em 同样经 mini_racer, 线程不安全, 跳过 (理由同 fetch_index_daily).
        """
        return _tencent_sina_fallback(code, start, end)

    def fetch_stock_daily(self, code: str, market: str = "A", start: date | None = None, end: date | None = None) -> pd.DataFrame:
        if market.upper() == "HK":
            # stock_hk_daily 不支持 start/end,返回全量后由调用方/归一化器裁剪.
            df = ak.stock_hk_daily(symbol=code, adjust="")
            df = normalize_daily(df)
            if start:
                df = df[df["trade_date"] >= start]
            if end:
                df = df[df["trade_date"] <= end]
            return df.reset_index(drop=True)
        df = ak.stock_zh_a_daily(symbol=code, start_date=_fmt(start), end_date=_fmt(end), adjust="")
        return normalize_daily(df)

    def fetch_macro_proxy(self, name: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        """宏观代理. 当前支持美债10Y (bond_zh_us_rate). 其他代理后续按需扩展."""
        if name == "us_treasury_10y":
            # bond_zh_us_rate 返回 中国/美国 多期限收益率,取 美10Y.
            raw = ak.bond_zh_us_rate(start_date=_fmt(start) or "20170101")
            if raw is None or raw.empty:
                return pd.DataFrame()
            # 列名含 "收益率" 类,选美国10年. 实际列名以 akshare 返回为准,这里宽松匹配.
            df = raw.copy()
            # 归一化为 (trade_date, close) 形态,复用 OHLCV 中 close 列.
            date_col = next((c for c in df.columns if "日期" in str(c) or c.lower() == "date"), df.columns[0])
            df = df.rename(columns={date_col: "trade_date"})
            df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
            us10y_col = next((c for c in df.columns if "美国" in str(c) and "10" in str(c)), None)
            if us10y_col is None:
                return pd.DataFrame()
            out = df[["trade_date", us10y_col]].rename(columns={us10y_col: "close"}).dropna()
            out["close"] = pd.to_numeric(out["close"], errors="coerce")
            out = out.dropna(subset=["close"])
            if start:
                out = out[out["trade_date"] >= start]
            if end:
                out = out[out["trade_date"] <= end]
            return out.sort_values("trade_date").reset_index(drop=True)
        # 未实现的代理返回空,让 registry 决定是否 fallback.
        return pd.DataFrame()
