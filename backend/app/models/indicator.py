from datetime import date

from sqlalchemy import Date, Float, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IndicatorValue(Base):
    """技术指标值 — 一行为 (资产类型 + 代码 + 日期) 下所有指标的聚合."""

    __tablename__ = "indicator_values"
    __table_args__ = (
        UniqueConstraint("asset_type", "code", "trade_date", name="uq_indicator_asset_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    asset_type: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    macd_dif: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    macd_dea: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    macd_hist: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)

    rsi: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)

    boll_upper: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    boll_mid: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    boll_lower: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)

    keltner_upper: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    keltner_mid: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    keltner_lower: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)

    atr: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
