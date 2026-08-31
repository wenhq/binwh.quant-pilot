# Agent 指南 — binwh.quant-pilot

## 架构

```
backend/          # FastAPI + SQLAlchemy async + MySQL
  app/
    main.py       # FastAPI 入口 + lifespan（调度器）
    config.py     # Pydantic Settings（读取 .env）
    database.py   # 异步引擎 + 会话
    models/       # 14 张 SQLAlchemy ORM 表
    routers/      # health, auth, data, indicators, market_regime
    services/
      auth/       # JWT httpOnly Cookie + BCrypt
      data/       # 多源数据引擎（akshare/baostock/guosen）
      indicators/ # MACD/RSI/Bollinger/Keltner/ATR + 前/后复权
      market_regime/ # PCA → HMM → LogisticRegression 管线
      scheduler.py  # 每日 15:05 CST 同步
frontend/         # Vue 3 + TypeScript + Ant Design Vue 4
docker-compose.yml # 双容器部署：frontend(nginx) + backend，MySQL 外置阿里云 RDS
notebooks/        # Jupyter 学习笔记（Python → 量化库 → 期权 → 可视化）
docs/             # 设计文档（见下方索引）
memory/           # Agent 本地记忆（不入 git）
```

## 设计文档索引

详细设计见 [`docs/`](docs/)，建议阅读顺序：

| 文档 | 内容 |
|---|---|
| [`docs/requirements.md`](docs/requirements.md) | 系统级需求说明（FR / NFR / 验收标准） |
| [`docs/database-design.md`](docs/database-design.md) | 数据库表结构、ER 关系、索引设计 |
| [`docs/api-design.md`](docs/api-design.md) | 后端 RESTful 接口清单（auth / data / indicators / market_regime） |
| [`docs/detailed-design.md`](docs/detailed-design.md) | 模块内部实现 + 前端设计 + KDD 与技术债（取代旧 frontend-design.md） |
| [`docs/deployment.md`](docs/deployment.md) | Docker Compose 自部署手册 |
| [`docs/plans/`](docs/plans/) | 按日期编号的功能方案（需求 + 决策 + 实现单元） |
| [`docs/brainstorms/`](docs/brainstorms/) | 早期需求头脑风暴 |

## 数据库

14 张表：users, stocks, stock_daily_klines, indices, index_daily_klines, etfs, etf_daily_klines, funds, fund_daily_klines, instruments, indicator_values, regime_runs, regime_states, import_errors

详见 [`docs/database-design.md`](docs/database-design.md)。

## 数据源

- **akshare**：主力，多级回退（腾讯 → 新浪）
- **baostock**：稳定 A 股源，无 V8 依赖，线程安全
- **guosen**：指数/ETF 备用，带熔断

## 配置

所有配置走 `.env`（不入 git）。模板：根目录 `.env.example`（compose 部署）、`backend/.env.example`（本地开发）。依赖唯一权威是 `backend/pyproject.toml`（uv.lock 与其同步）。

## 脚本

- `scripts/run_import.py` — 批量导入
- `scripts/run_regime.py` — 触发状态训练
- `scripts/backfill_indicators.py` — 回填 indicator_values
- `scripts/fix_etf_history.py` — 重新导入 ETF 历史

## 测试

18 个 pytest 文件 131 用例，覆盖 auth（含路由保护矩阵）、数据源、importer、registry、universe、指标（含 /all 实时路径回归）、市场状态（features/reduce/clustering/classifier/evaluation/persist/pipeline）、models。异步模式用 `pytest-asyncio`；conftest 强制内存 SQLite，测试不触生产 RDS。

## 本地记忆（不入 git）

`memory/` 存放 agent 本地上下文，不提交到 git。接手本项目时**先读 [`memory/README.md`](memory/README.md)** —— 涵盖个人偏好、启动命令、当前待办清单，以及指向 [`docs/`](docs/) 设计文档的索引。逐次会话历史在 [`memory/handover.md`](memory/handover.md)（倒序排列）。

## 前端调试（agent-browser）

对 Vue 3 前端做可视化调试 / QA / 截图，用 `agent-browser`。

快速开始：
```bash
# 终端 1 — 启动独立调试 Chrome（保持窗口开着）
"D:/Scoop/apps/google-chrome/current/chrome.exe" \
  --remote-debugging-port=9333 \
  --user-data-dir="$TEMP/ab-chrome-profile" \
  --no-first-run about:blank

# 终端 2 — 驱动
agent-browser --cdp 9333 open http://localhost:5173
agent-browser --cdp 9333 snapshot -i
agent-browser --cdp 9333 screenshot out.png
```

必设环境变量（首次用 `setx`）：`AGENT_BROWSER_SKILLS_DIR=D:\Scoop\apps\agent-browser\current\skill-data`

## Agent 偏好

- Commit message 使用**中文**
