"""标的字典表 instruments — 跨资产类别的统一代码目录.

每条记录描述一个标的: code/名称/类型/市场/取数源/分类/跟踪关系.
与 indices/etfs/stocks/funds 表的关系: 那些表存各自的 OHLCV 关联 (asset_id),
本表是全局代码目录, 查一个 code 立刻知道"是什么、走哪个源、属于什么类、跟踪谁".

由 universe 构建时同步写入 (run_import 导入前 upsert).
"""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Instrument(Base):
    """统一标的字典. code 全局唯一 (跨 index/etf/stock 不复用)."""

    __tablename__ = "instruments"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # index|etf|stock|fund
    market: Mapped[str | None] = mapped_column(String(16), nullable=True)  # SH|SZ|HK|US|CN|FX
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 宽基|科技|消费|国债|汇率|...
    data_source: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 取数源/接口 描述
    tracks_index: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ETF 跟踪的指数 code
    note: Mapped[str | None] = mapped_column(String(128), nullable=True)
