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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initialising database...")
    await init_db()

    logger.info("Connecting to Binance (testnet=%s)...", settings.binance_testnet)
    await exchange.connect()

    logger.info("Loading symbol filters...")
    await bot_engine.load_symbol_filters()

    # Start portfolio snapshot scheduler (every 5 minutes)
    from app.database import AsyncSessionLocal
    from app.services.portfolio import portfolio_service

    async def _portfolio_snapshot():
        async with AsyncSessionLocal() as db:
            await portfolio_service.take_snapshot(db)

    scheduler.add_job(_portfolio_snapshot, "interval", minutes=5, id="portfolio_snapshot")
    scheduler.start()

    # Take an initial snapshot immediately
    await _portfolio_snapshot()

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

app.include_router(api_router)

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")


@app.get("/health")
async def health():
    return {"status": "ok", "testnet": settings.binance_testnet, "bot_running": bot_engine.running}
