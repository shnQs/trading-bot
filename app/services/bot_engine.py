import asyncio
import logging
from typing import Dict

import pandas as pd
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.ohlcv import OHLCV
from app.models.trade import Trade
from app.services import strategy
from app.services.exchange import exchange
from app.services.order_manager import order_manager
from app.services.risk_manager import risk_manager
from app.services.strategy import Action

logger = logging.getLogger(__name__)


class BotEngine:
    def __init__(self):
        self.running: bool = False
        self._last_signals: Dict[str, str] = {}
        self._socket_tasks: Dict[str, asyncio.Task] = {}

    def start_streams(self) -> None:
        """Start kline sockets for all trading pairs (dashboard data, no trading)."""
        for symbol in settings.trading_pairs:
            if symbol not in self._socket_tasks:
                self._start_pair_socket(symbol)
        logger.info("Kline streams started for %d pairs", len(settings.trading_pairs))

    async def start(self) -> None:
        if self.running:
            logger.info("Bot already running")
            return
        self.running = True
        logger.info("Bot engine started — trading on %s pairs", len(settings.trading_pairs))
        await self._seed_candles()
        await self._reconcile_on_startup()
        for symbol in settings.trading_pairs:
            if symbol not in self._socket_tasks:
                self._start_pair_socket(symbol)

    async def stop(self) -> None:
        self.running = False
        logger.info("Bot engine stopped — no new orders will be placed")

    def _start_pair_socket(self, symbol: str) -> None:
        """Start a kline WebSocket for a single symbol and track its task."""
        task = exchange.start_kline_socket(
            symbol=symbol,
            interval=settings.candle_interval,
            callback=self._make_kline_callback(symbol),
        )
        if task is not None:
            self._socket_tasks[symbol] = task

    async def add_pair(self, symbol: str) -> None:
        """Seed candles, load filters, and start streaming a new symbol."""
        if symbol in settings.trading_pairs:
            return
        logger.info("[BotEngine] Adding pair %s", symbol)
        # Load filters
        try:
            info = await exchange.get_symbol_info(symbol)
            step_size, min_notional = 1.0, 10.0
            for f in info.get("filters", []):
                if f["filterType"] == "LOT_SIZE":
                    step_size = float(f["stepSize"])
                elif f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                    min_notional = float(f.get("minNotional", f.get("minNotional", 10.0)))
            risk_manager.set_symbol_filters(symbol, step_size, min_notional)
        except Exception as e:
            logger.warning("[BotEngine] Could not load filters for %s: %s", symbol, e)
        # Seed candles
        try:
            klines = await exchange.get_klines(symbol, settings.candle_interval, limit=200)
            async with AsyncSessionLocal() as db:
                for k in klines:
                    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                    stmt = sqlite_insert(OHLCV).values(
                        symbol=symbol, interval=settings.candle_interval, **k
                    ).on_conflict_do_nothing()
                    await db.execute(stmt)
                await db.commit()
            logger.info("[BotEngine] Seeded %d candles for %s", len(klines), symbol)
        except Exception as e:
            logger.error("[BotEngine] Candle seed failed for %s: %s", symbol, e)
        # Update pair list and start socket
        settings.trading_pairs = list(settings.trading_pairs) + [symbol]
        if self.running:
            self._start_pair_socket(symbol)

    async def remove_pair(self, symbol: str) -> None:
        """Stop streaming a symbol (only if no open trade)."""
        from app.models.trade import Trade
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Trade).where(Trade.symbol == symbol, Trade.status == "OPEN")
            )
            if result.scalar_one_or_none():
                logger.info("[BotEngine] Keeping %s — open trade exists", symbol)
                return
        # Cancel socket task
        task = self._socket_tasks.pop(symbol, None)
        if task:
            task.cancel()
        # Update pair list
        settings.trading_pairs = [p for p in settings.trading_pairs if p != symbol]
        logger.info("[BotEngine] Removed pair %s", symbol)

    async def update_pairs(self, new_symbols: list) -> None:
        """Diff current vs new pair list and add/remove accordingly."""
        current = set(settings.trading_pairs)
        updated = set(new_symbols)
        for sym in updated - current:
            await self.add_pair(sym)
        for sym in current - updated:
            await self.remove_pair(sym)
        logger.info("[BotEngine] Pairs updated: %s", settings.trading_pairs)

    def _make_kline_callback(self, symbol: str):
        async def callback(msg: dict) -> None:
            kline = msg.get("k", {})
            is_closed = kline.get("x", False)

            candle = {
                "open_time": kline["t"],
                "open": float(kline["o"]),
                "high": float(kline["h"]),
                "low": float(kline["l"]),
                "close": float(kline["c"]),
                "volume": float(kline["v"]),
                "close_time": kline["T"],
                "is_closed": is_closed,
            }

            # Broadcast live candle to dashboard
            from app.api.ws import ws_manager
            await ws_manager.broadcast({
                "type": "candle",
                "symbol": symbol,
                "data": candle,
            })

            # Store closed candle in DB
            if is_closed:
                await self._store_candle(symbol, candle)
                if self.running:
                    await self._evaluate_and_trade(symbol)

        return callback

    async def _store_candle(self, symbol: str, candle: dict) -> None:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        async with AsyncSessionLocal() as db:
            stmt = sqlite_insert(OHLCV).values(
                symbol=symbol,
                interval=settings.candle_interval,
                open_time=candle["open_time"],
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
                close_time=candle["close_time"],
                is_closed=candle["is_closed"],
            ).on_conflict_do_update(
                index_elements=["symbol", "interval", "open_time"],
                set_={
                    "close": candle["close"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "volume": candle["volume"],
                    "is_closed": candle["is_closed"],
                },
            )
            await db.execute(stmt)
            await db.commit()

    async def _evaluate_and_trade(self, symbol: str) -> None:
        async with AsyncSessionLocal() as db:
            # Load last 100 closed candles from DB
            result = await db.execute(
                select(OHLCV)
                .where(OHLCV.symbol == symbol, OHLCV.interval == settings.candle_interval)
                .order_by(OHLCV.open_time.desc())
                .limit(100)
            )
            rows = result.scalars().all()
            if not rows:
                return

            df = pd.DataFrame(
                [
                    {
                        "open_time": r.open_time,
                        "open": r.open,
                        "high": r.high,
                        "low": r.low,
                        "close": r.close,
                        "volume": r.volume,
                    }
                    for r in reversed(rows)
                ]
            )

            signal = strategy.evaluate(df, symbol=symbol)
            logger.debug("[%s] Signal: %s (%s)", symbol, signal.action, signal.reason)

            # Broadcast signal to dashboard
            from app.api.ws import ws_manager
            await ws_manager.broadcast({
                "type": "signal",
                "symbol": symbol,
                "action": signal.action,
                "indicators": signal.indicators,
            })

            # Check open trade for this symbol
            open_trade_result = await db.execute(
                select(Trade).where(Trade.symbol == symbol, Trade.status == "OPEN")
            )
            open_trade = open_trade_result.scalar_one_or_none()

            if signal.action == Action.BUY and open_trade is None:
                await self._try_enter(symbol, signal, db)
            elif signal.action == Action.SELL and open_trade is not None:
                await order_manager.exit_trade(open_trade, "SIGNAL", db)
                await self._broadcast_trade_update(open_trade)

    async def _try_enter(self, symbol: str, signal, db) -> None:
        # Count all open trades across all symbols
        result = await db.execute(
            select(Trade).where(Trade.status == "OPEN")
        )
        all_open = result.scalars().all()
        if len(all_open) >= settings.max_open_trades:
            logger.info("[%s] Max open trades (%d) reached, skipping", symbol, settings.max_open_trades)
            return

        # Get available balance
        try:
            balances = await exchange.get_account_balance()
        except Exception as e:
            logger.error("Could not fetch balance: %s", e)
            return

        available = balances.get("USDT", 0.0)

        # Check daily loss limit
        from app.services.portfolio import portfolio_service
        today_pnl = await portfolio_service.get_today_pnl(db)
        total_balance = available  # rough
        if risk_manager.check_daily_loss_limit(today_pnl, total_balance):
            logger.warning("[%s] Daily loss limit active — no new trades today", symbol)
            return

        # Calculate position
        current_price = signal.indicators.get("close", 0)
        if current_price <= 0:
            return

        position = risk_manager.calculate_position(symbol, current_price, available)
        if position is None:
            return

        trade = await order_manager.enter_trade(symbol, signal, position, db)
        if trade:
            await self._broadcast_trade_update(trade)

    async def _broadcast_trade_update(self, trade: Trade) -> None:
        from app.api.ws import ws_manager
        await ws_manager.broadcast({
            "type": "trade_update",
            "data": {
                "id": trade.id,
                "symbol": trade.symbol,
                "status": trade.status,
                "pnl_usdt": trade.pnl_usdt,
                "pnl_pct": trade.pnl_pct,
                "exit_reason": trade.exit_reason,
            },
        })

    async def _seed_candles(self) -> None:
        """Load last 200 candles for each pair from exchange into DB on startup."""
        for symbol in settings.trading_pairs:
            try:
                klines = await exchange.get_klines(symbol, settings.candle_interval, limit=200)
                async with AsyncSessionLocal() as db:
                    for k in klines:
                        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                        stmt = sqlite_insert(OHLCV).values(
                            symbol=symbol,
                            interval=settings.candle_interval,
                            **k,
                        ).on_conflict_do_nothing()
                        await db.execute(stmt)
                    await db.commit()
                logger.info("[%s] Seeded %d candles", symbol, len(klines))
            except Exception as e:
                logger.error("[%s] Candle seed failed: %s", symbol, e)

    async def _reconcile_on_startup(self) -> None:
        async with AsyncSessionLocal() as db:
            await order_manager.reconcile_open_trades(db)

    async def load_symbol_filters(self) -> None:
        """Fetch Binance symbol info for lot size + min notional filters."""
        for symbol in settings.trading_pairs:
            try:
                info = await exchange.get_symbol_info(symbol)
                step_size = 1.0
                min_notional = 10.0
                for f in info.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        step_size = float(f["stepSize"])
                    elif f["filterType"] == "MIN_NOTIONAL":
                        min_notional = float(f["minNotional"])
                risk_manager.set_symbol_filters(symbol, step_size, min_notional)
                logger.info("[%s] Filters loaded: step=%.8f min_notional=%.2f", symbol, step_size, min_notional)
            except Exception as e:
                logger.warning("[%s] Could not load filters: %s", symbol, e)


bot_engine = BotEngine()
