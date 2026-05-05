"""
Historical replay engine for Marci Measured Move v2.01.

Pulls OHLCV data from MT5 via copy_rates_range, then steps through it
bar-by-bar, injecting simulated ticks and bar windows into find_setup()
via the bar_provider / tick_provider interface.  No real orders are placed.
Outcomes are simulated by scanning forward bars for SL/TP touch.

Usage (from marci-python-bot/):
    python replay_run.py --from 2025-01-01 --to 2025-04-30
    python replay_run.py --from 2025-04-01 --to 2025-04-30 --profile blackbull-spot
    python replay_run.py --from 2025-04-01 --to 2025-04-30 --spread 0.30 --sleep 50
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import MetaTrader5 as mt5
import pandas as pd

from .signals  import TradeSetup
from .strategy import StrategyConfig, find_setup, _TF_MAP, _pip_size, _calc_lots

_log = logging.getLogger("marci.replay")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class FakeTick:
    """
    Minimal stand-in for the named tuple returned by mt5.symbol_info_tick().
    find_setup() reads only .bid and .ask.
    """
    bid: float
    ask: float


@dataclass
class ReplayTrade:
    bar_time:    datetime
    direction:   str
    entry:       float
    stop_loss:   float
    target:      float
    risk_reward: float
    lots:        float
    peak_px:     float
    x_move_pct:  float
    # filled by _simulate_outcome
    outcome:     str   = "OPEN"   # "TP" | "SL" | "OPEN"
    exit_price:  float = 0.0
    pips:        float = 0.0      # positive = profit, negative = loss


# ── Engine ────────────────────────────────────────────────────────────────────

class ReplayEngine:
    """
    Steps through historical OHLCV bars and calls find_setup() at every position,
    exactly as the live bot does on each new bar.

    The two live MT5 calls are replaced:
      _fetch()                → _bar_provider()   (rolling window slice of _df)
      mt5.symbol_info_tick()  → _tick_provider()  (FakeTick from bar close)

    One-trade-per-structure guard mirrors main.py's _alerted set,
    keyed on direction|peak_px.  Cleared when find_setup returns None.
    """

    def __init__(
        self,
        cfg:      StrategyConfig,
        from_dt:  datetime,
        to_dt:    datetime,
        spread:   float = 0.0,   # added to close price to form ask; bid = close
        sleep_ms: int   = 0,     # pause between bars in ms (0 = fast-forward)
    ):
        self.cfg      = cfg
        self.from_dt  = from_dt
        self.to_dt    = to_dt
        self.spread   = spread
        self.sleep_ms = sleep_ms

        self._df:      Optional[pd.DataFrame] = None
        self._cursor:  int = 0
        self._pip:     float = 0.0

        self.trades:   List[ReplayTrade] = []
        self._alerted: set = set()

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self) -> int:
        """
        Fetch all OHLCV bars in [from_dt, to_dt] from MT5.
        Returns the number of bars loaded.
        """
        tf = _TF_MAP.get(self.cfg.timeframe.upper())
        if tf is None:
            raise ValueError(f"Unknown timeframe: {self.cfg.timeframe}")

        self._pip = _pip_size(self.cfg.symbol)

        rates = mt5.copy_rates_range(
            self.cfg.symbol, tf,
            self.from_dt, self.to_dt,
        )
        if rates is None or len(rates) == 0:
            raise RuntimeError(
                f"MT5 returned no data for {self.cfg.symbol} [{self.cfg.timeframe}] "
                f"{self.from_dt.date()} → {self.to_dt.date()}  "
                f"error={mt5.last_error()}"
            )

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.rename(columns={"open": "o", "high": "h",
                            "low":  "l", "close": "c"}, inplace=True)
        self._df = df.reset_index(drop=True)

        self._cursor = self.cfg.candle_count   # first bar with a full window
        _log.info(
            "Loaded %d bars  %s → %s  (replay starts at bar %d)",
            len(self._df),
            self._df["time"].iloc[0].date(),
            self._df["time"].iloc[-1].date(),
            self._cursor,
        )
        return len(self._df)

    def run(self) -> List[ReplayTrade]:
        """
        Walk bar-by-bar from candle_count to end of history.
        At each position call find_setup() with injected providers,
        record any new setup as a virtual trade, then simulate outcome.
        """
        if self._df is None:
            raise RuntimeError("Call load() before run()")

        n = len(self._df)

        while self._cursor < n:
            if self.sleep_ms > 0:
                time.sleep(self.sleep_ms / 1000.0)

            setup = find_setup(
                self.cfg,
                bar_provider  = self._bar_provider,
                tick_provider = self._tick_provider,
            )

            if setup is None:
                self._alerted.clear()
            else:
                key = self._alert_key(setup)
                if key not in self._alerted:
                    self._alerted.add(key)
                    trade = self._record_trade(setup)
                    self.trades.append(trade)

            self._cursor += 1

        return self.trades

    def print_results(self) -> None:
        """Print a trade log table and summary statistics to stdout."""
        sep = "─" * 74

        print(f"\n{sep}")
        print(f"  REPLAY  —  {self.cfg.symbol} [{self.cfg.timeframe}]  "
              f"{self.from_dt.date()} → {self.to_dt.date()}")
        print(sep)

        if not self.trades:
            print("  No trades triggered.")
            print(sep)
            return

        hdr = (f"  {'#':>3}  {'Time':<17}  {'Dir':<5}  "
               f"{'Entry':>9}  {'SL':>9}  {'TP':>9}  "
               f"{'RR':>5}  {'Lots':>5}  {'Result':<6}  {'Pips':>8}")
        print(hdr)
        print(f"  {'─'*3}  {'─'*17}  {'─'*5}  "
              f"{'─'*9}  {'─'*9}  {'─'*9}  "
              f"{'─'*5}  {'─'*5}  {'─'*6}  {'─'*8}")

        for i, t in enumerate(self.trades, 1):
            ts   = t.bar_time.strftime("%Y-%m-%d %H:%M")
            pips = f"{t.pips:+.1f}" if t.outcome != "OPEN" else "  open"
            print(
                f"  {i:>3}  {ts:<17}  {t.direction:<5}  "
                f"{t.entry:>9.2f}  {t.stop_loss:>9.2f}  {t.target:>9.2f}  "
                f"{t.risk_reward:>5.2f}  {t.lots:>5.2f}  {t.outcome:<6}  {pips:>8}"
            )

        print(sep)

        wins   = [t for t in self.trades if t.outcome == "TP"]
        losses = [t for t in self.trades if t.outcome == "SL"]
        opens  = [t for t in self.trades if t.outcome == "OPEN"]
        closed = len(wins) + len(losses)
        wr     = len(wins) / closed * 100.0 if closed > 0 else 0.0
        net    = sum(t.pips for t in self.trades if t.outcome != "OPEN")

        shorts = [t for t in self.trades if t.direction == "SHORT"]
        longs  = [t for t in self.trades if t.direction == "LONG"]

        print(f"  Trades : {len(self.trades)}  "
              f"(SHORT={len(shorts)}  LONG={len(longs)})")
        print(f"  Results: TP={len(wins)}  SL={len(losses)}  OPEN={len(opens)}  "
              f"win rate={wr:.0f}%  (closed only)")
        print(f"  Pips   : {net:+.1f}")
        print(sep)

    # ── Injected providers ────────────────────────────────────────────────────

    def _bar_provider(self) -> pd.DataFrame:
        """Rolling window of candle_count completed bars ending at cursor."""
        start = self._cursor - self.cfg.candle_count
        return self._df.iloc[start : self._cursor].copy()

    def _tick_provider(self) -> FakeTick:
        """Simulate bid/ask from the most recent completed bar's close."""
        close = float(self._df["c"].iloc[self._cursor - 1])
        return FakeTick(bid=close, ask=close + self.spread)

    # ── Trade recording and outcome simulation ────────────────────────────────

    @staticmethod
    def _alert_key(setup: TradeSetup) -> str:
        return f"{setup.direction}|{setup.peak_px:.5f}"

    def _record_trade(self, setup: TradeSetup) -> ReplayTrade:
        """Build a ReplayTrade and simulate its outcome from forward bars."""
        bar_time = self._df["time"].iloc[self._cursor - 1].to_pydatetime()

        try:
            lots = _calc_lots(setup.entry, setup.stop_loss, self.cfg)
        except Exception:
            lots = 0.0

        outcome, exit_px, pips = self._simulate_outcome(setup)

        trade = ReplayTrade(
            bar_time    = bar_time,
            direction   = setup.direction,
            entry       = setup.entry,
            stop_loss   = setup.stop_loss,
            target      = setup.target,
            risk_reward = setup.risk_reward,
            lots        = lots,
            peak_px     = setup.peak_px,
            x_move_pct  = setup.x_move_pct,
            outcome     = outcome,
            exit_price  = exit_px,
            pips        = pips,
        )

        icon = "✓" if outcome == "TP" else ("✗" if outcome == "SL" else "~")
        _log.info(
            "[TRADE %s] %s  %s  entry=%.2f  SL=%.2f  TP=%.2f  → %s  pips=%+.1f",
            icon, bar_time.strftime("%Y-%m-%d %H:%M"),
            setup.direction, setup.entry, setup.stop_loss, setup.target,
            outcome, pips,
        )
        return trade

    def _simulate_outcome(self, setup: TradeSetup) -> tuple[str, float, float]:
        """
        Scan bars from cursor forward to find SL or TP touch.

        Conservative tie-break: if the same bar touches both SL and TP,
        SL wins — this is the worst-case / realistic assumption for volatile bars.

        Returns (outcome, exit_price, pips).
        pips is positive for a win, negative for a loss.
        """
        pip = self._pip if self._pip > 0 else 1.0
        sl  = setup.stop_loss
        tp  = setup.target

        for i in range(self._cursor, len(self._df)):
            row  = self._df.iloc[i]
            hi   = float(row["h"])
            lo   = float(row["l"])

            if setup.direction == "SHORT":
                sl_hit = hi >= sl
                tp_hit = lo <= tp
            else:
                sl_hit = lo <= sl
                tp_hit = hi >= tp

            # tie-break: SL first (conservative)
            if sl_hit:
                pips = (setup.entry - sl) / pip if setup.direction == "SHORT" \
                       else (sl - setup.entry) / pip
                return "SL", sl, pips

            if tp_hit:
                pips = (setup.entry - tp) / pip if setup.direction == "SHORT" \
                       else (tp - setup.entry) / pip
                return "TP", tp, pips

        # never hit either — mark as open with unrealised pnl at last close
        last = float(self._df["c"].iloc[-1])
        pips = (setup.entry - last) / pip if setup.direction == "SHORT" \
               else (last - setup.entry) / pip
        return "OPEN", last, pips
