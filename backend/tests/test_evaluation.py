"""U6 tests: 评估闭环 (人工对照历史 + 指标)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.market_regime.evaluation import (
    HISTORICAL_EPISODES,
    _extract_index_from_feature,
    build_overlay,
    compute_index_contributions,
    episode_coverage,
    evaluate,
    regime_economic_stats,
)


def _two_regime(n: int = 200):
    """前 n 低波动平静态, 后 n 高波动动荡态."""
    rng = np.random.default_rng(0)
    dates = pd.date_range("2024-01-01", periods=2 * n, freq="B")
    low_close = 100 + rng.normal(0, 0.2, n).cumsum()
    high_close = 100 + rng.normal(0, 3.0, n).cumsum()
    close = pd.Series(np.concatenate([low_close, high_close]), index=dates)
    labels = pd.Series([0] * n + [1] * n, index=dates, name="state")
    probs = pd.DataFrame(
        {
            "prob_state_0": [0.9] * n + [0.1] * n,
            "prob_state_1": [0.1] * n + [0.9] * n,
        },
        index=dates,
    )
    return close, labels, probs


def test_build_overlay_shape():
    close, labels, probs = _two_regime(100)
    ov = build_overlay(close, labels, probs)
    assert set(ov.columns) == {"trade_date", "close", "state_label", "state_prob"}
    assert len(ov) == len(close)
    # 后段动荡态 prob 高
    assert ov["state_prob"].iloc[-1] > 0.5


def test_regime_economic_stats_higher_vol_in_turbulent():
    """动荡态 (1) 年化波动率 > 平静态 (0) — 经济含义清晰."""
    close, labels, _ = _two_regime(200)
    stats = regime_economic_stats(close, labels)
    assert 0 in stats.index and 1 in stats.index
    assert stats.loc[1, "annual_vol"] > stats.loc[0, "annual_vol"]
    # 占比合计 ≈ 1
    assert abs(stats["pct"].sum() - 1.0) < 1e-6


def test_episode_coverage_keys_complete():
    _, labels, _ = _two_regime(100)
    cov = episode_coverage(labels)
    assert set(cov.keys()) == set(HISTORICAL_EPISODES.keys())


def test_evaluate_end_to_end_report():
    close, labels, probs = _two_regime(200)
    feats = pd.DataFrame(
        {"pc1": np.random.default_rng(1).normal(0, 1, len(close))}, index=close.index
    )
    report = evaluate(close, feats, labels, probs)
    assert "silhouette" in report.metrics
    assert len(report.overlay) == len(close)
    assert report.regime_stats.loc[1, "annual_vol"] > report.regime_stats.loc[0, "annual_vol"]
    assert "2024_rebound" in report.episode_coverage


def test_evaluate_with_classifier_metrics():
    close, labels, probs = _two_regime(200)
    feats = pd.DataFrame({"pc1": np.random.default_rng(2).normal(0, 1, len(close))}, index=close.index)

    class _FakeClassifierResult:
        test_actual = labels.iloc[200:]
        test_pred_proba = probs.iloc[200:, 1].values
        metrics = {"ks": 0.85}

    report = evaluate(close, feats, labels, probs, classifier_result=_FakeClassifierResult())
    assert report.metrics["ks"] == 0.85
    assert "confusion_matrix" in report.metrics
    assert len(report.metrics["confusion_matrix"]) == 2


# ---------- 指数贡献度分解 ----------


def test_extract_index_from_feature():
    assert _extract_index_from_feature("ret_5d_000300") == "000300"
    assert _extract_index_from_feature("realvol_21d_399006") == "399006"
    assert _extract_index_from_feature("cross_000300_000905") == "000905"
    assert _extract_index_from_feature("spread_512480_510880") == "510880"
    assert _extract_index_from_feature("CN10Y_diff") == "CN10Y"
    assert _extract_index_from_feature("USDCNY_diff") == "USDCNY"
    assert _extract_index_from_feature("unknown_feature") is None


def test_compute_index_contributions():
    feature_names = ["ret_5d_000300", "realvol_21d_000300", "ret_5d_000905", "realvol_21d_000905"]
    loadings = pd.DataFrame(
        np.array([[0.5, 0.3], [0.4, 0.2], [0.1, 0.1], [0.2, 0.4]]),
        index=feature_names,
        columns=["pc1", "pc2"],
    )
    contrib = compute_index_contributions(feature_names, loadings)
    assert "000300" in contrib
    assert "000905" in contrib
    assert abs(sum(contrib.values()) - 1.0) < 1e-6


def test_compute_index_contributions_empty():
    assert compute_index_contributions([], pd.DataFrame()) == {}  # 2x2
