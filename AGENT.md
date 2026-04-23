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
