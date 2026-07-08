from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Fund(Base):
    """公募基金元信息 (净值型,落配置端不落状态特征端)."""

    __tablename__ = "funds"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fund_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 股票型/混合型/债券型...

    klines: Mapped[list["FundDailyKline"]] = relationship(
        back_populates="fund", cascade="all, delete-orphan"
    )


class FundDailyKline(Base):
    """基金净值历史 (unit_nav 单位净值 / acc_nav 累计净值)."""

    __tablename__ = "fund_daily_klines"
    __table_args__ = (
        UniqueConstraint("fund_id", "trade_date", name="uq_fund_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fund_id: Mapped[int] = mapped_column(
        ForeignKey("funds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    unit_nav: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)  # 单位净值
    acc_nav: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)  # 累计净值

    fund: Mapped["Fund"] = relationship(back_populates="klines")
