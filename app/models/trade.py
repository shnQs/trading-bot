from datetime import datetime
from sqlalchemy import String, Float, DateTime, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OPEN", index=True)  # OPEN/CLOSED/CANCELLED

    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)

    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)

    entry_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    pnl_usdt: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    exit_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)  # TP/SL/SIGNAL/MANUAL

    exchange_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oco_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    strategy_signal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
