from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.portfolio import PortfolioOut
from app.services.portfolio import portfolio_service

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioOut)
async def get_portfolio(db: AsyncSession = Depends(get_db)):
    snapshot = await portfolio_service.get_latest(db)
    if not snapshot:
        raise HTTPException(status_code=404, detail="No portfolio snapshot yet")
    return snapshot
