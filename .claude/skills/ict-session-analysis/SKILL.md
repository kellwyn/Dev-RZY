---
name: ict-session-analysis
description: Runs the ICT RTH daily session analysis for the last 20 days with 30-day rolling baselines. Shows session volume vs baseline, daily volume vs baseline, money spent, directional bias, RSI, volatility, and flags anomalies. Usage: /ict-session-analysis XAUUSD
---

Run the ICT RTH session daily analysis for symbol from $ARGUMENTS.

Parse $ARGUMENTS as:
- First word = SYMBOL (e.g. XAUUSD, GOLD.f, XAUUSDp — default XAUUSD)

1. **Navigate to the signal lab**:
```bash
cd /c/Users/kellw/OneDrive/Dev-RZY/marci-signal-lab
```

2. **Run the analysis** (fetches 3M to build 30-day rolling baselines + 20-day display window):
```bash
python -u -c "
import sys
import MetaTrader5 as mt5

from config              import LabConfig
from fetcher             import fetch_ohlcv
from ict_session_daily   import build_ict_session_daily, print_ict_session_daily

SYMBOL = 'SYMBOL_HERE'

# RTH window defaults: 13:30–20:00 UTC (COMEX gold floor)
# For NQ/US equities use: rth_start_h=14, rth_start_m=30, rth_end_h=21, rth_end_m=0
cfg = LabConfig(
    symbol=SYMBOL,
    use_rth=True,
)

if not mt5.initialize():
    print(f'MT5 init failed: {mt5.last_error()}')
    sys.exit(1)

try:
    # Fetch 3M for sufficient rolling baseline history
    print(f'Fetching {SYMBOL} M30 — 3M (for 30-day rolling baselines)...')
    df = fetch_ohlcv(cfg, '3M')
    print(f'  {len(df):,} bars loaded  ({df[\"time\"].iloc[0].date()} → {df[\"time\"].iloc[-1].date()})')

    result = build_ict_session_daily(df, cfg)
    print_ict_session_daily(result, cfg)

    # Summary anomaly digest
    anomalous = result[result['anomaly'].str.len() > 0]
    if not anomalous.empty:
        print()
        print('  ANOMALY DIGEST:')
        for _, row in anomalous.iterrows():
            print(f'    {row[\"date\"]}  →  {row[\"anomaly\"]}')
    else:
        print()
        print('  No anomalies detected in the last 20 days.')

finally:
    mt5.shutdown()
"
```

3. **Interpret the output**:

| Column | Meaning |
|---|---|
| `SessVol` | Total tick_volume across all RTH slots that day |
| `30dSessBaseline` | 30-day rolling mean of SessVol (what's normal) |
| `%vsSess` | SessVol / 30d baseline × 100  — 100% = exactly average |
| `DailyVol` | Total tick_volume across ALL bars that day (24h) |
| `30dDailyBaseline` | 30-day rolling mean of DailyVol |
| `%vsDaily` | DailyVol / 30d baseline × 100 |
| `MoneySpent` | Σ(tick_volume × close) for RTH bars — proxy for capital deployed |
| `%Buyers / %Sellers` | % of RTH bars closing up / down |
| `AvgRSI` | Mean RSI(14) across all RTH bars that day |
| `Volat` | HIGH/NORMAL/LOW — avg range_pct vs 30-day rolling ± 1.5σ |
| `Anomalies` | Metrics that deviated > 1.5σ from 30-day rolling baseline |
| `*** row` | Day flagged with at least one anomaly |

**Anomaly codes:**
- `session_vol↑(+2.3σ)` — session volume 2.3 std above 30-day mean (unusually active)
- `session_vol↓(-1.8σ)` — session volume unusually quiet
- `daily_vol↑/↓` — full-day volume anomaly
- `RSI↑(72)` / `RSI↓(28)` — overbought / oversold session
- `BUYER_DOM` / `SELLER_DOM` — ≥ 70% of RTH bars in one direction
- `VOL↑` / `VOL↓` — range-based volatility anomaly

**Common patterns:**
- `session_vol↑` + `BUYER_DOM` on the same day = institutional accumulation / distribution spike
- `session_vol↓` + low `MoneySpent` = thin market / range day, avoid trading
- `VOL↑` + `RSI↑(>70)` = extended move, watch for reversal next session
- Consecutive `session_vol↓` days followed by `session_vol↑` = coil compression breakout
