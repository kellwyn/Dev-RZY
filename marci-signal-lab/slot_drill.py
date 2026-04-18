"""
Slot drill-down: daily tabular view for a single 30-min trading period.

For a chosen slot (0-47 or entered as HH:MM UTC), returns one row per
trading day over the last 1-365 calendar days showing:
  - OHLC, body%, H-L range%, direction (B/S/D), big-move flag, tight flag
  - Tick volume + relative volume vs that slot's historical average
  - ICT session
  - Whether a MM v1.02 setup fired in that slot that day (and the outcome)
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from periods import SLOT_LABELS


# ── Slot input parsing ────────────────────────────────────────────────────────

def parse_slot(raw: str) -> Optional[int]:
    """
    Accept:
      '14'       -> slot 14  (integer 0-47)
      '14:00'    -> slot 28  (HH:MM, minute must be 0 or 30)
      '07:30'    -> slot 15
    Returns slot index 0-47, or None if invalid.
    """
    raw = raw.strip()
    if raw.isdigit():
        s = int(raw)
        return s if 0 <= s <= 47 else None
    if ":" in raw:
        parts = raw.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h <= 23 and m in (0, 30):
                return h * 2 + (m // 30)
    return None


# ── Daily table builder ───────────────────────────────────────────────────────

def slot_daily_table(
    df:       pd.DataFrame,
    outcomes: pd.DataFrame,
    slot_id:  int,
    days:     int = 365,
) -> pd.DataFrame:
    """
    Build a day-by-day table for a single 30-min slot over the last `days`
    calendar days.

    Each row represents the M30 bar that fell in `slot_id` on that date.
    If a MM v1.02 setup was detected in that slot on that day (from
    `outcomes`), the setup direction and result are appended.

    Returns columns:
      date, open, high, low, close, body%, range%, dir,
      big, tight, tick_vol, rel_vol, session, setup, result
    """
    # ── Filter to this slot ───────────────────────────────────────────────────
    work = df[df["slot"] == slot_id].copy()

    # ── Trim to requested look-back ───────────────────────────────────────────
    if not work.empty:
        latest  = work["time"].iloc[-1]
        cutoff  = latest - pd.Timedelta(days=days)
        work    = work[work["time"] >= cutoff].copy()

    if work.empty:
        return pd.DataFrame()

    work["date"] = work["time"].dt.date

    # ── Relative volume vs this slot's own mean ───────────────────────────────
    slot_vol_mean = work["tick_volume"].mean()
    work["rel_vol"] = (
        work["tick_volume"] / slot_vol_mean if slot_vol_mean > 0 else 1.0
    ).round(2)

    # ── Setup + outcome lookup keyed by date ──────────────────────────────────
    setup_map: dict = {}
    if not outcomes.empty:
        slot_out = outcomes[outcomes["slot"] == slot_id].copy()
        for _, row in slot_out.iterrows():
            d = row["time"].date()
            if d not in setup_map:           # keep first setup of the day
                if row["outcome"] == 1:
                    res = "WIN"
                elif row["outcome"] == 0:
                    res = "LOSS"
                else:
                    res = "open"
                setup_map[d] = {
                    "setup": row["direction"],
                    "rr":    row["rr"],
                    "result": res,
                }

    # ── Build rows ────────────────────────────────────────────────────────────
    rows = []
    for _, bar in work.iterrows():
        d = bar["date"]
        s = setup_map.get(d, {})

        dir_char = "BUY" if bar["is_buy"] else ("SELL" if bar["is_sell"] else "DOJI")

        rows.append({
            "date":      d,
            "open":      round(float(bar["o"]), 3),
            "high":      round(float(bar["h"]), 3),
            "low":       round(float(bar["l"]), 3),
            "close":     round(float(bar["c"]), 3),
            "body%":     round(float(bar["move_pct"]),  3),
            "range%":    round(float(bar["range_pct"]), 3),
            "dir":       dir_char,
            "big":       "Y" if bar["is_big"]   else "",
            "tight":     "Y" if bar["is_tight"] else "",
            "tick_vol":  int(bar["tick_volume"]),
            "rel_vol":   float(bar["rel_vol"]),
            "session":   bar["session"],
            "setup":     s.get("setup",  ""),
            "rr":        s.get("rr",     ""),
            "result":    s.get("result", ""),
        })

    result = (
        pd.DataFrame(rows)
        .sort_values("date", ascending=False)
        .reset_index(drop=True)
    )
    return result


# ── Per-slot aggregate summary ────────────────────────────────────────────────

def slot_aggregate(table: pd.DataFrame, slot_id: int) -> dict:
    """Compute aggregate stats across all rows in the drill-down table."""
    if table.empty:
        return {}

    n          = len(table)
    n_buy      = (table["dir"] == "BUY").sum()
    n_sell     = (table["dir"] == "SELL").sum()
    n_big      = (table["big"] == "Y").sum()
    n_tight    = (table["tight"] == "Y").sum()
    n_setups   = (table["setup"] != "").sum()
    n_wins     = (table["result"] == "WIN").sum()
    n_losses   = (table["result"] == "LOSS").sum()
    decided    = n_wins + n_losses

    return {
        "label":         SLOT_LABELS[slot_id],
        "n_days":        n,
        "pct_buy":       round(n_buy  / n * 100, 1),
        "pct_sell":      round(n_sell / n * 100, 1),
        "pct_big":       round(n_big  / n * 100, 1),
        "pct_tight":     round(n_tight / n * 100, 1),
        "avg_body_pct":  round(table["body%"].mean(),  3),
        "avg_range_pct": round(table["range%"].mean(), 3),
        "avg_tick_vol":  round(table["tick_vol"].mean(), 0),
        "n_setups":      n_setups,
        "win_rate":      round(n_wins / decided * 100, 1) if decided > 0 else None,
        "n_wins":        n_wins,
        "n_losses":      n_losses,
    }
