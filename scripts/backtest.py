#!/usr/bin/env python3
"""
Offline backtest runner.

Usage:
    python scripts/backtest.py --symbol BTCUSDT --start 2024-01-01 --end 2024-12-31

Fetches historical klines from Binance public API (no auth needed),
runs the same strategy + risk manager, and prints a trade summary.
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import csv
from datetime import datetime, timezone

import httpx
import pandas as pd

from app.services.strategy import evaluate, Action
from app.services.risk_manager import RiskManager
from app.config import settings


BINANCE_PUBLIC_API = "https://api.binance.com/api/v3/klines"


async def fetch_klines(symbol: str, interval: str, start: str, end: str) -> list:
    start_ms = int(datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)

    all_klines = []
    async with httpx.AsyncClient(timeout=30) as client:
        while start_ms < end_ms:
            resp = await client.get(BINANCE_PUBLIC_API, params={
                "symbol": symbol,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1000,
            })
            resp.raise_for_status()
            klines = resp.json()
            if not klines:
                break
            all_klines.extend(klines)
            start_ms = klines[-1][0] + 1
            if len(klines) < 1000:
                break

    return all_klines


def klines_to_df(klines: list) -> pd.DataFrame:
    return pd.DataFrame({
        "open_time": [k[0] for k in klines],
        "open": [float(k[1]) for k in klines],
        "high": [float(k[2]) for k in klines],
        "low": [float(k[3]) for k in klines],
        "close": [float(k[4]) for k in klines],
        "volume": [float(k[5]) for k in klines],
    })


def run_backtest(df: pd.DataFrame, symbol: str, initial_balance: float = 10000.0):
    rm = RiskManager()
    rm.set_symbol_filters(symbol, step_size=0.00001, min_notional=10.0)

    balance = initial_balance
    trades = []
    open_trade = None

    for i in range(60, len(df)):
        window = df.iloc[:i + 1]
        signal = evaluate(window, symbol=symbol)

        if signal.action == Action.BUY and open_trade is None:
            price = float(df.iloc[i]["close"])
            pos = rm.calculate_position(symbol, price, balance)
            if pos is None:
                continue
            open_trade = {
                "entry_idx": i,
                "entry_price": price,
                "quantity": pos.quantity,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                "entry_time": datetime.utcfromtimestamp(df.iloc[i]["open_time"] / 1000),
            }
            balance -= pos.position_size_usdt

        elif open_trade is not None:
            price = float(df.iloc[i]["close"])
            hl = df.iloc[i]

            exit_price = None
            exit_reason = None

            if float(hl["low"]) <= open_trade["stop_loss"]:
                exit_price = open_trade["stop_loss"]
                exit_reason = "SL"
            elif float(hl["high"]) >= open_trade["take_profit"]:
                exit_price = open_trade["take_profit"]
                exit_reason = "TP"
            elif signal.action == Action.SELL:
                exit_price = price
                exit_reason = "SIGNAL"

            if exit_price is not None:
                pnl = (exit_price - open_trade["entry_price"]) * open_trade["quantity"]
                pnl_pct = (exit_price - open_trade["entry_price"]) / open_trade["entry_price"] * 100
                balance += open_trade["quantity"] * exit_price
                trades.append({
                    "symbol": symbol,
                    "entry_time": open_trade["entry_time"],
                    "exit_time": datetime.utcfromtimestamp(df.iloc[i]["open_time"] / 1000),
                    "entry_price": round(open_trade["entry_price"], 4),
                    "exit_price": round(exit_price, 4),
                    "quantity": open_trade["quantity"],
                    "pnl_usdt": round(pnl, 4),
                    "pnl_pct": round(pnl_pct, 4),
                    "exit_reason": exit_reason,
                })
                open_trade = None

    return trades, balance


def print_summary(trades, initial, final):
    total = len(trades)
    wins = [t for t in trades if t["pnl_usdt"] > 0]
    losses = [t for t in trades if t["pnl_usdt"] <= 0]
    win_rate = len(wins) / total * 100 if total > 0 else 0
    total_pnl = sum(t["pnl_usdt"] for t in trades)

    print(f"\n{'='*50}")
    print(f"  BACKTEST RESULTS")
    print(f"{'='*50}")
    print(f"  Total trades   : {total}")
    print(f"  Winners        : {len(wins)} ({win_rate:.1f}%)")
    print(f"  Losers         : {len(losses)}")
    print(f"  Total PnL      : {total_pnl:+.2f} USDT")
    print(f"  Return         : {(final - initial) / initial * 100:+.2f}%")
    print(f"  Final balance  : {final:.2f} USDT (started {initial:.2f})")
    if wins:
        print(f"  Best trade     : +{max(t['pnl_usdt'] for t in wins):.2f} USDT")
    if losses:
        print(f"  Worst trade    : {min(t['pnl_usdt'] for t in losses):.2f} USDT")
    print(f"{'='*50}\n")


async def main():
    parser = argparse.ArgumentParser(description="Binance trading bot backtest")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--balance", type=float, default=10000.0)
    parser.add_argument("--output", default=None, help="CSV output file path")
    args = parser.parse_args()

    print(f"Fetching {args.symbol} {args.interval} klines from {args.start} to {args.end}...")
    klines = await fetch_klines(args.symbol, args.interval, args.start, args.end)
    print(f"Downloaded {len(klines)} candles")

    df = klines_to_df(klines)
    trades, final_balance = run_backtest(df, args.symbol, initial_balance=args.balance)
    print_summary(trades, args.balance, final_balance)

    if args.output:
        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys() if trades else [])
            writer.writeheader()
            writer.writerows(trades)
        print(f"Results saved to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
