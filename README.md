# binwh.quant-pilot

量化投研平台 — 行情采集、技术指标、市场状态识别（ML）、用户认证。

## 技术栈

- **后端**：FastAPI + SQLAlchemy 2.0 (async) + MySQL (asyncmy) + JWT (httpOnly Cookie) + Alembic
- **前端**：Vite + Vue 3 + TypeScript + Ant Design Vue 4 + lightweight-charts (K线图表)
- **数据源**：akshare / baostock / 国信证券 (多源 + 限流熔断)
- **ML**：scikit-learn + hmmlearn (PCA + HMM 市场状态识别)

## 快速启动

### 后端

```bash
cd backend
pip install -r requirements.txt       # 或 uv sync
cp .env.example .env                  # 修改 DATABASE_URL 和 JWT 密钥
uvicorn app.main:app --reload --port 8000
```

访问：`http://localhost:8000/api/health` → `{"status":"ok"}`

### 前端

```bash
cd frontend
npm install
npm run dev
```

访问：`http://localhost:5173`

## API 接口

### 健康检查

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | /api/health | 健康检查 | 否 |

### 认证 (Cookie-based JWT)

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | /api/auth/register | 注册 | 否 |
| POST | /api/auth/login | 登录 (设置 httpOnly Cookie) | 否 |
| POST | /api/auth/refresh | 刷新 access token | 否 |
| POST | /api/auth/logout | 登出 (清除 Cookie) | 否 |
| GET | /api/auth/me | 当前用户信息 | 是 |

### 行情数据

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | /api/data/sync/{stock_code} | 同步个股日K (akshare → MySQL) | 否 |
| GET | /api/data/stock/{code}/daily | 查询个股日K | 否 |
| GET | /api/data/index/{code}/daily | 查询指数日K | 否 |
| GET | /api/data/etf/{code}/daily | 查询 ETF 日K | 否 |
| GET | /api/data/etfs | ETF 列表 + 最新价/涨跌幅 | 否 |
| POST | /api/data/import/batch | 后台批量导入 (沪深300 + 指数/ETF) | 否 |
| POST | /api/data/import/retry | 重试导入失败标的 | 否 |
| GET | /api/data/import/progress | 查询导入进度 | 否 |

### 技术指标 (支持 stock / index / etf)

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | /api/indicators/{asset_type}/{code}/macd | MACD (DIF/DEA/HIST) | 否 |
| GET | /api/indicators/{asset_type}/{code}/rsi | RSI | 否 |
| GET | /api/indicators/{asset_type}/{code}/boll | 布林带 | 否 |
| GET | /api/indicators/{asset_type}/{code}/all | K线 + 全指标 (含 Keltner/ATR) | 否 |

> 指标优先读 `indicator_values` 表，无数据时回退实时计算。

### 市场状态识别 (ML)

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | /api/market_regime/train/{market} | 触发单市场训练 (A / HK) | 否 |
| POST | /api/market_regime/train_all | 触发全部市场训练 | 否 |
| GET | /api/market_regime/states/{market} | 查询最新状态序列 | 否 |
| GET | /api/market_regime/runs/{market} | 查询训练历史 (metrics/params) | 否 |

## 目录结构

```
QuantPilot/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI 入口 + lifespan 调度器
│   │   ├── config.py                  # Pydantic Settings (JWT/数据源/ML超参/定时同步)
│   │   ├── database.py                # async engine + session
│   │   ├── models/                    # SQLAlchemy 模型 (10张表)
│   │   │   ├── user.py                # 用户
│   │   │   ├── stock.py               # 个股 + 日K
│   │   │   ├── index.py               # 指数 + 日K
│   │   │   ├── etf.py                 # ETF + 日K
│   │   │   ├── fund.py                # 基金 + 日K
│   │   │   ├── instrument.py          # 标的元信息
│   │   │   ├── indicator.py           # 指标值存储
│   │   │   ├── market_regime.py       # 市场状态 (run + state)
│   │   │   └── import_log.py          # 导入错误日志
│   │   ├── schemas/                   # Pydantic schemas
│   │   ├── routers/                   # API 路由
│   │   │   ├── health.py / auth.py / data.py
│   │   │   ├── indicators.py / market_regime.py
│   │   ├── core/                      # 认证依赖注入
│   │   └── services/                  # 业务逻辑
│   │       ├── auth/                  # JWT + BCrypt + Cookie
│   │       ├── data/                  # 多数据源采集引擎
│   │       │   ├── akshare_source.py / baostock_source.py / guosen_source.py
│   │       │   ├── importer.py        # 批量导入 (限流 + 熔断)
│   │       │   ├── normalizer.py / registry.py / universe.py
│   │       ├── indicators/            # 技术指标 (MA/MACD/RSI/布林/Keltner/ATR)
│   │       ├── market_regime/         # ML 管线
│   │       │   ├── features.py → reduce.py → clustering.py → classifier.py
│   │       │   ├── evaluation.py / persist.py / pipeline.py
│   │       └── scheduler.py           # 定时行情同步 (上海 15:05)
│   ├── alembic/                       # 数据库迁移
│   ├── scripts/ / tests/
│   ├── pyproject.toml / requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/                       # Axios 封装 (auth/etf/indicators/marketRegime)
│   │   ├── views/                     # 页面 (Dashboard/Login/Register/EtfView/IndicatorView)
│   │   ├── components/                # 组件 (PrivateRoute 路由守卫等)
│   │   ├── stores/                    # 认证状态管理
│   │   ├── router/                    # Vue Router
│   │   └── types/
│   ├── vite.config.ts
│   └── package.json
└── docs/
    ├── plans/                         # 开发计划文档 (7份)
    └── brainstorms/                   # 需求脑暴
```

## 已实现功能

| 模块 | 说明 |
|------|------|
| 用户认证 | JWT + httpOnly Cookie + refresh token |
| 行情采集 | akshare/baostock/国信 三数据源，限流 + 熔断 + 批量导入 + 定时同步 |
| K线存储 | 个股 / 指数 / ETF 日K (MySQL) |
| 技术指标 | MACD / RSI / 布林带 / Keltner / ATR，支持前/后复权 |
| 市场状态识别 | PCA 降维 + HMM 聚类，支持 A 股 / 港股双市场 |
| 前端 | Dashboard / ETF 行情 / 指标图表 (lightweight-charts) |

## 后续开发阶段

- Phase 4：研报抓取
- Phase 5：FCFF 估值模型
- Phase 6：资产组合管理
- Phase 7：两融数据分析
- 微信扫码登录集成

## 学习笔记

该项目还包含从 [binwh.pyquant-learn](https://github.com/binwh/pyquant-learn) 继承的 Jupyter 学习笔记，位于 `notebooks/` 目录：

| 目录 | 内容 |
|------|------|
| `1.准备/` | Docker/Jupyter 量化环境搭建 |
| `2.Python入门/` | Python / NumPy / Pandas / SciPy 基础 |
| `3.财经包/` | 量化库实战：AKShare / Backtrader / bt / empyrical / PyFolio |
| `4.金融产品/` | 期权定价 (Black-Scholes) |
| `5.画图/` | Seaborn 可视化 |
