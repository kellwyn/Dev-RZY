"""
Marci Silfrain — Measured Move Trend Strategy  (Expert Advisor)

Scans configured symbols and timeframes for "Little RZY" structures.
Prints a full strategy checklist for every detected setup, then waits
for your manual confirmation before sending any order to MT5.

Usage:
  1. Copy .env.example to .env and fill in your symbols / settings
  2. pip install -r requirements.txt
  3. python main.py
"""

import os
import time
from dotenv import load_dotenv

from bot.connection import connect, disconnect
from bot.strategy   import scan_all, print_dashboard
from bot.trader     import confirm_and_execute

load_dotenv()

SYMBOLS       = [s.strip() for s in os.getenv("SYMBOLS",       "NAS100,US500").split(",")]
TIMEFRAMES    = [t.strip() for t in os.getenv("TIMEFRAMES",    "H4,D1").split(",")]
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL",  "60"))
RISK_PERCENT  = float(os.getenv("RISK_PERCENT", "1.0"))
MIN_RR        = float(os.getenv("MIN_RR",       "1.5"))
CANDLES       = int(os.getenv("CANDLES",        "200"))
SWING_N       = int(os.getenv("SWING_LOOKBACK", "3"))

# Tracks setups already shown this session so the prompt isn't repeated
# for the same setup on every scan tick.
_alerted: set = set()


def _alert_key(setup) -> str:
    """Unique fingerprint for a setup — resets if entry price changes."""
    return f"{setup.symbol}|{setup.timeframe}|{setup.direction}|{setup.entry:.5f}"


def run():
    print(f"\n  Starting scanner...")
    print(f"  Symbols   : {', '.join(SYMBOLS)}")
    print(f"  Timeframes: {', '.join(TIMEFRAMES)}")
    print(f"  Interval  : every {SCAN_INTERVAL}s  |  Ctrl+C to stop\n")

    while True:
        try:
            setups = scan_all(SYMBOLS, TIMEFRAMES, CANDLES, SWING_N, MIN_RR)
            print_dashboard(setups, SYMBOLS, TIMEFRAMES)

            for setup in setups:
                key = _alert_key(setup)
                if key not in _alerted:
                    _alerted.add(key)
                    confirm_and_execute(setup, RISK_PERCENT)

            if not setups:
                # Expire old alerts so fresh ones appear after conditions reset
                _alerted.clear()

            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            print("\n  Stopped by user.")
            break
        except SystemExit:
            break
        except Exception as e:
            print(f"  ERROR: {e}")
            time.sleep(SCAN_INTERVAL)


def main():
    try:
        connect()
        run()
    finally:
        disconnect()


if __name__ == "__main__":
    main()
