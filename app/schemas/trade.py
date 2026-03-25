from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel


class TradeOut(BaseModel):
    id: int
    symbol: str
    side: str
    status: str
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    stop_loss: float
    take_profit: float
    entry_time: datetime
    exit_time: Optional[datetime]
    pnl_usdt: Optional[float]
    pnl_pct: Optional[float]
    exit_reason: Optional[str]
    exchange_order_id: Optional[str]
    strategy_signal: Optional[Any]

    model_config = {"from_attributes": True}
