---
title: "详细设计文档"
type: docs
date: 2026-08-31
---

# 详细设计文档

> 本文档是 binwh.quant-pilot 设计四件套的最后一环：需求说明（`docs/requirements.md`，FR/NFR-ID）→ 数据库设计（`docs/database-design.md`，14 表）→ 接口设计（`docs/api-design.md`，22 端点）→ **详细设计（本文档：模块内部如何实现）**。部署运维细节由 `docs/deployment.md`（另行撰写）承载，本文档第 7 节仅给部署设计概要。按 2026-08-31 代码现状撰写；`backend/app/services/scheduler.py` 采用 zoneinfo 显式时区（提交 f85556c）。

## 1. 概述

### 1.1 定位与读者

本文档回答"每个模块内部是怎么实现的、为什么这样实现"。读者为维护本项目的工程师（含 AI 代理）。撰写原则：

- **引用优先，不重复**：表结构、端点签名、需求条目一律引用三件套，本文只写三件套没写的"内部视角"；
- **可追溯**：设计要素尽量标注 FR-ID（如 FR-DATA-008 → `backend/app/config.py::import_rate_seconds`），但不机械逐条；
- **如实记录现状**：与理想设计有差距处（技术债）如实记入第 9 节，不粉饰。

### 1.2 代码地图

```
backend/
├── app/
│   ├── main.py                  # FastAPI 实例、CORS、路由挂载、lifespan
│   ├── config.py                # pydantic-settings Settings 单例（§5.2 全字段表）
│   ├── database.py              # async engine / AsyncSessionLocal / Base / init_db
│   ├── core/dependencies.py     # get_current_user（Cookie → JWT → DB 校验）
│   ├── routers/                 # health / auth / data / indicators / market_regime（§3.1）
│   ├── schemas/auth.py          # 仅 auth 模块有 pydantic 请求模型
│   ├── models/                  # 10 个 ORM 模块、14 张表（见 database-design.md）
│   └── services/
│       ├── auth/                # config.py（Cookie 常量）+ security.py（JWT/bcrypt）（§3.2）
│       ├── data/                # 多源取数与导入：base/registry/baostock/akshare/guosen/
│       │                        #   normalizer/universe/importer/_py_mini_racer_stub（§3.3–3.9）
│       ├── indicators/          # ta.py 五类指标 + adjust.py 复权（§3.10）
│       ├── market_regime/       # ML 管线 8 个子模块（§3.11）
│       └── scheduler.py         # 进程内每日同步调度器（§3.12 / §6）
├── scripts/                     # run_import / run_regime / backfill_indicators / fix_etf_history（§3.13）
├── tests/                       # 18 文件 / 131 用例 + conftest 隔离（§5.5）
├── pyproject.toml               # 依赖权威清单（requirements.txt 已陈旧，见 TD-07）
└── Dockerfile                   # 两阶段构建（§7）

frontend/
├── src/
│   ├── main.ts / App.vue        # 入口 + ConfigProvider(zhCN)
│   ├── router/index.ts          # Hash 路由表（§4.2）
│   ├── stores/auth.ts           # reactive 认证状态模块（§4.4）
│   ├── api/                     # index(axios+401 单飞) / auth / etf / indicators / marketRegime（§4.5–4.6）
│   ├── components/              # PrivateRoute / KlineChart / IndicatorChart / AuthLayout(死代码)（§4.3/4.8）
│   └── views/                   # Login / Register / Dashboard / EtfView / IndicatorView（§4.7）
├── vite.config.ts               # dev server 5173 + /api 代理
├── nginx.conf                   # 生产反代（§7）
├── Dockerfile                   # node 构建 → nginx 托管 dist（§7）
└── package.json                 # 依赖与脚本
docker-compose.yml               # 根目录：backend + frontend 两容器（§7）
```

### 1.3 建议阅读路径

- **新接手维护者**：§2（架构与生命周期）→ §6（调度与数据流）→ 按需查 §3/§4 对应模块节；
- **改动 API**：先读 `docs/api-design.md` 的端点契约，再读本文 §3.1 了解该 router 内部实现与会话/错误映射约定；
- **线上排障**：§5.3（日志点）→ §5.4（错误处理约定）→ §6.4（熔断）→ §9（是否为已知技术债）；
- **部署/运维**：本文 §7 概要 → `docs/deployment.md` 操作手册。

## 2. 系统架构

### 2.1 组件图

```mermaid
graph TB
    subgraph browser["浏览器"]
        FE["Vue 3 SPA（Hash 路由）<br/>frontend/src → dist/"]
    end
    subgraph fc["frontend 容器（nginx:alpine）"]
        NG["nginx :80<br/>静态资源 + gzip + SPA fallback"]
    end
    subgraph bc["backend 容器（python:3.12-slim）"]
        UV["uvicorn :8000<br/>单 worker + --proxy-headers"]
        subgraph fa["FastAPI 应用（单进程事件循环）"]
            RT["routers/：health · auth · data · indicators · market_regime"]
            DEP["core/dependencies.py<br/>get_current_user"]
            SV["services/：auth · data · indicators · market_regime · scheduler"]
            SCH["scheduler 后台 asyncio 任务"]
            IMP["importer 后台任务（信号量限速）"]
        end
    end
    RDS[("阿里云 RDS MySQL<br/>stockdb · 14 表")]
    BAO["baostock（纯 HTTP）"]
    AKS["akshare 生态：腾讯 / 新浪 / 中行牌价"]
    GSO["国信限免接口"]

    browser -- "HTTP 80" --> NG
    NG -- "静态 JS/CSS" --> browser
    NG -- "/api/ 反代（read_timeout 300s）" --> UV
    UV --> RT
    RT --> DEP
    RT --> SV
    SCH --> SV
    IMP --> SV
    SV -- "aiomysql / SQLAlchemy 2 async" --> RDS
    SV -- "run_in_executor 线程池" --> BAO
    SV --> AKS
    SV --> GSO
```

要点：

- **数据库不入容器**（FR-DEPLOY-002），backend 经连接串直连 RDS；compose 中仅保留可选 `local-db` profile 的 MySQL 服务供本地调试；
- **前后端同源**：生产环境所有请求经 nginx，`/api/` 反代到 `http://backend:8000/api/`，浏览器视角无跨域（FR-DEPLOY-004）；Cookie 域即前端域；
- **外部数据源全部在 backend 进程内消费**：同步阻塞 SDK 经线程池调用（KDD-08），registry 做多级回退与熔断（§6.4）。

### 2.2 后端分层

| 层 | 位置 | 职责 | 依赖方向 |
| --- | --- | --- | --- |
| 接入层 | `backend/app/routers/` | HTTP 协议、参数校验、鉴权声明、后台任务触发 | → services / models / core |
| 鉴权依赖 | `backend/app/core/dependencies.py` | `get_current_user` 单一依赖（§5.1） | → services/auth、models、database |
| 服务层 | `backend/app/services/` | 全部业务逻辑：取数、导入、指标、ML、调度 | → models / config / database |
| 持久层 | `backend/app/models/` + `database.py` | ORM 模型、engine/session 工厂、`init_db` | → config |
| 配置 | `backend/app/config.py` | `Settings` 单例（环境变量 > .env > 默认值） | 无 |

规则：router 不写业务逻辑（`routers/data.py::sync_stock` 是历史例外，见 TD-08）；service 不感知 HTTP（`PipelineResult` 等用 dataclass 而非 `HTTPException` 传错）；models 不含查询逻辑（查询散在 routers/services 中）。

### 2.3 请求生命周期

1. 浏览器发起同源请求 → nginx 匹配 `location /api/`，附加 `X-Forwarded-For/Proto`，`proxy_pass http://backend:8000/api/`（保留前缀，后端无需 `--root-path`）；
2. uvicorn 以 `--proxy-headers --forwarded-allow-ips <内网网段>` 信任 nginx 头，重写 client 地址（当前仅利于日志可读）；
3. `CORSMiddleware`（`allow_credentials=True` + origin 白名单 `settings.cors_origin_list`）——生产同源下不参与，仅开发 Vite 代理场景生效；
4. 路由匹配 → 路由级依赖 `get_current_user`（data / indicators / market_regime 三个 router 整体声明，FR-AUTH-007；auth 的 `/me` 端点级声明）；
5. handler 自行 `async with AsyncSessionLocal()` 开会话（不走 `Depends(get_db)`，`get_db` 目前仅 data.py import 未使用）；
6. 返回内联 dict（无统一包裹体，见 api-design 3.1）；会话随 `async with` 关闭；未 commit 的变更被丢弃。

### 2.4 lifespan 生命周期

`backend/app/main.py`：

```
lifespan:
  启动: init_db()          # import app.models 注册全部表到 Base.metadata →
                           # engine.begin() 事务内 Base.metadata.create_all（只建缺失表，无迁移，TD-01）
        start_scheduler()  # asyncio.create_task(_scheduler_loop)，模块级单例防重复启动
  yield                    # 服务期：请求处理 + 调度循环 + 导入/训练后台任务并存
  关停: stop_scheduler()   # task.cancel() → 循环捕获 CancelledError 退出
```

配套保障：compose `stop_grace_period: 30s` + Dockerfile `exec 形式 CMD` 保证 SIGTERM 直达 uvicorn → lifespan shutdown 有时间取消调度任务、释放 aiomysql 连接。`routers/__init__.py` 对 market_regime 的 import 包了 `try/except ImportError`——属防御性遗留（router 本身已延迟 import pipeline，该分支实际不会触发，见 FR-REGIME-007 与 KDD-09）。

### 2.5 并发模型

- **单进程事件循环**为唯一调度主体：调度器、导入器、训练任务都是同一 loop 上的 asyncio 任务；这是 uvicorn 必须 `--workers 1` 的根本原因（多 worker = 多份调度器重复同步，KDD-02）；
- **同步阻塞 SDK**（akshare / baostock / 国信 urllib）经 `loop.run_in_executor` 下放线程：导入器用默认 executor（`importer._fetch_async`），`routers/data.py::sync_stock` 用模块级 `ThreadPoolExecutor(max_workers=2)`；
- **线程安全约束**：baostock 是进程级全局 session，非线程安全——`baostock_source.py` 用模块级 `_bs_lock` 把 login+query 整段串行化、`_login_lock` 保证进程内只 login 一次；这是所有 baostock 调用必须走该模块封装的原因。

## 3. 后端模块设计

### 3.1 routers 与 core

| Router | 前缀 | 鉴权 | 内部要点 |
| --- | --- | --- | --- |
| `routers/health.py` | 无 | 公开 | 返回 `{"status": "ok"}`，供容器 healthcheck 与编排探活（AC-08/AC-10） |
| `routers/auth.py` | `/auth` | 4 公开 + `/me` 需登录 | `_set_cookie` 统一写 Cookie（HttpOnly + SameSite=Lax + `secure=settings.cookie_secure`）；refresh 只滚动 access_token 不轮换 refresh_token；logout 幂等 delete_cookie |
| `routers/data.py` | `/data` | 路由级 | `sync_stock` 自动注册标的信息 + 逐行 `session.merge` upsert（历史路径，TD-08）；`import/batch`、`import/retry` 以 `asyncio.create_task` 后台执行并存入模块级 `_bg_tasks` dict；`import/progress` 读 importer 进程内单例 |
| `routers/indicators.py` | `/indicators` | 路由级 | `_load_indicators`（读 indicator_values 缓存）与 `_load_klines`（读 K 线 + 现场复权）双通道；`/all` 按 trade_date 把两路数据 merge 成宽行；实时路径参数（fast/slow/period…）仅在 `source: "realtime"` 生效，db 路径回显但不生效 |
| `routers/market_regime.py` | `/market_regime` | 路由级 | `train/{market}` 校验 `market in ("A","HK")` 否则 400；pipeline import 全部延迟在 handler/任务函数内执行（可选加载）；`states/{market}` 取 `trained_at desc limit 1` 的最新 run 再取其状态序列 |

`core/dependencies.py::get_current_user(request) -> User`：取 `ACCESS_TOKEN_COOKIE` → `decode_token`（失败映射 `ValueError`）→ 按 `sub` 回查 `users` 表并校验 `is_active`；三种失败分别返回 401 `未认证` / `无效凭证` / `用户无效`。注意它自建 `AsyncSessionLocal` 会话而非复用请求级依赖。

#### 3.1.1 routers/auth.py 内部实现

- `_set_cookie(response, name, value, max_age)`：唯一的写 Cookie 出口——`httponly=True`、`samesite="lax"`、`secure=settings.cookie_secure`、`path="/"`；Cookie 名取自 `services/auth/config.py` 两个常量；Max-Age 与 token exp 同源（`settings.access_token_expire_minutes*60` / `refresh_token_expire_days*86400`）；
- `register`：用户名查重 → 400 `用户名已存在`；成功 201 返回 UserInfo，**不自动登录**（FR-AUTH-001，前端随后跳 login）；
- `login`：`verify_password` 失败 → 400 `用户名或密码错误`（文案刻意不区分"无此用户/密码错"，FR-AUTH-002；400 而非 401 的原因见 TD-03）；成功签双 token + set_cookie ×2 + UserInfo（FR-AUTH-006）；
- `refresh`：校验 refresh_token Cookie（缺失/无效 → 401 `未认证`）→ 只滚动签发新 access_token 并 set_cookie；**refresh_token 不轮换**（前端 Cookie 未过期期间可无限续期，FR-AUTH-005）；
- `logout`：`delete_cookie` ×2（带与写入时一致的 path/secure 参数才能真正删除），幂等（FR-AUTH-005）；
- `/me`：端点级 `Depends(get_current_user)`，返回 UserInfo——前端 `restoreSession` 的唯一数据源（FR-AUTH-004）。

#### 3.1.2 routers/data.py 内部实现

| 函数 | 内部要点 |
| --- | --- |
| `sync_stock` | 自动注册：`akshare_client.fetch_stock_info` 补名称/市场 → `_executor.submit(fetch_stock_daily)` 线程取数 → **逐行 `session.merge(kline)`** upsert（历史路径，慢于 ODKU，TD-08）；`adj_factor=None`；空数据 → 404 `数据源未返回数据` |
| `get_etfs` | 全量 ETF 列表 + 每只最近 2 根 K 线算 `latest_close`/`change_pct`——**N+1 查询**（约 6 只规模可接受，FR-FE-004 列表页） |
| `get_etf_klines` / `get_index_klines` / `get_stock_klines` | limit 上限 100/120/120；取最新 N 根后 `reversed` 成升序返回（图表组件按时间正序消费） |
| `import_batch` | 入参 universe 构建（默认 `build_universe()`；`retry=true` 走 `retry_errors`）；`background=true`（默认）→ `asyncio.create_task` 存 `_bg_tasks["import"]` 并立即返回进度快照；`background=false` → `await run_import` 返回最终进度 |
| `import_progress` | 读 importer 模块级 `_progress.to_dict()`；无任务时返回 `running=false` 空进度 |
| `import_retry` | 同 import_batch 的后台/同步双模式，任务体为 `retry_errors` |

#### 3.1.3 routers/indicators.py 内部实现

- `_load_klines(asset_type, code, limit, adjust_mode)`：asset_type 白名单校验 → 400 `asset_type must be etf/index/stock`；表缺失/标的不存在/无 K 线 → 404（四种 detail 文案）；`adjust_mode` 在**读取期**应用（存储始终是原始价 + 因子，FR-IND-006）；limit 截取最新 N 根后反转升序；
- `_load_indicators(asset_type, code, limit)`：直读 `indicator_values` 缓存表；**忽略** fast/slow/signal/period 等参数（回显但 db 路径不生效——缓存按默认参数计算，见 TD-12）；
- 四端点（macd/rsi/boll/all）响应带 `source` 字段：缓存命中 `"db"`、未命中现场计算 `"realtime"`（调用方据此理解数值口径差异）；
- `/all`：K 线 + 指标缓存按 trade_date 用 dict 合并成宽行（指标缺失日期填 null），额外附 keltner/atr 与 `source`——前端 `AllIndicatorsResponse` 类型未覆盖这些字段（api-design 6.4 / TD-12）。

#### 3.1.4 routers/market_regime.py 内部实现

- `train/{market}`：`market` 枚举校验（400 `market 必须是 A 或 HK`）→ `_bg_tasks[f"train_{market}"] = create_task(_run_train(market))`；`_run_train` 内自建会话调 `pipeline.run_pipeline`，结果只记日志（`success=False` 也不改 HTTP 响应——任务已 202 返回，FR-REGIME-006）；pipeline/依赖的 import 全部在函数体内（可选加载，KDD-09）；
- `states/{market}`：`RegimeRun.trained_at desc limit 1` 取最新 run → 其 states `reversed` 升序返回（含 state_label/state_prob/features_snapshot 摘要）；无任何 run → 404 `无 {market} 的 run`（Dashboard 显示 Empty 提示"需先训练"的来源，FR-FE-002）；
- `runs/{market}`：最近 10 次 run 元数据（trained_at/n_samples/n_components/metrics），供追溯对比（FR-REGIME-006）。

### 3.2 services/auth

- `config.py`：仅两个常量 `ACCESS_TOKEN_COOKIE = "access_token"`、`REFRESH_TOKEN_COOKIE = "refresh_token"`。Cookie 名是前后端契约，集中一处防漂移。
- `security.py`：
  - `pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")`；`hash_password` / `verify_password`（FR-AUTH-003，NFR-SEC-002）。bcrypt 钉在 `>=4.0.1,<4.1`（4.1+ 移除 `__about__`，passlib 1.7.4 读版本会报错，pyproject 有注释）；
  - `create_access_token(username)` / `create_refresh_token(username)`：claims 均为 `{"sub", "exp"}`，HS256，`exp` 用 `datetime.now(UTC).timestamp()` 手工计算；两 token 无 `typ` 区分（TD-02）；
  - `decode_token(token) -> dict`：`jwt.decode` 失败把 `JWTError` 归一为 `ValueError`，调用方只捕一种异常。

### 3.3 services/data/base —— 数据源契约

- `DataSource(ABC)`：四个抽象方法 `fetch_index_daily / fetch_etf_daily / fetch_stock_daily / fetch_macro_proxy`，统一签名 `(code, start?, end?) -> pd.DataFrame`（列：trade_date/open/close/high/low/volume/amount）。契约约定：空数据返回空 DataFrame（由 registry 决定是否换源），源端异常向上抛。
- `FetchResult(df, source)`：frozen dataclass，`source` 记录实际命中源名（如 `"baostock"` 或 ETF 合并路径的 `"baostock+akshare"`），供导入器回填 `instruments.data_source` 与进度展示。
- `_py_mini_racer_stub.py`：向 `sys.modules` 注入空壳 `py_mini_racer.MiniRacer`，解除 akshare 1.18.x 顶层对 mini-racer/V8 的硬依赖（V8 在部分平台 FATAL 崩进程）；`services/data/__init__.py` 第一行 import 它，保证先于任何 `import akshare` 执行（KDD-10）。

### 3.4 services/data/registry —— 多源调度与熔断

- `DataSourceRegistry`：`register()` 按序登记源并初始化 `_SourceHealth`；`_dispatch(fn)` 按注册顺序逐源 `_try`，命中第一个有数据的源即返回 `FetchResult`。
- `_try` 的四分支：熔断冷却期内直接跳过；`NotImplementedMarker`（源不支持该品类）静默跳过不计数；其他异常调 `health.trip()` 计数；空 DataFrame 视为"没拿到"继续换源；成功则 `record_success()` 清零。
- **ETF 是唯一例外**：`fetch_etf_daily` 不短路——向所有源都取数后 `pd.concat` 合并，按 `trade_date` 去重 `keep="first"`（注册顺序在前的源优先）。原因：baostock 只有近期约 6 个月数据，akshare/国信有完整历史，合并后既有长历史又有最新近端。
- `health_snapshot()`：暴露各源失败计数与熔断态（可观测，当前无端点消费）。
- `default_registry()` 的优先级：**baostock（A 股主源）→ akshare（港股/国债/外汇回退）→ guosen（兜底）**（FR-DATA-002/003/004，NFR-REL-001）。熔断状态机详见 §6.4。

### 3.5 services/data/baostock_source

- 定位：A 股主源。纯 HTTP、无 V8 依赖（模块 docstring 记录了替代 akshare 主路径的动机）。
- `_to_baostock_code(code, asset_type, market)`：裸代码 → `sh.600519` / `sz.000001`。优先用 universe 提供的 market 精确区分（000300 指数是沪市、000001 个股是深市，纯前缀无法区分）；无 market 时按前缀回退；非 A 股代码返回 None（调用方返回空 df）。
- `_query()`：`query_history_k_data_plus`，字段 `date,open,high,low,close,volume,amount`，`adjustflag="3"`（不复权，与"存原始价 + 因子"策略一致，见 database-design 4.3）；`_bs_lock` 串行化 + 幂等 login；数值列 `pd.to_numeric` 清洗后交 `normalize_daily`。
- 不支持品类（港股指数 `HSI/HSTECH` 等、国债 `CN10Y/US10Y` 等、外汇 `USDCNY`、港股个股、宏观代理）统一 `raise NotImplementedMarker`，把取数责任显式交还 registry 换源。

### 3.6 services/data/akshare_source 与 akshare_client

- `akshare_source.py`（实现 DataSource 契约）：
  - `fetch_index_daily`：非纯数字代码走 `_special_index_fallback`——国债按 `_BOND_MAP`（`bond_gb_us_sina` / `bond_gb_zh_sina`）、外汇按 `_FX_MAP`（`currency_boc_sina`，央行中间价填 OHLC 伪指数 `_fx_to_ohlc`）、港股指数（`_HK_INDEX_SYMBOLS`）走新浪港股接口；纯数字 A 股指数走 `_tencent_sina_fallback`：先腾讯 `stock_zh_index_daily_tx`（有 amount 无 volume，volume 填 0），失败再新浪 `stock_zh_index_daily`（有 volume 无 amount，全量返回后 `_clip_by_date` 裁剪）。**刻意跳过东方财富系接口**：其反爬 JS 经 mini_racer 执行，V8 isolate 非线程安全，在工作线程里会崩进程（模块注释明确记录）；
  - `fetch_etf_daily`：同样腾讯 → 新浪两级回退（FR-DATA-002）；
  - `fetch_stock_daily`：A 股 `stock_zh_a_daily(adjust="")`（不复权）；港股 `stock_hk_daily`（不支持 start/end，全量后裁剪）；
  - `fetch_macro_proxy`：仅实现 `us_treasury_10y`（`bond_zh_us_rate` 宽松匹配"美国…10"列）。
- `akshare_client.py`（旧直连路径，仅 `routers/data.py::sync_stock` 使用）：`fetch_stock_daily`（含中文列名 rename）与 `fetch_stock_info`（`stock_individual_info_em` 取股票简称/市场，失败降级返回 code 本身）。新代码应走 registry，不新增对它的依赖。

### 3.7 services/data/guosen_client 与 guosen_source

- `guosen_client.py`：标准库 urllib 直连 `settings.gs_api_base`（默认国信限免域名）+ `apiKey=settings.gs_api_key` + `softName`；`query_past_hq(code, set_code, want_nums)` 只能取"近 N 个交易日"，不支持日期范围（故定位为近端补数兜底，全量回填归 baostock/akshare）。`GuosenError` 覆盖三类失败：未配 key、HTTP 非 2xx（鉴权/限免失效）、网络异常/超时（15s）——统一供 registry 计入熔断。`SET_CODE` 映射 SH/SZ/BJ/HK/US。SSL 上下文为兼容旧服务器禁用了证书校验（`CERT_NONE` + `SECLEVEL=0`，TD-06）。
- `guosen_source.py`：`NotImplementedMarker` 异常定义于此（registry 与 baostock 反向 import 它）。`fetch_index_daily/fetch_etf_daily` 固定 `SET_CODE["SH"]`、`want_nums=5000` 后本地裁剪（`_market_to_setcode` 帮助函数存在但未被调用，属遗留）；个股与宏观代理显式标记不支持（沪深300个股由 baostock/akshare 负责）。`_parse_past_hq` 对响应结构做宽松解析（逐层找 `data/result/list` 键）+ `_FIELD_ALIASES` 字段名归一。

### 3.8 services/data/normalizer

`normalize_daily(df) -> pd.DataFrame` 是所有源的最后一道清洗：

1. 中文（东财系）与英文（港股系）列名统一映射；缺失必需列（trade_date/open/close/high/low/volume）抛 `ValueError`；
2. `trade_date` 统一转 `datetime.date`（杜绝 datetime 混入 DATE 列，见 database-design 4.6）；数值列 `to_numeric(errors="coerce")`；volume 补 0 转 int64；
3. 固定列序输出并按 trade_date 升序。

幂等 upsert 链路的第一环：**任何源的数据进入写库路径前都已是同一 schema**。

### 3.9 services/data/universe

纯数据结构模块（不写库，写库归 importer，便于独立测试）：

- `CORE_INDICES`（13 个：8 个 A 股宽基/成长指数 + HSI/HSTECH + CN10Y/US10Y 国债收益率 + USDCNY 汇率代理——宏观代理按"伪指数"建模）、`CORE_ETF`（6 只宽基 ETF，带 `tracks` 跟踪关系）、`SECTOR_ETF`（14 只行业/主题 ETF，用作进攻−防御价差特征源）；合计固定标的池 33；
- `build_stock_universe("000300")`：`index_stock_cons_csindex` 取成分股（按列位置取第 5/6 列防列名干扰）→ merge `stock_zh_a_spot_em` 总市值 → 市值降序（FR-DATA-006），市值缺失时保持原序；`_infer_market` 按代码段推断 SH/SZ/BJ；
- `build_universe()` 聚合为 `Universe` dataclass（stocks/indices/etfs/macro_proxies）。

### 3.10 services/data/importer —— 限速批量导入

职责：把 universe 变成库内数据（FR-DATA-005/007/008，NFR-PERF-003）。

- **进度**：`ImportProgress` dataclass + 模块级单例 `_progress`（进程内、不持久化，进程重启清零）；`to_dict()` 的 `recent_errors` 截取最近 20 条；`skipped` 语义 = 取到空数据但未报错。
- **元数据 upsert**：`_upsert_stock/_upsert_index/_upsert_etf` 按 code 先查后插（查到则回填可变字段）；`_upsert_instrument` 双方言：MySQL 走 `INSERT ... ON DUPLICATE KEY UPDATE`，SQLite（测试）降级 select+update/insert；`data_source` 优先 universe 配置、缺失回填实际命中源。
- **日线批量 upsert**：`_bulk_upsert_klines(session, table, asset_id_col, asset_id, df)` 按表实际拥有的列过滤（indices 无 adj_factor），逐行组装后一条 `mysql_insert(...).values(rows).on_duplicate_key_update(...)` 写入；更新列集合刻意排除 `(asset_id, trade_date)` 本身（幂等语义见 database-design 4.1，FR-DATA-009 / AC-03）。
- **主流程** `run_import(session_factory, universe=None, *, registry=None, concurrency=None, rate_seconds=None)`：展平任务列表 → `asyncio.Semaphore(concurrency)` → `asyncio.gather` 并发 `_import_task` → 完成置 `running=False`。`_import_task` 单标的流程：独立会话 → `_import_one`（取数 + 元数据 + 日线）→ `_upsert_instrument` → commit；异常截断到 500 字符写 `import_errors`（`retried_at` NULL）并计入 progress；**finally 中 `asyncio.sleep(rate)`**——限速发生在信号量槽位内，详见 §6.5。

```
_import_task(task):                                  # 槽位 = 信号量许可
    async with semaphore:
        try:
            df  = await _fetch_async(...)            # 线程池跑同步 SDK（按品类分派 registry/合并路径）
            inst = await _import_one(...)            # 元数据 upsert + _bulk_upsert_klines(ODKU)
            await session.commit(); progress.succeeded += 1
        except Exception as e:
            session.add(ImportError(asset_type, code, str(e)[:500]))   # retried_at=NULL
            progress.failed += 1
        finally:
            progress.done += 1
            await asyncio.sleep(rate_seconds)        # 槽内限速（§6.5）
```
- **重试** `retry_errors`：取 `retried_at IS NULL` 记录构建任务（固定 `Semaphore(2)`），复用 `_import_task`；任务结束后**无条件**回写原记录 `retried_at`——若重试仍失败，`_import_task` 内部会新插一条 `retried_at=NULL` 的 ImportError，天然进入下一轮重试候选（断点续传语义，NFR-PERF-003 / AC-12）。
- 取数统一经 `_fetch_async` → 默认 executor 线程池（同步 SDK 不阻塞事件循环）。

### 3.11 services/indicators

- `ta.py`（无状态纯函数，输入输出 pandas）：
  - `macd(close, fast=12, slow=26, signal=9)`：`ewm(span, adjust=False)`；`hist = (dif − dea) × 2`（A 股惯例放大 2 倍）；
  - `rsi(close, period=14)`：Wilder 平滑（`ewm(alpha=1/period)`）；
  - `bollinger(close, period=20, std_dev=2.0)`：SMA ± k·rolling.std()（pandas 默认样本标准差）；
  - `keltner(close, high, low, period=20, multiplier=1.5)`：EMA 中轨 ± 1.5×ATR(20)，TR 三分量取 max；
  - `atr(high, low, close, period=14)`：TR 的 rolling 均值。
- `adjust.py`：`adjust(df, mode)` 统一入口。前复权 `price × (adj_factor / latest_adj_factor)`（以最新一日为基准），后复权 `price × adj_factor`；OHLC 与 amount 同比例缩放，volume 不变；无因子列或全 NaN 时原样返回（FR-IND-006）。存储策略（存原始价 + 因子、`adjust_mode` 不落库）见 database-design 4.3。
- `__init__.py` 平面导出 8 个函数，router 与 scheduler 均从此 import。

### 3.12 services/market_regime —— ML 管线

模块顺序即管线顺序（FR-REGIME-002），各子模块可独立测试（各有对应 test 文件）：

- **config.py**：`MARKET_CONFIGS = {"A": ..., "HK": ...}`。A 股 `primary="composite"`（上证综指 0.5 + 深证成指 0.5 按收益率加权合成，`_build_composite_primary` 复利合成基期 100），`spread_pairs=[("512480","510880")]`（半导体进攻 − 红利防御）；HK `primary="HSI"`，`spread_pairs=[("HSTECH","HSI")]`。`macro` 字典仅作文档性配置——当前精简特征方案（`build_feature_matrix` docstring）**不**把宏观代理放进特征，避免噪音。
- **features.py**（U2，防泄漏核心）：`load_close_series`（index 表优先、回退 etf 表，返回按日期升序的 close Series）→ `multi_period_returns`（窗口取 `settings.regime_return_windows`=(5,21,63)）→ `realized_volatility`（对数收益 ewm span=21 标准差 × √252 年化，0/inf 置 NaN）→ spread 列（`log_spread_change` 一阶差分 + reindex/ffill 对齐主序列）→ 列有效样本 <50% 的剔除 → **`standardize_expanding(min_periods=60)`**：以"截至当日 t"的 expanding 均值/方差标准化，warmup 期 NaN 被 drop——全样本统计量被禁止进入特征（R2 防泄漏）。
- **reduce.py**（U3）：`PCA(n_components=settings.regime_pca_variance=0.95)`——float 语义由 sklearn 自动选达到累计方差的最少主成分数；输出 `PCAResult`（components 得分矩阵、loadings 载荷、累计方差）。模块注释说明 PCA 全样本 fit 的防泄漏论证（线性变换不直接产生预测，真正的泄漏口在 U2/U5 已封）。
- **clustering.py**（U4）：`GaussianHMM(covariance_type="full", n_iter=100)`；`fit_hmm` 跑 `n_init=5` 个种子（`regime_random_state + i`）取对数似然最优，缓解 HMM 初值敏感；**label 语义对齐**是关键设计——hmmlearn 的 label 分配是任意的，`_align_labels_by_return` 按主标的收益率重排（均值收益最低的状态 = 最高 label = "动荡"），把"动荡"锚定在"下跌"而非"高波动"（修正牛市高波动上涨被误判动荡的偏差）；无收益率时回退 `_align_labels`（pc1 波动对齐）。数据 < 2×n_components 抛 `ValueError`。
- **classifier.py**（U5，防泄漏第二核心）：监督目标 `y = state_label.shift(-1)`（t+1 状态），切断"同期特征预测同期标签"的泄漏路径；时序切分（前 60% 训练 / 后 40% 测试，不 shuffle），内置 `assert` 训练/测试日期不重叠；`LogisticRegression(max_iter=500, class_weight="balanced", random_state=42)`；动荡概率取 `proba[:, n_classes-1]`；metrics 含 accuracy/precision/recall/f1/KS（`scipy.stats.ks_2samp`，动荡 vs 非动荡二值化）。
- **evaluation.py**（U6）：`build_overlay` 产出 `{trade_date, close, state_label, state_prob}` 叠加序列（落库主体）；`regime_economic_stats`（各状态日均对数收益/年化波动/天数占比）；`HISTORICAL_EPISODES` 三个历史锚点（2018 贸易战/2022 调整/2024 反弹）的动荡态覆盖率（R7 人工对照门槛的结构化形态）；`compute_sector_attribution`（各状态下各指数平均收益）与 `compute_index_contributions`（按特征名后缀聚合 PCA 载荷贡献度）。注意 `build_overlay` 的 `state_prob` 固定取 `probabilities.iloc[:, 1]`——与 classifier 的 `n_classes-1` 口径在 K≠2 时不一致（TD-10）。
- **persist.py**（U7）：`save_run`（flush 取 id）+ `save_states`（**先删该 run 全部旧 states 再插**，覆盖式幂等）；`_to_jsonable` 把 numpy/pandas 类型递归转原生（JSON 列可序列化，NaN→None）；`_to_date` 统一日期归一。
- **pipeline.py**（编排）：`run_pipeline(session, market) -> PipelineResult`——特征 → 主序列（composite 或 primary）→ PCA → HMM（align_returns=主序列对数收益）→ 逻辑回归 → 评估 → save_run + save_states → commit；**任何异常 rollback 后返回 `success=False + error`，不抛**（调用方决定 HTTP 语义）；`run_all_markets` 每市场独立会话顺序执行，互不影响（FR-REGIME-001）。训练超参全部读 `settings.regime_*`（FR-REGIME-003）。

编排伪代码（标注各步落点模块）：

```
run_pipeline(session, market):
    cfg = MARKET_CONFIGS[market]
    closes = load_close_series(session, cfg["primary_assets"])      # features.py, index→etf 回退
    X = build_feature_matrix(closes, cfg)                            # features.py: 收益窗口+rv+spread → expanding 标准化
    comps = fit_pca(X, settings.regime_pca_variance)                 # reduce.py
    hmm = fit_hmm(comps.X, n_components=settings.regime_n_components,
                  n_init=5)                                          # clustering.py, 最优对数似然
    labels = align_labels_by_return(hmm.states, closes)              # 低收益态 → 最高 label
    clf  = train_classifier(X, labels, split=0.4)                    # classifier.py, y=shift(-1) 时序切分
    eval = evaluate(closes, labels, comps, cfg)                      # evaluation.py: overlay/stats/episodes/sector
    run   = save_run(session, market, metrics=clf.metrics, ...)      # persist.py, flush 取 id
    save_states(session, run, labels, probs, ...)                    # persist.py, 先删后插
    session.commit(); return PipelineResult(success=True, run_id=run.id)
# 异常 → session.rollback(); return PipelineResult(success=False, error=...)
```

### 3.13 services/scheduler —— 进程内调度器

> 业务规则：上海时间每交易日 15:05 触发、跳过周末、失败 30 分钟重试、参数读 settings（FR-DATA-010）。

- `_SH_TZ = ZoneInfo("Asia/Shanghai")`：显式时区，与宿主机/容器 TZ 彻底解耦；时区数据由 `tzdata` 包兜底（pyproject 声明，slim 镜像额外 apt 安装）。
- `_next_sync_shanghai(now) -> datetime`：入参统一转 Shanghai → replace 到 `market_sync_hour:market_sync_minute` 整分 → 已过触发点顺延一天 → `while weekday >= 5` 跳周末 → 返回 **UTC aware** datetime（调用方做 aware 差值精确 sleep，旧实现 naive + 固定 8 小时偏移在 TZ=+8 机器上会错一天，这是重写的根因）。法定节假日不单独维护，由"数据源无新数据自然跳过"兜底（requirements 5.4）。
- `_scheduler_loop`：`while True`：算下次触发点 → `asyncio.sleep` → `_run_daily_sync()`；`CancelledError` 退出；异常记 error 后 sleep `market_sync_retry_minutes`（重试语义缺口见 TD-09）。
- `_run_daily_sync`：**只覆盖固定池 ETF（20 只）+ 指数（13 个），不含沪深300个股**（个股靠手动批量导入）；每标的最小会话：`max(trade_date)` → `start = last + 1 day` 增量取数 → `_filter_new_rows` 双保险过滤 → ODKU upsert（`_upsert_klines` 与 importer 同构）→ 有写入才 `_recalc_indicators` → commit；ETF 以 `adjust_mode="forward"`、指数以 `"none"` 重算。单标的空数据/取数异常跳过不中断整体；写库异常上抛交调度循环重试路径。
- `_recalc_indicators(session, asset_type, entity_id, code, adjust_mode)`：全量读该标的 K 线 → `_calc_indicators`（复权 + 五类指标）→ dropna(how="all") → **先删该 `(asset_type, code)` 全部 indicator_values 再批量插入**（FR-IND-007"整体更新"，AC-06；与 persist.save_states 同一幂等模式）。
- `start_scheduler/stop_scheduler`：模块级 `_scheduler_task` 单例；lifespan 调用（§2.4）。

### 3.14 scripts/

| 脚本 | 用途 | 备注 |
| --- | --- | --- |
| `scripts/run_import.py` | CLI 批量导入 / retry / progress | 自带 `init_db()`，前台看实时日志 |
| `scripts/run_regime.py` | CLI 触发单市场或全部训练 | 与 API 同一 pipeline 入口 |
| `scripts/backfill_indicators.py` | 存量 K 线指标回填（ETF forward / index none） | 与 scheduler `_recalc_indicators` 逻辑同构（代码有重复，可接受） |
| `scripts/fix_etf_history.py` | 一次性修复：仅重导有完整历史的 ETF | 历史运维脚本，保留备查 |

## 4. 前端设计

> 本章吸收并取代 `docs/frontend-design.md`（已删除），并纠正其两处错误（见 4.3 与 4.9）。

### 4.1 技术栈与构建

Vue 3.4（`<script setup>` + Composition API）、TypeScript 5.6、Vite 5、Ant Design Vue 4（`App.vue` 以 `ConfigProvider` 注入 zhCN locale）、Vue Router 4（Hash）、Axios 1.7、Lightweight Charts v5。**无全局状态库**（KDD-04）。

- 开发：`npm run dev` → Vite 5173，`vite.config.ts` 把 `/api` 代理到 `http://localhost:8000`（`credentials: 'include'`；`frontend/.env.development` 的 `VITE_API_BASE_URL` 实际未被代码消费）；
- 构建：`npm run build` = `tsc && vite build`——先全量类型检查再打包；产物 `dist/`（入口 html + 带内容哈希的 assets，nginx 按一年 immutable 缓存）；
- 无 lint/test 工具链（TD-11）。

关键依赖（`frontend/package.json`）：

| 依赖 | 用途 | 备注 |
| --- | --- | --- |
| vue 3.4 / vue-router 4 | 框架与 Hash 路由 | 仅用 Composition API |
| ant-design-vue 4 | 全部 UI 组件（Table/Form/Result/Layout/ConfigProvider） | zhCN locale 注入 |
| axios 1.7 | 唯一 HTTP 客户端 | 实例集中配置，见 §4.5 |
| lightweight-charts 5 | K 线/指标渲染 | **v4→v5 API 变更**：`addSeries(CandlestickSeries)` 取代 `addCandlestickSeries`、`createSeriesMarkers` 独立插件化（历史踩坑点） |
| vite 5 / typescript 5.6 | 构建与类型检查 | `build = tsc && vite build`，tsc 失败即不产出 |

### 4.2 组件树与 Hash 路由表

```
App.vue (ConfigProvider zhCN)
└── RouterView
    ├── views/Login.vue            # /login（公开）
    ├── views/Register.vue         # /register（公开）
    └── components/PrivateRoute.vue  # "/" —— 布局 + 组件级保护
        └── RouterView
            ├── views/Dashboard.vue      # /        市场状态仪表盘
            ├── views/EtfView.vue        # /etf     ETF 列表 + 展开 K 线
            └── views/IndicatorView.vue  # /indicators  指标图表
```

| Hash 路径 | name | 组件 | 保护方式 |
| --- | --- | --- | --- |
| `/#/login` | Login | `views/Login.vue` | 公开 |
| `/#/register` | Register | `views/Register.vue` | 公开 |
| `/#/` | Dashboard | `views/Dashboard.vue` | PrivateRoute 包裹 |
| `/#/etf` | Etf | `views/EtfView.vue` | PrivateRoute 包裹 |
| `/#/indicators` | Indicators | `views/IndicatorView.vue` | PrivateRoute 包裹 |

`createWebHashHistory()`：路由切换不产生真实 HTTP 请求，nginx 无需 history 回退即可工作（FR-FE-006）；`nginx.conf` 仍保留 `try_files ... /index.html` 兜底。

### 4.3 PrivateRoute —— 组件级保护（纠正 frontend-design.md 的错误）

`frontend-design.md` 把 PrivateRoute 描述为"路由守卫"，**不准确**。本项目**没有** `router.beforeEach` 全局守卫（路由表里 login/register 的 `meta: { public: true }` 也没有任何消费者，属死配置）。实际机制是**组件级保护**：

1. `router/index.ts` 把 PrivateRoute 注册为 `/` 路径的**布局组件**，三个业务页面是它的 children——访问任何受保护页面都必须先渲染 PrivateRoute；
2. PrivateRoute `onMounted` 调 `restoreSession()`（`GET /auth/me` 恢复会话，§4.4）；
3. 渲染三态：`!authState.initialized` → 全屏 `<a-spin>`（防闪烁）；已登录 → 渲染侧边栏 Layout + `<router-view />`（业务页面）；未登录 → 渲染 `<a-result status="403" title="未授权" sub-title="请先登录">` + "去登录"按钮——**不渲染业务内容**（FR-AUTH-009），并顺带承担了侧边栏/顶栏布局职责（frontend-design.md 中引用的 `views/Home.vue` 不存在，布局就住在 PrivateRoute 里）；
4. 菜单 `selectedKeys` 由 `route.name` 推导；登出调 `logout()` 清 Cookie 后跳 `/#/login`。

效果与守卫等价：未登录看不到受保护页面内容；但保护发生在组件渲染层而非导航层，子页面挂载前状态已就绪（initialized 门控），无"页面闪现再跳走"问题。代价：若未来新增顶层受保护路由而忘记挂到 PrivateRoute 下，会绕过保护（守卫的集中式声明无此风险）。

### 4.4 reactive 认证状态模块

`stores/auth.ts`（非 Pinia，见 KDD-04）：

```ts
export const authState = reactive<{ user: UserInfo | null; initialized: boolean }>({ user: null, initialized: false })
export async function restoreSession()   // GET /auth/me 成功→set user；失败→null；finally→initialized=true
export function setUser(user) / clearUser()
```

- 模块单例即全局状态：`import { authState }` 处处拿到同一 reactive 对象，模板中直接读（PrivateRoute 的登录态判断就是 `!!authState.user`）；
- `initialized` 是防闪烁关键：首次进入时 PrivateRoute 等 `/auth/me` 返回后再决定渲染业务页还是 403；
- token 完全不进 JS（httpOnly Cookie，NFR-SEC-001），状态模块只持有 `UserInfo` 展示字段。

### 4.5 axios 封装与 401 单飞（FR-AUTH-010）

`api/index.ts`：实例 `baseURL: '/api'` + `withCredentials: true`；全部业务 api 模块共享该实例，前端代码不感知后端 host（dev 走 Vite 代理、生产走 nginx 反代）。

响应拦截器机制（模块级 `refreshing` 布尔 + `refreshQueue` 回调队列）：

1. 仅拦截 `status === 401` 且 `!config._retry` 的响应；置 `_retry = true` 防循环；
2. 若 `refreshing === false`：成为"leader"，置 `refreshing = true`，`await api.post('/auth/refresh')`；失败 → `window.location.href = '/#/login'` 并 reject；`finally` 中复位 `refreshing` 并 splice 队列逐个 resolve（唤醒 follower）；
3. follower（或 leader 走到队尾逻辑时）`await waitRefresh()` 排队，被唤醒后以原 config 重放 `api(original)`。

**实现缺陷（TD-05，如实记录）**：leader 在 refresh 成功后也会落到 `await waitRefresh()`——而此时队列已被自己清空，其 resolve 只会被**下一次**刷新周期的 finally 消费；单发 401 场景下 leader 的原请求将永久挂起（无超时）。并发 401 场景下 followers 行为正确，leader 请求丢失。修复方向：leader 在 try 成功分支内直接 `return api(original)`，不经过 waitRefresh。

登录 400 的配合：后端登录失败返回 400 而非 401（api-design 5.2），不会误触发该拦截器的 refresh 逻辑，Login.vue 直接把 `detail` 文案 `message.error` 展示（FR-FE-001）。

### 4.6 api 模块与类型

| 模块 | 封装的端点 | 备注 |
| --- | --- | --- |
| `api/auth.ts` | login / register / getMe / logout | 函数签名 `(username, password)`，密码不出现在 URL/日志 |
| `api/etf.ts` | `GET /data/etfs`、`GET /data/etf/{code}/daily?limit=` | ETF 列表与展开 K 线 |
| `api/marketRegime.ts` | `GET /market_regime/states/{market}?limit=2000`、`GET /data/index/{code}/daily?limit=` | 状态序列默认拉 2000 条以覆盖 K 线窗口 |
| `api/indicators.ts` | `GET /indicators/{assetType}/{code}/all?limit=&adjust_mode=` | `AllIndicatorsResponse` 未声明后端实际返回的 `source`/`keltner_*`/`atr` 字段（契约偏差，api-design 6.4 已记录，TD-12 一并跟踪） |
| 拦截器 | `POST /auth/refresh` | 唯一隐式调用方 |

类型定义：`types/auth.ts`（UserInfo）、`types/market.ts`（RegimeState/RegimeResponse/Kline/KlineResponse）。

### 4.7 views

- **Login.vue / Register.vue**：受控表单 + 前置非空校验；Register 多一步两次密码一致性校验；成功分别跳 `/#/`（login 内不 setUser——由 PrivateRoute 的 restoreSession 兜底拉取）与 `/#/login`；失败展示后端 `response.data.detail`。
- **Dashboard.vue**（FR-FE-002/003）：`activeMarket`（A/HK）切换；`Promise.all` 并行拉状态序列与主指数 K 线（A→`000001` 上证综指，HK→`HSI`），各自 `catch(() => null)` 容错（无训练记录时显示 Empty 提示"需先训练"）；摘要卡片四项（当前状态 Tag / 状态概率 / 训练时间 / 算法）；**bands computed** 是着色核心——把状态序列按 `state_label` 连续段折叠成 `{from, to, state}` 区间，且仅保留与 K 线日期有交集的段，另算 `bandsCoverage` 覆盖率 Tag（0 时提示"状态与 K 线日期未重叠"）。注意 `stateLabelMap` 只映射 0/1，K=3 时 label=2 显示为"状态2"且无色（TD-10 的前端侧表现）。
- **EtfView.vue**（FR-FE-004）：a-table（代码/名称/跟踪标的/最新收盘/涨跌幅，pageSize 20）；行展开懒加载——`onExpand` 时 `getEtfKlines(code)` 并缓存进 `expandedKlines` Map，展开行内渲染 `KlineChart`（无状态着色 bands）；加载失败回滚展开态。类型瑕疵：`Set<number>`/`Map<number, ...>` 实际以 string code 为键（TD-12）。
- **IndicatorView.vue**（FR-FE-005）：资产类型（etf/index/stock）/代码输入/复权模式三选择器 + MACD/RSI/BOLL 三开关；`watch([assetType, code, adjustMode])` 触发重查；默认 `etf 510300 forward limit=120`；数据喂给 `IndicatorChart`。

### 4.8 图表组件（Lightweight Charts v5）

- **KlineChart.vue**：props `klines` + `bands?`。`createChart` + `addSeries(CandlestickSeries)`；**状态着色实现**：bands 不用原生 band API，而是构造一条独立 priceScaleId 的 `HistogramSeries`（value 恒 1，color 按 state 映射：0→绿 12% 透明、1→红 12% 透明、其余灰）铺在蜡烛底层作背景带（FR-FE-002 的"平静=绿、动荡=红"）；另以 `createSeriesMarkers` 给每根 K 线加涨跌箭头（纯方向标记，frontend-design.md 待办项"箭头改造为模型信号"仍未做）；`ResizeObserver` 自适应宽度；`watch(klines, renderChart, {deep})` 全量重建图（2000 根量级无感，NFR-PERF-002）。
- **IndicatorChart.vue**：主图（蜡烛 + 成交量直方图 `scaleMargins top 0.8` 压底 + 可选 BOLL 三线）+ 两个独立子图（MACD：hist 正绿负红 + DIF/DEA 线；RSI：主线 + 30/70 虚线）；三个 `show*` props 控制子图挂载；任何 props 变化全量 `remove()` 重建对应 chart 实例。`IndicatorData` 中 null 值字段先 `filter(d => d.xxx != null)` 再 setData（v5 不接受 null 点）。

### 4.9 对 frontend-design.md 的吸收与勘误

| 旧文档表述 | 现状纠正 |
| --- | --- |
| 目录树列出 `views/Home.vue`（侧边栏布局） | **不存在**。侧边栏布局由 `components/PrivateRoute.vue` 承担（布局 + 保护一体） |
| PrivateRoute 是"路由守卫" | 实为**组件级保护**：无全局 beforeEach，未登录渲染 403 组件而非跳转（§4.3） |
| 待办"Dashboard console.log 清理" | 当前 Dashboard.vue 已无 console.log，待办已过时 |
| 待办"K 线箭头改造" | 仍有效：两图表组件仍绘制涨跌箭头标记（§4.8） |
| "401 自动 refresh" | 机制存在但 leader 分支有挂起缺陷（§4.5 / TD-05） |

另：`components/AuthLayout.vue`（登录页恢复会话 + 已登录跳转）未被任何文件引用，属死代码（TD-12）；路由 `meta.public` 同为死配置。

### 4.10 组件通信与代码约定

- **单向数据流**：view 持有全部页面状态（选择器、加载的数据、UI 开关）→ 经 props 下传图表组件；图表组件是纯展示层，**不发请求、不持业务状态**（仅持有 chart 实例与 ResizeObserver）；
- **数据获取**：view 直接 import `api/*` 模块函数调用，结果存本地 `ref/reactive`——认证态是唯一的"跨页共享状态"（§4.4），其余页面切换即重建，无缓存层；
- **无事件总线、无 provide/inject**：跨层通信只发生在 PrivateRoute → 子页面的路由挂载关系上；
- **错误呈现约定**：列表/图表数据失败静默降级（catch 后置空/Empty），表单动作失败 `message.error(e.response?.data?.detail ?? 默认文案)` 透传后端中文 detail（FR-FE-001）；
- **日期处理**：K 线 time 用 `YYYY-MM-DD` 字符串直接喂 Lightweight Charts（其自带解析），未引入 dayjs；`trade_date` 从后端到前端全程字符串，无时区换算面（与 database-design 4.6 的"DATE 无时区"约定呼应）。

## 5. 横切设计

### 5.1 认证与安全链路全图

```mermaid
flowchart TD
    LGIN["POST /auth/login"] --> SETC["_set_cookie ×2<br/>HttpOnly · SameSite=Lax<br/>secure=settings.cookie_secure<br/>Max-Age 900s / 604800s"]
    SETC --> REQ["受保护请求<br/>浏览器自动携带 Cookie"]
    REQ --> DEP["get_current_user<br/>（data / indicators / market_regime<br/>三个 router 路由级声明）"]
    DEP --> C1{"access_token Cookie 存在?"}
    C1 -- "否" --> R401a["401 未认证"]
    C1 -- "是" --> DEC["decode_token<br/>HS256 + settings.jwt_secret_key"]
    DEC -- "JWTError" --> R401b["401 无效凭证"]
    DEC -- "成功" --> DBQ["按 sub 查 users 表"]
    DBQ -- "无用户或 is_active=false" --> R401c["401 用户无效"]
    DBQ -- "通过" --> H["业务 handler"]
    EXP["access_token 过期"] --> R401a
    R401a --> FEI["前端拦截器<br/>单飞 POST /auth/refresh"]
    REF["POST /auth/refresh<br/>凭 refresh_token Cookie"] --> RE["滚动签发新 access_token<br/>（不轮换 refresh_token）"]
    RE --> FEI
    FEI -- "刷新失败" --> LOGIN["跳转 /#/login"]
    OUT["POST /auth/logout"] --> DEL["delete_cookie ×2<br/>会话即时终止"]
```

安全控制面汇总：bcrypt 口令哈希（NFR-SEC-002）；token 仅存 httpOnly Cookie，JS 不可读（NFR-SEC-001，KDD-03）；`SameSite=Lax` 承担 CSRF 防线（全站写操作均 POST）；CSRF token 未单独实现（Lax + 单用户自部署场景下接受）；ORM 全参数化查询（NFR-SEC-003）；机密仅经 .env 注入（NFR-SEC-004，§7）；access 15 分钟短效 + 登出即时失效（NFR-SEC-005）。已知弱化项：token claims 无 `typ`（TD-02）、国信客户端禁用 TLS 校验（TD-06）、JWT secret 存在代码默认值（部署必须覆盖，FR-DEPLOY-006）。

端点鉴权矩阵（与 `docs/api-design.md` 2.4 一致，此处标注声明位置）：

| 端点组 | 鉴权声明位置 | 未登录行为 |
| --- | --- | --- |
| `POST /auth/login` / `register` / `refresh` / `logout` | 公开（无依赖） | 可访问 |
| `GET /auth/me` | 端点级 `Depends(get_current_user)` | 401 |
| `/data/**`（9 端点） | router 级 `dependencies=[...]` | 401 |
| `/indicators/**`（6 端点） | router 级 | 401 |
| `/market_regime/**`（4 端点） | router 级 | 401 |
| `GET /health` | 公开 | 可访问（探活用） |

### 5.2 配置管理（Settings 全字段表）

`backend/app/config.py`，`pydantic_settings.BaseSettings`，优先级 **环境变量 > `.env` > 代码默认值**（tests 依赖该优先级，见 §5.5）；`extra="ignore"` 容忍多余变量。

| 环境变量 | 字段 | 默认值 | 消费方 |
| --- | --- | --- | --- |
| `DATABASE_URL` | database_url | `mysql+aiomysql://root:password@127.0.0.1:3306/stockdb` | `database.py` engine（生产必注入 RDS 串，FR-DEPLOY-002/003） |
| `HOST` / `PORT` | host / port | `0.0.0.0` / `8000` | **当前无消费方**（监听由 uvicorn CLI/Dockerfile CMD 提供），仅占位 |
| `JWT_SECRET_KEY` | jwt_secret_key | `change-me-in-production-use-a-real-secret` | security.py 签发/校验（生产必须覆盖，FR-DEPLOY-006） |
| `JWT_ALGORITHM` | jwt_algorithm | `HS256` | 同上 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | access_token_expire_minutes | `15` | access token exp + Cookie Max-Age（NFR-SEC-005） |
| `REFRESH_TOKEN_EXPIRE_DAYS` | refresh_token_expire_days | `7` | refresh token exp + Cookie Max-Age |
| `COOKIE_SECURE` | cookie_secure | `False` | `_set_cookie` 的 secure（FR-AUTH-008；https 时置 true） |
| `CORS_ORIGINS` | cors_origins | `http://localhost:5173` | `cors_origin_list` property（逗号分隔）→ CORSMiddleware |
| `GS_API_KEY` | gs_api_key | `None` | guosen_client（缺失时该源直接 `GuosenError`） |
| `GS_API_BASE` | gs_api_base | 国信限免域名 | guosen_client |
| `IMPORT_RATE_SECONDS` | import_rate_seconds | `2.0` | importer 每任务后 sleep（FR-DATA-008） |
| `IMPORT_CONCURRENCY` | import_concurrency | `2` | importer 信号量 |
| `IMPORT_CIRCUIT_THRESHOLD` | import_circuit_threshold | `5` | registry 连续失败熔断阈值（FR-DATA-004） |
| `IMPORT_CIRCUIT_COOLDOWN` | import_circuit_cooldown | `300.0` | 熔断冷却秒数（NFR-REL-002） |
| `REGIME_N_COMPONENTS` | regime_n_components | `3` | HMM 状态数（FR-REGIME-003） |
| `REGIME_PCA_VARIANCE` | regime_pca_variance | `0.95` | PCA 累计方差保留比例 |
| `REGIME_VOL_SPAN` | regime_vol_span | `21` | 实现波动率 ewm span |
| `REGIME_RETURN_WINDOWS` | regime_return_windows | `(5, 21, 63)` | 多周期收益率窗口（.env 写 JSON 数组） |
| `REGIME_RANDOM_STATE` | regime_random_state | `42` | HMM/PCA/Logistic 随机种子（可复现） |
| `MARKET_SYNC_HOUR` / `MARKET_SYNC_MINUTE` | market_sync_hour / minute | `15` / `5` | scheduler 触发时刻（上海时间，FR-DATA-010） |
| `MARKET_SYNC_RETRY_MINUTES` | market_sync_retry_minutes | `30` | 同步失败重试间隔 |

约束（NFR-MAINT-003）：新增字段必须带默认值且不破坏既有 .env。模板见 `backend/.env.example`（全占位符，含生成 secret 的示例命令）。

### 5.3 日志

- 标准 library logging：各模块 `logging.getLogger(__name__)`；应用入口**不**做 basicConfig（交给 uvicorn 的默认配置）；scripts 各自 `basicConfig(INFO)` 便于前台观察；
- 关键日志点：importer（失败 warning 含 `asset_type/code/截断错误`、bulk upsert info 含 rowcount）、scheduler（下次触发点 info、同步完成统计、失败 error）、pipeline（per-market 完成/失败 info/exception）、persist（run/state 写入行数）；
- 无结构化日志、无 request-id 贯通、无独立错误上报——当前依赖 `docker compose logs` 人工排查；机密不落日志（GS_API_KEY 只出现在请求 URL 构造中，未打印；NFR-SEC-004 靠约定维持）。

### 5.4 错误处理约定

| 层 | 约定 |
| --- | --- |
| router | 业务规则拒绝 → `HTTPException(400/404)`；后台任务异常不上抛（进度对象 + import_errors 承载） |
| service | 返回结构化结果（`PipelineResult.success/error`）或抛领域异常（`GuosenError`/`NotImplementedMarker`/`ValueError`）；**不**感知 HTTP |
| registry | 单源异常吞掉并计数熔断，多源全空返回空 `FetchResult`（`source=""`） |
| importer | 单标的异常截断入 `import_errors`，不中断整体 gather |
| scheduler | 单标的空数据跳过；写库异常上抛交循环重试路径 |
| pipeline | 全捕获 → rollback → `success=False`（FR-REGIME-007/AC-08 的"不崩进程"由可选加载 + 全捕获共同保证） |

### 5.5 测试策略与布局

**131 个用例 / 18 个文件**（`backend/tests/`，`asyncio_mode = "auto"`，pyproject 配置）：

| 域 | 文件（用例数） | 小计 |
| --- | --- | --- |
| 认证 | test_auth_security(4)、test_auth_router(10)、test_protected_routes(6) | 20 |
| 模型 | test_models(7) | 7 |
| 指标 | test_indicators(10)、test_indicators_all(1，锁定 /all 实时路径 keltner/atr 回归) | 11 |
| 数据层 | test_sources(15)、test_baostock_source(14)、test_registry(8)、test_universe(6)、test_importer(4) | 47 |
| 状态识别 | test_features(10)、test_evaluation(8)、test_clustering(8)、test_reduce(6)、test_classifier(6)、test_persist(5)、test_pipeline(3) | 46 |

覆盖策略：纯函数（ta/features/reduce/classifier）直接单测；含 IO 层用假源/假 registry 驱动；路由经 httpx ASGI 客户端做黑盒断言（含 401 矩阵，FR-AUTH-007 / AC-02）。前端无自动化测试（TD-11）。

代表性用例（说明各文件守住的关键行为）：

- `test_registry.py`：熔断计数累加与冷却期跳过、`NotImplementedMarker` 不计失败、多源顺序回退、**ETF 合并去重保留先注册源**（§3.4 例外路径的回归锁）；
- `test_baostock_source.py`：`_bs_lock` 下并发调用串行化不交缠、沪/深前缀与 `_market_map` 精确判定、非 A 股代码返回空 df、`adjustflag="3"` 不复权；
- `test_sources.py`：akshare 腾讯→新浪两级回退、全量结果按日期裁剪、港股/国债/外汇专用接口分派；
- `test_auth_router.py`：登录 400 文案、register 查重、refresh 不轮换、logout 后 Cookie 清除、Cookie 属性（httponly/samesite）断言；
- `test_protected_routes.py`：data/indicators/market_regime 三 router 未登录一律 401、登录后 200（AC-02 的自动化形态）；
- `test_indicators_all.py`：`/all` 实时路径包含 keltner/atr 字段（防止历史 NameError 缺陷回归的锁定用例）；
- `test_importer.py`：单标的失败写 `import_errors` 且 progress 计数正确、retry 后回写 `retried_at`；
- `test_pipeline.py`：缺数据 → `success=False` 不抛异常、A/HK 两市场相互独立；
- `test_persist.py`：save_states 先删后插的幂等性、numpy 类型 JSON 可序列化；
- `test_evaluation.py`：HISTORICAL_EPISODES 锚点覆盖率计算、sector_attribution 数值口径。

**conftest.py 隔离机制（防生产事故的关键设计，KDD-06）**：

1. `backend/.env` 的 `DATABASE_URL` 指向生产 RDS——任何触库测试若无隔离都可能读写生产；
2. conftest 在**任何 `app.*` import 之前**无条件 `os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"`（强制覆盖而非 setdefault，防开发者 shell 已导出真实串）；pydantic-settings 环境变量优先级高于 .env，于是 `app.config.Settings` → `app.database.engine` 在整个 pytest 会话绑定到**内存 SQLite**；
3. SQLAlchemy 2.0 对裸 `sqlite+aiosqlite://` 自动选 `StaticPool`——所有会话共享同一个内存库，跨用例数据可见；
4. `_app_db_tables` fixture 以模块级 flag 惰性建表（仅一次）；函数作用域而非 session 作用域是为了不绑定 session 级 event loop，且不触库的测试模块完全不受影响；
5. `client` fixture：`httpx.AsyncClient(transport=ASGITransport(app), base_url="http://test")`，Cookie 自动存于 client jar，登录后续请求自动带认证。

代价：SQLite 与 MySQL 方言差异（无 `ON DUPLICATE KEY UPDATE`）迫使生产代码写双方言分支（`_upsert_instrument`）或选跨方言的先删后插写法（indicator_values / regime_states，database-design 4.1 的例外即源于此）。

## 6. 调度与数据流设计

### 6.1 每日同步时序图（FR-DATA-010）

```mermaid
sequenceDiagram
    autonum
    participant L as _scheduler_loop
    participant F as _next_sync_shanghai
    participant R as DataSourceRegistry
    participant S as 数据源（baostock/akshare）
    participant DB as MySQL RDS

    L->>F: now（UTC aware）
    F-->>L: 下次触发点（UTC aware，已跳周末）
    L->>L: asyncio.sleep(间隔)
    Note over L: 上海时间 15:05 触发

    loop 每个 universe ETF（20 只，adjust=forward）
        L->>DB: SELECT max(trade_date)
        DB-->>L: last_date（增量起点 = last+1）
        L->>R: fetch_etf_daily(code, start)
        R->>S: 熔断检查 → 依优先级取数
        S-->>R: DataFrame / 空 / 异常（计数熔断）
        R-->>L: FetchResult(df, source)
        L->>L: _filter_new_rows 过滤已有日期
        L->>DB: INSERT ... ON DUPLICATE KEY UPDATE（批量）
        L->>DB: DELETE indicator_values(该标的) → 批量 INSERT（全量重算）
        L->>DB: commit
    end
    loop 每个 universe 指数（13 个，adjust=none，同上流程）
        L->>DB: 增量 upsert + 指标重算 + commit
    end
    Note over L: 单标的空数据/取数失败 → 跳过不中断<br/>写库异常 → error 日志 → sleep 30min → 重排计划
```

### 6.2 zoneinfo 时区设计

- 问题史：旧实现 naive datetime + `timedelta(hours=8)` 手工偏移，隐含"系统时区必须是 UTC"假设；在 TZ=+8 的 Windows 开发机或 `TZ=Asia/Shanghai` 容器里下次触发点会偏移 8 小时；
- 目标态：`_next_sync_shanghai` 全程 aware——任意输入（None/naive 按 UTC 解释）→ `astimezone(ZoneInfo("Asia/Shanghai"))` → 替换到 15:05 → 顺延/跳周末 → **返回 UTC aware**；调用方 `(next - now).total_seconds()` 得到精确 sleep 秒数，与时区环境零耦合；
- 时区数据来源：Python 3.12 的 zoneinfo 优先系统 tzdata，Windows 开发机与 `python:*-slim` 容器无系统级数据，由 `tzdata>=2024.1`（pyproject）+ runtime 层 apt tzdata 双保险；
- `trade_date` 语义 = 上海时区交易日（database-design 4.6）；调度仅跳周末，节假日由空数据兜底（requirements 5.4）。

### 6.3 幂等 upsert 链路（NFR-REL-003）

写库只有两种模式，全链路无"先查后插"的日线竞态：

1. **ODKU 增量合并**（日线表）：importer `_bulk_upsert_klines` 与 scheduler `_upsert_klines` 同构——`mysql_insert(table).values(rows).on_duplicate_key_update({非主键列})`；冲突判定键 = 各表命名唯一键 `uq_*_date`；重复导入/调度重试 = 最新值覆盖、行数不变（FR-DATA-009，AC-03）。前置保障：normalizer 统一 schema（§3.8）+ scheduler 增量起点与 `_filter_new_rows` 双保险减少无谓冲突；
2. **先删后插整体替换**（indicator_values / regime_states）：语义是"全量重算覆盖"而非逐行合并（FR-IND-007、同 run 重跑幂等），且天然跨 MySQL/SQLite 方言——见 database-design 4.1 的两个例外与理由。

元数据（stocks/indices/etfs）按 code 先查后插（行数极小、无并发冲突面）；instruments 双方言 upsert（§3.10）。

### 6.4 熔断状态机（FR-DATA-004 / NFR-REL-002）

```mermaid
stateDiagram-v2
    [*] --> Closed
    Closed --> Closed : 取数成功（失败计数清零）/ 失败（计数 +1，< 阈值 5）
    Closed --> Open : 连续失败 ≥ IMPORT_CIRCUIT_THRESHOLD(5)
    Open --> Open : 冷却期内（< 300s）→ registry 跳过该源
    Open --> HalfOpen : 冷却期满（cooled_down = True）
    HalfOpen --> Closed : 取数成功
    HalfOpen --> Open : 取数失败（计数累计重新熔断）
    note right of HalfOpen
        半开态为隐式实现：opened_at 过期后 _try 直接放行
        无显式状态字段
    end note
```

实现载体：`registry._SourceHealth`（`consecutive_failures` + `opened_at`，`time.monotonic()` 计时不受系统时钟回拨影响）。**进程内、不持久化**——每次导入任务/调度循环重建 registry 时熔断态清零；这是有意的取舍：单导入任务生命周期内熔断已够用（KDD-07），跨任务持久化反而可能在源已恢复后仍无谓跳过。对接口行为的体现：熔断期该源标的中止取数并落 `import_errors`，表现为 progress 的 `failed` 上升与 `recent_errors` 记录；冷却后 `/import/retry` 可恢复（api-design 5.3）。

### 6.5 导入限速模型（FR-DATA-008）

模型：**信号量 + 槽内尾 sleep**。`_import_task` 的 `finally: await asyncio.sleep(rate)` 发生在信号量槽位持有期间，因此单槽位周期 = `取数耗时 + rate(2s)`；总吞吐上界 ≈ `concurrency / (avg_fetch + rate)` 标的/秒。固定池 33 标的、并发 2：≥ 33 秒（实际分钟级，含合并取数）；全量含沪深300 成分股（约 330 任务）≈ 6–10 分钟，单次运行内完成（NFR-PERF-003）。选型理由：免费源封禁针对"请求频率"，槽内 sleep 精确限制每源见到的请求间隔，实现 6 行、无外部依赖；代价是 sleep 期间槽位空转（吞吐略降）与速率不随源动态调节。`retry_errors` 固定并发 2 + 同一 rate。

### 6.6 后台任务模型

`routers/data.py` 与 `routers/market_regime.py` 各持模块级 `_bg_tasks: dict[str, asyncio.Task]`：`asyncio.create_task` 后把引用存入 dict（防 task 被垃圾回收）。语义为 fire-and-forget：无取消端点、无状态端点、异常不推送；观测途径仅 `GET /data/import/progress`（导入）与 `/market_regime/runs/{market}` 是否出现新 run（训练）。重复触发会产生并行任务，训练以最后完成者落库（api-design 4.5 通用约定），见 TD-04。

### 6.7 端到端数据流：训练到展示

以"用户在 Dashboard 看到市场状态色带"为例的完整链路（跨 §3.11/§3.12/§3.14/§4.7）：

1. **触发**：Dashboard/脚本 `POST /api/market_regime/train/A` → 202 + 后台任务（§3.1.4）；
2. **特征**：`features.py` 从 `index_daily_klines`（缺失回退 `etf_daily_klines`）组装 raw features → `standardize_expanding` 防泄漏标准化（U2）；
3. **降维/聚类**：PCA(0.95) → GaussianHMM(3 状态, n_init=5) → label 按收益率对齐（动荡 = 最高 label，U3/U4）；
4. **监督校验**：逻辑回归 t+1 目标 + 时序切分 → metrics 含 KS（U5）；
5. **落库**：`save_run`（regime_runs 一行）→ `save_states` 先删后插 `regime_states`（trade_date, state_label, state_prob, features_snapshot JSON）（U7）；
6. **展示**：`GET /api/market_regime/states/A?limit=2000` → Dashboard 把 state 序列与 `getIndexKlines('000001')` 求日期交集 → **bands computed** 按 label 连续段折叠为 `{from, to, state}` → KlineChart 以 HistogramSeries(value=1) 底层铺色（0=平静绿 / 1=动荡红，label=2 无色，TD-10）；
7. **摘要卡**：states 末元素给"当前状态/概率"，run 元数据给"训练时间/算法"；`bandsCoverage` 低于预期提示"状态与 K 线日期未重叠"。

数据形状对照（§3.11 落库 → §4.7 消费）：

| regime_states 字段 | 前端消费点 |
| --- | --- |
| `trade_date` | band 的 from/to 边界、与 K 线日期交集判断 |
| `state_label` | `stateLabelMap`（0 平静/1 动荡）+ `STATE_COLORS` 着色 |
| `state_prob` | 摘要卡"状态概率"（取最新一行） |
| `features_snapshot`（JSON，在 regime_runs） | runs 接口追溯，Dashboard 不消费 |

行情侧对称链路：调度器每日 15:05（§6.1）→ kline 表增量 → indicator_values 整体重算（§3.13）→ `GET /indicators/{type}/{code}/all` → IndicatorChart 多子图渲染——两条链路在 `trade_date` 上对齐，构成"状态带 + 指标"叠加视图。

## 7. 部署设计概要

> 操作步骤、命令与环境准备由 `docs/deployment.md` 承载，此处仅记录目标态拓扑与设计约束（FR-DEPLOY-001~006）。

- **compose 拓扑（目标态，根目录 `docker-compose.yml`）**：`backend`（expose 8000，不映射宿主机端口）+ `frontend`（`127.0.0.1:80:80` 只绑回环，公网需改端口映射或前置 SLB）两容器；MySQL 不入库容器，默认直连远程 RDS，仅保留 `--profile local-db` 的可选本地 MySQL；`frontend` 以 `depends_on: condition: service_healthy` 等 backend 健康后启动。
- **镜像分层策略**：backend 两阶段（builder 装 build-essential + 独立 venv，runtime 仅 COPY venv 与 `app/` 源码；依赖清单经 tomllib 从 pyproject 提取走纯 pip，先 COPY 清单后装依赖以吃层缓存）；frontend 两阶段（node:20-alpine `npm ci` + `tsc && vite build` → nginx:alpine 托管 `dist/`）。**两镜像均为不可变制品，无源码 bind mount**；backend 以非 root `appuser` 运行。
- **进程约束**：uvicorn `--workers 1`（进程内调度器唯一性，KDD-02）+ `--proxy-headers --forwarded-allow-ips <内网网段>`（信任 nginx 的 X-Forwarded-*）；`stop_grace_period: 30s` + exec 形式 CMD 保证优雅停机走完 lifespan shutdown。
- **健康检查**：backend healthcheck 用 python 标准库探 `http://127.0.0.1:8000/api/health`（slim 镜像无 curl/wget，且不依赖 DB 连通——进程存活即可用）；frontend 用 busybox wget 探静态首页。
- **机密注入（FR-DEPLOY-003/006，NFR-SEC-004）**：全部凭据放仓库根 `.env`（复制根目录 `.env.example` 填写；本地开发模板另见 `backend/.env.example`），compose 以 `${DATABASE_URL:?...}` / `${JWT_SECRET_KEY:?...}` 插值——缺失或为空直接拒绝启动；`GS_API_KEY`、`CORS_ORIGINS`、`COOKIE_SECURE` 有默认/可空；容器 `TZ: Asia/Shanghai`（调度器时区算法本身已不依赖它，仅保证日志时间可读）。代码、镜像、文档中不得出现真实凭据。
- **网络与端口**：

| 组件 | 端口 | 暴露面 |
| --- | --- | --- |
| frontend（nginx） | 80 | 宿主机 `127.0.0.1:80`（仅回环，公网需改映射或前置 SLB，FR-DEPLOY-005） |
| backend（uvicorn） | 8000 | 仅容器网络内（`expose`，无宿主映射），唯一入口是 nginx `/api/` 反代与容器 healthcheck |
| RDS MySQL | 3306 | backend 容器**出站**连接 RDS 内网地址；compose 可选 local-db 服务仅 `--profile local-db` 时存在 |

  启动顺序：`docker compose up -d` → backend 先起（healthcheck 通过）→ frontend `depends_on: service_healthy` 后起；浏览器只与 frontend:80 通信，backend 对外不可达。

## 8. 关键设计决策（KDD）

**KDD-01 进程内 asyncio 调度器，而非 Celery / APScheduler**
为什么：单用户自部署（requirements 1.2），每日仅一次同步任务；进程内 `asyncio.create_task` + sleep 循环约 40 行即满足，且调度体与业务共享同一事件循环/连接池，无序列化与代理开销。代价：与 uvicorn 进程强绑定——必须单 worker（见 KDD-02）、进程重启才恢复调度、无任务持久化（重启后按当前时间重算下次触发点，天然幂等可接受）。

**KDD-02 uvicorn 单 worker（`--workers 1`）+ `--proxy-headers`**
为什么：调度器、导入进度单例（`_progress`）、`_bg_tasks`、baostock 进程级 login 都是进程内状态；多 worker = 多份调度器重复同步、进度互不可见。代价：无法横向扩容、单请求阻塞事件循环会影响整体（已用线程池化解同步 SDK 阻塞）；`--proxy-headers` 只影响 client 地址还原，属配合 nginx 的正确性配置而非扩容手段。

**KDD-03 httpOnly Cookie 双 token，而非 localStorage + Authorization 头**
为什么：token 不可被 JS 读取，规避 XSS 窃取整类风险（NFR-SEC-001）；浏览器自动携带 Cookie，前端零 token 管理代码。代价：跨源部署必须精确配 CORS（`allow_credentials=True` 时 origin 不能为 `*`）；CSRF 需靠 `SameSite=Lax`（本系统写操作全为 POST，已覆盖当前威胁模型）；无 refresh token 撤销列表——登出仅清 Cookie，7 天内泄露的 refresh token 在服务端无法吊销（单用户场景接受，TD-02 关联）。

**KDD-04 无 Pinia，reactive 模块单例管理认证态**
为什么：全局状态只有"当前用户 + initialized"两个值，Vue 3 的模块级 `reactive()` 天然单例且免依赖、免 devtools 配置；引入 Pinia 属过度设计。代价：无 devtools 时间旅行、跨页面状态联动靠 import 约定（无统一 dispatch 语义）；状态面扩大时需重新评估。

**KDD-05 Hash 路由（`createWebHashHistory`）**
为什么：路由切换不产生真实 HTTP 请求，nginx/静态托管零 history 回退配置即可用（FR-FE-006），对"静态资源 + /api 反代"的最小 nginx 配置最友好。代价：URL 带 `/#/` 不美观、SEO 无关紧要（登录后工具）、锚点语义被路由占用。

**KDD-06 测试隔离用内存 SQLite + 环境变量强制注入（conftest 前置改写 `DATABASE_URL`）**
为什么：`backend/.env` 直指生产 RDS，最危险的回归是测试触生产；pydantic-settings 的"环境变量 > .env"优先级给了零侵入的隔离点——conftest 首行强制 `os.environ["DATABASE_URL"]="sqlite+aiosqlite://"`，且发生在任何 app import 之前，engine 自然绑到内存库（StaticPool 共享）。代价：MySQL/SQLite 方言分叉（ODKU 不可用 → 双方言 upsert 分支与先删后插替代，见 §6.3），且测试无法覆盖 MySQL 特有行为（如真实 ODKU 冲突语义只能上生产验证）。

**KDD-07 多源 registry + 熔断为进程内实现、不持久化**
为什么：免费源无 SLA，故障是常态（NFR-REL-001/002）；按序回退 + 阈值熔断 150 行内解决，注册顺序即优先级，新源实现 DataSource 即插。代价：熔断态不跨导入任务/进程重启留存（每次重来一轮失败探测）；无半开态显式字段（冷却期满即试，失败再熔断，行为等价）。

**KDD-08 同步阻塞 SDK 经 `run_in_executor` 下放线程，而非改写为 async**
为什么：akshare/baostock 是同步库且接口随上游频繁变动，自己维护 async HTTP 版本成本高且易漂移；线程池包装 6 行代码即让事件循环不被阻塞。代价：线程切换开销（可忽略，取数以秒计）；并发线程需自理线程安全（baostock 全局锁，§2.5）；默认 executor 的线程数不受 `import_concurrency` 控制以外的方式约束。

**KDD-09 hmmlearn 可选加载（训练函数内延迟 import）**
为什么：hmmlearn 有本机 C++ 编译失败历史（requirements 5.1），必须保证"无 hmmlearn 环境能启动、能查询、只是不能训练"（FR-REGIME-007 / AC-08 / NFR-REL-004）；延迟 import 把依赖缺失从"启动失败"降级为"训练接口 500/明确错误"。代价：import 错误暴露时机后移（首次训练才报错）；`routers/__init__.py` 的 try/except 因此成为无用防御（无害遗留）。

**KDD-10 baostock 为主源 + py_mini_racer stub 注入**
为什么：akshare 1.18.x 顶层硬依赖 mini-racer（V8），在部分平台 FATAL 崩进程且东财系接口本身反爬严重；baostock 纯 HTTP 稳定，stub 让 `import akshare` 在不装 V8 的环境也可用（港股/国债/外汇回退仍需 akshare）。代价：多一层 `sys.modules` 注入的"魔法"（新人需读 stub docstring 才理解）；东财系接口被永久放弃（换取稳定性）。

**KDD-11 触发类操作用 fire-and-forget 后台任务（`asyncio.create_task` + 模块级 dict）**
为什么：导入/训练耗时分钟级到数十秒，HTTP 同步等待会撞网关/浏览器超时；默认后台 + `background=false` 同步选项兼顾轮询与脚本场景；dict 持引用防 task 被 GC。代价：无取消/状态/结果端点（TD-04），重复触发并行竞争，失败只能间接观测。

**KDD-12 幂等写库统一为 ODKU / 先删后插两种模式，拒绝先查后插**
为什么：调度重试、手动重复导入、断点续传都要求幂等（NFR-REL-003）；ODKU 单语句原子判定冲突，先查后插在并发 2 + 重试并存时有竞态窗口；整体替换类表（指标/状态）用先删后插兼顾跨方言测试。完整论证见 database-design 4.1（本文不重复）；代价：依赖线上唯一键的真实存在——无迁移体系下手建表漏建 `uq_*` 会让 ODKU 静默退化为普通 INSERT 产生重复数据（TD-01 关联风险）。

## 9. 已知技术债与改进方向

**TD-01 无 alembic 迁移体系（影响：高 / 优先级：高）**
schema 由 `init_db()` 的 `create_all` 直建，只建缺失表、不改既有表；ORM 加列/改类型后线上库不会跟随，需手工 ALTER；手建表漏掉 `uq_*_date` 唯一键会令 ODKU 幂等静默失效（KDD-12 的风险面）。alembic 1.13.3 已在 requirements 中但仅剩空 `backend/alembic/` 目录。建议：初始化 alembic + autogenerate 基线，纳入发布流程（database-design 6.2 同步记录）。

**TD-02 token claims 无 `typ`，access/refresh 校验层面可互换（影响：中 / 优先级：中）**
两类 token 同为 `{"sub","exp"}` + 同密钥 HS256：refresh token 能通过 `get_current_user`，access token 也能通过 `/auth/refresh`。15 分钟/7 天生命周期差下风险可控。建议：claims 加 `"typ": "access"/"refresh"`，decode 侧断言；与 KDD-03 的撤销列表议题一并规划。

**TD-03 登录失败返回 400 而非 401（影响：低 / 优先级：低，建议保留现状）**
语义上 401 更准确，但现状 400 恰好不会触发前端 401 拦截器对登录请求发起无意义 refresh，且登录页直接展示 `detail` 文案（api-design 5.2 有完整论证）。若未来改 401，必须同步在拦截器排除 `/auth/login`。

**TD-04 后台任务无取消/状态端点（影响：中 / 优先级：中）**
`_bg_tasks` 只存引用：导入/训练不可取消，无统一任务状态查询；重复触发训练会产生并行任务，以最后完成者落库，可能用旧窗口覆盖新结果。建议：为 train/import 增加"运行中拒绝重复触发"守卫（查 `prog.running` / task.done()），中期引入统一任务注册表（id、状态、可取消）。

**TD-05 前端 401 单飞 leader 请求挂起（影响：高 / 优先级：高）**
`api/index.ts` 拦截器中，leader 在 refresh 成功后仍落到 `await waitRefresh()`，而队列已被自己清空，其 resolve 只能等下一次刷新周期——单发 401 时原请求永久挂起、并发 401 时 leader 的那个请求丢失（§4.5）。建议：leader 在 try 成功分支内直接 `return api(original)`；并为 waitRefresh 加超时兜底。

**TD-06 国信客户端禁用 TLS 证书校验（影响：中 / 优先级：中）**
`guosen_client._ssl_context` 设 `CERT_NONE` + `SECLEVEL=0`（兼容旧服务器），意味着该通道可被中间人；仅传输行情数据且 key 随 URL 发送，风险限于数据源污染与 key 泄露面扩大。建议：默认开启校验，仅对确认的旧服务器以配置开关降级。

**TD-07 依赖清单三处不一致：requirements.txt / uv.lock / .env.docker 陈旧（影响：高 / 优先级：高）**
`requirements.txt` 缺 aiomysql、akshare、baostock、scikit-learn、hmmlearn、passlib 等（按它装出的环境无法连 MySQL、无法跑管线）；`uv.lock` 缺 auth 依赖（backend Dockerfile 注释明确弃用，构建走 tomllib+pip）；`backend/.env.docker` 仍是 asyncmy + `mysql` 主机的旧形态。pyproject.toml 是唯一权威。建议：删除或重生成 uv.lock 与 requirements.txt（`pip freeze` 对齐 venv）、更新 .env.docker，消除"按错清单装环境"的坑（database-design 1.4 同步记录）。

**TD-08 `routers/data.py::sync_stock` 逐行 `session.merge` upsert（影响：低 / 优先级：低）**
与 importer 的批量 ODKU 路径并存且更慢（每行一次 SELECT+WRITE 往返），且该 handler 自带取数/注册逻辑，违反 router 不写业务的分层约定（§2.2）。建议：改调 `importer._import_one`，handler 只留参数与响应。

**TD-09 调度器重试语义缺口 + 每日同步不含个股（影响：中 / 优先级：中）**
当前 `_scheduler_loop` 的 except 分支 sleep `market_sync_retry_minutes` 后回到循环顶部重算 `_next_sync_shanghai`——失败时刻已过 15:05，重算结果是次日触发点，即实际行为是"失败后冷却 30 分钟再进次日计划"，与 FR-DATA-010 / AC-05"失败后 30 分钟内重试"的语义不符（日志文案 "Retrying in 30min" 与行为不一致）。同时每日同步仅覆盖 ETF+指数，沪深300 个股不入每日同步（全靠手动批量导入）。建议：except 分支内直接重试 `_run_daily_sync`（可加重试上限），个股纳入每日同步或明确写进需求基线。

**TD-10 regime 多状态（K>2）的标签语义错位（影响：中 / 优先级：中）**
`regime_n_components` 默认 3，label 对齐后"动荡"= 最高 label（2），但：`evaluation.build_overlay` 的 `state_prob` 固定取 `probabilities.iloc[:, 1]`（K=3 时是中间态概率，非动荡概率）；前端 `stateLabelMap` 只映射 0/1、`STATE_COLORS` 无 2 的着色，label=2 显示"状态2"且背景带灰色。建议：overlay 统一取 `n_classes-1` 列概率；前端按 run 的实际状态数动态着色或后端落库"动荡 label"元数据。

**TD-11 前端无自动化测试与 lint 工具链（影响：中 / 优先级：中）**
package.json 无 test/lint 脚本，NFR-MAINT-002"前端最低限度验收清单"未落地；图表 bands 折叠、401 单飞等逻辑回归全靠手工。建议：先补 vitest + 单飞拦截器与 Dashboard bands 的纯函数抽取测试，再上 eslint。

**TD-12 前端/契约层杂项死代码与类型漂移（影响：低 / 优先级：低）**
`components/AuthLayout.vue` 无引用、路由 `meta.public` 无消费者、`frontend/.env.development` 的 `VITE_API_BASE_URL` 未被读取、EtfView 的 `Set<number>`/`Map<number>` 实际存 string 键、`api/indicators.ts` 未声明后端返回的 `source/keltner_*/atr` 字段、data.py import 未使用的 `get_db`。建议：一次性清理 + 在 api 模块补全响应类型（api-design 6.4 的契约偏差一并闭环）。

## 10. 验证记录

- **核对方式（2026-08-31）**：逐模块通读源码——`backend/app/` 全部（main/config/database/core/routers×5/schemas/services×5 域 24 个子模块）、`backend/scripts/` 4 个脚本、`backend/tests/` 18 个文件（以 `def test_` 计数核对 131 用例）、`frontend/src/` 全部 20 个文件、前后端 Dockerfile、`frontend/nginx.conf`、`frontend/vite.config.ts`、根 `docker-compose.yml`、`backend/pyproject.toml` / `.env.example`；
- **scheduler.py**：zoneinfo 显式时区改造已随同日提交 f85556c 落地（`ZoneInfo("Asia/Shanghai")`、15:05、跳周末、超参读 settings），本文描述与已提交实现一致；TD-09 记录了改造后仍存在的重试语义缺口与个股未覆盖事实；
- **frontend-design.md 勘误核对**：确认 `views/Home.vue` 不存在（Glob 全量核对）、`router/index.ts` 无 `beforeEach`、PrivateRoute 未登录分支渲染 `a-result 403`、AuthLayout.vue 零引用（Grep 全仓核对）、Dashboard.vue 无 console.log；
- **与三件套交叉引用核对**：14 表/字段仅引用不重述（database-design）；22 端点签名/错误码不重述，鉴权矩阵与 `dependencies=[Depends(get_current_user)]` 声明逐 router 核对一致（api-design 2.4）；FR-ID 追溯抽样核对（FR-AUTH-007/009/010、FR-DATA-004/008/009/010、FR-IND-006/007、FR-REGIME-003/007、FR-FE-002/006、FR-DEPLOY-001~006、NFR-REL-001/002/003、NFR-SEC-001/004/005）；
- **配置字段核对**：§5.2 表逐字段对照 `backend/app/config.py` 与 `backend/.env.example`，`host/port` 无消费方已如实标注；
- **部署目标态核对**：§7 与根 `docker-compose.yml`、两份 Dockerfile、`nginx.conf` 逐项对照（两容器、RDS 外置、`${VAR:?}` 插值、无 bind mount、单 worker + --proxy-headers、/api/health healthcheck 均与目标态一致）。

## 11. 变更日志

| 日期 | 说明 |
| --- | --- |
| 2026-08-31 | 初版：基于代码现状逆向撰写，覆盖后端 5 域 24 子模块 + 前端全部视图/api 模块；含 4 张 mermaid 图（系统组件图、认证安全链路图、每日同步时序图、熔断状态机）、12 条 KDD、12 条技术债。**吸收并取代 `docs/frontend-design.md`**（该文件同日删除），并纠正其两处错误（不存在的 views/Home.vue、PrivateRoute 误述为路由守卫）。 |
