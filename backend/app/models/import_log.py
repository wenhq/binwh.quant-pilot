from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ImportError(Base):
    """断点续传错误记录:失败标的入此表,供重试端点取 retried_at IS NULL."""

    __tablename__ = "import_errors"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # stock|index|etf|fund
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # akshare|guosen
    error_msg: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    retried_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
