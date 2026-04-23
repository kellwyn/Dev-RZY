@AGENT.md

<!-- Claude Code project instructions — imports AGENT.md for cross-agent compatibility -->

## Critical Rules

- Never hardcode credentials — use `keyring` for secrets, `.env` (gitignored) for non-sensitive config
- Mirror EA rules 1-for-1 in the Python bot — same rule numbers, same logic
- Set `MANUAL_CONFIRM=true` until any strategy is validated on demo
- Validate all new filters in signal lab on ≥3M data before enabling in live bot
- Commit format: `v1.02 — description` with trailer `Co-Authored-By: KSE`

## Commands

```bash
python main.py --profile metaquotes        # run bot on MetaQuotes profile
python main.py --symbol GOLD.f             # one-off symbol override
python main.py XAUUSD 3M                   # signal lab (symbol + duration)
pip install -r requirements.txt
flake8 bot/ --max-line-length=100          # lint
```

## Verification — Required Before Marking Done

| Change | How to verify |
|---|---|
| Python bot edit | Run one-shot diagnostic scan; confirm no errors |
| EA (.mq5) edit | Compile in MetaTrader (0 errors, 0 warnings); run `/deploy-ea` |
| New filter/rule | Signal lab on ≥3M data; check win rate delta |
| Credential change | `python -c "import keyring; print(keyring.get_password('mt5','<key>'))"` |

## Subagents — Invoke When Relevant

| Task | Command |
|---|---|
| Review changed code | `use the code-reviewer subagent` |
| Security scan | `use the security-reviewer subagent` |
| Check if bot is live | `use the bot-health-check subagent` |
| Deploy EA to MetaTrader | `use the ea-deployer subagent` |
| Commit and push | `use the git-push subagent` |

## When Compacting

Preserve: modified file list, current bot task ID (if running), open MT5 account, last diagnostic result.

## Non-Obvious Behaviours

- MT5 Python arrays: index 0 = oldest (opposite of MQL5 AsSeries)
- `copy_rates_from_pos(symbol, tf, 1, n)` — `pos=1` skips the forming bar; `pos=0` includes it
- `mt5.last_error()` always tells you exactly why an MT5 call failed — check it first
- Bot output won't flush to background task files unless run with `PYTHONUNBUFFERED=1 python -u`
