"""BaostockDataSource — 主数据源 (替代 akshare 主路径).

为什么用 baostock: akshare 1.18.64 依赖的 mini-racer (V8) 在 macOS arm64 间歇崩溃,
腾讯接口也偶发不稳; baostock 是纯 HTTP 接口, 无 JS/V8 依赖, 稳定可靠.

覆盖范围:
- A股指数 (000xxx/399xxx 等) → bs.query_history_k_data_plus
- A股 ETF (51xxxx/15xxxx 等) → 同上
- A股个股 (沪深) → 同上
- 港股指数 / 国债收益率 / 外汇 → NotImplementedMarker (留给 akshare 新浪接口回退)

baostock 是同步阻塞 + 进程级 login, 调用方应在线程池中执行 (registry 已做 run_in_executor).
login 用 threading.Lock + 进程内标志保证只登一次; 多次调用幂等.
"""
from __future__ import annotations

import logging
import threading
from datetime import date

import pandas as pd

from app.services.data.base import DataSource
from app.services.data.guosen_source import NotImplementedMarker
from app.services.data.normalizer import normalize_daily

logger = logging.getLogger(__name__)

# baostock 不支持的标的代码前缀/集合 → 让 registry 回退 akshare.
# 港股指数 (HSI/HSTECH)、国债 (CN10Y/US10Y)、外汇 (USDCNY) 由 akshare 新浪源负责.
_NON_A_SHARE_TOKENS = {"HSI", "HSTECH", "HSCEI", "CES100", "CN10Y", "US10Y", "US2Y",
                       "US30Y", "CN2Y", "CN30Y", "USDCNY"}

_login_lock = threading.Lock()
_logged_in = False
# baostock 用全局 session, 非线程安全: 并发 query 会死锁. 所有 bs 调用串行化.
_bs_lock = threading.Lock()

# code → market 映射 (从 universe 加载, 用于精确区分沪深; 懒加载避免 import 循环).
_market_map: dict[str, str] | None = None


def _get_market_map() -> dict[str, str]:
    global _market_map
    if _market_map is None:
        from app.services.data.universe import CORE_ETF, CORE_INDICES, SECTOR_ETF
        m: dict[str, str] = {}
        for i in CORE_INDICES:
            if i.get("market"):
                m[i["code"]] = i["market"]
        for e in CORE_ETF + SECTOR_ETF:
            code = e["code"]
            m[code] = "SH" if code.startswith(("5", "50", "51", "52", "56", "58")) else "SZ"
        _market_map = m
    return _market_map


def _ensure_login() -> None:
    """进程级单例 login (幂等). baostock 需要先 login 才能 query."""
    global _logged_in
    with _login_lock:
        if _logged_in:
            return
        import baostock as bs
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"baostock login failed: {lg.error_code} {lg.error_msg}")
        _logged_in = True
        logger.info("baostock logged in")


def _to_baostock_code(code: str, asset_type: str, market: str | None = None) -> str | None:
    """裸代码 → baostock 格式 (sh.600519 / sz.000001).

    优先用 market (universe 提供): SH→sh., SZ→sz.
    无 market 时按代码前缀回退 (个股 000xxx 是深市, 但指数 000300 是沪市 —— 必须 market 区分):
    沪市: 60/68/9/51/56/58/50/52 开头
    深市: 000/002/003(个股)/30/15/12/18/399 开头
    返回 None 表示该代码 baostock 不支持 (非 A 股代码或无法判断).
    """
    c = code.strip()
    if not c.isdigit():
        return None
    if market:
        m = market.strip().upper()
        if m in ("SH", "BJ"):
            return f"sh.{c}"
        if m == "SZ":
            return f"sz.{c}"
    # 无 market: 按代码前缀 (适用于个股, 指数/ETF 应带 market)
    if c.startswith(("60", "68", "9", "51", "56", "58", "50", "52")):
        return f"sh.{c}"
    if c.startswith(("000", "002", "003", "30", "15", "12", "18", "399")):
        return f"sz.{c}"
    return None


def _query(code: str, start: date | None, end: date | None, asset_type: str,
           market: str | None = None) -> pd.DataFrame:
    """baostock query_history_k_data_plus → 归一化 DataFrame.

    字段: date,open,high,low,close,volume,amount (baostock 全量返回, 无需分页).
    volume/amount 为字符串需转数值; normalize_daily 统一处理列名 (date→trade_date).
    market 用于精确区分沪深 (000300 指数是沪市, 000001 个股是深市).

    baostock 全局 session 非线程安全, 整段 login+query 串行化 (run_in_executor 并发下避免死锁).
    """
    bs_code = _to_baostock_code(code, asset_type, market)
    if bs_code is None:
        return pd.DataFrame()
    start_str = start.strftime("%Y-%m-%d") if start else "2000-01-01"
    end_str = end.strftime("%Y-%m-%d") if end else date.today().strftime("%Y-%m-%d")
    with _bs_lock:
        _ensure_login()
        import baostock as bs
        # adjustflag: 3=不复权 (前复权=1, 后复权=2). 状态识别用原始价 + 后续算复权因子.
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount",
            start_date=start_str,
            end_date=end_str,
            frequency="d",
            adjustflag="3",
        )
        if rs.error_code != "0":
            logger.warning("baostock query %s failed: %s %s", bs_code, rs.error_code, rs.error_msg)
            return pd.DataFrame()
        rows: list[list[str]] = []
        while rs.next():
            rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount"])
    # baostock date 列 → trade_date, 数值列转 float (normalize_daily 处理 date 与列名).
    df = df.rename(columns={"date": "trade_date"})
    for col in ("open", "high", "low", "close", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # volume: baostock 返回字符串, 空=''; 转数值后 int.
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    # normalize_daily 会重排序、转 trade_date 为 date 类型、统一列顺序.
    return normalize_daily(df)


class BaostockDataSource(DataSource):
    """baostock 数据源 (A股指数/ETF/个股). 港股/国债/外汇 NotImplementedMarker."""

    name = "baostock"

    def fetch_index_daily(self, code: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        if code.strip() in _NON_A_SHARE_TOKENS:
            raise NotImplementedMarker(f"baostock 不支持港股/国债/外汇指数 {code}")
        return _query(code, start, end, "index", _get_market_map().get(code))

    def fetch_etf_daily(self, code: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        return _query(code, start, end, "etf", _get_market_map().get(code))

    def fetch_stock_daily(self, code: str, market: str = "A", start: date | None = None, end: date | None = None) -> pd.DataFrame:
        if market.upper() == "HK":
            raise NotImplementedMarker("baostock 不支持港股个股")
        return _query(code, start, end, "stock")

    def fetch_macro_proxy(self, name: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        raise NotImplementedMarker(f"baostock 不支持宏观代理 {name}")


__all__ = ["BaostockDataSource"]
