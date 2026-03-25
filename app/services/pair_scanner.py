import logging
from datetime import datetime, timezone
from typing import List

from app.config import settings
from app.services.exchange import exchange

logger = logging.getLogger(__name__)

# Stablecoins and tokens that should never be traded
_STABLECOIN_BASES = {"USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD", "PYUSD", "USDT"}
# Substrings that indicate leveraged/inverse tokens
_LEVERAGED_KEYWORDS = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S")


class PairScanner:
    def __init__(self):
        self.last_scan_time: datetime | None = None
        self.last_pairs: List[str] = []

    async def scan(self) -> List[str]:
        """
        Fetch all 24h tickers, filter for liquid+volatile USDT pairs,
        return top N symbols sorted by quote volume descending.
        Falls back to current settings.trading_pairs on error.
        """
        try:
            tickers = await exchange.get_tickers_24hr()
        except Exception as e:
            logger.error("[PairScanner] Failed to fetch tickers: %s", e)
            return list(settings.trading_pairs)

        candidates = []
        for t in tickers:
            symbol: str = t.get("symbol", "")

            # Must end with USDT
            if not symbol.endswith("USDT"):
                continue

            base = symbol[:-4]  # strip "USDT"

            # Exclude stablecoins
            if base in _STABLECOIN_BASES:
                continue

            # Exclude leveraged tokens
            if any(kw in base for kw in _LEVERAGED_KEYWORDS):
                continue

            try:
                quote_volume = float(t.get("quoteVolume", 0))
                price_change_pct = abs(float(t.get("priceChangePercent", 0)))
            except (ValueError, TypeError):
                continue

            # On testnet, synthetic volume is near-zero — skip volume/volatility filters
            if not settings.binance_testnet:
                if quote_volume < settings.pair_scan_min_volume_usdt:
                    continue
                if price_change_pct < settings.pair_scan_min_price_change_pct:
                    continue

            candidates.append((symbol, quote_volume))

        # Sort by 24h USDT volume descending, take top N
        candidates.sort(key=lambda x: x[1], reverse=True)
        result = [sym for sym, _ in candidates[: settings.pair_scan_max_pairs]]

        if not result:
            logger.warning(
                "[PairScanner] No pairs passed filters — keeping current pairs %s",
                settings.trading_pairs,
            )
            return list(settings.trading_pairs)

        self.last_scan_time = datetime.now(timezone.utc)
        self.last_pairs = result
        logger.info("[PairScanner] Found %d pairs: %s", len(result), ", ".join(result))
        return result


pair_scanner = PairScanner()
