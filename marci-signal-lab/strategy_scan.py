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
    highs: np.ndarray, lows: np.ndarray,
    opens: np.ndarray, closes: np.ndarray,
    pip: float, cfg: LabConfig,
) -> Optional[dict]:
    n = len(highs)
    if n < 6:
        return None
    y_max = min(cfg.y_max_pct, 90.0)
    max_s = cfg.max_structure_bars

    # Try candidate peaks from most recent to oldest.
    # Minor low must form within max_s bars of peak; pb within max_s bars of minor.
    # If timing fails, discard and retry from step 1 with the next candidate.
    peak_idx = None
    peak_px = minor_idx = minor_px = pb_idx = pb_px = x_pct = x_move_px = None

    for p_idx in range(n - 1, -1, -1):
        if p_idx < 1:
            continue
        p_px = float(highs[p_idx])

        # Rule 1: X% UP move (body-to-body)
        p_body         = float(max(opens[p_idx], closes[p_idx]))
        prior_body_low = float(min(
            np.min(opens[:p_idx + 1]),
            np.min(closes[:p_idx + 1])
        ))
        if prior_body_low == 0:
            continue
        x_mv = p_body - prior_body_low
        if x_mv <= 0:
            continue
        x_p = x_mv / prior_body_low * 100.0
        if x_p < cfg.big_x_move_pct:
            continue

        # Rule 2: MINOR LOW within max_s bars after peak
        mn_end = min(p_idx + 1 + max_s, n)
        if mn_end <= p_idx + 1:
            continue
        mn_local = int(np.argmin(lows[p_idx + 1 : mn_end]))
        mn_idx   = p_idx + 1 + mn_local
        mn_px    = float(lows[mn_idx])

        # Rule 2: PULLBACK PEAK within max_s bars after minor
        pb_end = min(mn_idx + 1 + max_s, n)
        if pb_end <= mn_idx + 1:
            continue
        pb_seg = highs[mn_idx + 1 : pb_end]
        if len(pb_seg) == 0:
            continue
        pb_loc = int(np.argmax(pb_seg))
        pb_i   = mn_idx + 1 + pb_loc
        pb_p   = float(highs[pb_i])

        if pb_p >= p_px or mn_px >= pb_p:
            continue
        if n - pb_i - 1 < 2:
            continue

        # Y% gate
        mn_dist = p_px - mn_px
        if mn_dist <= 0 or mn_dist > (y_max / 100.0) * x_mv:
            continue

        # Rule 4: pullback depth + min impulse
        pb_depth = (pb_p - mn_px) / (p_px - mn_px) * 100.0
        if not (cfg.min_pullback_pct <= pb_depth <= cfg.max_pullback_pct):
            continue
        if pip > 0 and (mn_dist / pip) < cfg.min_impulse_pips:
            continue

        peak_idx  = p_idx;  peak_px  = p_px
        minor_idx = mn_idx; minor_px = mn_px
        pb_idx    = pb_i;   pb_px    = pb_p
        x_pct     = x_p;    x_move_px = x_mv
        break

    if peak_idx is None:
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
    highs: np.ndarray, lows: np.ndarray,
    opens: np.ndarray, closes: np.ndarray,
    pip: float, cfg: LabConfig,
) -> Optional[dict]:
    n = len(highs)
    if n < 6:
        return None
    y_max = min(cfg.y_max_pct, 90.0)
    max_s = cfg.max_structure_bars

    trough_idx = minor_idx = minor_px = pb_idx = pb_px = x_pct = x_move_px = None
    trough_px = None

    for t_idx in range(n - 1, -1, -1):
        if t_idx < 1:
            continue
        t_px = float(lows[t_idx])

        # Rule 1: X% DOWN move (body-to-body)
        t_body          = float(min(opens[t_idx], closes[t_idx]))
        prior_body_high = float(max(
            np.max(opens[:t_idx + 1]),
            np.max(closes[:t_idx + 1])
        ))
        if prior_body_high == 0:
            continue
        x_mv = prior_body_high - t_body
        if x_mv <= 0:
            continue
        x_p = x_mv / prior_body_high * 100.0
        if x_p < cfg.big_x_move_pct:
            continue

        # Rule 2: MINOR HIGH within max_s bars after trough
        mn_end = min(t_idx + 1 + max_s, n)
        if mn_end <= t_idx + 1:
            continue
        mn_local = int(np.argmax(highs[t_idx + 1 : mn_end]))
        mn_idx   = t_idx + 1 + mn_local
        mn_px    = float(highs[mn_idx])

        # Rule 2: PULLBACK TROUGH within max_s bars after minor
        pb_end = min(mn_idx + 1 + max_s, n)
        if pb_end <= mn_idx + 1:
            continue
        pb_seg = lows[mn_idx + 1 : pb_end]
        if len(pb_seg) == 0:
            continue
        pb_loc = int(np.argmin(pb_seg))
        pb_i   = mn_idx + 1 + pb_loc
        pb_p   = float(lows[pb_i])

        if pb_p <= t_px or mn_px <= pb_p:
            continue
        if n - pb_i - 1 < 2:
            continue

        mn_dist = mn_px - t_px
        if mn_dist <= 0 or mn_dist > (y_max / 100.0) * x_mv:
            continue

        pb_depth = (mn_px - pb_p) / (mn_px - t_px) * 100.0
        if not (cfg.min_pullback_pct <= pb_depth <= cfg.max_pullback_pct):
            continue
        if pip > 0 and (mn_dist / pip) < cfg.min_impulse_pips:
            continue

        trough_idx = t_idx;  trough_px = t_px
        minor_idx  = mn_idx; minor_px  = mn_px
        pb_idx     = pb_i;   pb_px     = pb_p
        x_pct      = x_p;    x_move_px = x_mv
        break

    if trough_idx is None:
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
    opens  = df["o"].values.astype(float)
    closes = df["c"].values.astype(float)

    setups: list[HistSetup] = []
    seen: set[tuple] = set()

    for i in range(wnd, n):
        h = highs[i - wnd:i]
        l = lows[i - wnd:i]
        o = opens[i - wnd:i]
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
            s = fn(h, l, o, c, pip, cfg)
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
