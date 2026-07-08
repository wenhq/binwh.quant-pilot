"""状态落库 — 写入数据层预留的 regime_runs / regime_states.

save_states 覆盖式: 先删该 run 的旧 states 再插, 保证 UniqueConstraint(run_id, trade_date)
幂等 (重跑同 run_id 不重复不报错; sqlite 不支持 ON DUPLICATE KEY 的稳妥替代).
numpy / pandas 类型 → 原生 (JSON 列可序列化).
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import numpy as np
import pandas as pd
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RegimeRun, RegimeState

logger = logging.getLogger(__name__)


def _to_jsonable(obj):
    """numpy / pandas / Timestamp → JSON 可序列化的原生类型; float NaN → None."""
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        v = float(obj)
        return None if pd.isna(v) else v
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (pd.Timestamp, datetime)):
        return pd.Timestamp(obj).isoformat()
    if obj is None:
        return None
    if isinstance(obj, float) and pd.isna(obj):
        return None
    return obj


def _to_date(d) -> date:
    """trade_date (date/datetime/Timestamp/str) → date. datetime 须先于 date 判断."""
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return pd.Timestamp(d).date()


async def save_run(
    session: AsyncSession,
    market: str,
    algorithm: str = "hmm",
    classifier: str = "logistic",
    params: dict | None = None,
    metrics: dict | None = None,
) -> RegimeRun:
    """写入一次训练的 run 元数据, flush 后返回带 id 的 RegimeRun."""
    run = RegimeRun(
        market=market,
        algorithm=algorithm,
        classifier=classifier,
        params=_to_jsonable(params) if params else None,
        metrics=_to_jsonable(metrics) if metrics else None,
    )
    session.add(run)
    await session.flush()
    logger.info("RegimeRun 写入 id=%d market=%s algo=%s", run.id, market, algorithm)
    return run


async def save_states(
    session: AsyncSession,
    run_id: int,
    overlay: pd.DataFrame,
    features_snapshot: pd.DataFrame | None = None,
) -> int:
    """覆盖式写状态序列. 返回写入行数.

    overlay 需含 trade_date / state_label / state_prob 列 (build_overlay 产出).
    features_snapshot 主成分矩阵 (可选), 按日期对齐写入 features_snapshot JSON 列.
    """
    # 覆盖式: 先删该 run 旧 states, 保证幂等
    await session.execute(delete(RegimeState).where(RegimeState.run_id == run_id))

    snap = None
    if features_snapshot is not None:
        snap = features_snapshot.reindex(overlay["trade_date"].values)

    count = 0
    for _, row in overlay.iterrows():
        feat = None
        if snap is not None:
            rec = snap.loc[row["trade_date"]]
            if isinstance(rec, pd.Series):
                feat = {c: _to_jsonable(v) for c, v in rec.items()}
        state = RegimeState(
            run_id=run_id,
            trade_date=_to_date(row["trade_date"]),
            state_label=int(row["state_label"]),
            state_prob=(
                float(row["state_prob"]) if pd.notna(row.get("state_prob")) else None
            ),
            features_snapshot=feat,
        )
        session.add(state)
        count += 1
    logger.info("RegimeState 写入 run_id=%d rows=%d", run_id, count)
    return count


__all__ = ["save_run", "save_states", "_to_jsonable"]
