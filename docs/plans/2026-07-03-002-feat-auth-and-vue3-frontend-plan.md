---
title: "feat: JWT 认证 + Vue 3 前端迁移 + Lightweight Charts 图表"
type: feat
date: 2026-07-03
---

## Summary

后端新增基于 httpOnly cookie 双 token 的 JWT 认证模块，前端从 React 迁移到 Vue 3 + Ant Design Vue + Lightweight Charts v5，优先交付市场状态仪表盘和 ETF 数据展示两个页面。

---

## Problem Frame

现有后端无用户认证，前端有 auth 页面但调用的 API 不存在。前端框架为 React，项目需要切换到用户熟悉的 Vue 3，同时引入专业金融图表库 Lightweight Charts 以支持 K 线展示和市场状态背景着色。

---

## Requirements

### 后端认证

- R1. 用户模型：username（唯一）、hashed_password、is_active、created_at
- R2. 密码使用 bcrypt 哈希存储，不存明文
- R3. `/auth/register` — 注册新用户，返回 201
- R4. `/auth/login` — 验证用户名密码，返回 httpOnly cookie（access_token 15min + refresh_token 7d）
- R5. `/auth/refresh` — 用 refresh_token 无感续期 access_token，返回新 cookie
- R6. `/auth/logout` — 清除两个 cookie
- R7. `/auth/me` — 返回当前登录用户信息
- R8. CORS 配置允许 credentials，cookie 设置 SameSite + Secure（生产）/ SameSite Lax（开发）
- R9. 受保护路由依赖注入当前用户，认证失败返回 401

### 前端迁移

- R10. 技术栈：Vue 3（Composition API + `<script setup>`）+ Vite 5 + TypeScript + Vue Router 4 + Axios + Ant Design Vue + Lightweight Charts v5
- R11. 保留 Vite 构建工具和开发服务器（端口 5173，代理 /api 到 localhost:8000）
- R12. Axios 全局配置 `withCredentials: true`，请求拦截器不再手动带 Authorization header
- R13. 401 响应时自动调用 `/auth/refresh`，refresh 也失败则跳登录页
- R14. Token 状态用 `reactive()` 管理，页面刷新时调用 `/auth/me` 恢复会话

### 市场状态仪表盘

- R15. 从 `/api/market_regime/states/A` 获取市场状态序列 + 指数日线数据
- R16. 用 Lightweight Charts 渲染 K 线图，背景按 state_label 着色（平静=绿底，动荡=红底）
- R17. 在 K 线图上标注波动方向箭头（基于相邻日涨跌和状态切换）

### ETF 数据展示

- R18. 列出 universe 中所有 ETF（代码、名称、跟踪指数、最新价格、涨跌幅）
- R19. 点击 ETF 行可展开查看近期 K 线图（Lightweight Charts）

---

## Key Technical Decisions

- KTD1. **httpOnly cookie + refresh token 双 token 模式。** 与主流 AI 产品一致（ChatGPT/Claude/Gemini），access_token 15 分钟过期，refresh_token 7 天过期，前端无感知续期。比 localStorage 安全（防 XSS），比单 token 体验好。
- KTD2. **前端保留 React 的 Ant Design 设计概念，切到 Ant Design Vue。** UI 组件风格一致（表格、表单、布局、中文 locale），学习成本低。
- KTD3. **图表层用 Lightweight Charts v5，不封装重型 Vue wrapper。** 用 `onMounted` + `ref` 直接挂载 Lightweight Charts 实例，保持轻量。K 线性能（数十万根）远超 ECharts/Ant Design Charts。
- KTD4. **市场状态颜色映射在前端做，不新增后端端点。** 后端保持 `/market_regime/states/{market}` 返回格式不变，前端根据 `state_label` 映射背景色。颜色映射是展示层逻辑，不应污染后端。
- KTD5. **前端路由用 Hash-based（`#/path`）。** 无需后端 catch-all 配置，部署简单。Vite 开发服务器和静态文件服务天然支持。

---

## High-Level Technical Design

### 后端架构

```
app/
├── models/
│   └── user.py          # User 模型（新增）
├── services/
│   └── auth/
│       ├── __init__.py
│       ├── security.py  # bcrypt hash + JWT encode/decode
│       └── config.py   # cookie/token 超时配置
├── routers/
│   └── auth.py          # /auth/* 端点（新增）
├── core/
│   └── dependencies.py  # get_current_user 依赖注入（新增）
```

### 前端架构

```
frontend/src/
├── main.ts              # Vue 入口
├── App.vue              # 根组件（RouterView + Layout）
├── router/
│   └── index.ts         # 路由定义
├── stores/
│   └── auth.ts          # reactive 状态管理
├── api/
│   ├── index.ts         # Axios 实例 + 拦截器
│   └── auth.ts          # auth API 函数
├── components/
│   └── KlineChart.vue   # Lightweight Charts 封装组件
├── views/
│   ├── Login.vue        # 登录页
│   ├── Register.vue     # 注册页
│   ├── Dashboard.vue    # 市场状态仪表盘
│   └── EtfView.vue      # ETF 数据展示
└── assets/
    └── main.css         # 全局样式
```

### 认证数据流

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

退出 → POST /auth/logout
  → 清除 cookie → 跳 /login
```

---

## Scope Boundaries

### 本计划包含

- 后端 JWT 认证完整模块（模型 + 服务 + 路由 + 依赖注入）
- 前端从 React 完全迁移到 Vue 3（删除 src/ 下所有 React 文件）
- 登录/注册页面重写
- 市场状态仪表盘（第一优先）
- ETF 数据展示页（第二优先）
- Lightweight Charts 封装组件

### Deferred to Follow-Up Work

- WebSocket 实时行情推送
- 回测引擎页面
- 技术指标计算（MACD/RSI/Boll）
- 研报解析 + LLM
- FCFF 估值模型
- 组合管理页面
- Docker 部署配置

### Outside this product's identity

- 微信登录
- MiniQMT 交易对接
- 移动端适配
- 多租户/权限体系

---

## Open Questions

无。httpOnly cookie 方案已确认。

---

## System-Wide Impact

- 后端新增 `app/core/dependencies.py` 依赖注入模式，后续所有受保护路由复用
- CORS 配置从无到有，影响所有前端 API 请求
- 前端完全重建，现有 React 代码无迁移路径（React 组件无法在 Vue 3 中复用）
- `backend/requirements.txt` 中已有 auth 相关依赖（python-jose、passlib、bcrypt），需确认是否已在 `pyproject.toml` 中

---

## Implementation Units

### U1. 后端用户模型与安全工具

**Goal:** 创建 User 模型和密码/JWT 工具函数

**Requirements:** R1, R2

**Files:**
- `backend/app/models/user.py` — 新建
- `backend/app/models/__init__.py` — 新增 User 导入
- `backend/app/services/auth/security.py` — 新建
- `backend/app/services/auth/__init__.py` — 新建
- `backend/app/services/auth/config.py` — 新建
- `backend/pyproject.toml` — 确认/补充 auth 依赖（python-jose、passlib、bcrypt）

**Approach:**
- User 模型继承 Base，字段：id (auto PK)、username (unique, indexed)、hashed_password (String(128))、is_active (Boolean, default True)、created_at (DateTime, server_default=func.now())
- security.py：`hash_password()`（passlib bcrypt）、`verify_password()`、`create_access_token()`（HS256, 15min expiry）、`create_refresh_token()`（HS256, 7d expiry）、`decode_token()`（返回 payload 或 raise HTTPException）
- config.py：从 Settings 读取 JWT_SECRET_KEY（新增 env var，默认随机字符串）、ALGORITHM、ACCESS_TOKEN_EXPIRE_MINUTES、REFRESH_TOKEN_EXPIRE_DAYS
- pyproject.toml：确认已有 `python-jose[cryptography]`、`passlib[bcrypt]`、`bcrypt` 依赖

**Patterns to follow:**
- 模型定义沿用 `Mapped[]` + `mapped_column` 风格（见 `models/stock.py`）
- 模块级 logger：`logger = logging.getLogger(__name__)`
- `from __future__ import annotations`

**Test scenarios:**
- Happy: 创建 User 实例，字段赋值正确
- Happy: hash_password → verify_password 匹配成功
- Happy: hash_password → verify_password 不匹配返回 False
- Happy: create_access_token 包含 sub(username) + exp，decode 后恢复
- Happy: create_refresh_token 包含 sub + exp(7d)
- Edge: decode 过期 token 抛出 401
- Edge: decode 无效 token 抛出 401
- Edge: 重复注册相同 username 触发 IntegrityError

**Verification:** `uv run pytest tests/test_auth.py -v` 全部通过

---

### U2. 后端 Auth 路由与依赖注入

**Goal:** 实现 /auth/* 五个端点 + get_current_user 依赖

**Requirements:** R3, R4, R5, R6, R7, R8, R9

**Files:**
- `backend/app/routers/auth.py` — 新建
- `backend/app/routers/__init__.py` — 新增 auth 导入
- `backend/app/core/dependencies.py` — 新建
- `backend/app/core/__init__.py` — 新建
- `backend/app/main.py` — 注册 auth router

**Approach:**
- `routers/auth.py`：5 个端点
  - `POST /auth/register` — 校验 username 唯一 → hash 密码 → 创建 User → 返回 {id, username}
  - `POST /auth/login` — 查 User → verify_password → 生成双 token → Set-Cookie httpOnly (access_token + refresh_token) → 返回 {username}
  - `POST /auth/refresh` — 从 cookie 读 refresh_token → decode → 查 User 仍 active → 生成新 access_token → Set-Cookie
  - `POST /auth/logout` — 清除两个 cookie（max_age=0）
  - `GET /auth/me` — 从 access_token 提取 username → 返回 {id, username, is_active}
- Cookie 参数：`httponly=True`、`samesite="lax"`、`secure=False`（开发）/ True（生产）、`domain` 可选
- `core/dependencies.py`：`get_current_user` async 依赖，从 request cookie 读 access_token → decode → 查 User → 返回 User 或 401
- `main.py`：`app.include_router(auth, prefix="/api")`
- CORS 中间件：`app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_credentials=True, ...)`

**Patterns to follow:**
- 路由沿用 `router = APIRouter(prefix="/auth", tags=["auth"])`
- 错误处理：`HTTPException(status_code=401, detail="...")`
- `from __future__ import annotations`

**Test scenarios:**
- Happy: POST /auth/register 创建用户，返回 201
- Happy: POST /auth/register 重复用户名返回 400
- Happy: POST /auth/login 正确密码返回 200 + Set-Cookie header
- Happy: POST /auth/login 错误密码返回 401
- Happy: GET /auth/me 带有效 cookie 返回用户信息
- Happy: GET /auth/me 不带 cookie 返回 401
- Happy: POST /auth/refresh 有效 refresh_token 返回新 access_token cookie
- Happy: POST /auth/logout 清除 cookie
- Edge: refresh_token 过期 → 401
- Edge: 已注销用户 token → 401

**Verification:** `uv run pytest tests/test_auth_router.py -v` 全部通过

---

### U3. 前端脚手架迁移到 Vue 3

**Goal:** 删除 React 代码，创建 Vue 3 + Vite + TypeScript 基础骨架

**Requirements:** R10, R11, R12

**Files:**
- `frontend/package.json` — 更新依赖（删 react/react-dom，增 vue/vue-router/ant-design-vue/lightweight-charts）
- `frontend/vite.config.ts` — 换 `@vitejs/plugin-vue`
- `frontend/src/main.ts` — 新建 Vue 入口
- `frontend/src/App.vue` — 新建根组件
- `frontend/src/assets/main.css` — 新建全局样式
- `frontend/index.html` — 确认挂载点 id="root"
- 删除：`frontend/src/main.tsx`、`App.tsx`、`api/`、`router/`、`store/`、`pages/` 下所有 React 文件

**Approach:**
- package.json 依赖：`vue`、`vue-router`、`ant-design-vue`、`lightweight-charts`、`axios`（保留），devDep：`@vitejs/plugin-vue`、`@types/node`
- vite.config.ts：plugins 换 `vue()`，proxy 配置不变
- main.ts：`createApp(App).use(router).use(antd).mount('#root')`
- App.vue：`<ConfigProvider locale={zhCN}>` + `<RouterView />`
- 保留 `index.html` 的 `<div id="root"></div>`

**Patterns to follow:**
- `<script setup lang="ts">` 风格
- Ant Design Vue 的 `ConfigProvider` + `zhCN` locale
- Vite proxy 配置沿用现有 `/api → localhost:8000`

**Test scenarios:**
- Happy: `npm run dev` 启动成功，访问 localhost:5173 看到 Vue 挂载
- Happy: 无控制台错误
- Edge: 构建 `npm run build` 通过

**Verification:** `cd frontend && npm run dev` 打开浏览器无报错

---

### U4. 前端 Auth 页面与状态管理

**Goal:** 登录/注册页面 + Axios 拦截器 + 认证状态管理

**Requirements:** R12, R13, R14

**Files:**
- `frontend/src/stores/auth.ts` — 新建
- `frontend/src/api/index.ts` — 新建
- `frontend/src/api/auth.ts` — 新建
- `frontend/src/router/index.ts` — 新建
- `frontend/src/views/Login.vue` — 新建
- `frontend/src/views/Register.vue` — 新建
- `frontend/src/components/PrivateRoute.vue` — 新建

**Approach:**
- `stores/auth.ts`：`reactive({ user: null, token: null })`，`login()` 从 `/auth/me` 恢复用户信息，`logout()` 调 `/auth/logout` 后清空
- `api/index.ts`：Axios 实例 `baseURL: '/api'`，`withCredentials: true`，响应拦截器：401 → 尝试 refresh → 成功重试原请求 → 失败跳 `/login`
- `api/auth.ts`：`login(username, password)`、`register(username, password)`、`getMe()`、`logout()`、`refreshToken()`
- `router/index.ts`：routes — `/login`、`/register`（公开），`/`、`/dashboard`、`/etf`（需 auth）
- `PrivateRoute.vue`：检查 auth store 有无 user，无则 `<navigate to="/login" replace>`
- `Login.vue`：Ant Design Vue 的 `<a-form>` + `<a-input>` + `<a-button>`，onFinish 调 `login()` → store.login() → navigate `/dashboard`
- `Register.vue`：同结构，onFinish 调 `register()` → 成功跳 `/login`

**Patterns to follow:**
- Ant Design Vue 组件：`a-form`、`a-form-item`、`a-input`、`a-button`、`a-card`、`a-message`
- `useRouter()`、`useRoute()` 来自 `vue-router`
- `reactive()` 做状态管理，小项目不用 Pinia

**Test scenarios:**
- Happy: 打开 /login 看到登录表单
- Happy: 输入正确凭据 → 登录成功 → 跳 /dashboard
- Happy: 输入错误密码 → a-message 显示错误
- Happy: /dashboard 未登录 → 自动跳 /login
- Edge: 注册重复用户名 → 后端返回 400 → 前端显示错误

**Verification:** 登录/注册流程端到端跑通

---

### U5. 市场状态仪表盘（Market Regime Dashboard）

**Goal:** K 线图 + 市场状态背景着色 + 波动方向标注

**Requirements:** R15, R16, R17

**Files:**
- `frontend/src/components/KlineChart.vue` — 新建
- `frontend/src/views/Dashboard.vue` — 新建
- `frontend/src/api/marketRegime.ts` — 新建

**Approach:**
- `api/marketRegime.ts`：`getStates(market)` 调 `/api/market_regime/states/{market}`，`getIndexKlines(indexCode)` 调 `/api/data/index/{code}/daily`
- `KlineChart.vue`：接收 `klines`（OHLCV 数组）和 `regimeBands`（{from, to, state} 数组），用 Lightweight Charts v5 的 `add candlestick series` + `addBand`（背景色带）
  - state=平静 → 浅绿背景，state=动荡 → 浅红背景
  - 波动方向：在对应 K 线上方加 `addMark`（向上箭头 / 向下箭头）
- `Dashboard.vue`：顶部两个 tab（A股 / 港股），默认 A股
  - onMounted：并行请求 states + 上证综指 klines
  - 数据对齐：按 trade_date merge states 和 klines
  - 传给 KlineChart 渲染
  - 顶部显示摘要卡片：当前状态、状态概率、最近切换日期

**Technical design:**

```
KlineChart.vue props:
  - klines: Array<{time, open, high, low, close, volume}>
  - bands: Array<{from: time, to: time, state: number, color: string}>

内部逻辑:
  const chart = createChart(container, { width, height, layout: { background: {color: '#fff'} } })
  const candleSeries = chart.addCandlestickSeries()
  candleSeries.setData(klines)
  bands.forEach(b => chart.addBand({ from: b.from, to: b.to, color: b.color }))
  klines 中涨日 → addMark({ time, position: 'aboveBar', shape: 'arrowUp' })
  klines 中跌日 → addMark({ time, position: 'belowBar', shape: 'arrowDown' })
```

**Patterns to follow:**
- Lightweight Charts v5 官方 API（`createChart`、`addCandlestickSeries`、`addBand`、`addMark`）
- `onMounted` + `ref<HTMLDivElement>` 挂载图表
- `onUnmounted` 调用 `chart.remove()` 防内存泄漏
- `watch` + `ResizeObserver` 响应容器大小变化

**Test scenarios:**
- Happy: 加载 Dashboard → 看到 K 线图 + 背景色带
- Happy: 切换 A股/港股 tab → 图表更新
- Happy: 窗口 resize → 图表自适应
- Edge: states 数据缺失某日 → 图表空白该段，不崩溃
- Edge: klines 为空 → 显示"暂无数据"

**Verification:** 打开 /dashboard 能看到上证综指 K 线图，背景按市场状态着色

---

### U6. ETF 数据展示页

**Goal:** ETF 列表 + 点击展开 K 线图

**Requirements:** R18, R19

**Files:**
- `frontend/src/api/etf.ts` — 新建
- `frontend/src/views/EtfView.vue` — 新建

**Approach:**
- `api/etf.ts`：`getEtfList()` 调 `/api/data/etfs`，`getEtfKlines(etfCode)` 调 `/api/data/etf/{code}/daily`
- `EtfView.vue`：
  - 顶部 `<a-table>` 列出所有 ETF（code, name, tracks_index, latest_close, change_pct）
  - 可排序列、可搜索
  - 点击行展开 `<a-table-expand>`，内部放一个 KlineChart 组件展示该 ETF 近期 K 线
  - 用 `<a-spin>` 做加载状态

**Patterns to follow:**
- Ant Design Vue Table：`:columns`、`:dataSource`、`:loading`、`#expandedRowRender`
- 复用 U5 的 KlineChart 组件
- `ref<ExpandedRow>` 控制展开/收起

**Test scenarios:**
- Happy: 打开 /etf 看到 ETF 表格
- Happy: 点击行展开 → 看到 K 线图
- Happy: 搜索 ETF 名称 → 表格过滤
- Edge: ETF 无 kline 数据 → 展开区显示"暂无数据"

**Verification:** 打开 /etf 能看到 ETF 列表，点击任意 ETF 展开看 K 线

---

### U7. 后端市场状态 API 适配前端

**Goal:** 确保 `/market_regime/states/{market}` 返回的数据格式前端能直接消费

**Requirements:** R15

**Files:**
- `backend/app/routers/market_regime.py` — 修改

**Approach:**
- 检查现有 `GET /market_regime/states/{market}` 返回格式
- 确保返回包含：`trade_date`、`state_label`、`state_prob`
- 如需补充指数日线数据：确认 `/api/data/index/{code}/daily?limit=120` 端点存在且可返回上证综指日线
- 数据对齐由前端按 trade_date 做，后端不做 join

**Patterns to follow:**
- 沿用现有路由的返回格式
- 不新增端点，只确认/微调现有端点

**Test scenarios:**
- Happy: GET /api/market_regime/states/A 返回 [{trade_date, state_label, state_prob}, ...]
- Happy: GET /api/data/index/000001/daily?limit=120 返回日线数据

**Verification:** 前端 Dashboard 能拿到两个接口数据并渲染

---

## Dependencies and Sequencing

```
U1 (User model + security) → U2 (auth router) → U4 (frontend auth pages)
U1 + U2 → U7 (API 适配)
U4 → U5 (Dashboard)
U5 → U6 (ETF page, reuses KlineChart)
```

并行窗口：U3（前端脚手架）可与 U1+U2（后端 auth）并行，互不依赖。

---

## Risks & Dependencies

- **后端已有 requirements.txt 中的 auth 依赖**：`python-jose[cryptography]`、`passlib[bcrypt]`、`bcrypt` 已在 legacy requirements.txt 中，但 `pyproject.toml` 中可能缺失。U1 需确认并补充。
- **Ant Design Vue 组件 API 与 React 版不同**：Login/Register 需按 Vue 版 API 重写，不能复用现有 React 组件。
- **Lightweight Charts v5 版本**：需确认最新稳定版 API，`addBand` 是 v5 新增特性。

---

## Sources & Research

- 技术选型参考：`D:\ac_base\B专业技能\2.3.金融工程\量化交易平台UI技术选型.md`（Lightweight Charts v5 + 轻量前端 + Python 后端）
- 后端模式参考：现有 `backend/app/routers/market_regime.py`（路由结构）、`backend/app/models/stock.py`（模型定义）
- 前端模式参考：现有 `frontend/src/api/auth.ts`（API 调用模式，需转为 Vue 版）
