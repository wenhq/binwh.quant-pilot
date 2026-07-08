"""PCA 降维 — 压缩高度相关的特征, 保留主要方差.

特征矩阵经 U2 expanding 标准化后往往高度相关 (多周期收益/波动率冗余),
PCA 压到少数主成分, 消除冗余, 提升下游 HMM 的稳定性.

防泄漏说明: PCA 是线性变换, fit 在全样本可接受 — 真正的防泄漏已在 U2 expanding
标准化 (截至 t 的统计) 与 U5 预测 t+1 状态 (切断同期标签) 处理. PCA 不直接产生预测.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from app.config import settings


@dataclass
class PCAResult:
    """PCA 降维结果."""

    components: pd.DataFrame            # 主成分得分矩阵 (index 保留, 列 pc1..pcN)
    n_components: int                   # 实际保留的主成分数
    explained_variance_ratio: np.ndarray  # 各主成分方差占比
    cumulative_variance: float          # 累计方差占比
    feature_names: list[str] = field(default_factory=list)
    loadings: pd.DataFrame = field(default_factory=pd.DataFrame)


def reduce_pca(X: pd.DataFrame, variance: float | None = None) -> PCAResult:
    """PCA 降维, 保留累计方差 >= variance (默认 settings.regime_pca_variance).

    n_components 接受 float → sklearn 自动选达到该方差比的最少主成分数.
    输入 inf/NaN 行被双重保险剔除 (U2 已 dropna, 此处再防).
    """
    var_threshold = settings.regime_pca_variance if variance is None else variance
    X_clean = X.replace([np.inf, -np.inf], np.nan).dropna()
    if X_clean.empty:
        raise ValueError("PCA 输入为空 (全 NaN/inf), 无法降维")
    pca = PCA(n_components=var_threshold, random_state=settings.regime_random_state)
    transformed = pca.fit_transform(X_clean.values)
    cols = [f"pc{i + 1}" for i in range(pca.n_components_)]
    components = pd.DataFrame(transformed, index=X_clean.index, columns=cols)
    loadings = pd.DataFrame(
        pca.components_.T, index=X_clean.columns, columns=cols
    )
    return PCAResult(
        components=components,
        n_components=int(pca.n_components_),
        explained_variance_ratio=pca.explained_variance_ratio_,
        cumulative_variance=float(pca.explained_variance_ratio_.sum()),
        feature_names=list(X_clean.columns),
        loadings=loadings,
    )


__all__ = ["PCAResult", "reduce_pca"]
