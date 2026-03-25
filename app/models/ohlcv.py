from sqlalchemy import String, Float, BigInteger, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OHLCV(Base):
    __tablename__ = "ohlcv"
    __table_args__ = (
        UniqueConstraint("symbol", "interval", "open_time", name="uq_ohlcv"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    interval: Mapped[str] = mapped_column(String(5), nullable=False)
    open_time: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)  # Unix ms
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    close_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_closed: Mapped[bool] = mapped_column(default=True)
