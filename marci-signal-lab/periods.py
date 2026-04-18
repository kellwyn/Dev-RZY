"""
30-min period framework: 48 slots per 24h, ICT session tagging, RTH filter.
"""
from __future__ import annotations

import pandas as pd
from config import LabConfig

# Slot labels: '00:00', '00:30', '01:00', ... '23:30'
SLOT_LABELS: list[str] = [
    f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)
]


def tag_slot(ts: pd.Timestamp) -> int:
    """Return slot index 0–47 for a UTC timestamp."""
    return ts.hour * 2 + (ts.minute // 30)


def _in_window(h: int, start: int, end: int) -> bool:
    """True if hour h is in [start, end), handling midnight-spanning windows."""
    if start > end:
        return h >= start or h < end
    return start <= h < end


def tag_session(ts: pd.Timestamp, cfg: LabConfig) -> str:
    h = ts.hour
    parts = []
    if _in_window(h, cfg.asian_start_h,  cfg.asian_end_h):
        parts.append("Asian")
    if _in_window(h, cfg.london_start_h, cfg.london_end_h):
        parts.append("London")
    if _in_window(h, cfg.ny_start_h,     cfg.ny_end_h):
        parts.append("NY")
    return "/".join(parts) if parts else "Off"


def tag_rth(ts: pd.Timestamp, cfg: LabConfig) -> bool:
    """True if the bar falls within the configured RTH window."""
    start_m = cfg.rth_start_h * 60 + cfg.rth_start_m
    end_m   = cfg.rth_end_h   * 60 + cfg.rth_end_m
    bar_m   = ts.hour * 60 + ts.minute
    if start_m <= end_m:
        return start_m <= bar_m < end_m
    return bar_m >= start_m or bar_m < end_m
