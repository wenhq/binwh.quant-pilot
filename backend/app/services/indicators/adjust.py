"""复权引擎 — 前复权 / 后复权计算.

存储原始不复权数据 + adj_factor（复权因子）。
前复权: price_adj = price * (adj_factor / latest_adj_factor)
后复权: price_adj = price * adj_factor

成交量不变，金额同比例缩放。
"""
from __future__ import annotations

import pandas as pd


def forward_adjust(df: pd.DataFrame) -> pd.DataFrame:
    """前复权: 以最新日期为基准, 所有历史价格乘以 adj_factor / latest_adj_factor."""
    if "adj_factor" not in df.columns or df["adj_factor"].isna().all():
        return df.copy()
    latest_factor = df["adj_factor"].iloc[-1]
    if latest_factor is None or latest_factor == 0:
        return df.copy()
    ratio = df["adj_factor"] / latest_factor
    result = df.copy()
    for col in ["open", "high", "low", "close"]:
        if col in result.columns:
            result[col] = result[col] * ratio
    if "amount" in result.columns:
        result["amount"] = result["amount"] * ratio
    return result


def backward_adjust(df: pd.DataFrame) -> pd.DataFrame:
    """后复权: 所有价格乘以 adj_factor."""
    if "adj_factor" not in df.columns or df["adj_factor"].isna().all():
        return df.copy()
    ratio = df["adj_factor"]
    result = df.copy()
    for col in ["open", "high", "low", "close"]:
        if col in result.columns:
            result[col] = result[col] * ratio
    if "amount" in result.columns:
        result["amount"] = result["amount"] * ratio
    return result


def adjust(df: pd.DataFrame, mode: str = "forward") -> pd.DataFrame:
    """统一入口: mode='forward' | 'backward' | 'none'."""
    if mode == "forward":
        return forward_adjust(df)
    elif mode == "backward":
        return backward_adjust(df)
    else:
        return df.copy()
