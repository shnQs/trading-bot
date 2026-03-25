from datetime import datetime
from pydantic import BaseModel


class PortfolioOut(BaseModel):
    id: int
    timestamp: datetime
    total_balance_usdt: float
    available_usdt: float
    unrealized_pnl: float
    realized_pnl_total: float
    realized_pnl_today: float
    win_count: int
    loss_count: int
    max_drawdown_pct: float
    open_trades_count: int

    model_config = {"from_attributes": True}

    @property
    def win_rate(self) -> float:
        total = self.win_count + self.loss_count
        return round(self.win_count / total * 100, 1) if total > 0 else 0.0
