---
name: diagnostic-scan
description: Runs a one-shot filter diagnostic on the active bot to identify which rules are passing or blocking. Use when the bot reports "No setup detected" and you need to know why.
---

Run a filter-by-filter diagnostic scan on the bot for symbol $ARGUMENTS (default: auto-detect).

1. **Determine the symbol** — use $ARGUMENTS if provided, otherwise auto-detect from the running bot:

```bash
# On Windows: read command-line args of any running Python process to find --symbol
powershell -Command "Get-WmiObject Win32_Process -Filter \"Name='python.exe' OR Name='python3.exe'\" | Select-Object ProcessId, CommandLine | Format-List"
```

Parse the output:
- Look for `main.py` processes with `--symbol SYM` or `--profile NAME` arguments
- If `--symbol XAUUSDp` is visible → use `XAUUSDp`
- If `--profile blackbull-spot` → check `.env` for `PROFILE_BLACKBULL_SPOT_SYMBOL`
- If no running bot found, read `main.py` cfg defaults (usually `XAUUSD`)
- **Never default to `GOLD.f`** — that is a MetaQuotes demo symbol only

2. **Check if the bot is already running** — if it is, its own terminal output shows live filter state. Check TaskOutput or ask the user to copy the current dashboard line. Only run a separate diagnostic if the live terminal isn't accessible.

3. **Find the bot directory**:
```bash
BOT_DIR=$(find . -maxdepth 1 -type d -name "*-python-bot" | head -1)
echo "Bot dir: $BOT_DIR"
```

4. **Run the diagnostic** — substitute the detected symbol for `SYMBOL_HERE`:

```bash
cd "$BOT_DIR" && python -u -c "
from pathlib import Path
from dotenv import load_dotenv
import os
_bot = Path.cwd()
load_dotenv(_bot.parent / '.env', override=True)   # root: strategy params
load_dotenv(_bot / '.env',        override=True)   # local: symbol/connection overrides
os.environ['SYMBOL'] = 'SYMBOL_HERE'               # explicit symbol wins last

from bot.connection import connect; connect()
import MetaTrader5 as mt5
from bot.strategy import (
    StrategyConfig,
    _fetch, _gap_guard, is_in_trading_session, check_and_update_tp_state,
    is_post_tp_cooldown, is_big_move_cooldown, is_near_key_level,
    _find_short_setup, _find_long_setup,
    _confirm_short_entry, _confirm_long_entry,
    _pip_size, get_current_session
)

def _f(k, d): return float(os.getenv(k, d))
def _i(k, d): return int(os.getenv(k, d))
def _b(k, d):
    v = os.getenv(k); return d if v is None else v.strip().lower() in ('true','1','yes')
def _s(k, d): return os.getenv(k, d)

cfg = StrategyConfig(
    symbol=_s('SYMBOL','XAUUSD'), timeframe=_s('TIMEFRAME','M1'),
    candle_count=_i('CANDLE_COUNT',20), big_x_move_pct=_f('BIG_X_MOVE_PCT',0.1),
    minor_max_pips=_f('MINOR_MAX_PIPS',5000.0), y_min_pct=_f('Y_MIN_PCT',25.0),
    tp_multiplier=_f('TP_MULTIPLIER',50.0), min_tp_dist=_f('MIN_TP_DIST',1.0),
    min_impulse_pips=_f('MIN_IMPULSE_PIPS',5.0),
    min_pullback_pct=_f('MIN_PULLBACK_PCT',2.0), max_pullback_pct=_f('MAX_PULLBACK_PCT',70.0),
    use_session=_b('USE_SESSION',False), gmt_offset=_i('GMT_OFFSET',0),
    asian_start_h=_i('ASIAN_START_H',23), asian_end_h=_i('ASIAN_END_H',9),
    london_start_h=_i('LONDON_START_H',7), london_end_h=_i('LONDON_END_H',16),
    ny_start_h=_i('NY_START_H',12), ny_end_h=_i('NY_END_H',17),
    use_post_tp_cooldown=_b('USE_POST_TP_COOLDOWN',True),
    post_tp_cooldown_mins=_i('POST_TP_COOLDOWN_MINS',20),
    use_big_move_cooldown=_b('USE_BIG_MOVE_COOLDOWN',True),
    big_move_pct=_f('BIG_MOVE_PCT',1.0), big_move_cooldown_bars=_i('BIG_MOVE_COOLDOWN_BARS',20),
    use_key_level=_b('USE_KEY_LEVEL',True), key_level_pips=_f('KEY_LEVEL_PIPS',10.0),
    max_zone_candles=_i('MAX_ZONE_CANDLES',3),
    max_structure_bars=_i('MAX_STRUCTURE_BARS',5), m1_structure_bars=_i('M1_STRUCTURE_BARS',10),
    magic=_i('MAGIC_NUMBER',20260412), slippage=_i('SLIPPAGE',20),
)

print(f'Symbol          : {cfg.symbol}')
df = _fetch(cfg.symbol, cfg.timeframe, cfg.candle_count)
if df is None:
    print(f'FETCH FAILED — {mt5.last_error()}')
    print('  Check: symbol name correct? Symbol visible in Market Watch?')
    mt5.shutdown(); exit()
highs  = df['h'].values.astype(float); lows   = df['l'].values.astype(float)
closes = df['c'].values.astype(float); opens  = df['o'].values.astype(float)
pip    = _pip_size(cfg.symbol)
tick   = mt5.symbol_info_tick(cfg.symbol)
print(f'bid/ask         : {tick.bid:.2f} / {tick.ask:.2f}')
if tick.bid == 0.0:
    print('  WARNING: bid=0 — symbol may not be in Market Watch or market is closed')
print(f'Gap guard       : {_gap_guard(df)}')
print(f'Session         : {is_in_trading_session(cfg)} ({get_current_session(cfg)})')
check_and_update_tp_state(cfg)
print(f'Post-TP cooldown: {is_post_tp_cooldown(closes[-1], cfg)}')
s  = _find_short_setup(highs, lows, opens, closes, cfg, pip)
lg = _find_long_setup(highs,  lows, opens, closes, cfg, pip)
print(f'SHORT structure : {\"FOUND\" if s  else \"not found\"}')
if s:
    ok, epx = _confirm_short_entry(s, highs, lows, closes, float(tick.bid), cfg)
    print(f'  entry confirm : {ok}  (eff_pb={epx:.2f})')
    print(f'  big move cd   : {is_big_move_cooldown(\"SHORT\", opens, closes, cfg)}')
    print(f'  key level     : {is_near_key_level(cfg.symbol, tick.bid, \"SHORT\", cfg)}')
print(f'LONG  structure : {\"FOUND\" if lg else \"not found\"}')
if lg:
    ok, epx = _confirm_long_entry(lg, highs, lows, closes, float(tick.ask), cfg)
    print(f'  entry confirm : {ok}  (eff_pb={epx:.2f})')
    print(f'  big move cd   : {is_big_move_cooldown(\"LONG\", opens, closes, cfg)}')
    print(f'  key level     : {is_near_key_level(cfg.symbol, tick.ask, \"LONG\", cfg)}')
mt5.shutdown()
"
```

5. **Interpret the output**:
   - **FETCH FAILED** — symbol name wrong or not in Market Watch; check broker suffix (`XAUUSDp`, `XAUUSD`, `GOLD.f`)
   - **bid=0 WARNING** — symbol not visible in Market Watch or market is closed
   - **Gap guard FAIL** — most recent bar opened outside prior bar's range; clears next bar
   - **Session blocked** — ICT session filter active; check `USE_SESSION` setting
   - **Post-TP cooldown** — TP exit within cooldown window + big move; wait for cooldown to expire
   - **Structure not found** — no valid impulse→minor→pullback sequence in lookback window; normal, just waiting
   - **Entry confirm false** — structure found but zone candle gate or price zone check failed
   - **Big move cooldown** — 1%+ bar within last 20 bars in trade direction; wait for bars to roll off
   - **Key level block** — price within 10 pips of ATH/ATL/weekly pivot; consider adjusting `KEY_LEVEL_PIPS`
