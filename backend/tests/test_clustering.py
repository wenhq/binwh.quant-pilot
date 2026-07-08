"""U4 tests: HMM 状态发现 + label 语义对齐."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.market_regime.clustering import fit_hmm, silhouette_over_k


def _two_regime_series(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """前 n 低波动, 后 n 高波动 (两态结构清晰)."""
    rng = np.random.default_rng(seed)
    low = rng.normal(0, 0.2, n)
    high = rng.normal(0, 3.0, n)
    return pd.DataFrame(
        {"pc1": np.concatenate([low, high])}, index=pd.RangeIndex(2 * n)
    )


def test_fit_hmm_returns_labels_and_shape():
    X = _two_regime_series()
    res = fit_hmm(X, n_components=2)
    assert len(res.labels) == len(X)
    assert res.n_components == 2
    assert set(res.labels.unique()).issubset({0, 1})
    assert res.probabilities.shape == (len(X), 2)
    assert res.transmat.shape == (2, 2)
    assert res.means.shape == (2, 1)


def test_fit_hmm_label_alignment_high_vol_is_1():
    """label=1 恒为高波动/动荡态 (核心: 避免 label 任意性)."""
    X = _two_regime_series(n=300)
    res = fit_hmm(X, n_components=2)
    # 后 300 (高波动) 应主要是 label 1
    assert (res.labels.iloc[300:] == 1).mean() > 0.7
    # 前 300 (低波动) 应主要是 label 0
    assert (res.labels.iloc[:300] == 0).mean() > 0.7


def test_align_labels_by_return_low_return_is_1():
    """收益率对齐: 低收益 (下跌) 状态 → label 1 (动荡). 直接测对齐逻辑 (确定性)."""
    from app.services.market_regime.clustering import _align_labels_by_return

    # HMM 原始 label: 状态0=高收益上涨, 状态1=低收益下跌
    labels = np.array([0, 0, 0, 1, 1, 1])
    returns = np.array([0.01, 0.02, 0.015, -0.02, -0.01, -0.015])
    aligned = _align_labels_by_return(labels, returns, n_components=2)
    # 状态1 (低收益/下跌) 应映射到 label 1 (动荡)
    assert aligned[3] == 1
    assert aligned[0] == 0


def test_fit_hmm_reproducible():
    """固定 random_state 序列 → 两次 fit 结果一致 (可复现)."""
    X = _two_regime_series()
    res1 = fit_hmm(X, n_components=2)
    res2 = fit_hmm(X, n_components=2)
    assert (res1.labels.values == res2.labels.values).all()
    assert res1.log_likelihood == pytest.approx(res2.log_likelihood)


def test_fit_hmm_too_short_raises():
    X = pd.DataFrame({"pc1": [0.1, 0.2, 0.3]}, index=pd.RangeIndex(3))
    with pytest.raises(ValueError, match="太短"):
        fit_hmm(X, n_components=2)


def test_fit_hmm_records_convergence_flag():
    X = _two_regime_series()
    res = fit_hmm(X, n_components=2)
    assert isinstance(res.converged, bool)


def test_fit_hmm_probabilities_sum_to_one():
    X = _two_regime_series()
    res = fit_hmm(X, n_components=2)
    sums = res.probabilities.sum(axis=1)
    assert np.allclose(sums.values, 1.0, atol=1e-6)


def test_silhouette_over_k_returns_dict():
    X = _two_regime_series()
    scores = silhouette_over_k(X, k_min=2, k_max=3)
    assert set(scores.keys()) == {2, 3}
    assert all(isinstance(v, float) for v in scores.values())
