#!/usr/bin/env python3
"""
exchange_rate.py — JPY/USD exchange rate utility.
Reads from config/exchange_rate.json if available, otherwise defaults to 150.
"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE / "config" / "exchange_rate.json"

_DEFAULT_JPY_PER_USD = 150.0


def get_jpy_per_usd() -> float:
    """Return the current JPY per USD exchange rate."""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            rate = data.get("jpy_per_usd", data.get("rate", _DEFAULT_JPY_PER_USD))
            return float(rate)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return _DEFAULT_JPY_PER_USD


def usd_to_jpy(usd: float) -> float:
    """Convert USD amount to JPY."""
    return usd * get_jpy_per_usd()


if __name__ == "__main__":
    rate = get_jpy_per_usd()
    print(f"Exchange rate: 1 USD = {rate:.2f} JPY")
    print(f"Example: $10.00 = {usd_to_jpy(10.0):,.0f} JPY")
