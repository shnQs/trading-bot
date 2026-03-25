from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.ohlcv import OHLCV
from app.schemas.ohlcv import OHLCVOut

router = APIRouter(prefix="/api/ohlcv", tags=["ohlcv"])


@router.get("/{symbol}", response_model=List[OHLCVOut])
async def get_ohlcv(
    symbol: str,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OHLCV)
        .where(OHLCV.symbol == symbol.upper(), OHLCV.interval == settings.candle_interval)
        .order_by(OHLCV.open_time.asc())
        .limit(limit)
    )
    return result.scalars().all()
