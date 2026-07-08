"""CLI: 限速分批导入历史数据.

用法:
  uv run python -m scripts.run_import           # 导入整个 universe
  uv run python -m scripts.run_import retry     # 重试失败标的
  uv run python -m scripts.run_import progress  # 查看进度 (独立进程, 仅看库内已写)

默认前台运行 (看实时日志). 限速由 settings.import_rate_seconds / import_concurrency 控制,
避免封 IP.
"""
import asyncio
import logging
import sys

from app.database import AsyncSessionLocal, init_db
from app.services.data.importer import retry_errors, run_import


async def main(mode: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # 确保表存在 (幂等).
    await init_db()

    if mode == "retry":
        prog = await retry_errors(AsyncSessionLocal)
    else:
        prog = await run_import(AsyncSessionLocal)
    print(prog.to_dict())


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "import"
    asyncio.run(main(mode))
