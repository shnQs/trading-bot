from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.ohlcv import OHLCV
from app.schemas.ohlcv import OHLCVOut
from app.services.exchange import exchange

router = APIRouter(prefix="/api/ohlcv", tags=["ohlcv"])


@router.get("/{symbol}", response_model=List[OHLCVOut])
async def get_ohlcv(
    symbol: str,
    limit: int = 200,
    interval: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    effective_interval = interval or settings.candle_interval

    # If the requested interval matches what we store, serve from DB
    if effective_interval == settings.candle_interval:
        result = await db.execute(
            select(OHLCV)
            .where(OHLCV.symbol == symbol.upper(), OHLCV.interval == effective_interval)
            .order_by(OHLCV.open_time.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return list(reversed(rows))

    # Otherwise fetch directly from Binance
    klines = await exchange.get_klines(symbol.upper(), effective_interval, limit=limit)
    return [
        OHLCVOut(
            symbol=symbol.upper(),
            interval=effective_interval,
            open_time=k["open_time"],
            open=k["open"],
            high=k["high"],
            low=k["low"],
            close=k["close"],
            volume=k["volume"],
            close_time=k["close_time"],
            is_closed=k["is_closed"],
        )
        for k in klines
    ]
