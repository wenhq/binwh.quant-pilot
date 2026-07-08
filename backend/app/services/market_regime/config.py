"""market_regime ML — 两市场标的/代理配置.

方案 B (见 origin req): A股 / 港股各自独立建模, 特征空间不对称.
- A股受国内信用/政策周期主导 → 国债 + 汇率 + 行业 ETF 价差
- 港股受美元流动性/南向资金影响 → 美债 10Y 代理离岸流动性

每个市场定义:
- primary: 状态识别的主价格序列 (状态切片叠加其上做人工对照)
- macro:   宏观代理 (一阶差分作特征)
- spread_pairs: 进攻 − 防御 价差代理 (对数价差变化作特征, KTD5)
"""
from __future__ import annotations

# A 股: 多指数融合状态识别
A_INDICES: list[dict] = [
    {"code": "000001", "name": "上证综指"},
    {"code": "399001", "name": "深证成指"},
    {"code": "399006", "name": "创业板指"},
    {"code": "000688", "name": "科创50"},
    {"code": "000300", "name": "沪深300"},
    {"code": "000016", "name": "上证50"},
    {"code": "000905", "name": "中证500"},
    {"code": "000852", "name": "中证1000"},
]

A_COMPOSITE: dict = {
    "primary": "composite",
    "components": [
        {"code": "000001", "name": "上证综指", "weight": 0.5},
        {"code": "399001", "name": "深证成指", "weight": 0.5},
    ],
}

A_CONFIG: dict = {
    "primary": "composite",
    "composite": A_COMPOSITE["components"],
    "indices": A_INDICES,
    "macro": {
        "CN10Y": "中国10年国债收益率 (信用/利率周期)",
        "USDCNY": "美元兑人民币 (汇率压力)",
    },
    "spread_pairs": [
        ("512480", "510880"),
    ],
}

# 港股: 恒生指数为状态识别对象
HK_CONFIG: dict = {
    "primary": "HSI",  # 恒生指数
    "macro": {
        "US10Y": "美国10年国债收益率 (离岸美元流动性)",
    },
    "spread_pairs": [
        ("HSTECH", "HSI"),  # 恒生科技 − 恒生指数 (成长 vs 宽基相对强弱)
    ],
}

MARKET_CONFIGS: dict[str, dict] = {"A": A_CONFIG, "HK": HK_CONFIG}

__all__ = ["A_CONFIG", "HK_CONFIG", "MARKET_CONFIGS"]
