import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd
import ta.momentum
import ta.trend

from app.config import settings

logger = logging.getLogger(__name__)

MIN_CANDLES = 60  # need enough history for MACD slow(26) + signal(9) + buffer


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class SignalResult:
    action: Action
    symbol: str = ""
    confidence: float = 0.0
    reason: str = ""
    indicators: dict = field(default_factory=dict)


def evaluate(df: pd.DataFrame, symbol: str = "") -> SignalResult:
    """
    Evaluate RSI + EMA + MACD signals on a DataFrame of OHLCV candles.

    df must have columns: open_time, open, high, low, close, volume
    Uses index -2 (last fully closed candle), never -1 (may still be forming).
    """
    if len(df) < MIN_CANDLES:
        return SignalResult(action=Action.HOLD, symbol=symbol, reason="insufficient_data")

    df = df.copy()
    close = df["close"].astype(float)

    # Calculate indicators
    df["rsi"] = ta.momentum.RSIIndicator(close=close, window=settings.rsi_period).rsi()
    df["ema_fast"] = ta.trend.EMAIndicator(close=close, window=settings.ema_fast).ema_indicator()
    df["ema_slow"] = ta.trend.EMAIndicator(close=close, window=settings.ema_slow).ema_indicator()

    macd = ta.trend.MACD(
        close=close,
        window_slow=settings.macd_slow,
        window_fast=settings.macd_fast,
        window_sign=settings.macd_signal,
    )
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    # Drop rows with NaN indicators (initial warmup candles)
    df.dropna(subset=["rsi", "ema_fast", "ema_slow", "macd", "macd_signal"], inplace=True)

    if len(df) < 3:
        return SignalResult(action=Action.HOLD, symbol=symbol, reason="insufficient_data_after_dropna")

    c = df.iloc[-2]   # last closed candle
    p = df.iloc[-3]   # prior candle

    indicators = {
        "rsi": round(float(c["rsi"]), 2),
        "ema_fast": round(float(c["ema_fast"]), 4),
        "ema_slow": round(float(c["ema_slow"]), 4),
        "macd": round(float(c["macd"]), 6),
        "macd_signal": round(float(c["macd_signal"]), 6),
        "close": round(float(c["close"]), 4),
    }

    # --- LONG ENTRY conditions ---
    macd_cross_up = (
        float(c["macd"]) > float(c["macd_signal"])
        and float(p["macd"]) <= float(p["macd_signal"])
    )
    ema_trend_up = float(c["ema_fast"]) > float(c["ema_slow"])
    rsi_in_range = settings.rsi_oversold < float(c["rsi"]) < 55.0

    if macd_cross_up and ema_trend_up and rsi_in_range:
        confidence = _score_long(c, p)
        logger.info("[%s] BUY signal — RSI=%.1f EMA_up=%s MACD_cross=%s conf=%.2f",
                    symbol, c["rsi"], ema_trend_up, macd_cross_up, confidence)
        return SignalResult(
            action=Action.BUY,
            symbol=symbol,
            confidence=confidence,
            reason="rsi_ema_macd_cross_up",
            indicators=indicators,
        )

    # --- LONG EXIT conditions (any one triggers) ---
    macd_cross_dn = (
        float(c["macd"]) < float(c["macd_signal"])
        and float(p["macd"]) >= float(p["macd_signal"])
    )
    ema_trend_dn = float(c["ema_fast"]) < float(c["ema_slow"])
    rsi_overbought = float(c["rsi"]) > settings.rsi_overbought

    exit_reasons = []
    if macd_cross_dn:
        exit_reasons.append("macd_cross_down")
    if ema_trend_dn:
        exit_reasons.append("ema_bearish")
    if rsi_overbought:
        exit_reasons.append("rsi_overbought")

    if exit_reasons:
        reason = "|".join(exit_reasons)
        logger.info("[%s] SELL signal — %s RSI=%.1f", symbol, reason, c["rsi"])
        return SignalResult(
            action=Action.SELL,
            symbol=symbol,
            reason=reason,
            indicators=indicators,
        )

    return SignalResult(action=Action.HOLD, symbol=symbol, indicators=indicators)


def _score_long(c: pd.Series, p: pd.Series) -> float:
    """Simple confidence score 0.0–1.0 based on signal strength."""
    score = 0.5
    rsi = float(c["rsi"])
    # RSI between 35–50 is ideal for entry (strong recovery, not overbought)
    if 35 <= rsi <= 50:
        score += 0.2
    # MACD histogram growing
    macd_hist = float(c["macd_hist"])
    prev_hist = float(p["macd_hist"]) if not pd.isna(p["macd_hist"]) else 0.0
    if macd_hist > prev_hist:
        score += 0.2
    # EMA separation (fast well above slow)
    ema_gap = (float(c["ema_fast"]) - float(c["ema_slow"])) / float(c["ema_slow"])
    if ema_gap > 0.002:
        score += 0.1
    return min(round(score, 2), 1.0)
