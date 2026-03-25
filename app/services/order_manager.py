import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trade import Trade
from app.services.exchange import exchange
from app.services.risk_manager import PositionParams, risk_manager
from app.services.strategy import SignalResult

logger = logging.getLogger(__name__)


class OrderManager:
    async def enter_trade(
        self,
        symbol: str,
        signal: SignalResult,
        position: PositionParams,
        db: AsyncSession,
    ) -> Optional[Trade]:
        """
        Place a market BUY order, then immediately place an OCO (SL+TP) order.
        Creates a Trade record in the DB.
        """
        # Place market entry
        try:
            entry_order = await exchange.place_market_order(
                symbol=symbol,
                side="BUY",
                quantity=position.quantity,
            )
        except Exception as e:
            logger.error("[%s] Failed to place entry order: %s", symbol, e)
            return None

        filled_price = float(entry_order.get("fills", [{}])[0].get("price", position.entry_price))
        if filled_price == 0:
            filled_price = position.entry_price

        # Recalculate SL/TP based on actual fill price
        from app.config import settings
        stop_loss = round(filled_price * (1 - settings.stop_loss_pct / 100), 8)
        take_profit = round(filled_price * (1 + settings.take_profit_pct / 100), 8)

        # Create trade record first so we have it even if OCO fails
        trade = Trade(
            symbol=symbol,
            side="BUY",
            status="OPEN",
            entry_price=filled_price,
            quantity=position.quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=datetime.utcnow(),
            exchange_order_id=str(entry_order.get("orderId", "")),
            strategy_signal=signal.indicators,
        )
        db.add(trade)
        await db.commit()
        await db.refresh(trade)

        # Place OCO order (SL + TP combined)
        try:
            oco_order = await exchange.place_oco_order(
                symbol=symbol,
                side="SELL",
                quantity=position.quantity,
                stop_price=stop_loss,
                take_profit_price=take_profit,
            )
            trade.oco_order_id = str(oco_order.get("orderListId", ""))
            await db.commit()
        except Exception as e:
            logger.error("[%s] OCO order failed, placing emergency market sell: %s", symbol, e)
            try:
                await exchange.place_market_order(symbol=symbol, side="SELL", quantity=position.quantity)
                trade.status = "CANCELLED"
                trade.exit_time = datetime.utcnow()
                trade.exit_reason = "OCO_FAILED"
                await db.commit()
            except Exception as e2:
                logger.critical("[%s] Emergency sell also failed: %s", symbol, e2)

        logger.info(
            "[%s] Trade opened: id=%d price=%.4f qty=%.6f SL=%.4f TP=%.4f",
            symbol, trade.id, filled_price, position.quantity, stop_loss, take_profit,
        )
        return trade

    async def exit_trade(
        self,
        trade: Trade,
        exit_reason: str,
        db: AsyncSession,
    ) -> bool:
        """
        Close an open trade: cancel OCO order, place market sell, update DB.
        """
        if trade.status != "OPEN":
            return False

        # Cancel OCO order if still active
        if trade.oco_order_id:
            try:
                await exchange.cancel_oco_order(symbol=trade.symbol, order_list_id=trade.oco_order_id)
            except Exception as e:
                logger.warning("[%s] Could not cancel OCO %s: %s", trade.symbol, trade.oco_order_id, e)

        # Market sell
        try:
            sell_order = await exchange.place_market_order(
                symbol=trade.symbol,
                side="SELL",
                quantity=trade.quantity,
            )
            exit_price = float(sell_order.get("fills", [{}])[0].get("price", trade.entry_price))
            if exit_price == 0:
                exit_price = trade.entry_price
        except Exception as e:
            logger.error("[%s] Exit market sell failed: %s", trade.symbol, e)
            return False

        pnl_usdt = (exit_price - trade.entry_price) * trade.quantity
        pnl_pct = (exit_price - trade.entry_price) / trade.entry_price * 100

        trade.status = "CLOSED"
        trade.exit_price = exit_price
        trade.exit_time = datetime.utcnow()
        trade.pnl_usdt = round(pnl_usdt, 4)
        trade.pnl_pct = round(pnl_pct, 4)
        trade.exit_reason = exit_reason
        await db.commit()

        logger.info(
            "[%s] Trade closed: id=%d exit=%.4f pnl=%.4f USDT (%.2f%%) reason=%s",
            trade.symbol, trade.id, exit_price, pnl_usdt, pnl_pct, exit_reason,
        )
        return True

    async def close_trade_by_exchange(
        self,
        trade: Trade,
        exit_price: float,
        exit_reason: str,
        db: AsyncSession,
    ) -> None:
        """Update trade record when OCO was filled on exchange (TP or SL hit)."""
        pnl_usdt = (exit_price - trade.entry_price) * trade.quantity
        pnl_pct = (exit_price - trade.entry_price) / trade.entry_price * 100

        trade.status = "CLOSED"
        trade.exit_price = exit_price
        trade.exit_time = datetime.utcnow()
        trade.pnl_usdt = round(pnl_usdt, 4)
        trade.pnl_pct = round(pnl_pct, 4)
        trade.exit_reason = exit_reason
        await db.commit()

    async def reconcile_open_trades(self, db: AsyncSession) -> None:
        """
        On startup: check if any OPEN trades had their OCO filled while bot was offline.
        """
        result = await db.execute(select(Trade).where(Trade.status == "OPEN"))
        open_trades = result.scalars().all()

        for trade in open_trades:
            if not trade.oco_order_id:
                continue
            try:
                open_orders = await exchange.get_open_orders(symbol=trade.symbol)
                open_ids = {str(o.get("orderListId")) for o in open_orders}
                if trade.oco_order_id not in open_ids:
                    # OCO is gone — it was filled. Try to find the fill price.
                    logger.info(
                        "[%s] OCO %s no longer active — marking trade %d as closed",
                        trade.symbol, trade.oco_order_id, trade.id,
                    )
                    trade.status = "CLOSED"
                    trade.exit_time = datetime.utcnow()
                    trade.exit_reason = "OCO_FILLED_OFFLINE"
                    await db.commit()
            except Exception as e:
                logger.error("[%s] Reconcile error for trade %d: %s", trade.symbol, trade.id, e)


order_manager = OrderManager()
