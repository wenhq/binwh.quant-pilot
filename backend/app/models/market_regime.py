from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RegimeRun(Base):
    """模型训练快照元数据 (一次聚类+分类训练 = 一个 run).

    Schema 预留,本数据层计划不写入;留给后续 ML 闭环 plan.
    """

    __tablename__ = "regime_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(16), nullable=False)  # A | HK
    algorithm: Mapped[str | None] = mapped_column(String(32), nullable=True)  # hmm | gmm | kmeans
    classifier: Mapped[str | None] = mapped_column(String(32), nullable=True)  # logistic | ...
    params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # KS/ROC-AUC/轮廓系数
    trained_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    states: Mapped[list["RegimeState"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RegimeState(Base):
    """状态序列:某 run 下每个交易日的状态标签 + 概率.

    Schema 预留,本数据层计划不写入.
    """

    __tablename__ = "regime_states"
    __table_args__ = (
        UniqueConstraint("run_id", "trade_date", name="uq_run_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("regime_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    state_label: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=平静 / 1=动荡 (扩展更多)
    state_prob: Mapped[float | None] = mapped_column(Float, nullable=True)  # 进入动荡期概率
    features_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    run: Mapped["RegimeRun"] = relationship(back_populates="states")
