# AGENT.md — MetaTrader Strategy Projects

> Cross-agent reference. Claude Code reads `CLAUDE.md` which imports this file.  
> Other agents (Cursor, Copilot, etc.) read this file directly.

Applies to: **Dev-RZY**, **DEV-8020Scalps**, **DEV-WySchematics**, **DEV-SwingBB**, **DEV-ParabolicShort**, **Dev**

---

## Project Identity

Each repo contains one complete trading strategy, structured in three components:

```
<strategy>-mq5-ea/        MQL5 Expert Advisor (MetaTrader 5)
<strategy>-python-bot/    Python bot — mirrors the EA logic via MT5 Python API
<strategy>-signal-lab/    Historical backtesting + analysis framework
```

The EA is the source of truth for strategy logic. The Python bot mirrors it. The signal lab validates it historically.

---

## Repo Structure

```
root/
├── <name>-mq5-ea/
│   └── <StrategyName>_v<X.XX>.mq5
├── <name>-python-bot/
│   ├── main.py                  CLI entry point (argparse: --profile, --symbol)
│   ├── bot/
│   │   ├── connection.py        MT5 connect/disconnect
│   │   ├── strategy.py          StrategyConfig + find_setup()
│   │   ├── trader.py            calc_lot_size() + send_order()
│   │   └── signals.py           TradeSetup dataclass
│   └── requirements.txt
├── <name>-signal-lab/
│   ├── main.py                  CLI entry point
│   ├── config.py                LabConfig dataclass
│   ├── fetcher.py               MT5 OHLCV retrieval
│   ├── strategy_scan.py         Historical setup detection
│   ├── tp_analysis.py           TP/SL outcome evaluation
│   ├── market_char.py           Candle + big-move profiling
│   ├── report.py                Console output
│   └── [correlations, periods, slot_drill as needed]
├── .env.example                 Non-secret config template
├── .gitignore
├── CREDENTIALS.md               Keyring vault setup guide
├── AGENT.md                     (this file)
└── SKILLS.md                    Reusable code patterns
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| EA | MQL5 — MetaTrader 5 |
| Python API | `MetaTrader5` pip package |
| Bot runtime | Python 3.10+ |
| Config | `python-dotenv` + `.env` |
| Credential vault | `keyring` → Windows Credential Manager |
| Data | `pandas`, `numpy` |
| Memory | LangChain MCP server (see Memory section) |

---

## MT5 API Quick Reference

### Python (`MetaTrader5`)
```python
mt5.initialize(path=..., login=..., password=..., server=...)
mt5.shutdown()
mt5.account_info()                          # balance, leverage, currency
mt5.symbol_info(symbol)                     # digits, point, volume_min/max/step
mt5.symbol_info_tick(symbol)                # bid, ask, last
mt5.copy_rates_from_pos(symbol, tf, 0, n)   # OHLCV array (pos=1 skips forming bar)
mt5.history_deals_get(from_dt, to_dt)       # closed deal history
mt5.order_send(request)                     # place market/pending order
mt5.positions_get(symbol=symbol)            # open positions
```

Timeframe constants: `mt5.TIMEFRAME_M1 / M5 / M15 / M30 / H1 / H4 / D1 / W1 / MN1`

Order constants: `mt5.ORDER_TYPE_BUY`, `mt5.ORDER_TYPE_SELL`, `mt5.TRADE_ACTION_DEAL`

### MQL5 (EA side)
```mql5
// Inputs
input group "=== Section ==="
input type InpVarName = default;  // description

// Lifecycle
int OnInit()    { /* init handles, set magic */ return INIT_SUCCEEDED; }
void OnTick()   { /* bar-open gate, RunStrategy() */ }
void OnDeinit(const int reason) { /* IndicatorRelease(), cleanup */ }
void OnTradeTransaction(...) { /* detect TP exits for cooldowns */ }

// Data
CopyHigh/Low/Close/Open(symbol, tf, 0, count, arr);
ArraySetAsSeries(arr, true);   // index 0 = most recent

// Execution
CTrade Trade;
Trade.SetExpertMagicNumber(InpMagicNumber);
Trade.Sell(lots, symbol, price, sl, tp, comment);
Trade.Buy(lots, symbol, price, sl, tp, comment);

// Indicators
int handle = iBands(symbol, tf, period, shift, dev, applied);
CopyBuffer(handle, 0, 0, count, buffer);
IndicatorRelease(handle);
```

---

## Naming Conventions

### MQL5
- Inputs: `InpVarName` (PascalCase, `Inp` prefix)
- Globals: `g_varName` (camelCase, `g_` prefix)
- Functions: `PascalCase` (`RunStrategy`, `FindSwings`, `CalcLots`)
- EA file: `StrategyName_v1.02.mq5`

### Python
- Functions: `snake_case` (`find_setup`, `calc_lot_size`)
- Private helpers: `_leading_underscore` (`_find_short_setup`, `_pip_size`)
- Classes: `PascalCase` (`StrategyConfig`, `TradeSetup`)
- Env vars: `UPPER_SNAKE_CASE` (`SYMBOL`, `RISK_PERCENT`)
- Profiles: `PROFILE_<BROKER>_<PARAM>` (`PROFILE_BLACKBULL_SPOT_SYMBOL`)

---

## Dos & Don'ts

### DO
- Mirror EA rules 1-for-1 in the Python bot — same rule numbers, same logic
- Use `pos=1` in `copy_rates_from_pos` to skip the forming bar
- Use `AsSeries=true` in MQL5 (index 0 = most recent); note Python arrays are reversed (index 0 = oldest)
- Group all strategy parameters in `StrategyConfig` or `LabConfig` — never scatter loose vars
- Use `manual_confirm=True` by default on new strategies until validated on demo
- Validate new strategies in signal lab before enabling auto-execute
- Add `# Why:` comments for any non-obvious filter or workaround
- Use `keyring` for credentials — never read passwords from `.env`

### DON'T
- Don't hardcode account numbers, passwords, API keys, or server names in source files
- Don't commit `.env` — only `.env.example` (with blank values) goes to git
- Don't process `OnTick()` on every tick — gate on new bar completion (`static lastBar`)
- Don't create a new module unless the responsibility is clearly separate
- Don't add filters beyond the strategy rules without validating in signal lab first
- Don't use `git push --force` on main
- Don't amend published commits — create new ones

---

## Security

Credentials are never in source. Priority order:

1. **Runtime**: `keyring.get_password("mt5", "<profile>_password")` — Windows Credential Manager
2. **Config**: `.env` (gitignored) — non-sensitive params only (symbol, timeframe, paths)
3. **Template**: `.env.example` — committed with blank credential fields

```python
# Correct credential access pattern
import keyring
password = keyring.get_password("mt5", f"{profile}_password")
```

Store once:
```bash
python -c "import keyring; keyring.set_password('mt5', 'metaquotes_password', 'YOUR_PW')"
```

See `CREDENTIALS.md` for full vault setup.

**.gitignore must include:**
```
.env
*.ex5
*.pdf
__pycache__/
.venv/
```

---

## Commands

```bash
# Run bot on specific symbol/profile
python main.py --symbol XAUUSD
python main.py --profile metaquotes
python main.py --profile blackbull-spot

# Run signal lab
python main.py XAUUSD 3M
python main.py XAUUSD 1Y

# One-shot diagnostic scan (bot)
python -u -c "from main import cfg; from bot.connection import connect; connect(); from bot.strategy import find_setup, print_dashboard; print_dashboard(find_setup(cfg), cfg)"

# Install dependencies
pip install -r requirements.txt

# Lint (Python)
flake8 bot/ --max-line-length=100
```

---

## Versioning & Commit Format

**Files**: `StrategyName_v1.02.mq5` (Major.Minor in filename + `#property version`)  
**Commits**: `v1.02 — short description of what changed`  
**Co-author trailer**: `Co-Authored-By: KSE`

Increment minor for filter changes, new rules, parameter tuning.  
Increment major for full strategy rewrites.

---

## PR Checklist

- [ ] EA version string matches filename (`#property version "1.02"`)
- [ ] Python bot mirrors updated EA rules
- [ ] Signal lab validated new filter/rule on ≥3M of data
- [ ] `.env.example` updated if new params added
- [ ] No credentials or API keys in any committed file (`use the security-reviewer subagent`)
- [ ] `MEMORY.md` updated if project context changed

---

## .claude/ Directory

```
.claude/
├── settings.json          hooks: lint on .py edit, deploy reminder on .mq5 edit, credential scan
├── agents/
│   ├── code-reviewer.md   reviews EA/bot rule parity + code quality
│   ├── security-reviewer.md  scans for hardcoded creds + gitignore gaps
│   ├── bot-health-check.md   MT5 connection + one-shot diagnostic scan
│   ├── ea-deployer.md     copies .mq5 to MetaTrader Experts folder
│   └── git-push.md        stages, commits (correct format), pushes to GitHub
└── skills/
    ├── diagnostic-scan/   /diagnostic-scan <SYMBOL>
    ├── deploy-ea/         /deploy-ea
    └── new-strategy/      /new-strategy <StrategyName>
```

---

## Memory System

Memory is managed via LangChain MCP server. Add to `.claude/settings.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "docs-langchain": {
      "url": "https://docs.langchain.com/mcp"
    }
  }
}
```

### Memory Types

| Type | What it stores | Location | Update cadence |
|---|---|---|---|
| **Semantic** | Strategy rules, EA parameters, broker profiles, instrument specs | `memory/semantic_<strategy>.md` | Weekly |
| **Episodic** | Trade results, signal lab findings, backtest insights | `memory/episodic_<strategy>.md` | Daily |
| **Procedural** | Code patterns, workflow steps, agent instructions | `memory/procedural.md` | On pattern changes |

### Cron Schedules

**Daily — episodic memory** (trade results + signal findings):
```bash
/schedule daily "Review today's closed trades and any signal lab runs for <strategy>. Update memory/episodic_<strategy>.md with outcomes, filter performance, and any anomalies observed."
```

**Weekly — semantic memory** (strategy facts + parameter state):
```bash
/schedule weekly "Review strategy rules and parameter performance this week. Update memory/semantic_<strategy>.md with any revised rules, new instrument profiles, or parameter adjustments validated in signal lab."
```

**On-demand — procedural memory** (after workflow or pattern changes):
```bash
/memory update procedural "Updated pattern: <description>"
```

---

## When Stuck

1. Run `/diagnostic-scan <SYMBOL>` — shows exactly which filter is blocking
2. Check `memory/` for prior decisions on this strategy
3. Use `bot-health-check` subagent for live connection issues
4. `mt5.last_error()` — always the first debug step for any MT5 API failure
5. MT5 Python API docs: https://www.mql5.com/en/docs/integration/python_metatrader5
6. MQL5 reference: https://www.mql5.com/en/docs

---

## AlgoPure — Execution Algorithm Bot

**AlgoPure** is a natural-language execution algorithm (not a signal bot). A human makes the trading decision; the bot executes, manages, and reports.

### Commands

```bash
# Start the execution REPL
python main.py --symbol USTEC.f --profile blackbull-spot
python main.py --symbol XAUUSDp --no-confirm   # skip manual confirm (demo only)

# Signal lab — terminal snapshot
python algopure-signal-lab/dashboard.py USTEC.f

# Signal lab — Streamlit web dashboard (port 8501)
cd algopure-signal-lab
python -m streamlit run dashboard_web.py -- --symbol USTEC.f
python -m streamlit run dashboard_web.py -- --symbol XAUUSDp --watch 30
```

### REPL Command Reference

```
buy/long  [SYMBOL] LOTS [limit|stop at PRICE] [sl VALUE [unit]] [tp VALUE [unit]]
sell/short [SYMBOL] LOTS [limit|stop at PRICE] [sl VALUE [unit]] [tp VALUE [unit]]

SL/TP units: price (absolute) | points (ticks) | pips (10×tick) | % (pct of entry)
If value > 100 with no unit → treated as price. If ≤ 100 → treated as points.

set sl VALUE [unit] [on ticket N]    — move stop loss on live position
set tp VALUE [unit] [on ticket N]    — move take profit
modify ticket N sl VALUE tp VALUE    — modify both at once
trail[ing] N points [on ticket N]    — activate trailing stop
close ticket N  /  close all         — close position(s)
hedge [SYMBOL] N lots                — open opposite position
kelly [for SYMBOL]                   — show Kelly criterion sizing table
status   — show all open positions + account summary
help     — full command reference
exit     — disconnect and quit
```

### Execution Speed Design

Order path is optimized to **2 MT5 calls** (tick + order_send):

| Step | Before | After |
|---|---|---|
| symbol_info calls per order | 5–6 | 0 (cached, 5-min TTL) |
| tick calls per order | 2 | 1 (fresh at execution) |
| Total MT5 round-trips | 7 | 2 |

Key functions in `bot/trader.py`:
- `_cached_sym_info(symbol)` — cache-first symbol info (filling mode, tick_size, vol constraints)
- `warm_symbol(symbol)` — call on startup to pre-populate cache
- `_filling_mode(info)` — maps `filling_mode` bitmask to `ORDER_FILLING_*` constant
- All `send_*_order()` accept `_info=` kwarg to share one cached lookup

**Filling mode pattern** (BlackBull and most brokers):
```python
# symbol.filling_mode bitmask: bit0=FOK, bit1=IOC
# ORDER_FILLING constants:      FOK=0,   IOC=1,   RETURN=2
fm = info.filling_mode
fill = mt5.ORDER_FILLING_FOK if fm & 1 else (mt5.ORDER_FILLING_IOC if fm & 2 else mt5.ORDER_FILLING_RETURN)
```

### Parallel Signal Lab Execution

After every successful order, `_fire_signal_lab(symbol)` launches a daemon thread that calls `fast_snapshot.run()` — a lightweight live-position snapshot (< 500ms, no historical fetch). Output prints ~150ms after the order confirmation so it doesn't interleave.

The full Streamlit dashboard (`dashboard_web.py`) runs separately and auto-refreshes every N seconds (sidebar toggle). Historical data is cached for 5 minutes.

```
Order confirmed (T=0ms)
order_send fires  (T=~30ms)
"ORDER EXECUTED #xxxxx" prints  (T=~50ms)
Signal lab snapshot fires in thread  (T=~200ms)  ← parallel
Next REPL prompt available  (T=~50ms)  ← doesn't wait for lab
```

### Signal Lab Files

| File | Purpose |
|---|---|
| `dashboard.py` | Rich terminal dashboard — all tables, no web server |
| `dashboard_web.py` | Streamlit web dashboard at localhost:8501 |
| `fast_snapshot.py` | Lightweight live-position snapshot, < 500ms, no historical fetch |
| `market_analysis.py` | 48-slot market char + ICT RTH session computations (pure pandas) |
| `live_metrics.py` | Risk metrics, 5 scenarios, SL/TP alternatives, hedge break-even |
| `fetcher.py` | MT5 OHLCV fetch → UTC timestamps |
| `config.py` | LabConfig — all times UTC, COMEX RTH = 13:30–20:00 UTC for gold |

### Timezone Reference (AlgoPure)

All timestamps are **UTC** (fetcher uses `pd.to_datetime(..., utc=True)`).

| Instrument | ICT RTH window (UTC) | US/Eastern equiv |
|---|---|---|
| Gold (XAUUSD / XAUUSDp / GOLD.f) | 13:30–20:00 | 09:30–16:00 ET |
| NQ / ES / US equities (USTEC.f) | 14:30–21:00 | 09:30–16:00 ET |
| The 48-slot chart labels are UTC clock hours | — | — |

### AlgoPure Skills

| Skill | Trigger | Description |
|---|---|---|
| `/deploy-ea` | After editing `.mq5` | Copies EA to MetaTrader Experts folder |
| `/diagnostic-scan` | Bot reports "No setup" | One-shot filter diagnostic |
| `/slot-market-char SYMBOL [DURATION]` | Market analysis needed | 48-slot UTC character analysis |
| `/ict-session-analysis SYMBOL` | Session analysis needed | 20-day RTH session with 30d baselines |
| `/ict-rth-table SYMBOL` | Focused RTH metrics | RTH-only aggregation, anomaly digest |

### AlgoPure Subagents

| Task | Command |
|---|---|
| Check MT5 connection + account | `use the bot-health-check subagent` |
| Review changed bot/EA code | `use the code-reviewer subagent` |
| Security scan before commit | `use the security-reviewer subagent` |
| Deploy EA to MetaTrader | `use the ea-deployer subagent` |
| Commit and push to GitHub | `use the git-push subagent` |
