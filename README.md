# Binance Day Trading Bot

Automated day trading bot for Binance (Testnet & Live) with a real-time web dashboard. Trades BTC/USDT, ETH/USDT, and BNB/USDT using RSI + EMA + MACD signals with built-in risk management.

## Features

- **Strategy**: RSI(14) + EMA(9/21) crossover + MACD(12/26/9) — all conditions must align for entry
- **Risk management**: 1% risk per trade, 2% stop-loss, 4% take-profit (OCO orders on exchange), max 3 open trades, daily loss circuit breaker
- **Web dashboard**: Real-time TradingView charts, open/closed trades table, portfolio stats, bot start/stop controls
- **Docker**: Single `docker-compose up` to start everything
- **Testnet-first**: Trades on Binance Testnet by default — switch to live with one env flag
- **Crash-safe**: OCO orders live on the exchange; bot reconciles on restart

## Quick Start

### 1. Get Testnet API Keys

Register at [testnet.binance.vision](https://testnet.binance.vision) and generate an API key + secret.

### 2. Configure

```bash
cp .env.example .env
# Edit .env and fill in BINANCE_API_KEY and BINANCE_SECRET_KEY
```

### 3. Run

```bash
docker-compose up --build
```

Open [http://localhost:8080](http://localhost:8080) to view the dashboard.

### 4. Start the Bot

By default `BOT_ENABLED=false` — the bot evaluates signals but does not place orders. Click **Start Bot** in the dashboard or set `BOT_ENABLED=true` in `.env` and restart.

## Project Structure

```
trading_bot/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # All settings via .env
│   ├── database.py          # SQLAlchemy async SQLite
│   ├── models/              # ORM models (Trade, OHLCV, Portfolio)
│   ├── schemas/             # Pydantic request/response schemas
│   ├── services/
│   │   ├── exchange.py      # Binance REST + WebSocket wrapper
│   │   ├── strategy.py      # RSI/EMA/MACD signal engine
│   │   ├── risk_manager.py  # Position sizing + SL/TP calculation
│   │   ├── order_manager.py # Order placement + crash recovery
│   │   ├── portfolio.py     # Balance, PnL, drawdown tracking
│   │   └── bot_engine.py    # Main trading loop
│   ├── api/                 # FastAPI routes + WebSocket hub
│   └── static/              # Web dashboard (HTML/Alpine.js/TailwindCSS)
├── tests/                   # pytest unit + integration tests
├── scripts/
│   ├── backtest.py          # Offline backtest on historical data
│   └── seed_testnet.py      # Verify testnet balance
├── data/                    # SQLite DB (volume-mounted, gitignored)
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Strategy

**Timeframe:** 15-minute candles

**LONG Entry** — all 4 conditions must be true on the last *closed* candle:
1. RSI > 30 (not in freefall)
2. RSI < 55 (room to run upward)
3. EMA9 > EMA21 (uptrend confirmed)
4. Fresh MACD bullish crossover (MACD crossed above signal on last candle)

**Exit** — any one triggers a market sell:
1. RSI > 70 (overbought)
2. EMA9 < EMA21 (trend reversed)
3. Fresh MACD bearish crossover

Stop-loss (2%) and take-profit (4%) are placed as OCO orders on Binance immediately after entry — they remain active even if the bot is offline.

## Risk Management

| Rule | Default |
|------|---------|
| Risk per trade | 1% of portfolio |
| Stop loss | 2% below entry |
| Take profit | 4% above entry (2:1 R/R) |
| Max open trades | 3 |
| Daily loss limit | 3% of portfolio |

## Running Tests

```bash
# Unit tests (no exchange connection needed)
docker-compose run --rm bot pytest tests/test_strategy.py tests/test_risk_manager.py -v

# All tests
docker-compose run --rm bot pytest -v
```

## Backtest

```bash
docker-compose run --rm bot python scripts/backtest.py --symbol BTCUSDT --start 2024-01-01 --end 2024-12-31
```

## Go Live

When ready to trade real money:
1. Edit `.env`: set `BINANCE_TESTNET=false`
2. Replace API keys with live Binance keys
3. Set `RISK_PER_TRADE_PCT=0.5` (start conservative)
4. `docker-compose up`

Zero code changes required.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/trades` | All trades (filter: `?status=open\|closed`) |
| GET | `/api/portfolio` | Latest portfolio snapshot |
| GET | `/api/ohlcv/{symbol}` | OHLCV candles (param: `?limit=200`) |
| POST | `/api/bot/start` | Start the trading bot |
| POST | `/api/bot/stop` | Stop the trading bot |
| PATCH | `/api/bot/config` | Update risk parameters live |
| WS | `/ws` | Real-time candle + trade + portfolio updates |

## Dashboard

![Dashboard](https://via.placeholder.com/800x400?text=Trading+Bot+Dashboard)

- **Chart**: Live TradingView candlestick chart with EMA9/EMA21 overlaid + RSI and MACD sub-charts
- **Open trades**: Entry price, current price, unrealized PnL, SL/TP levels, duration
- **Closed trades**: Full trade history with realized PnL and exit reason
- **Controls**: Start/stop bot, adjust risk parameters, portfolio summary

## Disclaimer

This bot is for educational purposes. Crypto trading carries significant risk of loss. Always test thoroughly on testnet before using real money. Past strategy performance does not guarantee future results.
