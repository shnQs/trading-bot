from fastapi import APIRouter

from app.api import trades, portfolio, ohlcv, bot_control, ws, manual_orders

api_router = APIRouter()
api_router.include_router(trades.router)
api_router.include_router(portfolio.router)
api_router.include_router(ohlcv.router)
api_router.include_router(bot_control.router)
api_router.include_router(ws.router)
api_router.include_router(manual_orders.router)
