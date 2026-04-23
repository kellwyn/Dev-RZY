---
name: slot-market-char
description: Runs the 48-slot 30-min market character analysis for a symbol and duration. Shows directional bias, volatility labels, RSI, volume vs ICT session and daily baselines, money spent, and big/tight candle frequency per period. Usage: /slot-market-char XAUUSD 3M
---

Run the 48-slot market character analysis for symbol and duration from $ARGUMENTS.

Parse $ARGUMENTS as:
- First word = SYMBOL  (e.g. XAUUSD, GOLD.f, XAUUSDp)
- Second word = DURATION (e.g. 1M, 3M, 6M, 1Y — default 3M if omitted)
- Optional flag: `--rth` to restrict to RTH bars only

1. **Navigate to the signal lab**:
```bash
cd /c/Users/kellw/OneDrive/Dev-RZY/marci-signal-lab
```

2. **Run the analysis**:
```bash
python -u -c "
import sys
import MetaTrader5 as mt5

from config           import LabConfig
from fetcher          import fetch_ohlcv
from slot_market_char import compute_slot_market_char, compute_rth_slots, print_slot_market_char

SYMBOL   = 'SYMBOL_HERE'
DURATION = 'DURATION_HERE'
USE_RTH  = False   # set True for --rth flag

cfg = LabConfig(symbol=SYMBOL)

if not mt5.initialize():
    print(f'MT5 init failed: {mt5.last_error()}')
    sys.exit(1)

try:
    print(f'Fetching {SYMBOL} M30 — {DURATION}...')
    df = fetch_ohlcv(cfg, DURATION)
    print(f'  {len(df):,} bars loaded  ({df[\"time\"].iloc[0].date()} → {df[\"time\"].iloc[-1].date()})')

    if USE_RTH:
        char = compute_rth_slots(df, cfg)
        title = '48-SLOT MARKET CHARACTER  [RTH ONLY]'
    else:
        char = compute_slot_market_char(df, cfg)
        title = '48-SLOT MARKET CHARACTER  [ALL SESSIONS]'

    # Print full table sorted by avg_volume (most active slots first)
    print_slot_market_char(char, cfg, title=title, top_n=48, sort_by='avg_volume')

    # Also print top 10 by directional bias strength
    print()
    print_slot_market_char(
        char[char['n_bars'] >= 10],
        cfg,
        title='TOP 10 SLOTS BY DIRECTIONAL BIAS STRENGTH',
        top_n=10,
        sort_by='bias_score',
    )

finally:
    mt5.shutdown()
"
```

3. **Interpret the output**:

| Column | Meaning |
|---|---|
| `%Buy / %Sell` | Directional bias — % of bars in this slot that closed up / down |
| `Bias` | `%Buy − %Sell` — positive = bullish slot, negative = bearish |
| `VolatLbl` | HIGH/NORMAL/LOW — percentile rank of annualised HV across all 48 slots |
| `RSI` | Average RSI(14) value across all bars in this slot |
| `VolLbl` | HIGH ≥ 1.5× daily bar mean  \|  LOW ≤ 0.5× daily mean |
| `AvgTickVol` | Average MT5 tick_volume (proxy for traded quantity) |
| `%ICTVol` | Slot avg tick_vol as % of avg ICT-session bar volume |
| `%DailyVol` | Slot avg tick_vol as % of overall daily bar mean |
| `%Big` | % of bars that are big-move candles (body ≥ cfg.big_move_pct) |
| `%Tight` | % of bars that are tight-range candles (H-L < cfg.tight_range_pct) |
| `MoneySpent` | avg(tick_volume × close) — dollar-turnover proxy per bar |

**Key signals to look for:**
- Slots with HIGH VolatLbl + HIGH VolLbl = most active, highest conviction moves
- Slots with bias_score > +20 consistently = structurally bullish time windows
- Slots with HIGH MoneySpent but NORMAL VolLbl = large orders absorbing quietly
- Big tight-range clusters = potential accumulation / stop-hunt zones
