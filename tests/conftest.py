import pytest
import pandas as pd
import numpy as np


def make_candle_df(n: int = 80, trend: str = "up") -> pd.DataFrame:
    """Create a synthetic OHLCV DataFrame for testing."""
    np.random.seed(42)
    prices = [100.0]
    for _ in range(n - 1):
        if trend == "up":
            change = np.random.normal(0.3, 1.0)
        elif trend == "down":
            change = np.random.normal(-0.3, 1.0)
        else:
            change = np.random.normal(0, 1.0)
        prices.append(max(1.0, prices[-1] + change))

    times = [1700000000000 + i * 900_000 for i in range(n)]
    df = pd.DataFrame({
        "open_time": times,
        "open": prices,
        "high": [p * 1.005 for p in prices],
        "low": [p * 0.995 for p in prices],
        "close": prices,
        "volume": [1000.0] * n,
    })
    return df


def make_buy_signal_df() -> pd.DataFrame:
    """
    DataFrame engineered to produce a BUY signal:
    - Uptrend (EMA9 > EMA21)
    - RSI in 30-55 range
    - MACD crosses up on last closed candle
    """
    np.random.seed(0)
    n = 80
    # Rising prices to create uptrend + MACD cross
    prices = [50.0 + i * 0.15 + np.random.normal(0, 0.1) for i in range(n)]
    # Force a dip and recovery to trigger MACD crossover
    for i in range(60, 70):
        prices[i] = prices[i] - 2.0
    for i in range(70, n):
        prices[i] = prices[i] + (i - 70) * 0.3

    times = [1700000000000 + i * 900_000 for i in range(n)]
    return pd.DataFrame({
        "open_time": times,
        "open": prices,
        "high": [p * 1.005 for p in prices],
        "low": [p * 0.995 for p in prices],
        "close": prices,
        "volume": [1000.0] * n,
    })
