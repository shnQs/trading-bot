import json
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Binance
    binance_api_key: str = ""
    binance_secret_key: str = ""
    binance_testnet: bool = True

    # Trading
    trading_pairs: List[str] = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    candle_interval: str = "15m"

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/trading_bot.db"

    # Strategy
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    ema_fast: int = 9
    ema_slow: int = 21
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # Risk management
    risk_per_trade_pct: float = 1.0
    max_open_trades: int = 3
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0
    daily_loss_limit_pct: float = 3.0

    # Bot state
    bot_enabled: bool = False

    @property
    def binance_base_url(self) -> str:
        if self.binance_testnet:
            return "https://testnet.binance.vision/api"
        return "https://api.binance.com/api"

    @property
    def binance_ws_url(self) -> str:
        if self.binance_testnet:
            return "wss://testnet.binance.vision/ws"
        return "wss://stream.binance.com:9443/ws"


settings = Settings()
