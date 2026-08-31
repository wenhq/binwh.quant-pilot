---
title: "数据库设计文档"
type: docs
date: 2026-08-31
---

# 数据库设计文档

## 1. 概述

### 1.1 设计目标

本文档描述 binwh.quant-pilot 的持久层设计。数据库层服务于四条核心链路（见 `docs/requirements.md`）：行情数据自动同步（FR-DATA）、技术指标计算与存储（FR-IND）、市场状态识别（FR-REGIME）、用户认证（FR-AUTH）。设计上优先保证三点：

1. **写入幂等**：重复导入、调度重试、断点续传均不产生重复行、不损坏既有数据（FR-DATA-009 / NFR-REL-003），由表级唯一键 + `ON DUPLICATE KEY UPDATE` 实现；
2. **结构贴合数据形态**：四类标的的日线数据结构天然异构（基金无 OHLCV、指数无复权因子），不强行合并成单一宽表；
3. **可追溯**：每次模型训练落 run 记录与逐日状态，每张库表可追溯至需求 ID（NFR-MAINT-001）。

### 1.2 技术底座（以运行时为准）

| 项目 | 内容 |
|------|------|
| 数据库 | MySQL，阿里云 RDS 托管实例，库名 `stockdb`（FR-DEPLOY-002） |
| 驱动 | **aiomysql 0.3.2**（venv 实装，依赖 PyMySQL；`.env` 使用 `mysql+aiomysql://` scheme） |
| ORM | SQLAlchemy 2.0.35（async，`DeclarativeBase` + `Mapped`/`mapped_column`） |
| 会话 | `AsyncSession` + `async_sessionmaker`（`expire_on_commit=False`，见 `backend/app/database.py`） |
| 建表 | `Base.metadata.create_all`，应用启动时在 FastAPI lifespan 内执行（`backend/app/main.py` → `init_db()`）；**无 alembic 迁移体系**（详见 6.2） |
| 事务 | 无全局 autocommit，由 API/服务层显式 commit/rollback |

SQLAlchemy 类型 → MySQL 类型映射（下文列定义表格均使用 MySQL 侧类型）：

| SQLAlchemy 类型 | MySQL 类型 |
|------|------|
| `int`（PK, autoincrement） | `INT AUTO_INCREMENT` |
| `BigInteger` | `BIGINT` |
| `String(n)` | `VARCHAR(n)` |
| `Numeric(p, s)` | `DECIMAL(p, s)` |
| `Boolean` | `TINYINT(1)` |
| `DateTime` | `DATETIME` |
| `Date` | `DATE` |
| `JSON` | `JSON`（要求 MySQL ≥ 5.7.8） |
| `Float` | `FLOAT` |

### 1.3 连接串（占位符示例）

```env
DATABASE_URL=mysql+aiomysql://user:password@your-rds-host.mysql.rds.aliyuncs.com:3306/stockdb?charset=utf8mb4
```

> 真实主机、账号、口令一律经 `.env` 注入（FR-DEPLOY-003 / NFR-SEC-004），文档与代码仓库中不得出现。

### 1.4 驱动名的事实核查

仓库内各处驱动表述（2026-08-31 已全部对齐），**运行时以 aiomysql 为准**：

| 位置 | 表述 | 判定 |
|------|------|------|
| `backend/.env` | `mysql+aiomysql://...` | **实际生效** |
| venv 已安装包 | aiomysql 0.3.2 + PyMySQL | **实际运行时** |
| `backend/pyproject.toml` + `uv.lock` | `aiomysql>=0.3.2`（uv.lock 2026-08-31 重生成同步） | **唯一权威清单**（陈旧 requirements.txt 同日删除） |
| `backend/app/config.py` 默认值 | `mysql+aiomysql://...` | 已修正为 aiomysql（此前为 asyncmy 遗留默认值） |
| `docs/requirements.md` §5.1 | "MySQL（aiomysql 驱动）" | 已与运行时对齐 |

### 1.5 与需求文档的追溯关系

每张表在"表结构明细"中标注追溯的需求 ID，取自 `docs/requirements.md` 的 FR-DATA-xxx / FR-IND-xxx / FR-REGIME-xxx / FR-AUTH-xxx，只列与该表结构直接相关的条目（宁少勿滥）。共追溯 25 个不同的 FR-ID。

---

## 2. 架构

### 2.1 ER 总览

```mermaid
erDiagram
    stocks               ||--o{ stock_daily_klines  : "stock_id (ON DELETE CASCADE)"
    indices              ||--o{ index_daily_klines  : "index_id (ON DELETE CASCADE)"
    etfs                 ||--o{ etf_daily_klines    : "etf_id (ON DELETE CASCADE)"
    funds                ||--o{ fund_daily_klines   : "fund_id (ON DELETE CASCADE)"
    regime_runs          ||--o{ regime_states       : "run_id (ON DELETE CASCADE)"
```

物理外键仅以上五组。其余为**逻辑关联**（无外键约束）：

- `instruments` — 独立全局代码目录，用 `code` 主键与四张元信息表按 code 对应，不持有任何 OHLCV 外键；
- `indicator_values` — 用 `(asset_type, code)` 字符串组合对应元信息表，不设外键（原因见 4.2/设计意图）；
- `import_errors` — 仅记录 `asset_type + code` 字符串，不指向任何表；
- `users` — 完全独立，业务表不引用用户（单用户场景，无租户隔离需求）。

### 2.2 表分组

| 分组 | 表 | 职责 |
|------|----|------|
| 认证 | `users` | 注册用户与 bcrypt 口令哈希 |
| 行情·元信息 | `stocks` `indices` `etfs` `funds` | 四类标的的元信息与代码唯一性锚点 |
| 行情·日线 | `stock_daily_klines` `index_daily_klines` `etf_daily_klines` `fund_daily_klines` | 各类标的的日级时间序列（OHLCV / 净值） |
| 行情·注册表 | `instruments` | 跨资产类别的统一代码目录（code → 类型/市场/数据源/分类/跟踪关系） |
| 指标 | `indicator_values` | MACD/RSI/Bollinger/Keltner/ATR 指标宽表，一行 = (资产, 代码, 交易日) |
| 状态 | `regime_runs` `regime_states` | 市场状态识别的训练运行记录与逐日状态序列 |
| 运维 | `import_errors` | 批量导入失败记录，支撑断点续传与导入进度展示 |

> **注意**：不存在名为 `assets` 的表；四张日线表的外键分别指向各自的元信息表（`stock_id → stocks.id`、`index_id → indices.id`、`etf_id → etfs.id`、`fund_id → funds.id`），并非指向统一父表。

---

## 3. 表结构明细

共 14 张表。列定义表格格式：**列名 | 类型 | 可空 | 默认 | 说明**。其中"默认"区分数据库默认（`DEFAULT xxx`，即 DDL 中真实存在）与 Python 侧默认（SQLAlchemy `default=`，仅 ORM insert 时生效，DDL 中无默认值）。

### 3.1 users

**用途**：注册用户账户。单用户自部署场景，通常仅一行。
**追溯**：FR-AUTH-001（注册，用户名唯一约束支撑重名返回 400）、FR-AUTH-002（登录凭据校验）、FR-AUTH-003（bcrypt 哈希存储，NFR-SEC-002）。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键 |
| username | VARCHAR(64) | 否 | — | 登录名，`UNIQUE`，有二级索引 |
| hashed_password | VARCHAR(128) | 否 | — | bcrypt 加盐哈希（`$2b$` 前缀），绝不存明文 |
| is_active | TINYINT(1) | 否 | Python 侧 `True` | 是否启用（DDL 无默认值） |
| created_at | DATETIME | 否 | `CURRENT_TIMESTAMP` | 创建时间，`server_default=func.now()` |

- **主键**：`id`
- **唯一键/索引**：`username`（UNIQUE + INDEX，由 `unique=True, index=True` 生成）
- **关联**：无外键；token 不入库（JWT 经 httpOnly Cookie 下发，登出即清 Cookie，FR-AUTH-005）
- **外键表文件**：`backend/app/models/user.py`

### 3.2 stocks

**用途**：股票元信息。标的池中沪深300成分股（按总市值降序构建，FR-DATA-006）导入时逐只 upsert。
**追溯**：FR-DATA-001、FR-DATA-005、FR-DATA-006、FR-DATA-011。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键，即日线表的 `stock_id` |
| code | VARCHAR(16) | 否 | — | 股票代码（如 `600519`），`UNIQUE` + 索引 |
| name | VARCHAR(64) | 是 | NULL | 股票名称 |
| market | VARCHAR(16) | 是 | NULL | 市场（SH/SZ/BJ，由代码段推断） |

- **主键**：`id`；**唯一键/索引**：`code`（UNIQUE + INDEX）
- **关联**：被 `stock_daily_klines.stock_id` 外键引用，级联删除
- **外键表文件**：`backend/app/models/stock.py`

### 3.3 stock_daily_klines

**用途**：股票日线 OHLCV + 复权因子。
**追溯**：FR-DATA-001、FR-DATA-009（唯一键支撑 upsert 幂等导入）、FR-DATA-011。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键 |
| stock_id | INT | 否 | — | 外键 → `stocks.id`，`ON DELETE CASCADE`，有索引 |
| trade_date | DATE | 否 | — | 交易日期 |
| open | DECIMAL(12,3) | 否 | — | 开盘价 |
| close | DECIMAL(12,3) | 否 | — | 收盘价 |
| high | DECIMAL(12,3) | 否 | — | 最高价 |
| low | DECIMAL(12,3) | 否 | — | 最低价 |
| volume | BIGINT | 否 | Python 侧 `0` | 成交量（手）；DDL 无默认值 |
| amount | DECIMAL(20,3) | 是 | NULL | 成交额（元），部分源缺失时为 NULL |
| adj_factor | DECIMAL(12,6) | 是 | NULL | 复权因子；复权价的存储策略见 4.3 |

- **主键**：`id`
- **唯一键**：`uq_stock_date (stock_id, trade_date)` —— 幂等导入（`ON DUPLICATE KEY UPDATE`）的冲突判定键
- **二级索引**：`stock_id`（外键索引）
- **关联**：`stock_id → stocks.id`（CASCADE）
- **外键表文件**：`backend/app/models/kline.py`

### 3.4 indices

**用途**：指数元信息，含核心宽基指数、港股指数，以及国债收益率/汇率等宏观代理（当作伪指数入库，如 `US10Y`、`USDCNY`）。
**追溯**：FR-DATA-001、FR-DATA-005。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键 |
| code | VARCHAR(32) | 否 | — | 指数代码（如 `000300`、`HSI`、`US10Y`），`UNIQUE` + 索引；长度 32 以容纳 `HSTECH` 等字符代码 |
| name | VARCHAR(64) | 是 | NULL | 指数名称 |
| market | VARCHAR(16) | 是 | NULL | 市场（SH/SZ/HK/CN/US/FX） |

- **主键**：`id`；**唯一键/索引**：`code`（UNIQUE + INDEX）
- **关联**：被 `index_daily_klines.index_id` 外键引用（CASCADE）
- **外键表文件**：`backend/app/models/index.py`

### 3.5 index_daily_klines

**用途**：指数日线 OHLCV。指数无需复权，**无 `adj_factor` 列**。
**追溯**：FR-DATA-001、FR-DATA-009、FR-DATA-011。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键 |
| index_id | INT | 否 | — | 外键 → `indices.id`，`ON DELETE CASCADE`，有索引 |
| trade_date | DATE | 否 | — | 交易日期 |
| open | DECIMAL(12,3) | 否 | — | 开盘价（宏观代理类为点位/收益率值） |
| close | DECIMAL(12,3) | 否 | — | 收盘价 |
| high | DECIMAL(12,3) | 否 | — | 最高价 |
| low | DECIMAL(12,3) | 否 | — | 最低价 |
| volume | BIGINT | 否 | Python 侧 `0` | 成交量 |
| amount | DECIMAL(20,3) | 是 | NULL | 成交额 |

- **主键**：`id`
- **唯一键**：`uq_index_date (index_id, trade_date)`
- **二级索引**：`index_id`
- **关联**：`index_id → indices.id`（CASCADE）
- **外键表文件**：`backend/app/models/index.py`

### 3.6 etfs

**用途**：ETF 元信息（核心宽基 ETF + 行业/主题 ETF）。
**追溯**：FR-DATA-001、FR-DATA-005、FR-DATA-012（`tracks` 支撑 ETF 列表的"跟踪指数"展示）。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键 |
| code | VARCHAR(16) | 否 | — | ETF 代码（如 `510300`），`UNIQUE` + 索引 |
| name | VARCHAR(64) | 是 | NULL | ETF 名称 |
| tracks | VARCHAR(128) | 是 | NULL | 跟踪标的（指数代码或描述，如 `000300`、`HSTECH`） |

- **主键**：`id`；**唯一键/索引**：`code`（UNIQUE + INDEX）
- **关联**：被 `etf_daily_klines.etf_id` 外键引用（CASCADE）
- **外键表文件**：`backend/app/models/etf.py`

### 3.7 etf_daily_klines

**用途**：ETF 日线 OHLCV + 复权因子。ETF 是标的池主要品种。
**追溯**：FR-DATA-001、FR-DATA-009、FR-DATA-011、FR-DATA-012（最新价/涨跌幅由最近两日 `close` 计算）。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键 |
| etf_id | INT | 否 | — | 外键 → `etfs.id`，`ON DELETE CASCADE`，有索引 |
| trade_date | DATE | 否 | — | 交易日期 |
| open | DECIMAL(14,6) | 否 | — | 开盘价（6 位小数，见 5.3 精度表） |
| close | DECIMAL(14,6) | 否 | — | 收盘价 |
| high | DECIMAL(14,6) | 否 | — | 最高价 |
| low | DECIMAL(14,6) | 否 | — | 最低价 |
| volume | BIGINT | 否 | Python 侧 `0` | 成交量 |
| amount | DECIMAL(22,6) | 是 | NULL | 成交额 |
| adj_factor | DECIMAL(14,6) | 是 | NULL | 复权因子 |

- **主键**：`id`
- **唯一键**：`uq_etf_date (etf_id, trade_date)`
- **二级索引**：`etf_id`
- **关联**：`etf_id → etfs.id`（CASCADE）
- **外键表文件**：`backend/app/models/etf.py`

### 3.8 funds

**用途**：公募基金元信息。净值型品种，不参与指标计算与状态识别特征。
**追溯**：FR-DATA-001（四类标的之一）。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键 |
| code | VARCHAR(16) | 否 | — | 基金代码，`UNIQUE` + 索引 |
| name | VARCHAR(64) | 是 | NULL | 基金名称 |
| fund_type | VARCHAR(32) | 是 | NULL | 类型（股票型/混合型/债券型…） |

- **主键**：`id`；**唯一键/索引**：`code`（UNIQUE + INDEX）
- **关联**：被 `fund_daily_klines.fund_id` 外键引用（CASCADE）
- **外键表文件**：`backend/app/models/fund.py`

### 3.9 fund_daily_klines

**用途**：基金净值历史。**无 OHLCV**，仅单位净值与累计净值。
**追溯**：FR-DATA-001、FR-DATA-009。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键 |
| fund_id | INT | 否 | — | 外键 → `funds.id`，`ON DELETE CASCADE`，有索引 |
| trade_date | DATE | 否 | — | 净值日期 |
| unit_nav | DECIMAL(12,4) | 是 | NULL | 单位净值 |
| acc_nav | DECIMAL(12,4) | 是 | NULL | 累计净值 |

- **主键**：`id`
- **唯一键**：`uq_fund_date (fund_id, trade_date)`
- **二级索引**：`fund_id`
- **关联**：`fund_id → funds.id`（CASCADE）
- **外键表文件**：`backend/app/models/fund.py`

### 3.10 instruments

**用途**：跨资产类别的统一代码目录（universe 构建时导入前 upsert 写入，`backend/app/services/data/importer.py` 的 `_upsert_instrument`）。回答"给定 code：是什么、走哪个源、属于什么类、跟踪谁"。
**追溯**：FR-DATA-005（预定义标的池的持久化形态）、FR-DATA-012（跟踪指数）。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| code | VARCHAR(32) | 否 | — | **主键**（非自增），全局唯一，跨 index/etf/stock/fund 不复用 |
| name | VARCHAR(64) | 是 | NULL | 标的名称 |
| asset_type | VARCHAR(16) | 否 | — | 类型：`index`/`etf`/`stock`/`fund`，有索引 |
| market | VARCHAR(16) | 是 | NULL | 市场：SH/SZ/BJ/HK/US/CN/FX |
| category | VARCHAR(32) | 是 | NULL | 分类：宽基/科技/消费/国债/汇率… |
| data_source | VARCHAR(64) | 是 | NULL | 取数源/接口描述；优先 universe 配置，无则回填实际命中源 |
| tracks_index | VARCHAR(32) | 是 | NULL | ETF 跟踪的指数 code |
| note | VARCHAR(128) | 是 | NULL | 备注 |

- **主键**：`code`（业务主键，String，非自增）
- **唯一键/索引**：`asset_type`（普通索引，按类型筛选）
- **关联**：无外键；`tracks_index` 与 `indices.code`、`code` 与四张元信息表的 `code` 均为逻辑对应
- **外键表文件**：`backend/app/models/instrument.py`

### 3.11 indicator_values

**用途**：技术指标宽表，一行汇聚 (asset_type, code, trade_date) 下全部指标。导入完成后按标的**全量重算并整体替换**（先删该标的全部行再插，`scheduler.py` 的 `_recalc_indicators`，对应 FR-IND-007 / AC-06）。
**追溯**：FR-IND-001/002/003/004/005（五类指标持久化）、FR-IND-006（复权因子在读取期使用，见 4.3）、FR-IND-007（整体更新）、FR-IND-008（按标的查询）。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键 |
| asset_type | VARCHAR(8) | 否 | — | 资产类型：`stock`/`index`/`etf`（fund 不算指标），有索引 |
| code | VARCHAR(32) | 否 | — | 标的代码（字符串，非外键，见 4.2），有索引 |
| trade_date | DATE | 否 | — | 交易日期，有索引 |
| macd_dif | DECIMAL(14,6) | 是 | NULL | MACD DIF |
| macd_dea | DECIMAL(14,6) | 是 | NULL | MACD DEA |
| macd_hist | DECIMAL(14,6) | 是 | NULL | MACD 柱 |
| rsi | DECIMAL(8,4) | 是 | NULL | RSI（0–100，4 位小数足够） |
| boll_upper | DECIMAL(14,6) | 是 | NULL | Bollinger 上轨 |
| boll_mid | DECIMAL(14,6) | 是 | NULL | Bollinger 中轨 |
| boll_lower | DECIMAL(14,6) | 是 | NULL | Bollinger 下轨 |
| keltner_upper | DECIMAL(14,6) | 是 | NULL | Keltner 上轨 |
| keltner_mid | DECIMAL(14,6) | 是 | NULL | Keltner 中轨 |
| keltner_lower | DECIMAL(14,6) | 是 | NULL | Keltner 下轨 |
| atr | DECIMAL(14,6) | 是 | NULL | ATR(14) |

- **主键**：`id`
- **唯一键**：`uq_indicator_asset_date (asset_type, code, trade_date)` —— 防重复写入的兜底约束（当前写入路径为整体替换，此约束保证任何路径下不出现重复行）
- **二级索引**：`asset_type`、`code`、`trade_date` 各自独立索引
- **关联**：无外键，`(asset_type, code)` 逻辑对应元信息表
- **外键表文件**：`backend/app/models/indicator.py`

### 3.12 regime_runs

**用途**：一次"特征工程 → PCA → HMM → LogisticRegression"训练的快照元数据（按市场 A/HK 独立建模）。由 `backend/app/services/market_regime/persist.py` 的 `save_run` 写入。
**追溯**：FR-REGIME-001（按市场独立建模 → `market` 列）、FR-REGIME-002（管线算法 → `algorithm`/`classifier` 列）、FR-REGIME-003（超参 → `params` 列）、FR-REGIME-004（运行记录落库）。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键，即 `regime_states.run_id` |
| market | VARCHAR(16) | 否 | — | 市场：`A` / `HK` |
| algorithm | VARCHAR(32) | 是 | NULL | 聚类算法：`hmm` / `gmm` / `kmeans` |
| classifier | VARCHAR(32) | 是 | NULL | 状态分类器：`logistic` 等 |
| params | JSON | 是 | NULL | 训练超参快照（HMM 状态数、PCA 方差比例、随机种子等） |
| metrics | JSON | 是 | NULL | 评估指标（KS / ROC-AUC / 轮廓系数） |
| trained_at | DATETIME | 否 | `CURRENT_TIMESTAMP` | 训练时间，`server_default=func.now()` |

- **主键**：`id`
- **索引**：无除主键外的二级索引；按市场过滤 run 时由全表扫描承担（run 量级极小，见第 5 节）
- **关联**：被 `regime_states.run_id` 外键引用，级联删除——删除 run 即删除其全部状态序列
- **外键表文件**：`backend/app/models/market_regime.py`

### 3.13 regime_states

**用途**：某次训练 run 下每个交易日的状态标签、概率与特征快照。由 `save_states` **先删后插覆盖式**写入（保证同 run 重跑幂等）。
**追溯**：FR-REGIME-004（逐日状态持久化）、FR-REGIME-005（按市场查询逐日状态序列）、FR-REGIME-007（训练模块可选加载——状态查询直接读本表，hmmlearn 缺失时仍可服务）。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键 |
| run_id | INT | 否 | — | 外键 → `regime_runs.id`，`ON DELETE CASCADE`，有索引 |
| trade_date | DATE | 否 | — | 交易日期 |
| state_label | INT | 否 | — | 状态标签（0=平静 / 1=动荡，默认 3 状态聚类下可扩展更多标签） |
| state_prob | FLOAT | 是 | NULL | 进入动荡期概率 |
| features_snapshot | JSON | 是 | NULL | 当日特征/主成分快照（numpy 类型经序列化转原生 JSON） |

- **主键**：`id`
- **唯一键**：`uq_run_date (run_id, trade_date)` —— 同一 run 内日期不重复
- **二级索引**：`run_id`（外键索引，取某 run 全序列的主路径）
- **关联**：`run_id → regime_runs.id`（CASCADE）
- **外键表文件**：`backend/app/models/market_regime.py`

> 模型类 docstring 中"Schema 预留，本数据层计划不写入"的注释已过时：`persist.py` 的 `save_run`/`save_states` 已在训练管线中实际写入这两张表。以代码现状为准。

### 3.14 import_errors

**用途**：批量导入失败记录（断点续传）。失败标的入此表；重试端点取 `retried_at IS NULL` 的记录重跑，成功后回写 `retried_at`。
**追溯**：FR-DATA-007（失败记录 + 按失败记录重试）、FR-DATA-014（导入进度查询展示完成/失败情况）。

| 列名 | 类型 | 可空 | 默认 | 说明 |
|------|------|------|------|------|
| id | INT AUTO_INCREMENT | 否 | — | 主键 |
| asset_type | VARCHAR(16) | 否 | — | 资产类型：`stock`/`index`/`etf`/`fund`，有索引 |
| code | VARCHAR(32) | 否 | — | 标的代码，有索引 |
| source | VARCHAR(16) | 是 | NULL | 数据源：`akshare` / `guosen` 等 |
| error_msg | VARCHAR(512) | 是 | NULL | 错误摘要（可读原因，AC-12） |
| created_at | DATETIME | 否 | `CURRENT_TIMESTAMP` | 失败发生时间，`server_default=func.now()` |
| retried_at | DATETIME | 是 | NULL | 重试时间；**NULL 即未重试**，兼具状态与时间戳双重语义 |

- **主键**：`id`
- **二级索引**：`asset_type`、`code`（待重试查询按这两维过滤）
- **关联**：无外键（失败发生时目标行可能尚不存在）
- **外键表文件**：`backend/app/models/import_log.py`

---

## 4. 关键设计决策

### 4.1 行情导入为何用 `ON DUPLICATE KEY UPDATE`（upsert）而非先查后插

批量导入与每日同步（FR-DATA-009 / FR-DATA-010 / NFR-REL-003）都要求幂等。实现选择：

- **先 SELECT 再 INSERT/UPDATE**：每个标的需要一次额外往返，且在并发导入（限并发 2）与调度重试并存时存在竞态窗口，仍可能撞唯一键报错；要彻底防重还得捕获异常重试，代码复杂。
- **整表先删后插**：日线是追加型时序，删除重插会放大 binlog 与锁开销，且失败时破坏既有数据，违反 NFR-REL-003"不损坏既有数据"。
- **`INSERT ... ON DUPLICATE KEY UPDATE`（SQLAlchemy `mysql_insert().on_duplicate_key_update()`）**：单条语句、单次往返、数据库侧原子判定冲突，重复导入时已有行被最新值覆盖，天然满足 AC-03（行数不变、值为最后一次导入值）。

该方案的前提是存在明确的冲突判定键——即每张日线表的命名唯一约束 `uq_*_date`（`stock_id, trade_date` 等）。更新列集合刻意**排除** `(asset_id, trade_date)` 本身，只更新 OHLCV/amount/adj_factor。

两个不使用 ODKU 的例外，各有原因：

- **`indicator_values`、`regime_states` 采用"先删后插"**：二者语义是"整体替换"（FR-IND-007 要求旧行被整体替换；`save_states` 要求同 run 重跑覆盖），不是逐行合并；且测试环境用 SQLite（不支持 MySQL 方言的 `on_duplicate_key_update`），先删后插可跨方言工作，唯一键仅作兜底防重。
- **`instruments` upsert**：MySQL 下用 ODKU（`_upsert_instrument`），SQLite 测试下降级为 select + update/insert——字典行数少（≤ 数百），降级路径的往返开销可忽略。

### 4.2 四类标的为何各建表，`instruments` 又为何独立存在

**各建表的"为什么"**：四类标的的日线结构真实异构——基金只有净值（无 OHLCV）、指数无复权因子、ETF 价格需要 6 位小数、股票/指数 3 位。若合并为单表 + `asset_type` 列：

- 会出现大量按类型"永远为 NULL"的列（fund 行的 OHLCV、index 行的 adj_factor），表结构失去自解释性；
- 唯一键必须变成 `(asset_type, asset_id, trade_date)` 之类的三列复合键，四类标的的 `id` 还得分段互斥或引入统一资产表，`ON DUPLICATE KEY UPDATE` 的冲突语义随之变绕；
- DECIMAL 精度只能统一取最高（14,6），白白放大存储。

分表后每张表获得精确结构 + 独立命名唯一键，ODKU 幂等导入直接可用。代价是"按 code 跨类型查"需要知道类型——这正是 `instruments` 存在的理由。

**`instruments` 的"为什么"**：它是**代码目录**而非资产父表，不承载 OHLCV 外键。导入流程需要"给定 code → 知道类型/市场/走哪个数据源"的快速映射来分发取数方法；`code` 直接做主键（非自增），因为 code 本身全局唯一且是所有外部交互的自然键（数据源、API、universe 配置都用 code）。它与四张元信息表按 code 逻辑对应（`Instrument.code` 注释明确"跨 index/etf/stock 不复用"），即使元信息表尚未建行，字典也可先写，两边解耦演进。`tracks_index`、`category` 等扩展属性放在字典侧，不侵入各元信息表。

同理，`indicator_values` 用 `(asset_type, code)` 字符串而非外键：指标重算先于元信息存在时不阻塞；指标 API 按 code 直接查、免一次 asset_id 解析 JOIN；代价是失去引用完整性——由 universe/导入流程保证 code 一致性，唯一键兜底防重。

### 4.3 复权模式存储策略：存原始价 + 因子，`adjust_mode` 不落库

K 线表存的是**未复权原始价 + `adj_factor` 复权因子列**；`adjust_mode`（`forward`/`backward`/`none`，默认 `forward`）只是指标计算与查询 API 的**读取期参数**（`routers/indicators.py`），不在任何表中存储。

原因：前复权价不是稳定数据——每次除权除息后，全部历史前复权价都会变化。若落库复权价，每次除权都得重写全表；落因子则只需在读取/计算时按 `adjust_mode` 现场还原任意模式（`indicators.py` 中 `df["adj_factor"].notna()` 时才应用 `adjust()`），一次因子更新即可支撑前复权/后复权/不复权三种视图。指数无分红除权，故无因子列；基金净值本身无需复权。

### 4.4 软删除：无

全部 14 张表均无 `is_deleted`/`deleted_at` 之类软删除列，删除均为物理删除：

- 行情/指标数据可从数据源随时重灌，删除不损失不可再生信息；
- 元信息与日线、run 与 states 均为 CASCADE 级联删除，父子同删不留孤儿；
- 唯一"删除语义"出现在 `import_errors.retried_at`——用 NULL/非 NULL 表达待处理/已处理，不做物理删除，保留失败历史供排查（见 4.1 的例外说明与 3.14）。

单用户研究场景没有审计/回收站需求，引入软删除只会让所有查询多一个 `WHERE is_deleted=0` 负担。

### 4.5 字符集：utf8mb4

标的名称、分类、错误摘要均为中文，且 `note`/`error_msg` 可能混入数据源返回的特殊字符。`VARCHAR` 侧必须 utf8mb4（4 字节，完整 BMP+增补平面），避免插入生僻字或 emoji 时报 `Incorrect string value`。

现状与约定：ORM 模型**未显式指定表级 `mysql_charset`**，实际字符集继承 RDS 库默认值；因此约定——连接串统一显式带 `?charset=utf8mb4`（本文档 1.3 示例即如此），建库时库默认字符集设为 utf8mb4，使 `create_all` 产出的新表自然继承。数值列（DECIMAL/INT/DATE）不受字符集影响。

### 4.6 时区存储约定

- 所有 `DATETIME` 列（`users.created_at`、`regime_runs.trained_at`、`import_errors.created_at/retried_at`）均为**无时区 naive 值**，由 `server_default=func.now()` 产生，即**数据库服务器时区**（RDS 实例时区，读取方须按同一时区解释）；
- 所有 `trade_date` 为 `DATE`，语义是**上海时区的交易日**（A 股日历，调度器按上海时间 15:05 触发同步，FR-DATA-010；周末跳过，节假日由"数据源无数据自然跳过"兜底，不建交易日历表）；
- 数据导入侧（pandas `Timestamp`）统一在写入前转为 `date`，杜绝 datetime 带时区混入 DATE 列。

---

## 5. 容量与性能估算

### 5.1 规模假设

| 参数 | 取值 | 依据 |
|------|------|------|
| 固定标的池 | 33（13 指数 + 6 宽基 ETF + 14 行业 ETF） | `services/data/universe.py` |
| 个股池 | ≤ 300（沪深300成分股，按市值降序，实际常按需取前 N） | FR-DATA-006 |
| 交易日/年 | ≈ 250 | A 股日历 |
| 单标的历史 | 10 年 ≈ 2 500 行 | NFR-PERF-004 同量级 |
| 单行体积（含索引摊销） | 日线 ≈ 150 B；指标行 ≈ 200 B；状态行（含 JSON 快照）≈ 1–2 KB | 列宽估算 |

### 5.2 行数与体积量级

| 表 | 行数估算 | 体积量级 |
|----|---------|---------|
| 四张元信息表 + instruments | ≤ 700（33 + 300 + 字典） | < 1 MB |
| 四张日线表（仅固定池） | 33 × 2 500 ≈ 8 万 | < 20 MB |
| 四张日线表（含全部 300 成分股） | ≈ 76 万 | 100–200 MB |
| indicator_values | ≤ 68 万（固定池 + 成分股，fund 除外） | 100–150 MB |
| regime_runs | 每次训练 +1~2 行 | 可忽略 |
| regime_states | 每次全量重训 ≈ 2 市场 × 2 500 行 ≈ 5 000 行 | ≈ 5–10 MB/次（JSON 快照放大） |
| import_errors | 与失败标的数同阶（数百/年） | 可忽略 |

结论：即使纳入全部沪深300成分股，总体量仍在 **GB 以下**，单实例 RDS MySQL 无需分区/分表；性能设计重点在索引与查询路径而非容量。

### 5.3 精度即容量：DECIMAL 选型

| 表 | 价格 | 成交额 | 理由 |
|----|------|--------|------|
| stock/index_daily_klines | DECIMAL(12,3) | DECIMAL(20,3) | A 股价格 3 位小数；指数点位 + 宏观代理值同精度 |
| etf_daily_klines | DECIMAL(14,6) | DECIMAL(22,6) | 低净值债券/货币 ETF 需 6 位小数表达 |
| fund_daily_klines | DECIMAL(12,4)（净值） | — | 公募净值惯例 4 位小数 |

### 5.4 regime_states 的增长形态（需要关注的一张表）

`regime_states` 不是"逐日 +1"式增长：每次训练一次性写入**整个训练窗口**的逐日状态，且历史 run 的 states 默认保留（可追溯 FR-REGIME-004/005）。因此增长正比于 **训练次数 × 窗口长度**：若每天对 A/HK 两市场各重训一次，年增 ≈ 2 × 2 500 × 250 ≈ 125 万行、GB 级 JSON 快照。控制手段：`features_snapshot` 按需写入（可 NULL）；旧 run 可整体删除（CASCADE 随 run 删 states）；按市场查询接口只读最新 run，读路径不受历史膨胀影响。

### 5.5 索引支撑的查询路径

| 查询 | 命中索引 | 对应需求 |
|------|---------|---------|
| 单标的日期区间日线（主路径） | `uq_*_date` 最左前缀 `asset_id` + `trade_date` 范围扫描 | FR-DATA-011 / NFR-PERF-001（1 年 ≤250 根，P95 < 1s） |
| 按 code 查元信息/字典 | `code` UNIQUE | FR-DATA-012 |
| 按 code 查指标序列 | `uq_indicator_asset_date` 最左前缀 `(asset_type, code)` + 日期范围 | FR-IND-008 / NFR-PERF-004（全量重算 ≤10s 的读入路径） |
| 某市场最新状态 | `regime_states.run_id` 索引（取最新 run 后按 run 取全序列） | FR-REGIME-005 |
| 待重试失败记录 | `import_errors.asset_type`/`code` | FR-DATA-007 |

唯一键同时承担"防重 + 查询"双重职责，无冗余二级索引；所有表合计索引数保持在最小集。

---

## 6. 验证记录

### 6.1 本次核对方式（2026-08-31）

以 ORM 源码为唯一权威，逐表静态比对：

1. **逐表比对**：通读 `backend/app/models/` 下全部 10 个模型文件（user / stock / kline / index / etf / fund / instrument / indicator / market_regime / import_log），将本文档 14 张表的列名、类型、可空性、默认值、唯一约束名、索引与 `mapped_column`/`UniqueConstraint` 定义逐一核对，不一致处以 ORM 为准修正；
2. **驱动核实**：`backend/.env` 的 `DATABASE_URL` scheme 为 `mysql+aiomysql://`（核对时已脱敏，凭据不入文档）；venv `aiomysql/_scm_version.py` 确认版本 0.3.2；`requirements.txt` 无 aiomysql、无 asyncmy；
3. **写入路径核实**：`services/data/importer.py`（ODKU 批量 upsert、instruments upsert）、`services/scheduler.py`（每日同步 upsert、indicator_values 先删后插）、`services/market_regime/persist.py`（run/states 写入）逐一确认，修正旧文档"regime 表未写入"的过时表述；
4. **迁移体系核实**：`backend/alembic/` 仅有空 `__init__.py`，仓库无 `alembic.ini`/`env.py`/`versions/`；`alembic==1.13.3` 虽在 requirements 中，但迁移体系未初始化。

### 6.2 无迁移体系的现状与风险

现状：schema 完全由 `init_db()` → `Base.metadata.create_all` 在应用启动时直建（`main.py` lifespan）。

风险与影响（如实记录，未在本仓库修复）：

- `create_all` 只**创建缺失的表**，不会对已存在的表做任何变更——ORM 加列/改类型/加索引后，线上库不会自动跟上，需要手工 `ALTER TABLE` 或 DROP 重建；
- 命名唯一约束（`uq_*_date`）若在线上手建时遗漏，ODKU 幂等导入会退化为普通 INSERT 并产生重复数据；
- 无法回溯"哪个 schema 版本对应哪次发布"，多环境（开发/RDS）间易漂移；alembic 已安装但未初始化，补齐 `alembic init` + autogenerate 基线是低成本改进项。

### 6.3 历史验证记录

| 验证时间 | 数据库 | 结果 |
|----------|--------|------|
| 2026-07-20 | stockdb（阿里云 RDS MySQL） | 14 张表结构与 ORM 比对一致（`DESCRIBE` + `SHOW INDEX` 逐表核对；`created_at`/`trained_at` 为 `DEFAULT_GENERATED now()`，`is_active` 映射 `tinyint(1)`） |
| 2026-08-31 | 本文档重写 | 以 ORM 源码逐表静态核对为准（见 6.1），未直连数据库；驱动表述修正为 aiomysql 0.3.2 |

---

## 7. 变更日志

| 日期 | 说明 |
|------|------|
| 2026-08-31 | 全面重写（对照 ORM 源码 + requirements.md 基线）。主要修正：① 驱动 asyncmy → aiomysql 0.3.2，连接串示例改为占位符并显式 `charset=utf8mb4`；② 修正 ER 说明中指向不存在的 `assets` 表的笔误（实际外键分别指向 stocks/indices/etfs/funds.id）；③ regime_runs/regime_states 由"Schema 预留不写入"更正为已由 `persist.py` 实际写入（save_states 先删后插覆盖式）；④ 列定义表格统一为"列名/类型/可空/默认/说明"，区分数据库默认与 Python 侧默认，补齐命名唯一约束 `uq_*`；⑤ 每表新增需求追溯（25 个 FR-ID）；⑥ 新增设计决策"为什么"（ODKU 幂等、分表 vs instruments、复权存储、软删除有无、字符集、时区）；⑦ 新增容量与性能估算、无迁移体系（create_all 直建）的现状与风险。 |
| 2026-07-20 | 初版，从 ORM 模型整理并入库验证（14 张表）。 |
