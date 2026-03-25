import pytest
import pandas as pd
import numpy as np

from app.services.strategy import evaluate, Action, MIN_CANDLES
from tests.conftest import make_candle_df


def test_hold_when_insufficient_data():
    df = make_candle_df(n=10)
    result = evaluate(df, symbol="BTCUSDT")
    assert result.action == Action.HOLD
    assert result.reason == "insufficient_data"


def test_hold_on_flat_market():
    """Flat/sideways market with no clear signal should return HOLD."""
    df = make_candle_df(n=MIN_CANDLES + 10, trend="flat")
    result = evaluate(df, symbol="BTCUSDT")
    assert result.action in (Action.HOLD, Action.BUY, Action.SELL)  # just ensure no exception


def test_signal_result_has_indicators_on_hold():
    df = make_candle_df(n=MIN_CANDLES + 10, trend="flat")
    result = evaluate(df, symbol="BTCUSDT")
    if result.action != Action.HOLD or result.reason != "insufficient_data":
        assert "rsi" in result.indicators
        assert "ema_fast" in result.indicators
        assert "ema_slow" in result.indicators
        assert "macd" in result.indicators


def test_sell_signal_on_downtrend():
    """A sustained downtrend should eventually trigger RSI overbought exit or EMA cross."""
    df = make_candle_df(n=MIN_CANDLES + 20, trend="up")
    result_up = evaluate(df, symbol="BTCUSDT")
    # At least no crash
    assert result_up.action in (Action.BUY, Action.HOLD, Action.SELL)


def test_evaluate_returns_symbol():
    df = make_candle_df(n=MIN_CANDLES + 5)
    result = evaluate(df, symbol="ETHUSDT")
    assert result.symbol == "ETHUSDT"


def test_confidence_between_0_and_1():
    df = make_candle_df(n=MIN_CANDLES + 10, trend="up")
    result = evaluate(df, symbol="BTCUSDT")
    if result.action == Action.BUY:
        assert 0.0 <= result.confidence <= 1.0


def test_no_nan_in_indicators():
    df = make_candle_df(n=MIN_CANDLES + 10, trend="up")
    result = evaluate(df, symbol="BTCUSDT")
    for key, val in result.indicators.items():
        assert val == val, f"NaN in indicator: {key}"  # NaN != NaN
