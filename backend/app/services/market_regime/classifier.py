"""逻辑回归预测 — 监督阶段, 预测未来 (t+1) 状态概率.

防泄漏 (KTD2): 目标 y = state_label.shift(-1) (t+1 状态), 特征只用 t 及之前.
切断原文「同期特征预测同期标签」的泄漏路径 (原文 ROC-AUC≈1.0 疑似由此).
时序安全切分: 前段训练 / 后段测试, 不 shuffle (避免未来进训练集).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ClassifierResult:
    """监督分类结果."""

    model: LogisticRegression
    test_features: pd.DataFrame
    test_actual: pd.Series
    test_pred_proba: np.ndarray   # 进动荡态 (label=1) 的概率
    split_date: object            # 训练/测试切分日 (X_train 最后一日)
    train_size: int
    metrics: dict                 # accuracy/precision/recall/f1/ks


def build_supervised_dataset(
    features: pd.DataFrame, state_labels: pd.Series
) -> tuple[pd.DataFrame, pd.Series]:
    """构造监督数据集: X=features(t), y=state(t+1). 剔除最后一天 (无 t+1 标签).

    这是防泄漏的核心构造: 目标是未来状态, 而非同期.
    """
    aligned = state_labels.reindex(features.index)
    target = aligned.shift(-1)  # t+1 状态
    mask = target.notna()
    X = features.loc[mask]
    y = target.loc[mask].astype(int)
    return X, y


def _ks_statistic(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """KS 统计量: 两类预测概率分布的最大分离."""
    from scipy.stats import ks_2samp

    pos = y_score[y_true == 1]
    neg = y_score[y_true == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    return float(ks_2samp(pos, neg).statistic)


def train_classifier(
    features: pd.DataFrame,
    state_labels: pd.Series,
    test_ratio: float = 0.4,
) -> ClassifierResult:
    """训练逻辑回归预测 t+1 状态. 时序安全切分 (不 shuffle)."""
    X, y = build_supervised_dataset(features, state_labels)
    split_idx = int(len(X) * (1 - test_ratio))
    if split_idx < 1 or split_idx >= len(X):
        raise ValueError(f"切分无效: split_idx={split_idx}, len={len(X)}")
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    # 泄漏自检: 训练集日期上界 <= 测试集日期下界 (时序不重叠)
    assert X_train.index.max() <= X_test.index.min(), "训练/测试日期重叠, 存在时序泄漏"
    if len(y_train.unique()) < 2:
        raise ValueError("训练集只有一个类别, 无法训练分类器")

    clf = LogisticRegression(
        max_iter=500,
        solver="lbfgs",
        class_weight="balanced",
        random_state=settings.regime_random_state,
    )
    clf.fit(X_train.values, y_train.values)

    n_classes = len(np.unique(y_train))
    proba_full = clf.predict_proba(X_test.values)
    turb_idx = n_classes - 1  # 动荡 = 最高 label (K2=1, K3=2)
    pred_proba = proba_full[:, turb_idx]   # 动荡态概率 (供 KS / 落库 state_prob)
    pred_label = clf.predict(X_test.values)  # argmax (多类正确, 优于 proba>=0.5)

    # KS: 二值化 (动荡 vs 非动荡), 多类下仍有意义
    y_turb_binary = (y_test.values == turb_idx).astype(int)
    metrics = {
        "accuracy": float(accuracy_score(y_test, pred_label)),
        "precision": float(precision_score(y_test, pred_label, average="macro", zero_division=0)),
        "recall": float(recall_score(y_test, pred_label, average="macro", zero_division=0)),
        "f1": float(f1_score(y_test, pred_label, average="macro", zero_division=0)),
        "ks": _ks_statistic(y_turb_binary, pred_proba),
    }
    logger.info(
        "分类器训练: split=%s train=%d test=%d acc=%.3f ks=%.3f",
        X_train.index[-1], len(X_train), len(X_test), metrics["accuracy"], metrics["ks"],
    )
    return ClassifierResult(
        model=clf,
        test_features=X_test,
        test_actual=y_test,
        test_pred_proba=pred_proba,
        split_date=X_train.index[-1],
        train_size=len(X_train),
        metrics=metrics,
    )


def predict_future_proba(model: LogisticRegression, features_row: pd.DataFrame) -> float:
    """预测单日进动荡态 (t+1) 的概率."""
    return float(model.predict_proba(features_row.values)[0, 1])


__all__ = [
    "ClassifierResult",
    "build_supervised_dataset",
    "train_classifier",
    "predict_future_proba",
]
