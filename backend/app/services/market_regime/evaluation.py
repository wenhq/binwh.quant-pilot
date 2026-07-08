"""评估闭环 — 状态切片人工对照历史 + 辅助指标.

核心门槛 (R7): 状态序列叠加价格, 人眼对照 2018 贸易战 / 2022 / 2024 历史重大阶段.
本模块产出结构化数据 (供后续前端 + 当下人工对照), 不做图 (前端 deferred).

辅助指标 (R8, 非门槛): 轮廓系数 / KS / 混淆矩阵; 状态分组经济含义
(动荡期日均收益更负、年化波动率显著高于平静期).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, silhouette_score

# 历史重大阶段 (人工对照锚点; A股)
HISTORICAL_EPISODES: dict[str, tuple[str, str]] = {
    "2018_trade_war": ("2018-03-22", "2018-12-25"),
    "2022_sell_off": ("2022-01-04", "2022-10-31"),
    "2024_rebound": ("2024-02-05", "2024-10-08"),
}


@dataclass
class EvaluationReport:
    overlay: pd.DataFrame            # {trade_date, close, state_label, state_prob}
    metrics: dict = field(default_factory=dict)        # silhouette / ks / confusion_matrix
    regime_stats: pd.DataFrame = field(default_factory=pd.DataFrame)  # 各状态经济含义
    episode_coverage: dict = field(default_factory=dict)  # 各历史阶段动荡态占比
    sector_attribution: dict = field(default_factory=dict)  # 各状态下各指数平均收益


def build_overlay(
    close: pd.Series, labels: pd.Series, probabilities: pd.DataFrame
) -> pd.DataFrame:
    """状态叠加价格序列 (人工对照核心产出)."""
    if probabilities is not None and probabilities.shape[1] >= 2:
        turb_prob = probabilities.iloc[:, 1].reindex(close.index)
    else:
        turb_prob = pd.Series(np.nan, index=close.index)
    return pd.DataFrame(
        {
            "trade_date": close.index,
            "close": close.values,
            "state_label": labels.reindex(close.index).values,
            "state_prob": turb_prob.values,
        }
    ).reset_index(drop=True)


def regime_economic_stats(close: pd.Series, labels: pd.Series) -> pd.DataFrame:
    """各状态经济含义: 日均对数收益、年化波动率、天数占比 (验证经济含义清晰)."""
    rets = np.log(close.replace([0, np.inf, -np.inf], np.nan)).diff()
    rows = []
    for state in sorted(labels.dropna().unique()):
        mask = labels == state
        srets = rets[mask].dropna()
        rows.append(
            {
                "state": int(state),
                "days": int(mask.sum()),
                "pct": float(mask.mean()),
                "daily_return_mean": float(srets.mean()) if len(srets) else float("nan"),
                "annual_vol": (
                    float(srets.std() * np.sqrt(252)) if len(srets) > 1 else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows).set_index("state")


def compute_sector_attribution(
    labels: pd.Series,
    index_closes: dict[str, pd.Series],
) -> dict[str, dict]:
    """按 regime 状态统计各指数的平均收益率, 用于板块归因.

    返回: {state_label: {index_code: avg_return}}
    """
    out: dict[str, dict] = {}
    for state in sorted(labels.dropna().unique()):
        mask = labels == state
        state_returns: dict[str, float] = {}
        for code, close in index_closes.items():
            aligned = close.reindex(labels.index)
            rets = np.log(aligned.replace([0, np.inf, -np.inf], np.nan)).diff()
            state_ret = rets[mask].dropna()
            state_returns[code] = float(state_ret.mean()) if len(state_ret) else float("nan")
        out[str(int(state))] = state_returns
    return out


def episode_coverage(labels: pd.Series) -> dict[str, float]:
    """各历史阶段区间内, 落在动荡态 (label=1) 的交易日占比 (人工对照辅助)."""
    idx = pd.to_datetime(labels.index)
    out: dict[str, float] = {}
    for name, (start, end) in HISTORICAL_EPISODES.items():
        mask = (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))
        seg = labels[mask]
        out[name] = float((seg == 1).mean()) if len(seg) else float("nan")
    return out


def _extract_index_from_feature(name: str) -> str | None:
    """从特征名中提取指数代码.

    ret_5d_000300 → 000300, cross_000300_000905 → 000905, CN10Y_diff → CN10Y.
    非指数后缀 (如 unknown_feature) → None.
    """
    parts = name.rsplit("_", 1)
    code = parts[-1]
    if code == "diff" and len(parts) >= 2:
        code = parts[0].rsplit("_", 1)[-1]
    if re.match(r"^(\d{4,6}|[A-Z][A-Z0-9]{1,9})$", code):
        return code
    return None


def compute_index_contributions(
    feature_names: list[str], loadings: pd.DataFrame
) -> dict[str, float]:
    """按指数分组汇总特征贡献度."""
    if loadings.empty or not feature_names:
        return {}
    contrib: dict[str, float] = {}
    for feat in feature_names:
        idx_code = _extract_index_from_feature(feat)
        key = idx_code if idx_code else "other"
        contrib[key] = contrib.get(key, 0.0) + float(loadings.loc[feat].abs().sum())
    total = sum(contrib.values())
    if total > 0:
        contrib = {k: round(v / total, 6) for k, v in contrib.items()}
    return contrib


def evaluate(
    close: pd.Series,
    features: pd.DataFrame,
    hmm_labels: pd.Series,
    hmm_probabilities: pd.DataFrame,
    classifier_result=None,
    pca_result=None,
    index_closes=None,
) -> EvaluationReport:
    """端到端评估: 叠加序列 + 指标 + 经济含义 + 历史阶段覆盖 + 指数贡献度 + 板块归因.

    features / hmm_labels / hmm_probabilities 应共享 index (PCA 矩阵及其 HMM 输出).
    pca_result: PCAResult 可选, 提供时输出各指数贡献度分解.
    index_closes: dict[str, pd.Series] 可选, 提供时输出各状态下各指数平均收益率 (板块归因).
    """
    overlay = build_overlay(close, hmm_labels, hmm_probabilities)
    regime_stats = regime_economic_stats(close, hmm_labels)

    metrics: dict = {
        "silhouette": float(silhouette_score(features.values, hmm_labels.values))
    }
    if classifier_result is not None:
        turb_idx = int(hmm_labels.max())
        actual_binary = (classifier_result.test_actual.values == turb_idx).astype(int)
        pred = (classifier_result.test_pred_proba >= 0.5).astype(int)
        metrics["ks"] = float(classifier_result.metrics.get("ks", float("nan")))
        metrics["confusion_matrix"] = confusion_matrix(
            actual_binary, pred, labels=[0, 1]
        ).tolist()

    index_contributions = {}
    if pca_result is not None and hasattr(pca_result, "feature_names") and hasattr(pca_result, "loadings"):
        index_contributions = compute_index_contributions(
            pca_result.feature_names, pca_result.loadings
        )
    if index_contributions:
        metrics["index_contributions"] = index_contributions

    sector_attr = {}
    if index_closes:
        sector_attr = compute_sector_attribution(hmm_labels, index_closes)
    if sector_attr:
        metrics["sector_attribution"] = sector_attr

    return EvaluationReport(
        overlay=overlay,
        metrics=metrics,
        regime_stats=regime_stats,
        episode_coverage=episode_coverage(hmm_labels),
        sector_attribution=sector_attr,
    )


__all__ = [
    "HISTORICAL_EPISODES",
    "EvaluationReport",
    "build_overlay",
    "regime_economic_stats",
    "episode_coverage",
    "evaluate",
]
