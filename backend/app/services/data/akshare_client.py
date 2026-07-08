import akshare as ak
import pandas as pd


def fetch_stock_daily(stock_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    Fetch daily k-line for a single stock via akshare.

    Returns DataFrame with columns:
        trade_date, open, close, high, low, volume, amount
    """
    df = ak.stock_zh_a_daily(
        symbol=stock_code,
        start_date=start_date,
        end_date=end_date,
        adjust=""  # original (unadjusted) prices
    )
    if df is None or df.empty:
        return pd.DataFrame()

    # akshare may return different column names depending on version;
    # normalize to standard names.
    col_map = {
        "date": "trade_date",
        "开盘": "open",
        "close": "close",
        "high": "high",
        "low": "low",
        "volume": "volume",
        "amount": "amount",
    }
    for old, new in col_map.items():
        if old in df.columns:
            df = df.rename(columns={old: new})

    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


def fetch_stock_info(stock_code: str) -> dict:
    """Fetch basic stock info via akshare."""
    try:
        df = ak.stock_individual_info_em(symbol=stock_code)
        if df is None or df.empty:
            return {}
        # df columns: item, value
        info = dict(zip(df["item"], df["value"]))
        name = info.get("股票简称", stock_code)
        market = info.get("所属市场", "")
        return {"name": name, "market": market}
    except Exception:
        return {"name": stock_code, "market": ""}
