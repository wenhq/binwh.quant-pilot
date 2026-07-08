"""market_regime API — 训练触发 + 状态查询.

仿 routers/data.py 的后台任务模式 (asyncio.create_task + AsyncSessionLocal).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import RegimeRun, RegimeState
from app.services.market_regime.pipeline import run_all_markets, run_pipeline

router = APIRouter(prefix="/market_regime", tags=["market_regime"])
_bg_tasks: dict[str, asyncio.Task] = {}


async def _run_bg(market: str) -> None:
    async with AsyncSessionLocal() as s:
        await run_pipeline(s, market)


async def _run_all_bg() -> None:
    await run_all_markets(AsyncSessionLocal)


@router.post("/train/{market}")
async def train_market(market: str, background: bool = True):
    """触发单市场训练. 默认后台跑; background=False 同步等结果."""
    if market not in ("A", "HK"):
        raise HTTPException(status_code=400, detail="market 必须是 A 或 HK")
    if background:
        _bg_tasks[f"train_{market}"] = asyncio.create_task(_run_bg(market))
        return {
            "status": "started",
            "market": market,
            "hint": f"GET /api/market_regime/runs/{market}",
        }
    async with AsyncSessionLocal() as s:
        res = await run_pipeline(s, market)
    if not res.success:
        raise HTTPException(status_code=500, detail=res.error)
    return {
        "market": market,
        "success": True,
        "run_id": res.run_id,
        "rows": res.n_rows,
        "metrics": res.metrics,
    }


@router.post("/train_all")
async def train_all(background: bool = True):
    """触发 A + HK 两市场训练 (各自独立, 某市场失败不影响另一市场)."""
    if background:
        _bg_tasks["train_all"] = asyncio.create_task(_run_all_bg())
        return {"status": "started", "hint": "GET /api/market_regime/runs/A"}
    results = await run_all_markets(AsyncSessionLocal)
    return [
        {
            "market": r.market,
            "success": r.success,
            "run_id": r.run_id,
            "rows": r.n_rows,
            "metrics": r.metrics,
            "error": r.error,
        }
        for r in results
    ]


@router.get("/states/{market}")
async def get_states(market: str, limit: int = 100):
    """查某市场最新 run 的状态序列 (供人工对照历史 + 前端)."""
    async with AsyncSessionLocal() as s:
        run = (
            await s.execute(
                select(RegimeRun)
                .where(RegimeRun.market == market)
                .order_by(RegimeRun.trained_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if not run:
            raise HTTPException(status_code=404, detail=f"无 {market} 的 run")
        states = (
            await s.execute(
                select(RegimeState)
                .where(RegimeState.run_id == run.id)
                .order_by(RegimeState.trade_date.desc())
                .limit(limit)
            )
        ).scalars().all()
        return {
            "market": market,
            "run_id": run.id,
            "trained_at": str(run.trained_at),
            "algorithm": run.algorithm,
            "metrics": run.metrics,
            "states": [
                {
                    "trade_date": str(st.trade_date),
                    "state_label": st.state_label,
                    "state_prob": st.state_prob,
                }
                for st in reversed(states)
            ],
        }


@router.get("/runs/{market}")
async def get_runs(market: str, limit: int = 10):
    """查某市场的 run 元数据列表 (metrics/params)."""
    async with AsyncSessionLocal() as s:
        runs = (
            await s.execute(
                select(RegimeRun)
                .where(RegimeRun.market == market)
                .order_by(RegimeRun.trained_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return {
            "market": market,
            "runs": [
                {
                    "id": r.id,
                    "trained_at": str(r.trained_at),
                    "algorithm": r.algorithm,
                    "classifier": r.classifier,
                    "metrics": r.metrics,
                }
                for r in runs
            ],
        }
