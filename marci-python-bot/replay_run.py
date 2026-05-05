"""
Replay CLI — Marci Measured Move v2.01

Feeds historical OHLCV bars from MT5 into the bot's strategy logic bar-by-bar.
No real orders are placed. Outcomes are simulated from forward bar data.

Usage:
    cd marci-python-bot
    python replay_run.py --from 2025-01-01 --to 2025-04-30
    python replay_run.py --from 2025-04-01 --to 2025-04-30 --profile blackbull-spot
    python replay_run.py --from 2025-04-01 --to 2025-04-30 --symbol XAUUSDp
    python replay_run.py --from 2025-04-01 --to 2025-04-30 --spread 0.30 --sleep 50

Options:
    --from YYYY-MM-DD   Start date (UTC midnight, inclusive)
    --to   YYYY-MM-DD   End date (UTC 23:59, inclusive)
    --symbol SYM        Symbol override (e.g. XAUUSDp)
    --profile NAME      Broker profile from .env (e.g. blackbull-spot)
    --spread FLOAT      Ask–bid spread in price units (default 0.0)
    --sleep  INT        Milliseconds to pause between bars — 0 = fast forward

Does NOT import from main.py (main.py has module-level argparse that conflicts).
Config is built inline from .env using the same helper pattern as main.py.

Tip: replay always forces use_post_tp_cooldown=False because there are no MT5
     deal history entries for simulated trades.  All other filters (big move
     cooldown, key levels, session, gap guard) run as configured in .env.
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
_here = Path(__file__).parent
load_dotenv(_here.parent / ".env", override=True)  # root: strategy params
load_dotenv(_here / ".env",        override=True)  # local: symbol/connection overrides

from bot.connection import connect, disconnect
from bot.replay     import ReplayEngine
from bot.strategy   import StrategyConfig, setup_logging


# ── Config helpers (mirrors main.py — not imported to avoid argparse conflict) ─

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


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Marci Measured Move Replay  v2.01",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--from",    dest="date_from", required=True,
                        metavar="YYYY-MM-DD", help="Replay start date (UTC)")
    parser.add_argument("--to",      dest="date_to",   required=True,
                        metavar="YYYY-MM-DD", help="Replay end date (UTC)")
    parser.add_argument("--symbol",  metavar="SYM",    default=None,
                        help="Symbol override (e.g. XAUUSDp)")
    parser.add_argument("--profile", metavar="NAME",   default=None,
                        help="Broker profile name from .env")
    parser.add_argument("--spread",  type=float, default=0.0,
                        metavar="FLOAT",
                        help="Ask–bid spread in price units (default 0.0)")
    parser.add_argument("--sleep",   type=int, default=0,
                        metavar="MS",
                        help="Pause in ms between bars; 0 = fast forward")
    args = parser.parse_args()

    # ── Profile resolution ────────────────────────────────────────────────────
    if args.profile:
        key = args.profile.upper().replace("-", "_")
        sym      = os.getenv(f"PROFILE_{key}_SYMBOL")
        path     = os.getenv(f"PROFILE_{key}_MT5_PATH")
        login    = os.getenv(f"PROFILE_{key}_MT5_LOGIN")
        password = os.getenv(f"PROFILE_{key}_MT5_PASSWORD")
        server   = os.getenv(f"PROFILE_{key}_MT5_SERVER")
        if sym is None:
            print(f"  ERROR: profile '{args.profile}' not found in .env "
                  f"(expected PROFILE_{key}_SYMBOL)")
            sys.exit(1)
        if sym:      os.environ["SYMBOL"]       = sym
        if path:     os.environ["MT5_PATH"]     = path
        if login:    os.environ["MT5_LOGIN"]    = login
        if password: os.environ["MT5_PASSWORD"] = password
        if server:   os.environ["MT5_SERVER"]   = server

    if args.symbol:
        os.environ["SYMBOL"] = args.symbol

    # ── Build config ──────────────────────────────────────────────────────────
    cfg = StrategyConfig(
        symbol         = _str("SYMBOL",          "XAUUSD"),
        timeframe      = _str("TIMEFRAME",        "M1"),
        manual_confirm = False,

        risk_pct       = _float("RISK_PERCENT",   0.15),
        min_rr         = _float("MIN_RR",         0.0),
        max_lots       = _float("MAX_LOTS",        7.0),

        candle_count   = _int("CANDLE_COUNT",     20),
        big_x_move_pct = _float("BIG_X_MOVE_PCT", 0.1),
        minor_max_pips = _float("MINOR_MAX_PIPS", 5000.0),
        y_min_pct      = _float("Y_MIN_PCT",      25.0),
        tp_multiplier  = _float("TP_MULTIPLIER",  50.0),

        min_impulse_pips = _float("MIN_IMPULSE_PIPS", 5.0),
        min_pullback_pct = _float("MIN_PULLBACK_PCT",  2.0),
        max_pullback_pct = _float("MAX_PULLBACK_PCT", 70.0),

        use_session      = _bool("USE_SESSION",    False),
        gmt_offset       = _int("GMT_OFFSET",      0),
        asian_start_h    = _int("ASIAN_START_H",   23),
        asian_end_h      = _int("ASIAN_END_H",     9),
        london_start_h   = _int("LONDON_START_H",  7),
        london_end_h     = _int("LONDON_END_H",    16),
        ny_start_h       = _int("NY_START_H",      12),
        ny_end_h         = _int("NY_END_H",        17),

        # Post-TP cooldown is always off in replay — no real MT5 deal history
        use_post_tp_cooldown  = False,
        post_tp_cooldown_mins = _int("POST_TP_COOLDOWN_MINS", 20),

        use_big_move_cooldown  = _bool("USE_BIG_MOVE_COOLDOWN",  True),
        big_move_pct           = _float("BIG_MOVE_PCT",          1.0),
        big_move_cooldown_bars = _int("BIG_MOVE_COOLDOWN_BARS",  20),

        use_key_level  = _bool("USE_KEY_LEVEL",  True),
        key_level_pips = _float("KEY_LEVEL_PIPS", 10.0),

        max_zone_candles   = _int("MAX_ZONE_CANDLES",   3),
        max_structure_bars = _int("MAX_STRUCTURE_BARS", 5),
        m1_structure_bars  = _int("M1_STRUCTURE_BARS",  10),

        magic    = _int("MAGIC_NUMBER", 20260412),
        slippage = _int("SLIPPAGE",     20),
    )

    # ── Parse dates ───────────────────────────────────────────────────────────
    try:
        from_dt = datetime.strptime(args.date_from, "%Y-%m-%d").replace(
            tzinfo=timezone.utc)
        to_dt   = datetime.strptime(args.date_to, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc)
    except ValueError as exc:
        print(f"  ERROR: invalid date format — {exc}  (expected YYYY-MM-DD)")
        sys.exit(1)

    # ── Setup logging ─────────────────────────────────────────────────────────
    setup_logging(_str("LOG_LEVEL", "INFO"))

    print(f"\n  Marci Replay  —  {cfg.symbol} [{cfg.timeframe}]")
    print(f"  Period  : {from_dt.date()} → {to_dt.date()}")
    print(f"  Spread  : {args.spread}  |  sleep: {args.sleep}ms  "
          f"|  candle_count: {cfg.candle_count}")
    print(f"  X%      : {cfg.big_x_move_pct}%  |  "
          f"pullback: {cfg.min_pullback_pct}–{cfg.max_pullback_pct}%  |  "
          f"zone candles: {cfg.max_zone_candles}")

    # ── Run replay ────────────────────────────────────────────────────────────
    try:
        connect()

        engine = ReplayEngine(
            cfg      = cfg,
            from_dt  = from_dt,
            to_dt    = to_dt,
            spread   = args.spread,
            sleep_ms = args.sleep,
        )

        n = engine.load()
        print(f"  Bars    : {n:,}  (replay window: {n - cfg.candle_count:,} steps)\n")

        engine.run()
        engine.print_results()

    except RuntimeError as exc:
        print(f"\n  ERROR: {exc}")
        sys.exit(1)
    finally:
        disconnect()


if __name__ == "__main__":
    main()
