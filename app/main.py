import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config import settings
from app.database import init_db
from app.services.exchange import exchange
from app.services.bot_engine import bot_engine
from app.services.pair_scanner import pair_scanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    from app.database import AsyncSessionLocal
    from app.services.portfolio import portfolio_service

    logger.info("Initialising database...")
    await init_db()

    # Restore peak balance from DB history
    async with AsyncSessionLocal() as db:
        await portfolio_service.init_peak_balance(db)

    logger.info("Connecting to Binance (testnet=%s)...", settings.binance_testnet)
    await exchange.connect()

    # If pair scanning enabled, discover pairs first then load their filters
    if settings.pair_scan_enabled:
        logger.info("Scanning for trading pairs...")
        discovered = await pair_scanner.scan()
        settings.trading_pairs = discovered

    logger.info("Loading symbol filters...")
    await bot_engine.load_symbol_filters()

    # Start portfolio snapshot scheduler (every 1 minute)

    async def _portfolio_snapshot():
        async with AsyncSessionLocal() as db:
            snapshot = await portfolio_service.take_snapshot(db)
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

    scheduler.add_job(_portfolio_snapshot, "interval", minutes=1, id="portfolio_snapshot")

    async def _broadcast_latest_candles():
        """Fetch the latest 1m candle for each pair and push to dashboard clients."""
        from app.api.ws import ws_manager
        for symbol in settings.trading_pairs:
            try:
                klines = await exchange.get_klines(symbol, settings.candle_interval, limit=2)
                if klines:
                    c = klines[-1]
                    await ws_manager.broadcast({"type": "candle", "symbol": symbol, "data": c})
                    await bot_engine._store_candle(symbol, c)
            except Exception as e:
                logger.warning("[candle_refresh] %s: %s", symbol, e)

    scheduler.add_job(_broadcast_latest_candles, "interval", minutes=1, id="candle_refresh")

    if settings.pair_scan_enabled:
        async def _pair_scan():
            discovered = await pair_scanner.scan()
            await bot_engine.update_pairs(discovered)

        scheduler.add_job(
            _pair_scan,
            "interval",
            minutes=settings.pair_scan_interval_minutes,
            id="pair_scan",
        )

    scheduler.start()

    # Take an initial snapshot immediately
    await _portfolio_snapshot()

    # Always seed candles on startup so the dashboard has data to display
    logger.info("Seeding candle history...")
    await bot_engine._seed_candles()
    await bot_engine._reconcile_on_startup()

    # Always stream kline data for the dashboard, regardless of bot_enabled
    logger.info("Starting kline streams for dashboard...")
    bot_engine.start_streams()

    # Auto-start bot if configured
    if settings.bot_enabled:
        logger.info("BOT_ENABLED=true — starting bot engine automatically")
        await bot_engine.start()
    else:
        logger.info("BOT_ENABLED=false — bot is in observer mode (no orders placed)")

    yield

    # Shutdown
    logger.info("Shutting down...")
    scheduler.shutdown(wait=False)
    await bot_engine.stop()
    await exchange.disconnect()


app = FastAPI(
    title="Binance Trading Bot",
    description="Automated day trading bot with RSI+EMA+MACD strategy",
    version="1.0.0",
    lifespan=lifespan,
)

@app.get("/health")
async def health():
    return {"status": "ok", "testnet": settings.binance_testnet, "bot_running": bot_engine.running}

app.include_router(api_router)

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
