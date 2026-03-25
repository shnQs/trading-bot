import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.trade import Trade
from app.services.exchange import exchange
from app.services.order_manager import order_manager
from app.services.risk_manager import PositionParams, risk_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["manual_orders"])


class ManualBuyRequest(BaseModel):
    symbol: str
    usdt_amount: float
    aggressive: bool = False


class ManualCloseRequest(BaseModel):
    pass  # trade_id comes from path


@router.post("/buy")
async def manual_buy(req: ManualBuyRequest, db: AsyncSession = Depends(get_db)):
    symbol = req.symbol.upper()

    if req.usdt_amount <= 0:
        raise HTTPException(status_code=400, detail="usdt_amount must be positive")

    # Get current price
    try:
        if req.aggressive:
            ticker = await exchange.get_symbol_ticker(symbol)
            current_price = float(ticker["price"])
        else:
            klines = await exchange.get_klines(symbol, settings.candle_interval, limit=1)
            if not klines:
                raise HTTPException(status_code=400, detail="Could not fetch current price")
            current_price = klines[-1]["close"]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Exchange error: {e}")

    # Get lot size filters — use cache or fetch live from exchange
    filters = risk_manager._symbol_filters.get(symbol)
    if not filters:
        try:
            info = await exchange.get_symbol_info(symbol)
            step_size, min_notional = 0.0, 10.0
            for f in info.get("filters", []):
                if f["filterType"] == "LOT_SIZE":
                    step_size = float(f["stepSize"])
                elif f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                    min_notional = float(f.get("minNotional", 10.0))
            risk_manager.set_symbol_filters(symbol, step_size, min_notional)
            filters = risk_manager._symbol_filters[symbol]
        except Exception as e:
            logger.warning("[%s] Could not fetch symbol filters: %s", symbol, e)
            filters = {"step_size": 0.0, "min_notional": 10.0}

    step_size = filters["step_size"]
    min_notional = filters["min_notional"]

    raw_qty = req.usdt_amount / current_price
    quantity = risk_manager._round_step(raw_qty, step_size) if step_size > 0 else round(raw_qty, 6)

    if quantity <= 0 or quantity * current_price < min_notional:
        raise HTTPException(
            status_code=400,
            detail=f"Order too small. Min notional: {min_notional} USDT, got {round(quantity * current_price, 2)} USDT"
        )

    # Check for existing open trade on this symbol
    existing = await db.execute(
        select(Trade).where(Trade.symbol == symbol, Trade.status == "OPEN")
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Already have an open trade on {symbol}")

    # Place order
    if req.aggressive:
        limit_price = round(current_price * 1.001, 8)
        try:
            entry_order = await exchange.place_limit_order(
                symbol=symbol, side="BUY", quantity=quantity, price=limit_price
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Order failed: {e}")

        # Poll up to 3s for fill (almost always immediate)
        order_id = str(entry_order.get("orderId", ""))
        for _ in range(3):
            if entry_order.get("status") == "FILLED":
                break
            await asyncio.sleep(1)
            try:
                entry_order = await exchange.get_order(symbol=symbol, order_id=order_id)
            except Exception:
                pass

        if entry_order.get("status") != "FILLED":
            try:
                await exchange.cancel_order(symbol=symbol, order_id=order_id)
            except Exception:
                pass
            raise HTTPException(status_code=408, detail="Aggressive limit order did not fill — cancelled")
    else:
        try:
            entry_order = await exchange.place_market_order(symbol=symbol, side="BUY", quantity=quantity)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Order failed: {e}")

    filled_price = float(entry_order.get("fills", [{}])[0].get("price", current_price))
    if filled_price == 0:
        filled_price = current_price

    stop_loss = round(filled_price * (1 - settings.stop_loss_pct / 100), 8)
    take_profit = round(filled_price * (1 + settings.take_profit_pct / 100), 8)

    trade = Trade(
        symbol=symbol,
        side="BUY",
        status="OPEN",
        entry_price=filled_price,
        quantity=quantity,
        stop_loss=stop_loss,
        take_profit=take_profit,
        entry_time=datetime.utcnow(),
        exchange_order_id=str(entry_order.get("orderId", "")),
        strategy_signal={"source": "manual_aggressive" if req.aggressive else "manual", "usdt_amount": req.usdt_amount},
    )
    db.add(trade)
    await db.commit()
    await db.refresh(trade)

    # Place OCO (SL + TP)
    try:
        oco = await exchange.place_oco_order(
            symbol=symbol, side="SELL", quantity=quantity,
            stop_price=stop_loss, take_profit_price=take_profit,
        )
        trade.oco_order_id = str(oco.get("orderListId", ""))
        await db.commit()
    except Exception as e:
        logger.warning("[%s] Manual buy OCO failed: %s", symbol, e)

    logger.info("[%s] Manual buy: qty=%.6f price=%.6f SL=%.6f TP=%.6f", symbol, quantity, filled_price, stop_loss, take_profit)

    from app.api.ws import ws_manager
    await ws_manager.broadcast({"type": "trade_update", "data": {"id": trade.id, "symbol": symbol, "status": "OPEN"}})

    return {
        "id": trade.id,
        "symbol": symbol,
        "quantity": quantity,
        "entry_price": filled_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "usdt_spent": round(filled_price * quantity, 2),
    }


@router.post("/close/{trade_id}")
async def manual_close(trade_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one_or_none()

    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if trade.status != "OPEN":
        raise HTTPException(status_code=400, detail="Trade is not open")

    success = await order_manager.exit_trade(trade, "MANUAL", db)
    if not success:
        raise HTTPException(status_code=502, detail="Failed to close trade on exchange")

    # Refresh portfolio snapshot immediately after close
    from app.services.portfolio import portfolio_service
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as snap_db:
        snapshot = await portfolio_service.take_snapshot(snap_db)

    from app.api.ws import ws_manager
    await ws_manager.broadcast({
        "type": "portfolio_update",
        "data": {
            "total_balance_usdt": snapshot.total_balance_usdt,
            "realized_pnl_today": snapshot.realized_pnl_today,
            "realized_pnl_total": snapshot.realized_pnl_total,
            "win_count": snapshot.win_count,
            "loss_count": snapshot.loss_count,
            "max_drawdown_pct": snapshot.max_drawdown_pct,
            "open_trades_count": snapshot.open_trades_count,
        },
    })
    await ws_manager.broadcast({
        "type": "trade_update",
        "data": {"id": trade.id, "symbol": trade.symbol, "status": "CLOSED", "exit_reason": "MANUAL"},
    })

    return {
        "id": trade.id,
        "symbol": trade.symbol,
        "exit_price": trade.exit_price,
        "pnl_usdt": trade.pnl_usdt,
        "pnl_pct": trade.pnl_pct,
    }
