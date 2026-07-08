"""U3 tests: PCA 降维."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.market_regime.reduce import reduce_pca


def test_pca_reduces_redundant_dimensions():
    """高度冗余特征 → 主成分数 < 原特征数, 累计方差 >= 设定."""
    rng = np.random.default_rng(0)
    base = rng.normal(0, 1, 500)
    # 10 列但只有 1 个主导信号 (其余是微小扰动)
    X = pd.DataFrame(
        {f"f{i}": base + rng.normal(0, 0.01, 500) for i in range(10)},
        index=pd.RangeIndex(500),
    )
    res = reduce_pca(X, variance=0.95)
    assert res.n_components <= 10
    assert res.cumulative_variance >= 0.95
    assert res.components.shape == (500, res.n_components)


def test_pca_variance_threshold_respected():
    rng = np.random.default_rng(1)
    X = pd.DataFrame(
        rng.normal(0, 1, (300, 5)), columns=[f"f{i}" for i in range(5)]
    )
    res = reduce_pca(X, variance=0.50)
    assert res.cumulative_variance >= 0.50


def test_pca_components_named_and_index_preserved():
    rng = np.random.default_rng(2)
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    X = pd.DataFrame(rng.normal(0, 1, (200, 4)), columns=list("abcd"), index=idx)
    res = reduce_pca(X, variance=0.99)
    assert list(res.components.columns) == [f"pc{i+1}" for i in range(res.n_components)]
    assert (res.components.index == X.index).all()


def test_pca_inf_nan_rows_dropped():
    """含 inf/NaN 行被双重保险剔除."""
    rng = np.random.default_rng(3)
    X = pd.DataFrame(rng.normal(0, 1, (100, 3)), columns=list("abc"))
    X.iloc[5, 0] = np.inf
    X.iloc[10, 1] = np.nan
    res = reduce_pca(X, variance=0.95)
    assert res.components.shape[0] == 98  # 2 行被剔除


def test_pca_empty_input_raises():
    X = pd.DataFrame({"a": [np.nan, np.nan], "b": [np.inf, np.inf]})
    with pytest.raises(ValueError, match="为空"):
        reduce_pca(X)


def test_pca_fewer_features_than_implied():
    """特征数少于方差比隐含的主成分 → 降维到实际特征数."""
    rng = np.random.default_rng(4)
    X = pd.DataFrame(rng.normal(0, 1, (200, 3)), columns=list("abc"))
    res = reduce_pca(X, variance=0.99)
    assert res.n_components <= 3
