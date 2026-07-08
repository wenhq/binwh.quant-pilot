from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Etf(Base):
    """ETF 元信息 (国债ETF / 恒生科技ETF 等)."""

    __tablename__ = "etfs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tracks: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 跟踪标的

    klines: Mapped[list["EtfDailyKline"]] = relationship(
        back_populates="etf", cascade="all, delete-orphan"
    )


class EtfDailyKline(Base):
    __tablename__ = "etf_daily_klines"
    __table_args__ = (
        UniqueConstraint("etf_id", "trade_date", name="uq_etf_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    etf_id: Mapped[int] = mapped_column(
        ForeignKey("etfs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    amount: Mapped[float | None] = mapped_column(Numeric(22, 6), nullable=True)
    adj_factor: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)

    etf: Mapped["Etf"] = relationship(back_populates="klines")
