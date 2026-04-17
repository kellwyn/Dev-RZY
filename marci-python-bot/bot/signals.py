"""
TradeSetup dataclass — v1.02 structure.
Carries every level needed to display the full summary and execute the order.
"""

from dataclasses import dataclass, field
from typing import List, Literal


@dataclass
class TradeSetup:
    symbol:    str
    timeframe: str
    direction: Literal["LONG", "SHORT"]

    # ── Order levels ─────────────────────────────────────────────────────────
    entry:       float
    stop_loss:   float
    target:      float
    risk_reward: float          # e.g. 2.3 means 1:2.3

    # ── v1.02 structure levels ────────────────────────────────────────────────
    # SHORT: peak = X% UP peak (HIGH),  minor = minor LOW,  pb_peak = pullback HIGH
    # LONG : peak = X% DOWN trough (LOW), minor = minor HIGH, pb_peak = pullback LOW
    peak_px:    float           # X% impulse peak / trough price
    minor_px:   float           # minor LOW (SHORT) or minor HIGH (LONG)
    pb_peak_px: float           # pullback peak: lower HIGH (SHORT) / higher LOW (LONG)
    midpoint:   float           # (peak_px + minor_px) / 2

    # ── Move context ─────────────────────────────────────────────────────────
    x_move_pct: float           # X% that qualified the peak (prior base → peak)

    # ── Session ──────────────────────────────────────────────────────────────
    session:    str             # active ICT session name(s)

    # ── Human-readable checklist ─────────────────────────────────────────────
    setup_notes: List[str] = field(default_factory=list)
