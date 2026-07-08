"""端到端编排 — 两市场独立 pipeline.

把 U2-U7 串联: 特征工程 → PCA → HMM → 逻辑回归 → 评估 → 落库.
A股 / 港股各跑一套 (方案 B, 不假设同步). 某市场失败不影响另一市场.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.market_regime.classifier import train_classifier
from app.services.market_regime.clustering import fit_hmm
from app.services.market_regime.config import MARKET_CONFIGS
from app.services.market_regime.evaluation import evaluate
from app.services.market_regime.features import build_feature_matrix, load_close_series
from app.services.market_regime.persist import save_run, save_states
from app.services.market_regime.reduce import reduce_pca

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    market: str
    success: bool
    run_id: int = 0
    metrics: dict = field(default_factory=dict)
    n_states: int = 0
    n_rows: int = 0
    error: str | None = None


async def run_pipeline(session: AsyncSession, market: str) -> PipelineResult:
    """单市场端到端. 失败返回 success=False + error (不抛, 调用方决定处理)."""
    if market not in MARKET_CONFIGS:
        return PipelineResult(market, False, error=f"未知市场 {market}")
    try:
        # U2 特征工程 (expanding 防泄漏)
        features = await build_feature_matrix(session, market)
        if features.empty:
            raise ValueError(f"{market} 特征矩阵为空 (主标的或辅助数据不足)")

        # 主标的 close:  composite 场景取合成序列, 否则取 primary
        cfg = MARKET_CONFIGS[market]
        if cfg.get("primary") == "composite" and cfg.get("composite"):
            raw_closes: dict[str, pd.Series] = {}
            for comp in cfg["composite"]:
                raw_closes[comp["code"]] = await load_close_series(session, comp["code"])
            from app.services.market_regime.features import _build_composite_primary
            primary = _build_composite_primary(raw_closes, cfg["composite"])
        else:
            primary = await load_close_series(session, cfg["primary"])
        primary_ret = np.log(primary.replace([0, np.inf, -np.inf], np.nan)).diff()

        # U3 PCA 降维
        pca_res = reduce_pca(features)
        components = pca_res.components

        # U4 HMM 状态发现
        hmm_res = fit_hmm(components, align_returns=primary_ret)

        # U5 逻辑回归预测 t+1 状态
        clf_res = train_classifier(components, hmm_res.labels)

        # 板块归因: 加载各指数 close (用于 evaluate 的 sector_attribution)
        index_closes: dict[str, pd.Series] = {}
        for comp in cfg.get("composite", []):
            code = comp["code"]
            s = await load_close_series(session, code)
            if not s.empty:
                index_closes[code] = s
        for idx in cfg.get("indices", []):
            code = idx["code"] if isinstance(idx, dict) else idx
            if code not in index_closes:
                s = await load_close_series(session, code)
                if not s.empty:
                    index_closes[code] = s

        # U6 评估 (传入 pca_result + index_closes)
        primary_aligned = primary.reindex(features.index)
        report = evaluate(
            primary_aligned, components, hmm_res.labels, hmm_res.probabilities, clf_res,
            pca_result=pca_res,
            index_closes=index_closes if index_closes else None,
        )

        # U7 落库
        run = await save_run(
            session,
            market,
            params={
                "n_components": hmm_res.n_components,
                "pca_variance": pca_res.cumulative_variance,
                "pca_n_components": pca_res.n_components,
                "label_align": "returns",
            },
            metrics={
                **clf_res.metrics,
                "silhouette": report.metrics.get("silhouette"),
                "episode_coverage": report.episode_coverage,
                **({} if not report.sector_attribution else {"sector_attribution": report.sector_attribution}),
            },
        )
        n_rows = await save_states(
            session, run.id, report.overlay, features_snapshot=components
        )
        await session.commit()

        logger.info(
            "市场 %s pipeline 完成: run_id=%d rows=%d acc=%.3f ks=%.3f",
            market, run.id, n_rows,
            clf_res.metrics.get("accuracy", 0), clf_res.metrics.get("ks", 0),
        )
        return PipelineResult(
            market=market,
            success=True,
            run_id=run.id,
            metrics={**clf_res.metrics, "silhouette": report.metrics.get("silhouette")},
            n_states=hmm_res.n_components,
            n_rows=n_rows,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("市场 %s pipeline 失败", market)
        await session.rollback()
        return PipelineResult(market, False, error=str(e))


async def run_all_markets(
    session_factory: Callable[[], AsyncSession],
) -> list[PipelineResult]:
    """A + HK 各跑一套 (各自独立 session), 某市场失败不影响另一市场."""
    results = []
    for market in MARKET_CONFIGS:
        async with session_factory() as s:
            results.append(await run_pipeline(s, market))
    return results


__all__ = ["PipelineResult", "run_pipeline", "run_all_markets"]
