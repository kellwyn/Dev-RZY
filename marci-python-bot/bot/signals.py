"""
TradeSetup dataclass — carries every piece of information needed to
display the full strategy checklist and execute the order.
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

    # ── Measured Move components ─────────────────────────────────────────────
    # SHORT: anchor = swing low, pullback_extreme = pullback high (trendline ref)
    # LONG : anchor = swing high, pullback_extreme = pullback low  (trendline ref)
    anchor_price:      float
    pullback_extreme:  float
    measured_distance: float    # abs(pullback_extreme - anchor_price)

    # ── Bollinger Band context ────────────────────────────────────────────────
    bb_upper:   float
    bb_middle:  float
    bb_lower:   float
    bb_position: str            # BEYOND_UPPER | NEAR_UPPER | MIDDLE | NEAR_LOWER | BEYOND_LOWER

    # ── Signal quality ────────────────────────────────────────────────────────
    structure_count: int        # which RZY in this trend (1 = first = strongest)
    signal_strength: str        # HIGH | MEDIUM | LOW

    # ── Human-readable checklist (printed before confirmation) ───────────────
    setup_notes:       List[str] = field(default_factory=list)
    invalidation_price: float   = 0.0   # price that would invalidate the setup
