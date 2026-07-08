# Brainstorm: A股多指数融合状态识别

**Date:** 2026-07-03
**Status:** Draft
**Origin:** Extends `docs/plans/2026-06-22-001-feat-market-regime-ml-pipeline-plan.md` (completed)

---

## Problem Frame

现有 `market_regime` 模块对 A 股的状态识别仅基于**沪深300（000300）**单一指数。沪深300覆盖大盘蓝筹，但无法反映中证500（中盘）、创业板指（成长）、上证综指（全市场）等板块的状态差异。当板块分化明显时（如大盘稳、小盘跌），单一指数输出可能失真。

目标：**多指数特征融合 → 统一的 A 股市场状态输出**，保持现有 API 不变（`GET /market_regime/states/A` 仍返回一个状态序列），但底层特征从「单指数」扩展为「多指数联合」。

---

## Requirements

### R1. 多指数特征输入

- 特征工程阶段读取多个 A 股指数的日线数据，参与构造特征矩阵。
- 默认覆盖：上证综指（000001）、深证成指（399001）、创业板指（399006）、科创50（000688）、沪深300（000300）、上证50（000016）、中证500（000905）、中证1000（000852）。
- 每个指数独立构造多周期收益率和实现波动率特征，特征名带指数前缀（如 `ret_5d_000300`、`realvol_21d_399006`），避免列名冲突。
- 宏观代理（国债/汇率）和进攻-防御价差代理保持不变。

### R2. 统一特征矩阵 + expanding 标准化

- 所有指数的特征按交易日对齐（以主指数交易日为基准，其余指数 ffill 填充）。
- expanding 标准化对所有特征列统一执行（不区分指数），保持防泄漏不变。
- 某指数数据起始较晚（如科创50只有1564行）→ 该指数特征在有效样本不足时自动剔除（沿用现有 `dropna(axis=1, thresh=50%)` 逻辑）。

### R3. 单市场单状态输出

- A 股仍输出**一个状态序列**（`market="A"`），不是每个指数一个状态。
- 评估阶段可额外输出每个指数对当前状态的贡献度（特征重要性或状态概率分解），但这是可选增强，不是核心输出。
- API 不变：`GET /market_regime/states/A` 返回结构不变。

### R4. 配置驱动，可扩展

- 新增 `A_INDICES` 配置列表，默认包含上述 8 个指数。
- 可通过配置增删指数（如未来加入行业指数），无需改代码。
- 配置缺失或某指数无数据时，自动跳过并记录 warning，不影响其他指数。

### R5. 向后兼容

- 港股（HK）pipeline 不变，仍基于 HSI。
- 现有 `A_CONFIG` 的 `primary`/`macro`/`spread_pairs` 保留，`primary` 仍用于人工对照叠加，但不再是唯一的特征来源。

---

## Scope Boundaries

### 本迭代包含

- `features.py` 支持多指数特征构造
- `config.py` 新增 `A_INDICES` 配置
- pipeline 适配多指数输入（A 股端）
- 测试覆盖多指数特征构造、对齐、缺失处理
- 评估输出可选的指数贡献度分解

### Deferred to Follow-Up Work

- 每个指数独立输出状态（板块轮动/分化分析）—— 当前需求是统一状态，独立状态是下一步。
- 指数权重学习（如给沪深300更高权重）—— 当前等权融合，后续可加学习机制。
- 港股多指数扩展（目前港股只有 HSI + HSTECH，数据也较少）。

### Outside this product's identity

- 个股级别状态识别（个股只参与配置端，不参与状态识别）。
- 实时/日内状态更新（当前是日度）。

---

## Key Technical Decisions

- **KTD1. 特征融合方式：等权拼接 → 单 HMM。**
  Why: 最简单、最可解释。把所有指数的收益率/波动率拼接成宽特征矩阵，HMM 在联合空间中发现共同状态。不需要先各自预测再融合——那样会丢失跨指数相关性信号。
  How: `build_feature_matrix` 读取 `A_INDICES` 列表，每个指数构造特征后 concat 成 wide matrix，统一 expanding 标准化。

- **KTD2. primary 保留用于人工对照，不再是唯一特征来源。**
  Why: 人工对照（叠加价格图）需要一条主序列，沪深300是最成熟的宽基。但特征空间现在是多指数的。
  How: `primary="000300"` 保留在 config 中，用于 `evaluation.py` 的状态-价格叠加输出；特征构造不再依赖它独占。

- **KTD3. 指数数据缺失处理：自动剔除 + warning。**
  Why: 科创50（000688）只有 ~4 年数据，与沪深300的 10+ 年不匹配。强行对齐会导致 expanding warmup 砍掉大量历史。
  How: 沿用现有 `dropna(axis=1, thresh=50%)` 逻辑，但阈值改为按绝对交易日数（如最少 1000 行），避免短数据列拖累长数据指数。

- **KTD4. 评估阶段增加指数贡献度分解（可选）。**
  Why: 虽然输出是统一状态，但知道「哪个指数在驱动当前状态判断」对人工对照和后续板块分析有价值。
  How: 用逻辑回归系数绝对值之和作为每个特征的贡献度，按指数分组汇总。输出到 metrics JSON，不影响核心状态序列。

---

## Open Questions

- 上证综指（000001）和深证成指（399001）是等权还是有隐含优先级？（建议：等权，后续看效果再调）
- 指数贡献度分解是否需要在 API 响应中暴露，还是只写入评估 metrics？（建议：先写 metrics，API 不改）

---

## Sources & Research

- 现有 plan: `docs/plans/2026-06-22-001-feat-market-regime-ml-pipeline-plan.md`
- 数据现状: `backend/app/services/data/universe.py` (CORE_INDICES 已定义 8 个 A 股指数)
- 特征工程: `backend/app/services/market_regime/features.py` (build_feature_matrix 当前只读 single primary)
- 配置: `backend/app/services/market_regime/config.py` (A_CONFIG 当前只有 primary + macro + spread_pairs)
