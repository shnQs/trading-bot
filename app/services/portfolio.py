import logging
from datetime import datetime, date

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import PortfolioSnapshot
from app.models.trade import Trade
from app.services.exchange import exchange

logger = logging.getLogger(__name__)


class PortfolioService:
    def __init__(self):
        self._peak_balance: float = 0.0

    async def take_snapshot(self, db: AsyncSession) -> PortfolioSnapshot:
        try:
            balances = await exchange.get_account_balance()
        except Exception as e:
            logger.error("Failed to fetch balance: %s", e)
            balances = {}

        usdt_total = balances.get("USDT", 0.0)
        available_usdt = usdt_total

        # Unrealized PnL from open trades (rough estimate based on entry price)
        result = await db.execute(select(Trade).where(Trade.status == "OPEN"))
        open_trades = result.scalars().all()
        unrealized_pnl = sum(
            (t.entry_price * 0.0)  # placeholder; real calc needs current price
            for t in open_trades
        )

        # Realized PnL — all time
        total_pnl_result = await db.execute(
            select(func.sum(Trade.pnl_usdt)).where(Trade.status == "CLOSED")
        )
        realized_pnl_total = total_pnl_result.scalar() or 0.0

        # Realized PnL — today
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_pnl_result = await db.execute(
            select(func.sum(Trade.pnl_usdt)).where(
                Trade.status == "CLOSED",
                Trade.exit_time >= today_start,
            )
        )
        realized_pnl_today = today_pnl_result.scalar() or 0.0

        # Win/loss counts
        win_result = await db.execute(
            select(func.count()).where(Trade.status == "CLOSED", Trade.pnl_usdt > 0)
        )
        win_count = win_result.scalar() or 0

        loss_result = await db.execute(
            select(func.count()).where(Trade.status == "CLOSED", Trade.pnl_usdt <= 0)
        )
        loss_count = loss_result.scalar() or 0

        # Max drawdown (peak-to-trough)
        if usdt_total > self._peak_balance:
            self._peak_balance = usdt_total
        max_drawdown_pct = 0.0
        if self._peak_balance > 0:
            max_drawdown_pct = round(
                (self._peak_balance - usdt_total) / self._peak_balance * 100, 2
            )

        snapshot = PortfolioSnapshot(
            timestamp=datetime.utcnow(),
            total_balance_usdt=usdt_total,
            available_usdt=available_usdt,
            unrealized_pnl=unrealized_pnl,
            realized_pnl_total=round(realized_pnl_total, 4),
            realized_pnl_today=round(realized_pnl_today, 4),
            win_count=win_count,
            loss_count=loss_count,
            max_drawdown_pct=max_drawdown_pct,
            open_trades_count=len(open_trades),
        )
        db.add(snapshot)
        await db.commit()
        await db.refresh(snapshot)
        logger.debug("Portfolio snapshot: %.2f USDT pnl_today=%.4f", usdt_total, realized_pnl_today)
        return snapshot

    async def get_latest(self, db: AsyncSession) -> PortfolioSnapshot | None:
        result = await db.execute(
            select(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_today_pnl(self, db: AsyncSession) -> float:
        today_start = datetime.combine(date.today(), datetime.min.time())
        result = await db.execute(
            select(func.sum(Trade.pnl_usdt)).where(
                Trade.status == "CLOSED",
                Trade.exit_time >= today_start,
            )
        )
        return result.scalar() or 0.0


portfolio_service = PortfolioService()
