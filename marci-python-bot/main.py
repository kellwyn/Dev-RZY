"""
Marci Silfrain — Measured Move Trend Strategy  v2.01  (Python Bot)

Mirrors MarciMeasuredMove_v2.01.mq5.
Default parameters loaded from v102_settings_xauone.set (XAUUSD profile).

Usage:
  1. Copy .env.example to .env — fill in MT5 credentials and broker profiles
  2. pip install -r requirements.txt
  3. python main.py                          # uses SYMBOL / MT5_PATH from .env
     python main.py --profile metaquotes    # named broker profile
     python main.py --profile blackbull-spot
     python main.py --symbol XAUUSDp        # one-off symbol override

Environment variables override all defaults (see .env.example).
--profile and --symbol CLI args override environment variables.
"""

import argparse
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Force UTF-8 output so box-drawing characters render on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from bot.connection import connect, disconnect
from bot.strategy   import StrategyConfig, find_setup, print_dashboard, setup_logging
from bot.trader     import execute_setup

_here = Path(__file__).parent
# Load root .env first (strategy params), then local .env (symbol/connection overrides).
# override=True on both so file contents always win over stale injected env vars
# (e.g. VSCode python.terminal.useEnvFile from an older terminal session).
load_dotenv(_here.parent / ".env", override=True)  # root: strategy params
load_dotenv(_here / ".env",        override=True)  # local: symbol/connection overrides

# ── CLI arguments ─────────────────────────────────────────────────────────────

_parser = argparse.ArgumentParser(description="Marci Measured Move Bot v2.01")
_parser.add_argument("--profile", metavar="NAME",
                     help="Broker profile name defined in .env (e.g. metaquotes, blackbull-spot)")
_parser.add_argument("--symbol",  metavar="SYM",
                     help="Symbol override — takes precedence over profile and .env")
_args = _parser.parse_args()

# ── Profile resolution ────────────────────────────────────────────────────────
# Profiles are defined in .env as PROFILE_<NAME>_SYMBOL and PROFILE_<NAME>_MT5_PATH.
# A profile sets MT5_PATH and SYMBOL in the environment before cfg is built,
# so all downstream _str/_int/_float helpers pick them up automatically.

if _args.profile:
    key = _args.profile.upper().replace("-", "_")
    sym  = os.getenv(f"PROFILE_{key}_SYMBOL")
    path = os.getenv(f"PROFILE_{key}_MT5_PATH")
    login    = os.getenv(f"PROFILE_{key}_MT5_LOGIN")
    password = os.getenv(f"PROFILE_{key}_MT5_PASSWORD")
    server   = os.getenv(f"PROFILE_{key}_MT5_SERVER")
    if sym is None:
        print(f"  ERROR: profile '{_args.profile}' not found in .env "
              f"(expected PROFILE_{key}_SYMBOL)")
        sys.exit(1)
    if sym:      os.environ["SYMBOL"]       = sym
    if path:     os.environ["MT5_PATH"]     = path
    if login:    os.environ["MT5_LOGIN"]    = login
    if password: os.environ["MT5_PASSWORD"] = password
    if server:   os.environ["MT5_SERVER"]   = server

# --symbol always wins over profile / .env
if _args.symbol:
    os.environ["SYMBOL"] = _args.symbol

# ── Configuration — defaults from v102_settings_xauone.set ───────────────────

def _bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in ("true", "1", "yes")

def _int(key: str, default: int) -> int:
    return int(os.getenv(key, default))

def _float(key: str, default: float) -> float:
    return float(os.getenv(key, default))

def _str(key: str, default: str) -> str:
    return os.getenv(key, default)


cfg = StrategyConfig(
    # Instrument
    symbol         = _str("SYMBOL",          "XAUUSD"),
    timeframe      = _str("TIMEFRAME",        "M1"),

    # Execution
    manual_confirm = _bool("MANUAL_CONFIRM",  False),   # false = auto-execute

    # Risk Management
    risk_pct       = _float("RISK_PERCENT",   0.15),
    min_rr         = _float("MIN_RR",         0.0),     # 0 = disabled
    max_lots       = _float("MAX_LOTS",        7.0),

    # Strategy Parameters
    candle_count   = _int("CANDLE_COUNT",     20),
    big_x_move_pct = _float("BIG_X_MOVE_PCT", 0.1),
    minor_max_pips = _float("MINOR_MAX_PIPS", 5000.0),  # R2 hard cap; XAUUSDp: 5000=~$50
    y_min_pct      = _float("Y_MIN_PCT",      25.0),    # R2 floor: minor >= % of X move
    tp_multiplier  = _float("TP_MULTIPLIER",  50.0),

    # Pullback Strength Gates
    min_impulse_pips = _float("MIN_IMPULSE_PIPS", 5.0),
    min_pullback_pct = _float("MIN_PULLBACK_PCT",  2.0),
    max_pullback_pct = _float("MAX_PULLBACK_PCT", 70.0),

    # ICT Session Filter (Rule 8) — off by default for XAUUSD
    use_session      = _bool("USE_SESSION",    False),
    gmt_offset       = _int("GMT_OFFSET",      0),
    asian_start_h    = _int("ASIAN_START_H",   23),
    asian_end_h      = _int("ASIAN_END_H",     9),
    london_start_h   = _int("LONDON_START_H",  7),
    london_end_h     = _int("LONDON_END_H",    16),
    ny_start_h       = _int("NY_START_H",      12),
    ny_end_h         = _int("NY_END_H",        17),

    # Post-TP Cooldown (Rule 9)
    use_post_tp_cooldown  = _bool("USE_POST_TP_COOLDOWN",  True),
    post_tp_cooldown_mins = _int("POST_TP_COOLDOWN_MINS",  20),

    # Big Move Cooldown (Rule 7)
    use_big_move_cooldown  = _bool("USE_BIG_MOVE_COOLDOWN",  True),
    big_move_pct           = _float("BIG_MOVE_PCT",          1.0),
    big_move_cooldown_bars = _int("BIG_MOVE_COOLDOWN_BARS",  20),

    # Key Level Filter (Rule 7)
    use_key_level  = _bool("USE_KEY_LEVEL",  True),
    key_level_pips = _float("KEY_LEVEL_PIPS", 10.0),

    # Entry zone candle limit
    max_zone_candles = _int("MAX_ZONE_CANDLES", 3),

    # Structure timing gates (Rules 2-3)
    max_structure_bars = _int("MAX_STRUCTURE_BARS", 5),   # non-M1
    m1_structure_bars  = _int("M1_STRUCTURE_BARS",  10),  # M1 only

    # Trade Settings
    magic    = _int("MAGIC_NUMBER", 20260412),
    slippage = _int("SLIPPAGE",     20),
)

SCAN_INTERVAL = _int("SCAN_INTERVAL", 60)   # seconds between scans
LOG_LEVEL     = _str("LOG_LEVEL",     "INFO")  # DEBUG for full rule trace

setup_logging(LOG_LEVEL)

# Tracks setups already shown to avoid re-prompting on the same signal
_alerted: set = set()


def _alert_key(setup) -> str:
    # Key on peak_px so the same structure is executed at most once.
    # When find_setup returns None (structure expired), _alerted is cleared
    # and a fresh X% evaluation begins for the next structure.
    return f"{setup.symbol}|{setup.direction}|{setup.peak_px:.5f}"


# ── Main scan loop ────────────────────────────────────────────────────────────

def run():
    mode = "AUTO-EXECUTE" if not cfg.manual_confirm else "MANUAL CONFIRM"
    print(f"\n  Starting scanner — {cfg.symbol} [{cfg.timeframe}]")
    print(f"  Mode      : {mode}")
    print(f"  Risk      : {cfg.risk_pct}%  |  Max lots: {cfg.max_lots}")
    print(f"  Interval  : every {SCAN_INTERVAL}s  |  Ctrl+C to stop\n")

    while True:
        try:
            setup = find_setup(cfg)
            print_dashboard(setup, cfg)

            if setup:
                key = _alert_key(setup)
                if key not in _alerted:
                    _alerted.add(key)
                    execute_setup(setup, cfg)
            else:
                _alerted.clear()

            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            print("\n  Stopped by user.")
            break
        except SystemExit:
            break
        except Exception as exc:
            print(f"  ERROR: {exc}")
            time.sleep(SCAN_INTERVAL)


def main():
    try:
        connect()
        run()
    finally:
        disconnect()


if __name__ == "__main__":
    main()
