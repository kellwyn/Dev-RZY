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
import os; os.environ['SYMBOL'] = 'SYMBOL_HERE'
from dotenv import load_dotenv; load_dotenv()
from bot.connection import connect; connect()
import MetaTrader5 as mt5
from bot.strategy import (
    _fetch, _gap_guard, is_in_trading_session, check_and_update_tp_state,
    is_post_tp_cooldown, is_big_move_cooldown, is_near_key_level,
    _find_short_setup, _find_long_setup,
    _confirm_short_momentum, _confirm_long_momentum,
    _pip_size, get_current_session
)
from main import cfg
print(f'Symbol          : {cfg.symbol}')
df    = _fetch(cfg.symbol, cfg.timeframe, cfg.candle_count)
if df is None:
    print(f'FETCH FAILED — {mt5.last_error()}')
    print('  Check: symbol name correct? Symbol visible in Market Watch?')
    mt5.shutdown()
    exit()
highs = df['h'].values.astype(float); lows = df['l'].values.astype(float)
closes= df['c'].values.astype(float); opens= df['o'].values.astype(float)
pip   = _pip_size(cfg.symbol)
tick  = mt5.symbol_info_tick(cfg.symbol)
print(f'bid/ask         : {tick.bid:.2f} / {tick.ask:.2f}')
if tick.bid == 0.0:
    print('  WARNING: bid=0 — symbol may not be in Market Watch or market is closed')
print(f'Gap guard       : {_gap_guard(df)}')
print(f'Session         : {is_in_trading_session(cfg)} ({get_current_session(cfg)})')
check_and_update_tp_state(cfg)
print(f'Post-TP cooldown: {is_post_tp_cooldown(closes[-1], cfg)}')
s  = _find_short_setup(highs, lows, cfg, pip)
lg = _find_long_setup(highs,  lows, cfg, pip)
print(f'SHORT structure : {\"FOUND\" if s  else \"not found\"}')
if s:
    print(f'  momentum    : {_confirm_short_momentum(closes, s[\"pb_idx\"])}')
    print(f'  entry zone  : {s[\"minor_px\"] < tick.bid < s[\"pb_px\"]}')
    print(f'  big move cd : {is_big_move_cooldown(\"SHORT\", opens, closes, cfg)}')
    print(f'  key level   : {is_near_key_level(cfg.symbol, tick.bid, \"SHORT\", cfg)}')
print(f'LONG  structure : {\"FOUND\" if lg else \"not found\"}')
if lg:
    print(f'  momentum    : {_confirm_long_momentum(closes, lg[\"pb_idx\"])}')
    print(f'  entry zone  : {lg[\"pb_px\"] < tick.ask < lg[\"minor_px\"]}')
    print(f'  big move cd : {is_big_move_cooldown(\"LONG\",  opens, closes, cfg)}')
    print(f'  key level   : {is_near_key_level(cfg.symbol, tick.ask,  \"LONG\",  cfg)}')
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
   - **Momentum false** — structure found but 2-bar confirmation not yet formed
   - **Entry zone false** — structure found but price outside minor↔pullback range
   - **Big move cooldown** — 1%+ bar within last 20 bars in trade direction; wait for bars to roll off
   - **Key level block** — price within 10 pips of ATH/ATL/weekly pivot; consider adjusting `KEY_LEVEL_PIPS`
