# 前端设计文档

> Vue 3 + TypeScript + Vite + Ant Design Vue 4 + Lightweight Charts v5

源码目录：`frontend/src/`

## 技术栈选型

| 层 | 技术 | 说明 |
|---|---|---|
| 框架 | Vue 3（Composition API + `<script setup>`） | |
| 构建 | Vite 5（端口 5173，代理 `/api` → `localhost:8000`） | |
| 路由 | Vue Router 4（Hash 模式 `#/path`） | 无需后端 catch-all |
| HTTP | Axios（`withCredentials: true`） | 401 自动 refresh |
| UI | Ant Design Vue 4（`ConfigProvider` + zhCN locale） | |
| 图表 | Lightweight Charts v5 | K 线/指标渲染 |

> 选型理由详见 `plans/2026-07-03-002-feat-auth-and-vue3-frontend-plan.md` KTD2~KTD5。

## 目录结构

```
frontend/src/
├── main.ts                # Vue 入口
├── App.vue                # 根组件（ConfigProvider + RouterView + Layout）
├── router/index.ts        # 路由定义
├── stores/auth.ts         # reactive 状态管理（无 Pinia）
├── api/
│   ├── index.ts           # Axios 实例 + 拦截器
│   ├── auth.ts            # auth API
│   ├── etf.ts             # ETF 数据
│   ├── indicators.ts      # 指标数据
│   └── marketRegime.ts    # 市场状态
├── components/
│   ├── KlineChart.vue         # K 线图（带市场状态背景色）
│   ├── IndicatorChart.vue     # K 线 + MACD/RSI/BOLL 多子图
│   └── PrivateRoute.vue       # 路由守卫
└── views/
    ├── Login.vue / Register.vue   # 登录/注册
    ├── Home.vue                    # 侧边栏布局
    ├── Dashboard.vue               # 市场状态仪表盘（A股/港股 tab）
    ├── EtfView.vue                 # ETF 列表 + 展开看 K 线
    └── IndicatorView.vue           # 个股指标查询
```

## 认证流程

- 登录成功 → httpOnly Cookie（access 15min + refresh 7d）
- Axios 拦截器：401 → 单次 refresh 锁 → 重试或跳 `/login`
- 页面刷新 → `GET /auth/me` 恢复会话

详见 `plans/2026-07-03-002-feat-auth-and-vue3-frontend-plan.md` R1~R14。

## 图表（Lightweight Charts v5）

**KlineChart.vue**（`components/KlineChart.vue`）：
- 接收 `klines`（OHLCV）+ `bands`（{from, to, state} 市场状态色带）
- 状态 0 → 绿底，状态 1 → 红底
- `createChart` + `addSeries(CandlestickSeries)` + 背景色直方图叠加

**IndicatorChart.vue**（`components/IndicatorChart.vue`）：
- 主图：K 线 + 成交量 + 可选 BOLL 带叠加
- 子图：MACD（DIF/DEA/HIST）+ RSI（带 30/70 线）
- 由 props `showMACD` / `showRSI` / `showBoll` 控制显示

## 待办

- [ ] K 线图箭头改造：当前是纯涨跌方向标记（冗余），计划替换为模型指标信号
- [ ] Dashboard `console.log` 调试日志清理
- [ ] ETF 列表页和指标页的实际测试
