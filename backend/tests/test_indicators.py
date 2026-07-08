"""Tests for indicators service: adjust + ta."""
import numpy as np
import pandas as pd
import pytest

from app.services.indicators import adjust, macd, rsi, bollinger, forward_adjust, backward_adjust


@pytest.fixture
def sample_df():
    np.random.seed(42)
    n = 100
    close = pd.Series(np.cumsum(np.random.randn(n) * 0.5) + 100, name="close")
    adj = pd.Series(np.linspace(1.0, 1.5, n))
    return pd.DataFrame({
        "trade_date": pd.date_range("2026-01-01", periods=n),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": np.random.randint(1000, 10000, n),
        "amount": close * 1000,
        "adj_factor": adj,
    })


def test_forward_adjust_latest_unchanged(sample_df):
    """Happy: 前复权后最新日价格不变."""
    fwd = forward_adjust(sample_df)
    assert abs(fwd["close"].iloc[-1] - sample_df["close"].iloc[-1]) < 0.001


def test_backward_adjust_oldest_unchanged(sample_df):
    """Happy: 后复权后最早日价格不变 (adj_factor=1)."""
    bwd = backward_adjust(sample_df)
    assert abs(bwd["close"].iloc[0] - sample_df["close"].iloc[0]) < 0.001


def test_adjust_none_returns_copy(sample_df):
    """Happy: adjust(mode='none') 返回原始数据."""
    raw = adjust(sample_df, "none")
    pd.testing.assert_frame_equal(raw, sample_df)


def test_macd_columns(sample_df):
    """Happy: MACD 返回 dif/dea/hist 三列."""
    fwd = forward_adjust(sample_df)
    m = macd(fwd["close"])
    assert set(m.columns) == {"dif", "dea", "hist"}
    assert len(m) == len(sample_df)


def test_macd_custom_params(sample_df):
    """Happy: 自定义参数."""
    m = macd(sample_df["close"], fast=5, slow=20, signal=5)
    assert len(m) == len(sample_df)


def test_rsi_range(sample_df):
    """Happy: RSI 值在 0-100 之间."""
    r = rsi(sample_df["close"], period=14)
    valid = r.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_bollinger_columns(sample_df):
    """Happy: Boll 返回 upper/mid/lower 三列."""
    b = bollinger(sample_df["close"])
    assert set(b.columns) == {"upper", "mid", "lower"}
    valid = b.dropna()
    assert (valid["upper"] >= valid["mid"]).all()
    assert (valid["mid"] >= valid["lower"]).all()


def test_bollinger_custom_params(sample_df):
    """Happy: 自定义周期和标准差倍数."""
    b = bollinger(sample_df["close"], period=10, std_dev=1.5)
    assert len(b) == len(sample_df)


def test_no_adj_factor_returns_copy(sample_df):
    """Edge: 无 adj_factor 列时返回 copy."""
    df = sample_df.drop(columns=["adj_factor"])
    result = forward_adjust(df)
    pd.testing.assert_frame_equal(result, df)


def test_nan_adj_factor_returns_copy(sample_df):
    """Edge: adj_factor 全 NaN 时返回 copy."""
    df = sample_df.copy()
    df["adj_factor"] = np.nan
    result = forward_adjust(df)
    pd.testing.assert_frame_equal(result, df)
