"""HMM 状态发现 — 无监督发现潜在市场状态 (平静/动荡).

GaussianHMM 建模状态转移的持续性 (金融状态有惯性), 比 K-Means/GMM 静态聚类更贴合状态语义.

label 语义对齐 (KTD): fit 后按状态波动重排, label=1 恒为高波动/动荡态,
避免每次 fit 的 label 任意性 (hmmlearn 的 label 分配取决于初始化).
多 seed (n_init) 取最优对数似然, 缓解 HMM 对初始值敏感.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.metrics import silhouette_score

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class HMMResult:
    """HMM 状态发现结果."""

    labels: pd.Series             # 逐日状态标签 (0=平静, 1=动荡), index 同 X
    probabilities: pd.DataFrame   # 逐日各状态概率
    transmat: np.ndarray          # 状态转移矩阵 P(i→j)
    n_components: int
    converged: bool
    log_likelihood: float
    means: np.ndarray             # 各状态在高维空间的均值


def _fit_one(X: np.ndarray, n_components: int, seed: int) -> GaussianHMM:
    hmm = GaussianHMM(
        n_components=n_components,
        covariance_type="full",
        n_iter=100,
        random_state=seed,
    )
    hmm.fit(X)
    return hmm


def _align_labels(labels: np.ndarray, X: np.ndarray, n_components: int) -> np.ndarray:
    """重排 label 使高波动状态 = 1 (回退方案, 无收益率时用).

    波动代理: 各状态样本在 pc1 (最大方差主成分) 上的 std. std 最高 → label=1.
    """
    vol = np.zeros(n_components)
    for k in range(n_components):
        mask = labels == k
        if mask.sum() > 1:
            vol[k] = float(X[mask, 0].std())
    sorted_states = np.argsort(vol)  # 升序: 低波动 → 高波动
    remap = {old: new for new, old in enumerate(sorted_states)}
    return np.array([remap[int(l)] for l in labels])


def _align_labels_by_return(
    labels: np.ndarray, returns: np.ndarray, n_components: int
) -> np.ndarray:
    """重排 label 使低收益 (下跌) 状态 = 1 (动荡). 收益率对齐贴合宏观直觉.

    动荡的市场含义是「下跌」, 而非仅「高波动」(牛市高波动上涨不算动荡).
    这修正了 pc1 波动对齐把牛市上涨误判为动荡的偏差 (R7 人工对照根因).
    """
    mean_ret = np.full(n_components, np.nan)
    for k in range(n_components):
        mask = labels == k
        if mask.sum() > 0:
            mean_ret[k] = float(np.nanmean(returns[mask]))
    # 升序: 低收益 (下跌) → 高收益; 低收益 = 高 label (动荡=1)
    order = np.argsort(np.nan_to_num(mean_ret, nan=0.0))
    remap = {old: n_components - 1 - i for i, old in enumerate(order)}
    return np.array([remap[int(l)] for l in labels])


def fit_hmm(
    X: pd.DataFrame,
    n_components: int | None = None,
    n_init: int = 5,
    align_returns: pd.Series | None = None,
) -> HMMResult:
    """fit HMM, 多 seed 取最优对数似然, label 语义对齐.

    align_returns 提供时, label 按主标的收益率对齐 (动荡=下跌, 贴合宏观直觉);
    否则回退到 pc1 波动对齐.
    n_components 默认 settings.regime_n_components. 数据太短 (< 2*n_components) 抛 ValueError.
    """
    n_components = settings.regime_n_components if n_components is None else n_components
    if len(X) < 2 * n_components:
        raise ValueError(
            f"HMM 数据太短: {len(X)} 行 < 2*n_components={2 * n_components}"
        )
    Xv = X.values
    best: GaussianHMM | None = None
    best_ll = -np.inf
    for i in range(n_init):
        seed = settings.regime_random_state + i
        try:
            hmm = _fit_one(Xv, n_components, seed)
            ll = float(hmm.score(Xv))
            if ll > best_ll:
                best, best_ll = hmm, ll
        except Exception as e:  # noqa: BLE001
            logger.warning("HMM seed %d fit 失败: %s", seed, e)
    if best is None:
        raise RuntimeError(
            f"HMM fit 全部失败 (n_components={n_components}, {n_init} seeds)"
        )

    raw_labels = best.predict(Xv)
    probs = best.predict_proba(Xv)
    if align_returns is not None:
        ret_aligned = align_returns.reindex(X.index).to_numpy()
        labels = _align_labels_by_return(raw_labels, ret_aligned, n_components)
    else:
        labels = _align_labels(raw_labels, Xv, n_components)

    converged = bool(best.monitor_.converged)
    if not converged:
        logger.warning("HMM 未收敛 (n_components=%d), 考虑增加 n_iter 或调整 K", n_components)

    return HMMResult(
        labels=pd.Series(labels, index=X.index, name="state"),
        probabilities=pd.DataFrame(
            probs,
            index=X.index,
            columns=[f"prob_state_{i}" for i in range(n_components)],
        ),
        transmat=best.transmat_,
        n_components=n_components,
        converged=converged,
        log_likelihood=best_ll,
        means=best.means_,
    )


def silhouette_over_k(
    X: pd.DataFrame, k_min: int = 2, k_max: int = 4
) -> dict[int, float]:
    """轮廓系数对照多 K (辅助人工选 K, 非主路径). 越接近 +1 越好."""
    Xv = X.values
    scores: dict[int, float] = {}
    for k in range(k_min, k_max + 1):
        try:
            res = fit_hmm(X, n_components=k)
            scores[k] = float(silhouette_score(Xv, res.labels.values))
        except Exception as e:  # noqa: BLE001
            logger.warning("silhouette k=%d 失败: %s", k, e)
            scores[k] = float("nan")
    return scores


__all__ = ["HMMResult", "fit_hmm", "silhouette_over_k"]
