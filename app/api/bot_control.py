from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.services.bot_engine import bot_engine
from app.services.pair_scanner import pair_scanner

router = APIRouter(prefix="/api/bot", tags=["bot"])


class BotStatus(BaseModel):
    running: bool
    bot_enabled: bool
    trading_pairs: list
    risk_per_trade_pct: float
    max_open_trades: int
    stop_loss_pct: float
    take_profit_pct: float
    candle_interval: str
    testnet: bool
    last_scan_time: datetime | None = None
    pair_scan_enabled: bool = True


class ConfigUpdate(BaseModel):
    risk_per_trade_pct: Optional[float] = None
    max_open_trades: Optional[int] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None


@router.get("/status", response_model=BotStatus)
async def get_status():
    return BotStatus(
        running=bot_engine.running,
        bot_enabled=settings.bot_enabled,
        trading_pairs=settings.trading_pairs,
        risk_per_trade_pct=settings.risk_per_trade_pct,
        max_open_trades=settings.max_open_trades,
        stop_loss_pct=settings.stop_loss_pct,
        take_profit_pct=settings.take_profit_pct,
        candle_interval=settings.candle_interval,
        testnet=settings.binance_testnet,
        last_scan_time=pair_scanner.last_scan_time,
        pair_scan_enabled=settings.pair_scan_enabled,
    )


@router.post("/start")
async def start_bot():
    await bot_engine.start()
    return {"status": "started", "running": bot_engine.running}


@router.post("/stop")
async def stop_bot():
    await bot_engine.stop()
    return {"status": "stopped", "running": bot_engine.running}


@router.patch("/config")
async def update_config(update: ConfigUpdate):
    if update.risk_per_trade_pct is not None:
        settings.risk_per_trade_pct = update.risk_per_trade_pct
    if update.max_open_trades is not None:
        settings.max_open_trades = update.max_open_trades
    if update.stop_loss_pct is not None:
        settings.stop_loss_pct = update.stop_loss_pct
    if update.take_profit_pct is not None:
        settings.take_profit_pct = update.take_profit_pct
    return {"status": "updated", "config": {
        "risk_per_trade_pct": settings.risk_per_trade_pct,
        "max_open_trades": settings.max_open_trades,
        "stop_loss_pct": settings.stop_loss_pct,
        "take_profit_pct": settings.take_profit_pct,
    }}


@router.post("/scan")
async def trigger_scan():
    """Manually trigger a pair rescan and update active pairs."""
    new_pairs = await pair_scanner.scan()
    await bot_engine.update_pairs(new_pairs)
    return {
        "status": "scanned",
        "pairs": settings.trading_pairs,
        "last_scan_time": pair_scanner.last_scan_time,
    }
