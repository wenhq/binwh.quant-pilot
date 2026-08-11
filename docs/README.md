# Docs 索引

本目录存放项目设计文档。接手时建议阅读顺序：**数据库 → 后端接口 → 前端设计 → plans（按需）**。

## 核心文档

| 文档 | 内容 |
|---|---|
| [database-design.md](database-design.md) | 数据库表结构、ER 关系、索引设计 |
| [api-design.md](api-design.md) | 后端 RESTful 接口清单（auth/data/indicators/market_regime） |
| [frontend-design.md](frontend-design.md) | 前端架构、目录结构、认证流程、图表组件 |

## 功能方案（按日期倒序）

每个方案含需求分析 + 技术决策 + 实现单元 + 验证标准。

| 日期 | 文档 | 主题 |
|---|---|---|
| 2026-07-03 | [002-feat-auth-and-vue3-frontend-plan.md](plans/2026-07-03-002-feat-auth-and-vue3-frontend-plan.md) | JWT 认证 + Vue 3 前端迁移 + Lightweight Charts |
| 2026-07-03 | [001-feat-multi-index-regime-plan.md](plans/2026-07-03-001-feat-multi-index-regime-plan.md) | 多指数市场状态识别 |
| 2026-06-22 | [001-feat-market-regime-ml-pipeline-plan.md](plans/2026-06-22-001-feat-market-regime-ml-pipeline-plan.md) | 市场状态 ML 管线 |
| 2026-06-21 | [002-feat-market-regime-data-layer-plan.md](plans/2026-06-21-002-feat-market-regime-data-layer-plan.md) | 市场状态数据层 |
| 2026-06-21 | [001-feat-market-regime-req.md](plans/2026-06-21-001-feat-market-regime-req.md) | 市场状态需求 |
| 2026-06-09 | [001-feat-quantpilot-platform-plan.md](plans/2026-06-09-001-feat-quantpilot-platform-plan.md) | QuantPilot 平台总体方案 |
| 2026-06-05 | [001-feat-quant-mvp-skeleton-plan.md](plans/2026-06-05-001-feat-quant-mvp-skeleton-plan.md) | 量化 MVP 骨架 |

## 头脑风暴

| 日期 | 文档 | 主题 |
|---|---|---|
| 2026-07-03 | [multi-index-regime-requirements.md](brainstorms/2026-07-03-multi-index-regime-requirements.md) | 多指数市场状态需求头脑 |
