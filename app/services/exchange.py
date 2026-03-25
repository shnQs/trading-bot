import asyncio
import logging
from typing import Callable, List, Optional

from binance import AsyncClient, BinanceSocketManager
from binance.exceptions import BinanceAPIException

from app.config import settings

logger = logging.getLogger(__name__)


class BinanceClient:
    def __init__(self):
        self._client: Optional[AsyncClient] = None
        self._bsm: Optional[BinanceSocketManager] = None
        self._socket_tasks: list = []

    async def connect(self) -> None:
        self._client = await AsyncClient.create(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_secret_key,
            testnet=settings.binance_testnet,
        )
        self._bsm = BinanceSocketManager(self._client)
        logger.info(
            "Binance client connected (testnet=%s)", settings.binance_testnet
        )

    async def disconnect(self) -> None:
        for task in self._socket_tasks:
            task.cancel()
        if self._client:
            await self._client.close_connection()
        logger.info("Binance client disconnected")

    async def get_klines(
        self, symbol: str, interval: str, limit: int = 200
    ) -> List[dict]:
        raw = await self._client.get_klines(
            symbol=symbol, interval=interval, limit=limit
        )
        return [
            {
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": k[6],
                "is_closed": True,
            }
            for k in raw
        ]

    async def get_account_balance(self) -> dict:
        info = await self._client.get_account()
        return {
            b["asset"]: float(b["free"])
            for b in info["balances"]
            if float(b["free"]) > 0 or float(b["locked"]) > 0
        }

    async def get_symbol_info(self, symbol: str) -> dict:
        info = await self._client.get_symbol_info(symbol)
        return info

    async def place_market_order(
        self, symbol: str, side: str, quantity: float
    ) -> dict:
        try:
            order = await self._client.create_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=quantity,
            )
            logger.info("Market order placed: %s %s %s", side, quantity, symbol)
            return order
        except BinanceAPIException as e:
            logger.error("Market order failed: %s", e)
            raise

    async def place_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        take_profit_price: float,
    ) -> dict:
        """
        OCO order: stop_price = stop-loss trigger, take_profit_price = limit price.
        For a SELL OCO: take_profit_price > current > stop_price.
        """
        try:
            order = await self._client.create_oco_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=str(round(take_profit_price, 8)),
                stopPrice=str(round(stop_price, 8)),
                stopLimitPrice=str(round(stop_price * 0.999, 8)),  # slight buffer
                stopLimitTimeInForce="GTC",
            )
            logger.info(
                "OCO order placed: SL=%.4f TP=%.4f %s",
                stop_price,
                take_profit_price,
                symbol,
            )
            return order
        except BinanceAPIException as e:
            logger.error("OCO order failed: %s", e)
            raise

    async def cancel_order(self, symbol: str, order_id: str) -> dict:
        return await self._client.cancel_order(symbol=symbol, orderId=order_id)

    async def cancel_oco_order(self, symbol: str, order_list_id: str) -> dict:
        return await self._client.cancel_order_list(
            symbol=symbol, orderListId=order_list_id
        )

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[dict]:
        if symbol:
            return await self._client.get_open_orders(symbol=symbol)
        return await self._client.get_open_orders()

    async def get_order(self, symbol: str, order_id: str) -> dict:
        return await self._client.get_order(symbol=symbol, orderId=order_id)

    async def get_tickers_24hr(self) -> List[dict]:
        """Fetch 24h ticker stats for all symbols."""
        return await self._client.get_ticker()

    async def get_symbol_ticker(self, symbol: str) -> dict:
        """Lightest single-symbol price endpoint."""
        return await self._client.get_symbol_ticker(symbol=symbol)

    async def place_limit_order(
        self, symbol: str, side: str, quantity: float, price: float
    ) -> dict:
        try:
            order = await self._client.create_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                timeInForce="GTC",
                quantity=quantity,
                price=str(round(price, 8)),
            )
            logger.info("Limit order placed: %s %s %s @ %.8f", side, quantity, symbol, price)
            return order
        except BinanceAPIException as e:
            logger.error("Limit order failed: %s", e)
            raise

    def start_kline_socket(
        self, symbol: str, interval: str, callback: Callable
    ) -> asyncio.Task:
        async def _run():
            retry_delay = 5
            while True:
                try:
                    async with self._bsm.kline_socket(
                        symbol=symbol, interval=interval
                    ) as stream:
                        retry_delay = 5  # reset on successful connect
                        while True:
                            msg = await stream.recv()
                            if msg:
                                await callback(msg)
                except asyncio.CancelledError:
                    logger.info("Kline socket cancelled: %s %s", symbol, interval)
                    return
                except Exception as e:
                    logger.warning(
                        "Kline socket error %s %s: %s — reconnecting in %ds",
                        symbol, interval, e, retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60)

        task = asyncio.create_task(_run())
        self._socket_tasks.append(task)
        logger.info("Kline socket started: %s %s", symbol, interval)
        return task


# Singleton
exchange = BinanceClient()
