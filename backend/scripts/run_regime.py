"""CLI 触发 regime 训练 (单市场或全部).

用法:
  uv run python -m scripts.run_regime A    # 只训练 A 股
  uv run python -m scripts.run_regime HK   # 只训练港股
  uv run python -m scripts.run_regime      # A + HK 全部
"""
from __future__ import annotations

import asyncio
import sys

from app.database import AsyncSessionLocal
from app.services.market_regime.pipeline import run_all_markets, run_pipeline


async def main(market: str | None = None) -> None:
    if market:
        async with AsyncSessionLocal() as s:
            res = await run_pipeline(s, market)
        print(
            f"{market}: success={res.success} run_id={res.run_id} rows={res.n_rows} "
            f"metrics={res.metrics} error={res.error}"
        )
    else:
        results = await run_all_markets(AsyncSessionLocal)
        for r in results:
            print(
                f"{r.market}: success={r.success} run_id={r.run_id} rows={r.n_rows} "
                f"error={r.error}"
            )


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(arg))
