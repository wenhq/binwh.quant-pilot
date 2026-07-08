---
title: "feat: 量化分析系统 MVP 基础框架"
type: feat
status: completed
date: 2026-06-05
origin: null
---

## Summary

搭建量化分析系统的 MVP 基础框架：FastAPI 后端（用户认证、MySQL 连接层、API 路由骨架）+ Vite + React + Ant Design 前端（空白项目可运行），包含用户名密码登录（BCrypt 加密）和基础项目结构，后续 Phase 在此框架上叠加行情/指标/估值/组合/两融功能。

---

## Problem Frame

当前没有任何可运行的前后端基础框架，无法承接后续行情、技术指标、FCFF 估值、资产组合、两融研究等功能模块的开发。必须先搭好骨架，后续功能才能在统一架构下增量交付。

---

## Requirements

- R1. 后端服务启动后可通过 HTTP 访问，返回标准 JSON 响应
- R2. 用户可使用用户名 + 密码注册账号，密码在数据库中以 BCrypt 加密存储
- R3. 用户可使用用户名 + 密码登录，获取有效 JWT Token，后续请求需携带 Token
- R4. 前端空白项目可 `npm run dev` 启动，访问 localhost:5173 返回 Ant Design 基础页面
- R5. 前端登录页可提交用户名密码，登录成功后跳转到首页
- R6. MySQL 数据库表结构通过 SQL 迁移文件管理，版本可控
- R7. 前后端项目均可在本地通过文档步骤启动，无需特殊配置

---

## Key Technical Decisions

- **FastAPI**：异步 Python Web 框架，与 Pandas/TA-Lib 生态无缝集成，类型提示完整，适合量化场景
- **SQLAlchemy 2.0（异步）**：通过 `asyncmy` 驱动连接已有 MySQL，避免同步阻塞；ORM 模式管理表结构
- **JWT (PyJWT) + python-jose**：登录后签发 access_token，Token 有效期 24 小时，前端存入 localStorage
- **BCrypt (passlib[bcrypt])**：密码哈希，数据库存摘要不存明文
- **Vite + React 18 + Ant Design 5**：前端开发体验好，热更新快，Ant Design 企业级组件库成熟
- **Axios**：前端 HTTP 客户端，统一封装 request/response 拦截器（自动附加 Token）
- **前后端分离 SPA**：后端 8000 端口提供 REST API，前端 5173 端口 Vite 开发服务器，Vite proxy 代理 `/api` 到后端
- **PyJWT Token 存续策略**：Refresh Token 不做，MVP 仅 access_token，失效后重新登录

---

## Assumptions

- MySQL 已在本地/服务器运行，可提供连接地址、端口、用户名、密码、库名
- 前端开发者（用户）有 Node.js 18+ 和 Python 3.11+ 环境
- 微信扫码登录后续集成，届时前端登录页替换为微信扫码组件即可，登录后接口兼容

---

## Implementation Units

### U1. 后端项目骨架搭建

**Goal：** 创建可运行的 FastAPI 项目结构，包含配置文件、环境变量、依赖管理、MySQL 连接测试。

**Requirements：** R1, R7

**Files：**

```
backend/
├── requirements.txt
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # 配置加载（pydantic-settings）
│   ├── database.py          # MySQL 异步连接引擎
│   ├── dependencies.py      # 公共依赖（如 get_db）
│   └── routers/
│       ├── __init__.py
│       └── health.py        # 健康检查路由
└── tests/
    └── test_health.py
```

**Approach：** 使用 pydantic-settings 加载 .env 环境变量；SQLAlchemy 2.0 异步引擎连接 MySQL（URL 格式 `mysql+asyncmy://user:pass@host:3306/db`）；启动命令 `uvicorn app.main:app --reload --port 8000`。

**Patterns to follow：** FastAPI 官方项目结构（app/routers 分离）；pydantic-settings 最佳实践。

**Test Scenarios：** 应用启动后 GET /api/health 返回 `{"status": "ok"}`；MySQL 连接失败时启动报错提示清晰。

---

### U2. 用户认证：数据模型与数据库迁移

**Goal：** 创建 users 表，通过 Alembic 迁移文件管理，支持用户注册和登录查询。

**Requirements：** R2, R6

**Files：**

```
backend/app/models/
├── __init__.py
└── user.py              # SQLAlchemy User 模型

backend/app/schemas/
├── __init__.py
└── user.py              # Pydantic 请求/响应 schema

backend/alembic/
├── env.py
├── script.py.mako
└── versions/
    └── 001_create_users.py  # 初始迁移

backend/tests/
└── test_user_model.py
```

**Approach：** User 模型字段：`id`(自增 PK)、`username`(唯一)、`email`(唯一，可选)、`hashed_password`(BCrypt摘要)、`created_at`、`is_active`(默认True)。使用 passlib[bcrypt] 生成和校验摘要。Alembic 管理迁移，迁移文件纳入版本控制。

**Test Scenarios：** 用户注册后数据库中密码为 BCrypt 摘要，非明文；相同用户名重复注册返回 409 冲突；用户名不存在时登录返回 401。

---

### U3. 用户认证：注册与登录接口

**Goal：** 提供 POST /api/auth/register 和 POST /api/auth/login 两个接口，登录成功返回 JWT。

**Requirements：** R2, R3

**Files：**

```
backend/app/routers/
├── __init__.py
├── auth.py              # 注册/登录路由
└── user.py              # 当前用户信息查询路由

backend/app/core/
├── __init__.py
├── security.py          # 密码校验、JWT 签发/验证
└── jwt.py               # JWT 配置常量
```

**Approach：** register：接收 username/password，校验 username 不重复，BCrypt 哈希密码，存入 DB，返回用户信息（不含密码）。login：接收 username/password，查询用户，BCrypt 校验，校验通过则签发 JWT（claims 含 user_id 和 username），返回 access_token。JWT secret 和算法配置在 .env 中。

**Test Scenarios：** 正确凭据登录返回 200 和含 access_token 的 JSON；密码错误返回 401；注册后 login 可正常登录；Token 伪造或过期返回 401。

---

### U4. 前端项目骨架搭建

**Goal：** 创建可 `npm run dev` 运行的 Vite + React + Ant Design 空白项目。

**Requirements：** R4, R7

**Files：**

```
frontend/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── .env.development
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── api/
    │   ├── index.ts       # Axios 实例，拦截器
    │   └── auth.ts        # 登录/注册接口调用
    ├── pages/
    │   ├── Login.tsx
    │   └── Home.tsx
    ├── components/
    │   └── Layout.tsx
    └── router/
        └── index.tsx      # React Router 配置
```

**Approach：** 使用 `npm create vite@latest` 初始化，选择 React + TypeScript 模板；安装 antd、axios、react-router-dom；Vite dev server 监听 5173，proxy `/api` 请求到后端 8000；登录页使用 Ant Design Form + Input + Button。

**Test Scenarios：** `npm install && npm run dev` 无报错启动；访问 localhost:5173 显示 Ant Design Button；开发控制台无非预期错误。

---

### U5. 前端登录与认证流程

**Goal：** 登录页提交用户名密码，成功后跳转到 Home 页；请求头自动附加 Authorization Token。

**Requirements：** R3, R5

**Files：**（在 U4 目录结构上增加）

```
frontend/src/
├── api/
│   └── auth.ts            # 登录/注册 API 调用
├── pages/
│   ├── Login.tsx          # 登录表单
│   ├── Register.tsx       # 注册表单
│   └── Home.tsx           # 登录后首页
├── router/
│   └── index.tsx           # 路由守卫：未登录重定向到 /login
└── store/
    └── auth.ts            # 用户登录状态（简单 context 或 zustand）
```

**Approach：** Axios 拦截器：请求自动在 headers 添加 `Authorization: Bearer <token>`；401 响应时清除 Token 并跳转登录页。Token 存 localStorage，页面刷新后从 localStorage 恢复登录态。

**Test Scenarios：** 输入错误密码点击登录，提示"用户名或密码错误"；正确登录后跳转 / 并在页面显示用户名；刷新页面保持登录态；点击退出登录清除 Token 并跳转 /login。

---

### U6. API 受保护路由与依赖注入

**Goal：** 将认证 Token 校验封装为 FastAPI 依赖，保护需要登录的 API；演示一个受保护接口（如获取当前用户信息）。

**Requirements：** R3

**Files：**（扩展 U3）

```
backend/app/dependencies.py    # 新增 get_current_user 依赖
backend/app/routers/user.py  # 扩展：GET /api/users/me 受保护
```

**Approach：** `get_current_user` 依赖：读取 Authorization Header，验证 JWT，查询数据库返回当前用户对象；注入到需要认证的路由参数中。受保护路由 `/api/users/me` 返回当前登录用户的 username/email/created_at。

**Test Scenarios：** 请求不带 Token 访问 /api/users/me 返回 401；带有效 Token 返回用户信息；带伪造 Token 返回 401。

---

## Scope Boundaries

### Deferred for later

- 所有行情数据采集、K线多周期存储、历史数据补录
- 技术指标计算（MA、MACD、RSI、布林带等）
- 研究报告抓取（东方财富、同花顺等）
- FCFF 估值模型
- 资产组合管理
- 两融数据分析
- 微信扫码登录集成

### Outside this product's identity

- 交易下单、实盘对接（无计划）
- 非 A 股数据（港股、美股初期不在范围）
- 移动端 App

---

## Open Questions

- Q1. MySQL 连接信息（host/port/dbname/用户名/密码）：请在 .env 中配置后告知，我将在 U1 完成后验证连接
- Q2. 是否需要 Git 初始化和 .gitignore？当前工作目录为 `D:\ac_base`，涉及多个子项目，建议 backend 和 frontend 各自初始化 git 还是共享一个仓库？默认各自分离，但可统一在 `D:\ac_base\4项目实践\量化分析系统\` 下管理

---

## System-Wide Impact

- 新增 `backend/` 和 `frontend/` 两个子目录，放在 `D:\ac_base\4项目实践\` 下
- MySQL 中新建 `quant_user` 表（如库中已有 users 表名冲突需重命名）
- 前端 API 请求通过 Vite 代理打到后端，避免跨域
- JWT secret 需在 .env 中配置，不得提交到 Git