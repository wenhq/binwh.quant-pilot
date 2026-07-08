"""技术指标计算引擎 — MACD / RSI / Bollinger Bands.

所有指标接受 pandas DataFrame (含 close 列), 返回 Series 或 DataFrame.
计算使用复权后的 close 价格.
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD 指标: DIF = EMA(fast) - EMA(slow), DEA = EMA(signal) of DIF, MACD柱 = (DIF - DEA) * 2."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": hist})


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI 指标: 使用 Wilder's smoothing method."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi_val = 100 - (100 / (1 + rs))
    rsi_val.name = "rsi"
    return rsi_val


def bollinger(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """布林带: 中轨 = SMA(period), 上轨 = 中轨 + std_dev * STD, 下轨 = 中轨 - std_dev * STD."""
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return pd.DataFrame({"upper": upper, "mid": mid, "lower": lower})


def keltner(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 20, multiplier: float = 1.5) -> pd.DataFrame:
    """肯特纳通道: 中轨 = EMA(period), 上轨 = 中轨 + multiplier * ATR(period), 下轨 = 中轨 - multiplier * ATR(period)."""
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    mid = close.ewm(span=period, adjust=False).mean()
    upper = mid + multiplier * atr
    lower = mid - multiplier * atr
    return pd.DataFrame({"upper": upper, "mid": mid, "lower": lower})


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ATR (Average True Range)."""
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    result = tr.rolling(window=period).mean()
    result.name = "atr"
    return result
