import logging
import math
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class PositionParams:
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size_usdt: float


class RiskManager:
    def __init__(self):
        # Symbol filters fetched from exchange on startup: {symbol: {step_size, min_notional}}
        self._symbol_filters: dict = {}

    def set_symbol_filters(self, symbol: str, step_size: float, min_notional: float) -> None:
        self._symbol_filters[symbol] = {
            "step_size": step_size,
            "min_notional": min_notional,
        }

    def calculate_position(
        self, symbol: str, current_price: float, available_balance: float
    ) -> PositionParams | None:
        """
        Calculate position size using fixed fractional risk.
        Returns None if the position would be below minimum notional.
        """
        position_size_usdt = available_balance * (settings.risk_per_trade_pct / 100)
        quantity = position_size_usdt / current_price

        filters = self._symbol_filters.get(symbol)
        if filters:
            quantity = self._round_step(quantity, filters["step_size"])
            min_notional = filters["min_notional"]
        else:
            quantity = round(quantity, 6)
            min_notional = 10.0  # Binance default minimum

        if quantity * current_price < min_notional:
            logger.warning(
                "[%s] Position too small: %.4f USDT < min_notional %.2f",
                symbol, quantity * current_price, min_notional,
            )
            return None

        stop_loss = round(current_price * (1 - settings.stop_loss_pct / 100), 8)
        take_profit = round(current_price * (1 + settings.take_profit_pct / 100), 8)

        logger.info(
            "[%s] Position: qty=%.6f price=%.4f SL=%.4f TP=%.4f size=%.2f USDT",
            symbol, quantity, current_price, stop_loss, take_profit, quantity * current_price,
        )

        return PositionParams(
            quantity=quantity,
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_usdt=round(quantity * current_price, 2),
        )

    @staticmethod
    def _round_step(quantity: float, step_size: float) -> float:
        if step_size == 0:
            return quantity
        precision = int(round(-math.log10(step_size)))
        return round(math.floor(quantity / step_size) * step_size, precision)

    def check_daily_loss_limit(self, realized_pnl_today: float, total_balance: float) -> bool:
        """Returns True if trading should be halted due to daily loss limit."""
        if total_balance <= 0:
            return False
        loss_pct = abs(realized_pnl_today) / total_balance * 100
        if realized_pnl_today < 0 and loss_pct >= settings.daily_loss_limit_pct:
            logger.warning(
                "Daily loss limit reached: %.2f%% (limit %.2f%%)",
                loss_pct, settings.daily_loss_limit_pct,
            )
            return True
        return False


risk_manager = RiskManager()
