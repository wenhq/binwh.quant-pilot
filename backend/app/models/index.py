from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Index(Base):
    """市场指数元信息 (沪深300 / 中证500 / 恒生指数 / 恒生科技 等)."""

    __tablename__ = "indices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    market: Mapped[str | None] = mapped_column(String(16), nullable=True)  # A | HK

    klines: Mapped[list["IndexDailyKline"]] = relationship(
        back_populates="index", cascade="all, delete-orphan"
    )


class IndexDailyKline(Base):
    __tablename__ = "index_daily_klines"
    __table_args__ = (
        UniqueConstraint("index_id", "trade_date", name="uq_index_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    index_id: Mapped[int] = mapped_column(
        ForeignKey("indices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    amount: Mapped[float | None] = mapped_column(Numeric(20, 3), nullable=True)

    index: Mapped["Index"] = relationship(back_populates="klines")
