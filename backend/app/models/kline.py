from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StockDailyKline(Base):
    __tablename__ = "stock_daily_klines"
    __table_args__ = (
        UniqueConstraint("stock_id", "trade_date", name="uq_stock_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    amount: Mapped[float | None] = mapped_column(Numeric(20, 3), nullable=True)
    adj_factor: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)

    stock: Mapped["Stock"] = relationship(back_populates="klines")


from app.models.stock import Stock  # noqa: E402,F401
