---
title: "feat: A股多指数融合状态识别 — 等权特征拼接 + 单 HMM 统一输出"
type: feat
status: in_progress
date: 2026-07-03
origin: docs/brainstorms/2026-07-03-multi-index-regime-requirements.md
project: binwh.QuantPilot
module: market_regime
depth: standard
---

## Summary

将 A 股 market_regime pipeline 的特征来源从单一沪深300（000300）扩展为 8 个核心指数联合特征（上证综指/深证成指/创业板指/科创50/沪深300/上证50/中证500/中证1000），保持输出为一个统一状态序列，API 不变。评估阶段额外输出各指数贡献度分解。

---

## Problem Frame

现有 `market_regime` 模块对 A 股的状态识别仅基于沪深300单一指数（`backend/app/services/market_regime/config.py:16`）。沪深300覆盖大盘蓝筹，但无法反映中证500（中盘）、创业板指（成长）、上证综指（全市场）等板块的状态差异。当板块分化明显时，单一指数输出可能失真。

目标：多指数特征融合 → 统一的 A 股市场状态输出，保持现有 API 不变。

---

## Requirements

- R1. 特征工程读取多个 A 股指数日线数据，每个指数独立构造收益率和波动率特征，特征名带指数前缀
- R2. 多指数特征按交易日对齐、统一 expanding 标准化，短数据指数自动剔除
- R3. A 股仍输出一个状态序列，API 不变
- R4. 配置驱动（`A_INDICES`），可增删指数
- R5. 港股 pipeline 不变，向后兼容
- R6. 评估阶段输出各指数贡献度分解（写入 metrics，API 不变）

---

## Scope Boundaries

### 本计划包含

- `config.py` 新增 `A_INDICES` 配置列表
- `features.py` 支持多指数特征构造 + 指数间相对强弱特征
- `evaluation.py` 增加指数贡献度分解（逻辑回归系数分组汇总）
- 测试覆盖多指数特征、对齐、缺失处理、贡献度计算
- API 不变

### Deferred to Follow-Up Work

- 每个指数独立输出状态（板块轮动/分化分析）
- 指数权重学习（等权 → 学习权重）
- 港股多指数扩展

### Outside this product's identity

- 个股级别状态识别
- 实时/日内状态更新

---

## Key Technical Decisions

- **KTD1. 等权拼接 + 单 HMM。**
  Why: 最简单可解释。所有指数收益率/波动率拼接成宽特征矩阵，HMM 在联合空间发现共同状态。PCA 自动处理量级差异。
  How: `build_feature_matrix` 读取 `A_INDICES` 列表，每个指数构造特征后 concat，统一 expanding 标准化。

- **KTD2. primary 保留用于人工对照，不再是唯一特征来源。**
  Why: 人工对照需要一条主序列，沪深300最成熟。特征空间现在是多指数的。
  How: `primary="000300"` 保留在 config 中，用于 evaluation 的状态-价格叠加。

- **KTD3. 指数数据缺失处理：自动剔除 + warning。**
  Why: 科创50仅 ~4 年数据，与沪深300的 10+ 年不匹配。强行对齐会砍掉大量历史。
  How: 沿用现有 `dropna` 逻辑，短数据列自动剔除。

- **KTD4. 评估阶段增加指数贡献度分解。**
  Why: 虽然输出是统一状态，但知道哪个指数在驱动判断对人工对照有价值。
  How: 用逻辑回归系数绝对值之和作为每个特征的贡献度，按指数分组汇总，写入 metrics JSON。

---

## Implementation Units

### U1. config.py 新增 A_INDICES 配置

- **Goal:** 定义 A 股 8 个核心指数列表，驱动多指数特征工程。
- **Requirements:** R4
- **Dependencies:** 无
- **Files:**
  - `backend/app/services/market_regime/config.py` (改)
- **Approach:**
  - 新增 `A_INDICES` 列表，包含 000001/399001/399006/000688/000300/000016/000905/000852
  - 保留现有 `A_CONFIG` 的 `primary`/`macro`/`spread_pairs`，`primary` 仍为 `"000300"`
  - `MARKET_CONFIGS` 结构不变，HK 端不动
- **Patterns to follow:** 现有 `CORE_INDICES` 的列表风格（`universe.py:21-35`）
- **Test scenarios:**
  - Happy: `A_INDICES` 包含 8 个指数代码
  - Edge: 列表为空时 pipeline 有明确错误提示
- **Verification:** 配置可导入，列表内容正确。

---

### U2. features.py 支持多指数特征构造

- **Goal:** 从 8 个指数读取日线，构造带指数前缀的特征矩阵，支持指数间相对强弱特征。
- **Requirements:** R1, R2
- **Dependencies:** U1
- **Files:**
  - `backend/app/services/market_regime/features.py` (改)
  - `backend/tests/test_features.py` (改/扩)
- **Approach:**
  - 重构 `build_feature_matrix`：读取 `A_INDICES` 列表，每个指数独立构造 `multi_period_returns` + `realized_volatility`，特征名加指数前缀（`ret_5d_000300`、`realvol_21d_000905`）
  - 主标的（`primary="000300"`）的特征仍保留，但不独占
  - 新增指数间相对强弱特征：取两个主要宽基（如 000300 vs 000905）的同期收益率差 `ret_5d_spread_000300_000905`，捕捉大小盘分化
  - 所有特征按 primary 交易日对齐、ffill 填充
  - expanding 标准化统一执行
  - 短数据列（有效样本 < 50%）自动剔除并 warning
- **Patterns to follow:** 现有 `build_raw_features` 的特征构造逻辑；`universe.py` 的 `CORE_INDICES` 列表风格
- **Test scenarios:**
  - Happy: 给定 2 个合成指数日线，产出带前缀的特征矩阵，列名符合约定
  - Happy(相对强弱): 两个指数的收益率差特征正确计算
  - Edge(防泄漏): expanding 均值/方差不含未来信息（复用现有断言）
  - Edge: 某指数数据起始晚 → 该指数特征列被自动剔除，warning 记录
  - Edge: warmup 期行被正确丢弃
  - Integration: 从真实 `index_daily_klines` 读 8 个指数，产出非空宽特征矩阵
- **Verification:** 特征矩阵列名带指数前缀、无泄漏、短数据自动处理、相对强弱特征正确。

---

### U3. evaluation.py 增加指数贡献度分解

- **Goal:** 在评估报告中输出各指数对当前状态判断的贡献度。
- **Requirements:** R6
- **Dependencies:** U2
- **Files:**
  - `backend/app/services/market_regime/evaluation.py` (改)
  - `backend/tests/test_evaluation.py` (改/扩)
- **Approach:**
  - 利用逻辑回归的系数（`clf_res.coef_`），计算每个特征的绝对系数作为贡献度
  - 按指数前缀分组汇总（如 `ret_5d_000300`、`realvol_21d_000300` 归到 `000300`）
  - 输出 `index_contributions: dict[str, float]`（指数代码 → 贡献度），写入 metrics JSON
  - 不改变 `EvaluationReport` 的核心字段，只扩展示外数据
- **Patterns to follow:** 现有 `evaluate()` 返回 `EvaluationReport` + metrics dict 的模式
- **Test scenarios:**
  - Happy: 给定已知系数，贡献度按指数分组正确汇总
  - Edge: 某指数无特征入选 → 贡献度为 0，不报错
  - Edge: 所有系数为 0 → 返回空 dict
- **Verification:** 贡献度字典键为指数代码、值为归一化贡献度、写入 metrics。

---

### U4. 端到端验证 + API 回归测试

- **Goal:** 确保多指数 pipeline 跑通、API 不变、HK 不受影响。
- **Requirements:** R3, R5
- **Dependencies:** U2, U3
- **Files:**
  - `backend/app/services/market_regime/pipeline.py` (验证，基本不改)
  - `backend/tests/test_pipeline.py` (扩)
  - `backend/app/routers/market_regime.py` (验证，不改)
- **Approach:**
  - `pipeline.py` 的 `run_pipeline` 不需要改——它调用 `build_feature_matrix(market)`，A 股端自动走多指数路径
  - 验证 `POST /api/market_regime/train?market=A` 跑通，产出 run + states
  - 验证 `GET /api/market_regime/states/A` 返回结构不变（`market`/`run_id`/`states`/`metrics` + `index_contributions`）
  - 验证 HK pipeline 仍基于 HSI 单指数，不受影响
  - 验证 `run_all_markets` 两市场独立运行
- **Patterns to follow:** 现有 `test_pipeline.py` 的 mock 源 + 内存库模式
- **Test scenarios:**
  - Happy: A 股 pipeline 端到端跑通，产出 run + states + index_contributions
  - Happy: HK pipeline 跑通，输出与 A 股独立
  - Integration: `POST /market_regime/train?market=A` 后台任务完成，`GET /market_regime/states/A` 返回含 `index_contributions` 的响应
  - Edge: 某指数数据缺失 → pipeline 仍跑通（用剩余指数）
  - Error: HK 数据不足 → A 股不受影响
- **Verification:** A 股端到端跑通、HK 不受影响、API 响应结构兼容。

---

## Risks & Dependencies

- **风险:特征维度膨胀（8 指数 × 约 5 特征 = 40+ 列）。** Mitigation: PCA 自动降维到设定方差比例（默认 95%），实际主成分通常 5-10 维。
- **风险:短数据指数（科创50仅 4 年）拖累 expanding 统计。** Mitigation: U2 的 50% 阈值自动剔除，不影响长数据指数。
- **风险:指数间量级差异导致某些特征主导。** Mitigation: expanding 标准化统一执行，PCA 消除量级差异。
- **风险:逻辑回归系数解释性随特征增加而下降。** Mitigation: 贡献度按指数分组汇总，提供聚合视图而非单特征解释。

---

## Open Questions

- 指数间相对强弱特征是否需要更多配对（如 000300/399006 大盘/成长、000016/000852 超大盘/小盘）？—— 当前先做 1 对（000300/000905 大盘/中盘），效果不佳再加。
- 指数贡献度是否需要在 API 响应中独立字段暴露？—— 当前嵌入 metrics，后续若前端需要再暴露。

---

## Sources & Research

- 需求文档: `docs/brainstorms/2026-07-03-multi-index-regime-requirements.md`
- 现有 plan: `docs/plans/2026-06-22-001-feat-market-regime-ml-pipeline-plan.md`
- 数据现状: `backend/app/services/data/universe.py` (CORE_INDICES 已定义 8 个 A 股指数)
- 特征工程: `backend/app/services/market_regime/features.py` (build_feature_matrix 当前只读 single primary)
- 配置: `backend/app/services/market_regime/config.py` (A_CONFIG 当前只有 primary + macro + spread_pairs)
- 评估: `backend/app/services/market_regime/evaluation.py` (EvaluationReport + metrics dict)
