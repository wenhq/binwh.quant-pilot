# 后端接口文档

> 所有接口前缀 `/api`，由 `backend/app/main.py` 统一挂载。路由文件位于 `backend/app/routers/`。

## 认证（Cookie-based JWT）

路由文件：`backend/app/routers/auth.py`（prefix `/auth`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/register` | 注册新用户，返回 201 |
| POST | `/api/auth/login` | 验证用户名密码，设置 httpOnly Cookie（access 15min + refresh 7d） |
| POST | `/api/auth/refresh` | 用 refresh_token 续期 access_token |
| POST | `/api/auth/logout` | 清除两个 cookie |
| GET | `/api/auth/me` | 返回当前登录用户信息（需登录） |

**认证流程**：
```
登录 → POST /auth/login
  → 后端验证 → Set-Cookie(access, refresh) httpOnly
  → 前端跳转 Dashboard

访问受保护 API
  → Axios 自动带 cookie
  → 后端验证 access_token
  → 401 → 自动 POST /auth/refresh
    → 成功：重试原请求
    → 失败：清除状态 → 跳 /login
```

## 数据

路由文件：`backend/app/routers/data.py`（prefix `/data`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/data/sync/{stock_code}` | 同步日 K 线（akshare → MySQL） |
| GET | `/api/data/stock/{code}/daily` | 个股日 K 线 |
| GET | `/api/data/index/{code}/daily` | 指数日 K 线 |
| GET | `/api/data/etf/{code}/daily` | ETF 日 K 线 |
| GET | `/api/data/etfs` | ETF 列表 + 最新价/涨跌幅 |
| POST | `/api/data/import/batch` | 批量导入沪深 300 + 指数/ETF |
| POST | `/api/data/import/retry` | 重试失败导入 |
| GET | `/api/data/import/progress` | 导入进度 |

## 指标

路由文件：`backend/app/routers/indicators.py`（prefix `/indicators`，参数 `asset_type: stock/index/etf`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/indicators/{asset_type}/{code}/macd` | MACD |
| GET | `/api/indicators/{asset_type}/{code}/rsi` | RSI |
| GET | `/api/indicators/{asset_type}/{code}/boll` | 布林带 |
| GET | `/api/indicators/{asset_type}/{code}/all` | K 线 + 全部指标 |

**缓存策略**：优先读 `indicator_values` 表；无缓存时回退到实时计算。

## 市场状态 ML

路由文件：`backend/app/routers/market_regime.py`（prefix `/market_regime`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/market_regime/train/{market}` | 训练单个市场（A / HK） |
| POST | `/api/market_regime/train_all` | 训练全部市场 |
| GET | `/api/market_regime/states/{market}` | 最新状态序列 |
| GET | `/api/market_regime/runs/{market}` | 训练历史 |

**ML 管线**：特征（多周期收益率、已实现波动率、宏观差值、价差）→ PCA（95% 方差）→ HMM（3 状态、多种子）→ LogisticRegression（t+1 状态预测）→ 评估（KS、状态统计、episode 覆盖率）

## 健康检查

路由文件：`backend/app/routers/health.py`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | `{"status":"ok"}` |
