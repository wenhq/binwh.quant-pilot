"""U5 tests: 逻辑回归预测 (t+1 状态) + 防泄漏."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.market_regime.classifier import (
    build_supervised_dataset,
    train_classifier,
)


def _make_data(n: int = 200, seed: int = 0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    feats = pd.DataFrame(
        rng.normal(0, 1, (n, 3)), index=idx, columns=["pc1", "pc2", "pc3"]
    )
    states = pd.Series(rng.integers(0, 2, n), index=idx, name="state")
    return feats, states


def test_build_supervised_target_is_t_plus_1():
    """y[t] == state[t+1] (预测未来, 非同期 — 防泄漏核心)."""
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    feats = pd.DataFrame({"pc1": [1.0, 2, 3, 4, 5]}, index=idx)
    states = pd.Series([0, 1, 0, 1, 0], index=idx)
    X, y = build_supervised_dataset(feats, states)
    assert len(y) == 4  # 最后一天 (无 t+1) 剔除
    assert list(y.values) == [1, 0, 1, 0]  # == states[1:]
    assert list(X.index) == list(idx[:4])


def test_build_supervised_drops_last_day():
    feats, states = _make_data(n=50)
    X, y = build_supervised_dataset(feats, states)
    assert len(y) == 49
    assert X.index[-1] == feats.index[-2]  # 倒数第二天


def test_train_classifier_returns_metrics():
    feats, states = _make_data(n=200)
    res = train_classifier(feats, states, test_ratio=0.4)
    for k in ("accuracy", "precision", "recall", "f1", "ks"):
        assert k in res.metrics
    # build_supervised 剔除最后一天 → 199; split=int(199*0.6)=119
    assert res.train_size == 119
    assert len(res.test_actual) == 80


def test_train_classifier_temporal_split_no_leak():
    """训练集日期上界 <= 测试集日期下界 (时序安全)."""
    feats, states = _make_data(n=200)
    res = train_classifier(feats, states, test_ratio=0.4)
    assert res.split_date <= res.test_features.index.min()


def test_train_classifier_single_class_raises():
    feats, _ = _make_data(n=100)
    states = pd.Series(np.zeros(100, dtype=int), index=feats.index)
    with pytest.raises(ValueError, match="一个类别"):
        train_classifier(feats, states)


def test_train_classifier_too_short_raises():
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    feats = pd.DataFrame({"pc1": [1.0, 2]}, index=idx)
    states = pd.Series([0, 1], index=idx)
    # build_supervised 剔除最后一天 → 1 行; split_idx=int(1*0.6)=0 <1 → 切分无效
    with pytest.raises(ValueError, match="切分无效"):
        train_classifier(feats, states, test_ratio=0.4)
