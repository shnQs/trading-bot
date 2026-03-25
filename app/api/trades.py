from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.trade import Trade
from app.schemas.trade import TradeOut

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("", response_model=List[TradeOut])
async def get_trades(
    status: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    query = select(Trade).order_by(Trade.entry_time.desc()).limit(limit)
    if status:
        query = query.where(Trade.status == status.upper())
    result = await db.execute(query)
    return result.scalars().all()
