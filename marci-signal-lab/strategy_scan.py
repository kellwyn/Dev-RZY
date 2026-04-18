"""
Historical MarciMeasuredMove v1.02 setup scanner.

Applies Rules 1–6 (structure + momentum + entry zone) on a rolling window
across the full M30 dataset. Rules 7–9 (cooldowns, key levels, sessions)
are intentionally excluded so the scan measures the raw strategy potential
before runtime filters.

Array convention: chronological (index 0 = oldest, -1 = most recent),
matching the Python bot in marci-python-bot/bot/strategy.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from config import LabConfig


@dataclass
class HistSetup:
    bar_idx:     int
    time:        pd.Timestamp
    slot:        int
    session:     str
    direction:   str        # 'SHORT' or 'LONG'
    entry:       float      # last bar close (entry approximation)
    stop_loss:   float
    target:      float
    risk_reward: float
    peak_px:     float      # SHORT: peak HIGH  |  LONG: trough LOW
    minor_px:    float      # SHORT: minor LOW  |  LONG: minor HIGH
    pb_px:       float      # SHORT: pullback HIGH  |  LONG: pullback LOW
    midpoint:    float
    x_move_pct:  float


# ── Rule 1–6: SHORT structure ─────────────────────────────────────────────────

def _find_short(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    pip: float, cfg: LabConfig,
) -> Optional[dict]:
    n = len(highs)
    if n < 6:
        return None
    y_max = min(cfg.y_max_pct, 90.0)

    # Rule 1: PEAK — absolute highest high in window
    peak_idx = int(np.argmax(highs))
    peak_px  = float(highs[peak_idx])
    if n - peak_idx - 1 < 4:
        return None

    # Rule 1: validate X% UP move (prior low → peak)
    prior_low  = float(np.min(lows[:peak_idx + 1]))
    x_move_px  = peak_px - prior_low
    if x_move_px <= 0 or prior_low == 0:
        return None
    x_pct = x_move_px / prior_low * 100.0
    if x_pct < cfg.big_x_move_pct:
        return None

    # Rule 2: PULLBACK PEAK — highest high in bars AFTER peak (lower high)
    seg      = highs[peak_idx + 1:]
    pb_local = int(np.argmax(seg))
    pb_idx   = peak_idx + 1 + pb_local
    pb_px    = float(highs[pb_idx])
    if pb_px >= peak_px:
        return None
    if n - pb_idx - 1 < 2:     # need 2 confirmed bars after pb peak
        return None

    # Rule 2: MINOR LOW — lowest low strictly BETWEEN peak and pullback peak
    window = lows[peak_idx + 1:pb_idx]
    if len(window) < 1:
        return None
    minor_local = int(np.argmin(window))
    minor_idx   = peak_idx + 1 + minor_local
    minor_px    = float(lows[minor_idx])
    if minor_px >= pb_px:
        return None

    # Y% gate — minor point stays minor vs the X move
    minor_dist = peak_px - minor_px
    if minor_dist <= 0:
        return None
    if minor_dist > (y_max / 100.0) * x_move_px:
        return None

    # Rule 4: pullback depth gate
    pb_depth = (pb_px - minor_px) / (peak_px - minor_px) * 100.0
    if not (cfg.min_pullback_pct <= pb_depth <= cfg.max_pullback_pct):
        return None

    # Rule 4: minimum impulse size (pips)
    if pip > 0 and (minor_dist / pip) < cfg.min_impulse_pips:
        return None

    # Rule 5: momentum — 2 declining closes after pullback peak
    if not (closes[-1] < closes[-2] and closes[-2] <= closes[pb_idx]):
        return None

    # Rule 6: entry zone — last close between minor_px and pb_px
    cur = float(closes[-1])
    if not (minor_px < cur < pb_px):
        return None

    # Rule 3: TP / SL calculation
    midpoint = (peak_px + minor_px) / 2.0
    dist     = midpoint - minor_px                          # always > 0
    tp_px    = minor_px - dist * (cfg.tp_multiplier / 100.0)
    sl_opt1  = midpoint + pip * 2.0
    sl_opt2  = pb_px    + pip * 2.0
    sl_px    = min(sl_opt1, sl_opt2)                        # tighter stop

    risk   = sl_px - cur
    reward = cur   - tp_px
    rr     = round(reward / risk, 2) if (risk > 0 and reward > 0) else 0.0

    return dict(
        peak_px=peak_px, minor_px=minor_px, pb_px=pb_px,
        midpoint=midpoint, tp_px=tp_px, sl_px=sl_px,
        rr=rr, x_pct=x_pct, entry=cur,
    )


# ── Rule 1–6: LONG structure ──────────────────────────────────────────────────

def _find_long(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    pip: float, cfg: LabConfig,
) -> Optional[dict]:
    n = len(highs)
    if n < 6:
        return None
    y_max = min(cfg.y_max_pct, 90.0)

    # Rule 1: TROUGH — absolute lowest low in window
    trough_idx = int(np.argmin(lows))
    trough_px  = float(lows[trough_idx])
    if n - trough_idx - 1 < 4:
        return None

    # Rule 1: validate X% DOWN move (prior high → trough)
    prior_high = float(np.max(highs[:trough_idx + 1]))
    x_move_px  = prior_high - trough_px
    if x_move_px <= 0 or prior_high == 0:
        return None
    x_pct = x_move_px / prior_high * 100.0
    if x_pct < cfg.big_x_move_pct:
        return None

    # Rule 2: PULLBACK TROUGH — lowest low in bars AFTER trough (higher low)
    seg      = lows[trough_idx + 1:]
    pb_local = int(np.argmin(seg))
    pb_idx   = trough_idx + 1 + pb_local
    pb_px    = float(lows[pb_idx])
    if pb_px <= trough_px:
        return None
    if n - pb_idx - 1 < 2:
        return None

    # Rule 2: MINOR HIGH — highest high strictly BETWEEN trough and pb trough
    window = highs[trough_idx + 1:pb_idx]
    if len(window) < 1:
        return None
    minor_local = int(np.argmax(window))
    minor_idx   = trough_idx + 1 + minor_local
    minor_px    = float(highs[minor_idx])
    if minor_px <= pb_px:
        return None

    minor_dist = minor_px - trough_px
    if minor_dist <= 0:
        return None
    if minor_dist > (y_max / 100.0) * x_move_px:
        return None

    pb_depth = (minor_px - pb_px) / (minor_px - trough_px) * 100.0
    if not (cfg.min_pullback_pct <= pb_depth <= cfg.max_pullback_pct):
        return None

    if pip > 0 and (minor_dist / pip) < cfg.min_impulse_pips:
        return None

    # Rule 5: momentum — 2 rising closes after pullback trough
    if not (closes[-1] > closes[-2] and closes[-2] >= closes[pb_idx]):
        return None

    # Rule 6: entry zone
    cur = float(closes[-1])
    if not (pb_px < cur < minor_px):
        return None

    midpoint = (trough_px + minor_px) / 2.0
    dist     = minor_px - midpoint
    tp_px    = minor_px + dist * (cfg.tp_multiplier / 100.0)
    sl_opt1  = midpoint - pip * 2.0
    sl_opt2  = pb_px    - pip * 2.0
    sl_px    = max(sl_opt1, sl_opt2)

    risk   = cur   - sl_px
    reward = tp_px - cur
    rr     = round(reward / risk, 2) if (risk > 0 and reward > 0) else 0.0

    return dict(
        peak_px=trough_px, minor_px=minor_px, pb_px=pb_px,
        midpoint=midpoint, tp_px=tp_px, sl_px=sl_px,
        rr=rr, x_pct=x_pct, entry=cur,
    )


# ── Rolling scan ──────────────────────────────────────────────────────────────

def scan_setups(df: pd.DataFrame, cfg: LabConfig, pip: float) -> list[HistSetup]:
    """
    Slide a window of candle_count bars across df.
    At each position attempt SHORT then LONG setup detection.

    Deduplication: at most one setup per (date, slot, direction) to avoid
    the same structure firing on consecutive bars.

    Returns a list of HistSetup instances sorted chronologically.
    """
    n   = len(df)
    wnd = cfg.candle_count
    if n < wnd + 2:
        return []

    highs  = df["h"].values.astype(float)
    lows   = df["l"].values.astype(float)
    closes = df["c"].values.astype(float)

    setups: list[HistSetup] = []
    seen: set[tuple] = set()

    for i in range(wnd, n):
        h = highs[i - wnd:i]
        l = lows[i - wnd:i]
        c = closes[i - wnd:i]

        row      = df.iloc[i - 1]
        ts       = row["time"]
        date_key = ts.date()
        slot     = int(row["slot"])
        session  = row["session"]

        for direction, fn in (("SHORT", _find_short), ("LONG", _find_long)):
            key = (date_key, slot, direction)
            if key in seen:
                continue
            s = fn(h, l, c, pip, cfg)
            if s is None:
                continue
            seen.add(key)
            setups.append(HistSetup(
                bar_idx     = i - 1,
                time        = ts,
                slot        = slot,
                session     = session,
                direction   = direction,
                entry       = s["entry"],
                stop_loss   = s["sl_px"],
                target      = s["tp_px"],
                risk_reward = s["rr"],
                peak_px     = s["peak_px"],
                minor_px    = s["minor_px"],
                pb_px       = s["pb_px"],
                midpoint    = s["midpoint"],
                x_move_pct  = s["x_pct"],
            ))

    return setups
