# SKILLS.md — Reusable Patterns

Standard patterns for MetaTrader strategy projects. Reference these when scaffolding new components.

## Invocable Skills (`.claude/skills/`)

| Skill | Command | What it does |
|---|---|---|
| `diagnostic-scan` | `/diagnostic-scan GOLD.f` | Filter-by-filter bot diagnostic |
| `deploy-ea` | `/deploy-ea` | Copy .mq5 to MetaTrader Experts folder |
| `new-strategy` | `/new-strategy SwingBB` | Scaffold a new strategy repo |

## Subagents (`.claude/agents/`)

| Agent | When to use |
|---|---|
| `code-reviewer` | After implementing a rule or filter |
| `security-reviewer` | Before any commit |
| `bot-health-check` | When bot seems stuck or silent |
| `ea-deployer` | After saving .mq5 changes |
| `git-push` | To commit and push with correct format |

---

## SKILL: MQL5_EA_SHELL

Standard EA skeleton. Every EA follows this structure.

```mql5
//+------------------------------------------------------------------+
//| StrategyName_v1.00.mq5                                           |
//| Author — Kellwyn Edwin                                           |
//+------------------------------------------------------------------+
#property copyright "Kellwyn Edwin"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

//── Inputs ─────────────────────────────────────────────────────────
input group "=== Instrument ==="
input string  InpSymbol       = "";       // blank = current chart symbol
input ENUM_TIMEFRAMES InpTF   = PERIOD_M1;

input group "=== Risk ==="
input double  InpRiskPct      = 0.15;     // % of balance per trade
input double  InpMaxLots      = 7.0;
input int     InpMagicNumber  = 20260412;
input int     InpSlippage     = 20;

input group "=== Execution ==="
input bool    InpManualConfirm = false;

//── Globals ─────────────────────────────────────────────────────────
CTrade Trade;
string g_symbol;

//── Init ─────────────────────────────────────────────────────────────
int OnInit()
{
    g_symbol = (InpSymbol == "") ? _Symbol : InpSymbol;
    Trade.SetExpertMagicNumber(InpMagicNumber);
    Trade.SetDeviationInPoints(InpSlippage);
    PrintFormat("EA init — %s [%s]  Risk %.2f%%  Magic %d",
                g_symbol, EnumToString(InpTF), InpRiskPct, InpMagicNumber);
    return INIT_SUCCEEDED;
}

//── Tick ─────────────────────────────────────────────────────────────
void OnTick()
{
    static datetime lastBar = 0;
    datetime barTime = iTime(g_symbol, InpTF, 0);
    if(barTime == lastBar) return;
    lastBar = barTime;

    if(HasOpenPosition()) return;
    RunStrategy();
}

//── Deinit ────────────────────────────────────────────────────────────
void OnDeinit(const int reason)
{
    // IndicatorRelease() any handles here
    Comment("");
}

//── Helpers ───────────────────────────────────────────────────────────
bool HasOpenPosition()
{
    for(int i = PositionsTotal() - 1; i >= 0; i--)
        if(PositionGetSymbol(i) == g_symbol &&
           PositionGetInteger(POSITION_MAGIC) == InpMagicNumber) return true;
    return false;
}

double CalcLots(double entryPrice, double slPrice)
{
    double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
    double riskAmt  = balance * InpRiskPct / 100.0;
    double slDist   = MathAbs(entryPrice - slPrice);
    double tickVal  = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_VALUE);
    double tickSize = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_SIZE);
    if(slDist == 0 || tickSize == 0 || tickVal == 0) return SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MIN);
    double lots = riskAmt / (slDist / tickSize * tickVal);
    double maxLot = MathMin(SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MAX), InpMaxLots);
    double minLot = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MIN);
    double step   = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_STEP);
    lots = MathMax(minLot, MathMin(maxLot, lots));
    if(step > 0) lots = MathFloor(lots / step) * step;
    return lots;
}

void RunStrategy() { /* implement strategy rules here */ }
```

---

## SKILL: PYTHON_BOT_SHELL

Standard Python bot structure. Every bot mirrors its EA exactly.

**`bot/signals.py`** — TradeSetup dataclass:
```python
from dataclasses import dataclass, field
from typing import List

@dataclass
class TradeSetup:
    symbol: str
    timeframe: str
    direction: str          # "LONG" or "SHORT"
    entry: float
    stop_loss: float
    target: float
    risk_reward: float
    session: str = "ALL"
    setup_notes: List[str] = field(default_factory=list)
```

**`bot/connection.py`** — MT5 connection with multi-terminal + keyring support:
```python
import os
import keyring
import MetaTrader5 as mt5

def connect():
    path     = os.getenv("MT5_PATH")
    profile  = os.getenv("KEYRING_PROFILE")
    if profile:
        login    = keyring.get_password("mt5", f"{profile}_login")
        password = keyring.get_password("mt5", f"{profile}_password")
        server   = keyring.get_password("mt5", f"{profile}_server")
    else:
        login, password, server = os.getenv("MT5_LOGIN"), os.getenv("MT5_PASSWORD"), os.getenv("MT5_SERVER")

    kwargs = {}
    if path: kwargs["path"] = path
    if login and password and server:
        kwargs.update(login=int(login), password=password, server=server)

    if not (mt5.initialize(**kwargs) if kwargs else mt5.initialize()):
        raise RuntimeError(f"MT5 connection failed: {mt5.last_error()}")

    info = mt5.account_info()
    print(f"  Connected — {info.name} (#{info.login}) | {info.server} | {info.balance:,.2f} {info.currency}")

def disconnect():
    mt5.shutdown()
```

**`bot/strategy.py`** — StrategyConfig + find_setup():
```python
from dataclasses import dataclass
from typing import Optional
import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from .signals import TradeSetup

@dataclass
class StrategyConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "M1"
    manual_confirm: bool = False
    risk_pct: float = 0.15
    min_rr: float = 0.0
    max_lots: float = 7.0
    candle_count: int = 20
    magic: int = 20260412
    slippage: int = 20
    # add strategy-specific params here

_TF_MAP = {
    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1, "MN1": mt5.TIMEFRAME_MN1,
}

def _pip_size(symbol: str) -> float:
    info = mt5.symbol_info(symbol)
    if info is None: return 0.0001
    return info.point * 10 if info.digits in (3, 5) else info.point

def _fetch(symbol: str, tf_str: str, count: int) -> Optional[pd.DataFrame]:
    tf = _TF_MAP.get(tf_str.upper())
    if tf is None: return None
    rates = mt5.copy_rates_from_pos(symbol, tf, 1, count)   # pos=1 skips forming bar
    if rates is None or len(rates) == 0: return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c"}, inplace=True)
    return df

def find_setup(cfg: StrategyConfig) -> Optional[TradeSetup]:
    df = _fetch(cfg.symbol, cfg.timeframe, cfg.candle_count)
    if df is None or len(df) < 6: return None
    # implement detection rules here
    return None
```

**`main.py`** — CLI entry point:
```python
import argparse, os, sys, time
from dotenv import load_dotenv
load_dotenv()

parser = argparse.ArgumentParser()
parser.add_argument("--profile", metavar="NAME")
parser.add_argument("--symbol",  metavar="SYM")
args = parser.parse_args()

if args.profile:
    key = args.profile.upper().replace("-", "_")
    for var in ["SYMBOL", "MT5_PATH", "MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER", "KEYRING_PROFILE"]:
        val = os.getenv(f"PROFILE_{key}_{var}")
        if val: os.environ[var] = val
if args.symbol:
    os.environ["SYMBOL"] = args.symbol

# build cfg, connect, scan loop
```

---

## SKILL: SIGNAL_LAB_SHELL

Standard signal lab structure for historical backtesting.

```
<name>-signal-lab/
├── main.py              CLI: python main.py <SYMBOL> <DURATION>
├── config.py            LabConfig dataclass (mirrors StrategyConfig + lab params)
├── fetcher.py           fetch_ohlcv(symbol, tf, from_date, to_date) → DataFrame
├── strategy_scan.py     scan_setups(df, cfg) → List[HistSetup]  (rules 1-N, no live filters)
├── tp_analysis.py       evaluate_outcomes(setups, df) + summary tables
├── market_char.py       candle profiling, big-move stats
└── report.py            print_*() formatters — all console output here
```

Key rules for signal lab:
- `strategy_scan.py` runs structure detection only — no session/cooldown filters (those are live-only)
- `tp_analysis.py` scans forward `tp_lookahead_bars` bars to determine TP/SL/neither outcome
- Always analyse ≥ 3M of data before drawing conclusions
- Report win rate by: direction, session slot (30-min), X% move size, day of week

---

## SKILL: RISK_CALC

Risk-based lot sizing — identical logic in both MQL5 (`CalcLots`) and Python (`calc_lot_size`).

```python
def calc_lot_size(setup: TradeSetup, cfg: StrategyConfig) -> float:
    sym  = mt5.symbol_info(setup.symbol)
    acct = mt5.account_info()
    if sym is None or acct is None: return sym.volume_min if sym else 0.01

    risk_amt   = acct.balance * cfg.risk_pct / 100.0
    sl_dist    = abs(setup.entry - setup.stop_loss)
    if sl_dist == 0 or sym.trade_tick_size == 0 or sym.trade_tick_value == 0:
        return sym.volume_min

    val_per_pt = sym.trade_tick_value / sym.trade_tick_size
    lot = risk_amt / (sl_dist * val_per_pt)
    lot = max(sym.volume_min, min(min(sym.volume_max, cfg.max_lots), lot))
    if sym.volume_step > 0:
        lot = round(round(lot / sym.volume_step) * sym.volume_step, 8)
    return lot
```

---

## SKILL: ENV_SETUP

Standard `.env.example` structure for every repo:

```bash
# MT5 Connection
MT5_PATH=                         # path to terminal64.exe (multi-terminal)
MT5_LOGIN=                        # leave blank if terminal already logged in
MT5_PASSWORD=                     # use keyring instead (see CREDENTIALS.md)
MT5_SERVER=

# Broker Profiles  (python main.py --profile <name>)
PROFILE_METAQUOTES_SYMBOL=XAUUSD
PROFILE_METAQUOTES_MT5_PATH=C:/MT5_MetaQuotes/terminal64.exe
PROFILE_METAQUOTES_KEYRING_PROFILE=metaquotes
PROFILE_METAQUOTES_MT5_SERVER=MetaQuotes-Demo

PROFILE_BLACKBULL_SPOT_SYMBOL=XAUUSDp
PROFILE_BLACKBULL_SPOT_MT5_PATH=C:/MT5_BlackBull/terminal64.exe
PROFILE_BLACKBULL_SPOT_KEYRING_PROFILE=blackbull
PROFILE_BLACKBULL_SPOT_MT5_SERVER=BlackBullMarkets-Demo

# Instrument
SYMBOL=XAUUSD
TIMEFRAME=M1
SCAN_INTERVAL=60

# Execution
MANUAL_CONFIRM=true               # always true until strategy validated on demo

# Risk
RISK_PERCENT=0.15
MIN_RR=0
MAX_LOTS=7.0

# Magic + Slippage
MAGIC_NUMBER=20260412
SLIPPAGE=20
```

**`.gitignore` must include:**
```
.env
*.ex5
*.pdf
__pycache__/
*.pyc
.venv/
```

---

## SKILL: VERSIONING

**File naming**: `StrategyName_v1.02.mq5`  
**MQL5 header**: `#property version "1.02"`  
**Commit format**: `v1.02 — description`  
**Co-author**: `Co-Authored-By: KSE`

| Change type | Version bump |
|---|---|
| New filter, rule tweak, param change | Minor (1.01 → 1.02) |
| Full strategy rewrite | Major (1.x → 2.00) |
| Bug fix only | Minor patch (1.02 → 1.03) |

New repo baseline is always `v1.00`. Never delete old version files — keep them in the folder.

---

## SKILL: DIAGNOSTIC_SCAN

One-shot filter diagnostic — run when bot reports "No setup detected" to identify the blocker:

```python
# Run from <strategy>-python-bot/ directory
python -u -c "
from dotenv import load_dotenv; load_dotenv()
import os; os.environ['SYMBOL'] = 'SYMBOL_HERE'
from bot.connection import connect; connect()
import MetaTrader5 as mt5
from bot.strategy import _fetch, _gap_guard, is_in_trading_session, _pip_size
from main import cfg

df    = _fetch(cfg.symbol, cfg.timeframe, cfg.candle_count)
tick  = mt5.symbol_info_tick(cfg.symbol)
print(f'bid/ask      : {tick.bid:.2f} / {tick.ask:.2f}')
print(f'gap guard    : {_gap_guard(df)}')
print(f'session      : {is_in_trading_session(cfg)}')
print(f'bars fetched : {len(df)}')
mt5.shutdown()
"
```
