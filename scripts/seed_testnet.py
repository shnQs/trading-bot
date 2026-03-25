#!/usr/bin/env python3
"""
Verify Binance testnet connectivity and check account balance.
Run this before starting the bot to confirm your API keys work.

Usage:
    python scripts/seed_testnet.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from app.services.exchange import exchange
from app.config import settings


async def main():
    if not settings.binance_testnet:
        print("WARNING: BINANCE_TESTNET is false — this will query the live exchange!")
        input("Press Enter to continue or Ctrl+C to abort...")

    if not settings.binance_api_key or settings.binance_api_key == "your_testnet_api_key_here":
        print("ERROR: Please set BINANCE_API_KEY in your .env file")
        print("Get testnet keys from: https://testnet.binance.vision/")
        sys.exit(1)

    print(f"Connecting to Binance (testnet={settings.binance_testnet})...")
    await exchange.connect()

    print("\nFetching account balances...")
    balances = await exchange.get_account_balance()

    print(f"\n{'Asset':<10} {'Free Balance':>15}")
    print("-" * 26)
    for asset, amount in sorted(balances.items()):
        if amount > 0:
            print(f"{asset:<10} {amount:>15.6f}")

    usdt = balances.get("USDT", 0)
    if usdt >= 1000:
        print(f"\n✓ Testnet ready — {usdt:.2f} USDT available")
    else:
        print(f"\n⚠ Only {usdt:.2f} USDT available. Visit https://testnet.binance.vision/ to get test funds.")

    print("\nFetching symbol filters for trading pairs...")
    for symbol in settings.trading_pairs:
        info = await exchange.get_symbol_info(symbol)
        status = info.get("status", "UNKNOWN")
        print(f"  {symbol}: {status}")

    await exchange.disconnect()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
