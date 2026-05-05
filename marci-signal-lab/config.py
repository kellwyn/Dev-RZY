"""
Signal Lab — instrument + strategy configuration.
Mirrors v102_settings_xauone.set defaults (XAUUSD).
Change SYMBOL to switch instruments (one instrument per lab instance).
"""
from dataclasses import dataclass

DURATIONS: dict[str, int] = {
    "1W":  7,
    "1M":  30,
    "3M":  90,
    "6M":  180,
    "1Y":  365,
    "2Y":  730,
    "5Y":  1825,
}

DURATION_LABELS = list(DURATIONS.keys())


@dataclass
class LabConfig:
    # ── Instrument (single, changeable) ──────────────────────────────────────
    symbol:      str = "XAUUSD"
    analysis_tf: str = "M30"       # 48 × 30-min slots per 24h

    # ── RTH filter ────────────────────────────────────────────────────────────
    # Default = COMEX gold floor session (13:30–20:00 UTC)
    use_rth:     bool = False
    rth_start_h: int  = 13
    rth_start_m: int  = 30
    rth_end_h:   int  = 20
    rth_end_m:   int  = 0

    # ── Candle classification thresholds ─────────────────────────────────────
    big_move_pct:    float = 1.0    # bar body >= this % = big-move candle
    tight_range_pct: float = 0.15   # bar H-L / open < this % = tight range

    # ── Strategy parameters — v102_settings_xauone.set ───────────────────────
    candle_count:     int   = 20
    big_x_move_pct:   float = 0.3
    y_max_pct:        float = 600.0   # capped to 90 at runtime
    tp_multiplier:    float = 50.0          # % of mid→minor distance  e.g. 50 = 50%
    min_impulse_pips: float = 5.0
    min_pullback_pct: float = 2.0
    max_pullback_pct: float = 70.0

    # ── ICT session hours (UTC / GMT) ─────────────────────────────────────────
    asian_start_h:  int = 23
    asian_end_h:    int = 9
    london_start_h: int = 7
    london_end_h:   int = 16
    ny_start_h:     int = 12
    ny_end_h:       int = 17

    # ── TP outcome lookahead ─────────────────────────────────────────────────
    tp_lookahead_bars: int = 50    # max forward bars to find TP or SL hit

    # ── Entry zone candle limit ──────────────────────────────────────────────
    max_zone_candles: int = 3    # max candles allowed in minor↔pb zone

    # ── Structure timing gates ────────────────────────────────────────────────
    max_structure_bars: int = 5  # minor must form within N bars of peak; pb within N bars of minor

    # ── Indicator periods ─────────────────────────────────────────────────────
    adx_period:    int = 14
    rsi_period:    int = 14
    atr_period:    int = 14
    vol_ma_period: int = 20        # rolling window for relative volume
