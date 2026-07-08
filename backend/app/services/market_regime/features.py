"""特征工程 — 从指数/ETF 日线构造无泄漏特征矩阵.

防泄漏核心 (R2): expanding 窗口标准化 — 截至当日 t 的均值/方差, 严禁全样本统计量.
辅助标的对齐到主标的交易日, 缺失用 ffill (向前填充, 只用过去已知值, 安全).

特征族 (R1):
- 主指数收益率 + 实现波动率 (单 primary)
- 指数间相对强弱 (交叉价差, 如沪深300−中证500 收益率差)
- 宏观代理一阶差分 (国债/汇率)
- 进攻−防御价差变化 (行业 ETF / 相对强弱, KTD5)

A股: 单 primary (000300) 特征 + 交叉价差辅助信号 → 统一 expanding 标准化 → 单 HMM.
港股: 单 primary (HSI) + 宏观/行业代理 (向后兼容).
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Etf, EtfDailyKline, Index, IndexDailyKline
from app.services.market_regime.config import MARKET_CONFIGS

logger = logging.getLogger(__name__)

TRADING_DAYS = 252  # 年化因子


async def load_close_series(session: AsyncSession, code: str) -> pd.Series:
    """读某 code 的收盘价序列 (index 优先, 回退 etf).

    返回 pd.Series(trade_date 为 index, float, name=code); 无数据返回空 Series.
    """
    stmt = (
        select(IndexDailyKline.trade_date, IndexDailyKline.close)
        .join(Index, Index.id == IndexDailyKline.index_id)
        .where(Index.code == code)
        .order_by(IndexDailyKline.trade_date)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        stmt = (
            select(EtfDailyKline.trade_date, EtfDailyKline.close)
            .join(Etf, Etf.id == EtfDailyKline.etf_id)
            .where(Etf.code == code)
            .order_by(EtfDailyKline.trade_date)
        )
        rows = (await session.execute(stmt)).all()
    if not rows:
        logger.warning("load_close_series: %s 无数据", code)
        return pd.Series(dtype=float, name=code)
    return pd.Series(
        {r[0]: float(r[1]) for r in rows}, name=code, dtype=float
    ).sort_index()


def multi_period_returns(close: pd.Series, windows: tuple[int, ...]) -> pd.DataFrame:
    """多周期收益率 (pct_change over 各窗口)."""
    return pd.DataFrame({f"ret_{w}d": close.pct_change(w) for w in windows})


def realized_volatility(close: pd.Series, span: int) -> pd.Series:
    """实现波动率: 对数收益的 ewm std, 年化. 0/inf 替换为 NaN 防爆."""
    log_ret = np.log(close.replace([0, np.inf, -np.inf], np.nan)).diff()
    return (log_ret.ewm(span=span).std() * math.sqrt(TRADING_DAYS)).rename(f"realvol_{span}d")


def macro_diff(series: pd.Series) -> pd.Series:
    """宏观代理一阶差分 (收益率/汇率水平的变化)."""
    return series.diff()


def log_spread_change(a: pd.Series, b: pd.Series) -> pd.Series:
    """log(a) − log(b) 的一阶差分 (价差/相对强弱变化)."""
    spread = np.log(a.replace([0, np.inf, -np.inf], np.nan)) - np.log(
        b.replace([0, np.inf, -np.inf], np.nan)
    )
    return spread.diff()


def build_raw_features(
    primary: pd.Series,
    cfg: dict[str, Any],
    aux: dict[str, pd.Series],
) -> pd.DataFrame:
    """构造原始 (未标准化) 特征矩阵, 对齐到 primary 的交易日.

    特征列名带 primary 代码后缀 (如 ret_5d_000300), 方便后续按指数分组贡献度.
    辅助特征 (宏观 diff / 价差) 名称不变.
    """
    code = cfg["primary"]
    windows = tuple(settings.regime_return_windows)
    feats = multi_period_returns(primary, windows)
    rv = realized_volatility(primary, settings.regime_vol_span)
    feats[rv.name] = rv
    return feats.add_suffix(f"_{code}")


def _cross_spread_features(
    closes: dict[str, pd.Series], pairs: list[tuple[str, str]], index: pd.DatetimeIndex
) -> pd.DataFrame:
    """指数间相对强弱特征: 两个指数的同期收益率差."""
    feats = {}
    for a_code, b_code in pairs:
        sa, sb = closes.get(a_code), closes.get(b_code)
        if sa is None or sb is None or sa.empty or sb.empty:
            logger.warning("交叉价差 %s−%s 数据不足, 跳过", a_code, b_code)
            continue
        ra = sa.pct_change()
        rb = sb.pct_change()
        spread = (ra - rb).reindex(index).ffill()
        feats[f"cross_{a_code}_{b_code}"] = spread
    return pd.DataFrame(feats)


def standardize_expanding(X: pd.DataFrame, min_periods: int = 60) -> pd.DataFrame:
    """expanding 窗口标准化 (防泄漏核心): 截至当日 t 的均值/方差, 不含未来信息.

    min_periods: expanding 统计最少样本数 (默认 60 交易日 ≈ 3 月); 不足的 warmup 期 NaN 被 drop.
    """
    mean = X.expanding(min_periods=min_periods).mean()
    std = X.expanding(min_periods=min_periods).std()
    scaled = (X - mean) / std
    return scaled.replace([np.inf, -np.inf], np.nan).dropna()


def _build_composite_primary(
    closes: dict[str, pd.Series], components: list[dict]
) -> pd.Series:
    """按权重合成 composite close 序列."""
    weights = {c["code"]: c.get("weight", 1.0 / len(components)) for c in components}
    valid = {code: s for code, s in closes.items() if code in weights and not s.empty}
    if not valid:
        raise ValueError("composite 成分指数无数据")
    aligned = pd.DataFrame(valid)
    total_w = sum(weights[c] for c in valid)
    norm_weights = {c: w / total_w for c, w in weights.items() if c in valid}
    rets = aligned.pct_change()
    composite_ret = (rets * pd.Series(norm_weights)).sum(axis=1)
    composite_close = 100 * (1 + composite_ret).cumprod()
    composite_close.name = "composite"
    return composite_close


async def build_feature_matrix(session: AsyncSession, market: str) -> pd.DataFrame:
    """端到端: 读数据 → 构造原始特征 → expanding 标准化. 返回无泄漏特征矩阵.

    精简特征方案 (参考源文章):
    - composite primary 多周期收益率 + 波动率
    - 一个价差代理 (进攻 vs 防御)
    不加宏观代理 (国债/汇率) 和交叉价差, 避免噪音.
    """
    cfg = MARKET_CONFIGS[market]
    primary_code = cfg["primary"]

    composite_components = cfg.get("composite")
    if primary_code == "composite" and composite_components:
        closes: dict[str, pd.Series] = {}
        for comp in composite_components:
            closes[comp["code"]] = await load_close_series(session, comp["code"])
        primary = _build_composite_primary(closes, composite_components)
        if primary.empty or primary.isna().all():
            raise ValueError(f"composite primary 合成失败 (成分数据不足)")
    else:
        primary = await load_close_series(session, primary_code)
        if primary.empty:
            raise ValueError(f"市场 {market} 主标的 {primary_code} 无数据, 无法构造特征")

    raw = build_raw_features(primary, cfg, {})

    # 进攻−防御价差 (仅 spread_pairs)
    for pair in cfg.get("spread_pairs", []):
        a_code, b_code = pair[0], pair[1]
        sa = await load_close_series(session, a_code)
        sb = await load_close_series(session, b_code)
        if sa is not None and not sa.empty and sb is not None and not sb.empty:
            common = pd.concat([sa.rename("a"), sb.rename("b")], axis=1).dropna()
            sp = log_spread_change(common["a"], common["b"])
            raw[f"spread_{a_code}_{b_code}"] = sp.reindex(primary.index).ffill()
        else:
            logger.warning("价差代理 %s−%s 数据不足, 跳过", a_code, b_code)

    min_valid = max(1, int(len(raw) * 0.5))
    before_cols = set(raw.columns)
    raw = raw.dropna(axis=1, thresh=min_valid)
    dropped = before_cols - set(raw.columns)
    if dropped:
        logger.warning("市场 %s 剔除有效样本不足的特征列: %s", market, sorted(dropped))

    scaled = standardize_expanding(raw)
    logger.info(
        "市场 %s 特征矩阵: %d 行 × %d 列 (%s)",
        market, scaled.shape[0], scaled.shape[1], primary_code,
    )
    return scaled


__all__ = [
    "TRADING_DAYS",
    "load_close_series",
    "multi_period_returns",
    "realized_volatility",
    "macro_diff",
    "log_spread_change",
    "build_raw_features",
    "_build_composite_primary",
    "_cross_spread_features",
    "standardize_expanding",
    "build_feature_matrix",
]
