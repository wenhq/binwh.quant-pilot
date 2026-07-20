# 数据库设计文档

## 1. 概述

| 项目 | 内容 |
|------|------|
| 数据库 | MySQL |
| 驱动 | asyncmy (`mysql+asyncmy://...`) |
| ORM | SQLAlchemy 2.x Async (`DeclarativeBase`) |
| 会话 | `AsyncSession` + `async_sessionmaker`（`expire_on_commit=False`） |
| 建表 | `Base.metadata.create_all`（开发模式自动建表） |
| 事务 | 无全局 autocommit，依赖 API 层显式 commit/rollback |

默认连接串（`.env` 覆盖）：

```env
DATABASE_URL=mysql+asyncmy://root:password@127.0.0.1:3306/quantpilot
```

---

## 2. ER 概览

```
users (1) ──< (N) 无直接 FK，用户独立

stocks (1) ──< (N) stock_daily_klines          CASCADE DELETE
indices (1) ──< (N) index_daily_klines         CASCADE DELETE
etfs   (1) ──< (N) etf_daily_klines            CASCADE DELETE
funds  (1) ──< (N) fund_daily_klines           CASCADE DELETE

regime_runs (1) ──< (N) regime_states          CASCADE DELETE

instruments ── 独立字典表，不持有 OHLCV FK

indicator_values ── 独立指标宽表，用字符串 code 关联资产（不设 FK）
import_errors    ── 独立错误记录表
```

> **模式说明**：`stocks / indices / etfs / funds` 四张元信息表结构高度一致，各自附带一张 `_daily_klines` 日线表，通过 `asset_id → assets.id` 外键级联删除。

---

## 3. 表结构明细

### 3.1 users

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| username | varchar(64) | unique, not null, indexed | 登录名 |
| hashed_password | varchar(128) | not null | BCrypt 哈希密码 |
| is_active | bool | default true, not null | 是否启用 |
| created_at | datetime | server_default=now(), not null | 创建时间 |

---

### 3.2 stocks + stock_daily_klines

**stocks**

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| code | varchar(16) | unique, not null, indexed | 股票代码（如 `600519`） |
| name | varchar(64) | nullable | 股票名称 |
| market | varchar(16) | nullable | 市场（SH/SZ） |

**stock_daily_klines**

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| stock_id | int | FK→stocks.id ON DELETE CASCADE, not null, indexed | 股票 ID |
| trade_date | date | not null | 交易日期 |
| open | numeric(12,3) | not null | 开盘价 |
| close | numeric(12,3) | not null | 收盘价 |
| high | numeric(12,3) | not null | 最高价 |
| low | numeric(12,3) | not null | 最低价 |
| volume | bigint | default 0, not null | 成交量（手） |
| amount | numeric(20,3) | nullable | 成交额（元） |
| adj_factor | numeric(12,6) | nullable | 前复权因子 |

唯一约束：`UNIQUE(stock_id, trade_date)`

---

### 3.3 indices + index_daily_klines

**indices**

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| code | varchar(32) | unique, not null, indexed | 指数代码（如 `000300`） |
| name | varchar(64) | nullable | 指数名称 |
| market | varchar(16) | nullable | 市场（A/HK） |

**index_daily_klines**

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| index_id | int | FK→indices.id ON DELETE CASCADE, not null, indexed | 指数 ID |
| trade_date | date | not null | 交易日期 |
| open | numeric(12,3) | not null | 开盘价 |
| close | numeric(12,3) | not null | 收盘价 |
| high | numeric(12,3) | not null | 最高价 |
| low | numeric(12,3) | not null | 最低价 |
| volume | bigint | default 0, not null | 成交量 |
| amount | numeric(20,3) | nullable | 成交额 |

> 指数日线 **无** `adj_factor`（指数无需复权）。

唯一约束：`UNIQUE(index_id, trade_date)`

---

### 3.4 etfs + etf_daily_klines

**etfs**

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| code | varchar(16) | unique, not null, indexed | ETF 代码 |
| name | varchar(64) | nullable | ETF 名称 |
| tracks | varchar(128) | nullable | 跟踪标的（指数代码或描述） |

**etf_daily_klines**

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| etf_id | int | FK→etfs.id ON DELETE CASCADE, not null, indexed | ETF ID |
| trade_date | date | not null | 交易日期 |
| open | numeric(14,6) | not null | 开盘价 |
| close | numeric(14,6) | not null | 收盘价 |
| high | numeric(14,6) | not null | 最高价 |
| low | numeric(14,6) | not null | 最低价 |
| volume | bigint | default 0, not null | 成交量 |
| amount | numeric(22,6) | nullable | 成交额 |
| adj_factor | numeric(14,6) | nullable | 前复权因子 |

> ETF 价格精度为 6 位小数（`numeric(14,6)`），以适应低净值的债券/货币 ETF。

唯一约束：`UNIQUE(etf_id, trade_date)`

---

### 3.5 funds + fund_daily_klines

**funds**

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| code | varchar(16) | unique, not null, indexed | 基金代码 |
| name | varchar(64) | nullable | 基金名称 |
| fund_type | varchar(32) | nullable | 类型（股票型/混合型/债券型…） |

**fund_daily_klines**

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| fund_id | int | FK→funds.id ON DELETE CASCADE, not null, indexed | 基金 ID |
| trade_date | date | not null | 交易日期 |
| unit_nav | numeric(12,4) | nullable | 单位净值 |
| acc_nav | numeric(12,4) | nullable | 累计净值 |

> 基金表 **无 OHLCV**，仅记录净值（`unit_nav / acc_nav`）。

唯一约束：`UNIQUE(fund_id, trade_date)`

---

### 3.6 instruments（统一标的字典）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| code | varchar(32) | PK（非自增） | 标的代码，全局唯一 |
| name | varchar(64) | nullable | 标的名称 |
| asset_type | varchar(16) | not null, indexed | 类型：index/etf/stock/fund |
| market | varchar(16) | nullable | 市场：SH/SZ/HK/US/CN/FX |
| category | varchar(32) | nullable | 分类：宽基/科技/消费/国债/汇率/… |
| data_source | varchar(64) | nullable | 取数源/接口描述 |
| tracks_index | varchar(32) | nullable | ETF 跟踪的指数 code |
| note | varchar(128) | nullable | 备注 |

> **设计意图**：`instruments` 是跨资产类别的统一代码目录，由 universe 构建时同步写入（import 前 upsert）。查一个 code 立刻知道"是什么、走哪个源、属于什么类、跟踪谁"。

---

### 3.7 indicator_values（技术指标宽表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| asset_type | varchar(8) | not null, indexed | 资产类型：stock/index/etf |
| code | varchar(32) | not null, indexed | 标的代码（字符串，非 FK） |
| trade_date | date | not null, indexed | 交易日期 |
| macd_dif | numeric(14,6) | nullable | MACD DIF |
| macd_dea | numeric(14,6) | nullable | MACD DEA |
| macd_hist | numeric(14,6) | nullable | MACD 柱 |
| rsi | numeric(8,4) | nullable | RSI(14) |
| boll_upper | numeric(14,6) | nullable | 布林带上轨 |
| boll_mid | numeric(14,6) | nullable | 布林带中轨 |
| boll_lower | numeric(14,6) | nullable | 布林带下轨 |
| keltner_upper | numeric(14,6) | nullable | 肯特纳上轨 |
| keltner_mid | numeric(14,6) | nullable | 肯特纳中轨 |
| keltner_lower | numeric(14,6) | nullable | 肯特纳下轨 |
| atr | numeric(14,6) | nullable | ATR(14) |

唯一约束：`UNIQUE(asset_type, code, trade_date)`

> **设计意图**：一行汇聚 MACD / RSI / Bollinger / Keltner / ATR 全部指标，便于一次性读取绘图。用 `(asset_type, code, trade_date)` 做唯一键而非 FK，避免指标表与资产元信息表的强耦合，简化回填和跨资产查询。

---

### 3.8 regime_runs + regime_states（Market Regime ML）

**regime_runs**

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| market | varchar(16) | not null | 市场：A / HK |
| algorithm | varchar(32) | nullable | 聚类算法：hmm / gmm / kmeans |
| classifier | varchar(32) | nullable | 分类器：logistic / … |
| params | json | nullable | 模型超参 |
| metrics | json | nullable | 评估指标（KS / ROC-AUC / 轮廓系数） |
| trained_at | datetime | server_default=now(), not null | 训练时间 |

**regime_states**

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| run_id | int | FK→regime_runs.id ON DELETE CASCADE, not null, indexed | 训练批次 ID |
| trade_date | date | not null | 交易日期 |
| state_label | int | not null | 状态标签（0=平静 / 1=动荡，可扩展） |
| state_prob | float | nullable | 进入动荡期概率 |
| features_snapshot | json | nullable | 特征快照 |

唯一约束：`UNIQUE(run_id, trade_date)`

> **Schema 预留**：当前数据层不写入，由后续 ML 闭环 plan 落地。

---

### 3.9 import_errors（断点续传错误记录）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK, autoincrement | 主键 |
| asset_type | varchar(16) | not null, indexed | 资产类型：stock/index/etf/fund |
| code | varchar(32) | not null, indexed | 标的代码 |
| source | varchar(16) | nullable | 数据源：akshare / guosen |
| error_msg | varchar(512) | nullable | 错误摘要 |
| created_at | datetime | server_default=now(), not null | 错误发生时间 |
| retried_at | datetime | nullable | 重试时间（NULL 表示未重试） |

> **查询模式**：`WHERE retried_at IS NULL` 取出待重试记录；重试成功后回写 `retried_at`。

---

## 4. 索引汇总

| 表名 | 索引列 | 类型 | 用途 |
|------|--------|------|------|
| users | username | unique | 登录查重 |
| stocks | code | unique | 按代码查股票 |
| indices | code | unique | 按代码查指数 |
| etfs | code | unique | 按代码查 ETF |
| funds | code | unique | 按代码查基金 |
| instruments | code | PK | 全局代码字典 |
| instruments | asset_type | normal | 按类型筛选 |
| *_daily_klines | (asset_id, trade_date) | unique | 防重复 + 日期范围查询 |
| *_daily_klines | asset_id | normal | 某标的的全部历史 |
| indicator_values | (asset_type, code, trade_date) | unique | 指标查询主键 |
| indicator_values | asset_type / code / trade_date | normal | 各维度过滤 |
| regime_states | run_id | normal | 某 run 的全部状态序列 |
| regime_states | (run_id, trade_date) | unique | 防重复 |
| import_errors | asset_type / code | normal | 待重试查询 |

---

## 5. 设计决策

### 5.1 indicator_values 使用字符串 code 而非 FK

指标表存储 `asset_type + code`（字符串），不指向 `stocks/indices/etfs` 的任何 FK。

**原因**：
- 指标回填脚本可能比元信息表更早写入数据，取消 FK 依赖可独立运行。
- 同一 code 在不同 asset_type 下可能重复（如指数和 ETF 代码段重叠），用字符串区分更灵活。
- 减少 JOIN 开销，指标 API 可按 code 直接查，无需先查 asset_id。

### 5.2 instruments 独立字典表

`instruments` 用 `code` 做主键（非自增 ID），作为跨资产类别的统一目录。

**原因**：
- import 流程需要 "给定 code → 知道类型/市场/数据源" 的快速映射。
- 与 OHLCV 表解耦，即使资产元信息表尚未创建，字典也可预先存在。
- 支持 ETF 跟踪关系（`tracks_index`）等扩展属性，不侵入元信息表。

### 5.3  numeric 精度差异

| 表 | 价格精度 | 成交额精度 | 说明 |
|----|---------|-----------|------|
| stock_daily_klines | (12,3) | (20,3) | A 股价格 3 位小数（港股通 3 位） |
| index_daily_klines | (12,3) | (20,3) | 同股票 |
| etf_daily_klines | (14,6) | (22,6) | 低净值 ETF 需要更多小数位 |
| fund_daily_klines | (12,4) | — | 净值通常 4 位小数 |

### 5.4 基金表无 OHLCV

`fund_daily_klines` 仅记录 `unit_nav / acc_nav`，不设 open/high/low/volume。

**原因**：公募基金净值型数据不提供盘中分时高低，只有每日单一净值。

### 5.5 import_errors 的 retried_at 机制

用 `retried_at IS NULL` 筛选未重试记录，而非单独的布尔字段。

**原因**：自然记录重试时间，兼具状态和时间戳双重作用，无需额外列。
