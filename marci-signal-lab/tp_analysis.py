"""
TP / SL outcome evaluation for historical setups.

For each HistSetup we scan forward up to tp_lookahead_bars M30 bars and
determine which was hit first: TP (outcome=1), SL (outcome=0), or
neither within the lookahead window (outcome=-1, excluded from statistics).

Aggregations provided:
  - slot_summary    : win rate + counts by 30-min slot
  - session_summary : win rate by ICT session
  - direction_summary: SHORT vs LONG breakdown
  - x_move_summary  : win rate bucketed by X% impulse size
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy_scan import HistSetup
from periods import SLOT_LABELS
from config import LabConfig


def evaluate_outcomes(
    setups: list[HistSetup],
    df: pd.DataFrame,
    cfg: LabConfig,
) -> pd.DataFrame:
    """
    Scan forward from each setup bar to determine TP/SL outcome.
    Returns a DataFrame with one row per setup + outcome columns.

    Outcome values:
       1  = TP hit before SL
       0  = SL hit before TP
      -1  = neither hit within tp_lookahead_bars (excluded from win-rate stats)

    When TP and SL are both touched on the same bar (gap / spike), SL is
    recorded (conservative worst-case assumption).
    """
    n    = len(df)
    rows = []

    for s in setups:
        outcome         = -1
        bars_to_outcome = None

        for j in range(1, cfg.tp_lookahead_bars + 1):
            idx = s.bar_idx + j
            if idx >= n:
                break
            bar = df.iloc[idx]

            if s.direction == "SHORT":
                hit_sl = float(bar["h"]) >= s.stop_loss
                hit_tp = float(bar["l"]) <= s.target
            else:
                hit_sl = float(bar["l"]) <= s.stop_loss
                hit_tp = float(bar["h"]) >= s.target

            if hit_sl:                  # SL checked first (conservative)
                outcome = 0
                bars_to_outcome = j
                break
            if hit_tp:
                outcome = 1
                bars_to_outcome = j
                break

        rows.append({
            "time":        s.time,
            "slot":        s.slot,
            "session":     s.session,
            "direction":   s.direction,
            "entry":       s.entry,
            "target":      s.target,
            "stop_loss":   s.stop_loss,
            "rr":          s.risk_reward,
            "x_move_pct":  s.x_move_pct,
            "outcome":     outcome,
            "bars_held":   bars_to_outcome,
        })

    if not rows:
        return pd.DataFrame(columns=[
            "time", "slot", "session", "direction", "entry",
            "target", "stop_loss", "rr", "x_move_pct", "outcome", "bars_held",
        ])
    return pd.DataFrame(rows)


# ── Aggregation helpers ───────────────────────────────────────────────────────

def _decided(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Filter to rows with a definite outcome (TP or SL hit)."""
    return outcomes[outcomes["outcome"] >= 0].copy()


def slot_summary(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Win rate, setup count, avg RR, avg bars-held — per 30-min slot."""
    dec = _decided(outcomes)
    if dec.empty:
        return pd.DataFrame()

    grp = dec.groupby("slot")
    r = pd.DataFrame(index=range(48))
    r.index.name = "slot"
    r["label"]     = SLOT_LABELS
    r["n_setups"]  = grp["outcome"].count().reindex(range(48), fill_value=0)
    r["n_wins"]    = grp["outcome"].sum().reindex(range(48), fill_value=0)
    r["win_rate"]  = (r["n_wins"] / r["n_setups"].clip(lower=1) * 100).round(1)
    r["avg_rr"]    = grp["rr"].mean().reindex(range(48)).round(2)
    r["avg_bars"]  = grp["bars_held"].mean().reindex(range(48)).round(1)
    r = r[r["n_setups"] > 0].copy()
    return r.sort_values("win_rate", ascending=False)


def session_summary(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Win rate breakdown by ICT session."""
    dec = _decided(outcomes)
    if dec.empty:
        return pd.DataFrame()
    grp = dec.groupby("session")
    r = pd.DataFrame()
    r["n_setups"] = grp["outcome"].count()
    r["n_wins"]   = grp["outcome"].sum()
    r["win_rate"] = (r["n_wins"] / r["n_setups"] * 100).round(1)
    r["avg_rr"]   = grp["rr"].mean().round(2)
    return r.sort_values("win_rate", ascending=False)


def direction_summary(outcomes: pd.DataFrame) -> pd.DataFrame:
    """SHORT vs LONG performance."""
    dec = _decided(outcomes)
    if dec.empty:
        return pd.DataFrame()
    grp = dec.groupby("direction")
    r = pd.DataFrame()
    r["n_setups"] = grp["outcome"].count()
    r["n_wins"]   = grp["outcome"].sum()
    r["win_rate"] = (r["n_wins"] / r["n_setups"] * 100).round(1)
    r["avg_rr"]   = grp["rr"].mean().round(2)
    r["avg_bars"] = grp["bars_held"].mean().round(1)
    return r.sort_values("win_rate", ascending=False)


def x_move_summary(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Win rate bucketed by X% impulse size (0–1%, 1–2%, 2–5%, 5%+)."""
    dec = _decided(outcomes)
    if dec.empty:
        return pd.DataFrame()

    bins   = [0, 1, 2, 5, np.inf]
    labels = ["0–1%", "1–2%", "2–5%", "5%+"]
    dec = dec.copy()
    dec["x_bucket"] = pd.cut(dec["x_move_pct"], bins=bins, labels=labels, right=False)
    grp = dec.groupby("x_bucket", observed=True)
    r = pd.DataFrame()
    r["n_setups"] = grp["outcome"].count()
    r["n_wins"]   = grp["outcome"].sum()
    r["win_rate"] = (r["n_wins"] / r["n_setups"].clip(lower=1) * 100).round(1)
    r["avg_rr"]   = grp["rr"].mean().round(2)
    return r[r["n_setups"] > 0]
