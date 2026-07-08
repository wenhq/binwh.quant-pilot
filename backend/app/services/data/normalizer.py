import pandas as pd
from datetime import datetime


def normalize_daily(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize akshare daily kline data to standard schema columns.
    Expected input columns (varied by akshare version):
        日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # Defensive copy
    df = df.copy()

    # Map Chinese (akshare 个股/指数/ETF) AND English (akshare 港股) column names.
    col_map = {
        # Chinese (东方财富系列)
        "日期": "trade_date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        # English (akshare 港股 stock_hk_daily)
        "date": "trade_date",
    }
    for src, dst in col_map.items():
        if src in df.columns and dst not in df.columns:
            df = df.rename(columns={src: dst})

    # Ensure required columns exist
    required = ["trade_date", "open", "close", "high", "low", "volume"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}. Got: {list(df.columns)}")

    # Convert trade_date
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    # Numeric columns
    for col in ["open", "close", "high", "low", "amount"]:  # volume usually int
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("int64")

    # Select and order
    cols = ["trade_date", "open", "close", "high", "low", "volume", "amount"]
    df = df[[c for c in cols if c in df.columns]].sort_values("trade_date").reset_index(drop=True)

    return df
