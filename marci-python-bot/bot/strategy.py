"""
Marci Silfrain — Measured Move Trend Strategy  v1.02
Python implementation mirroring MarciMeasuredMove_v1.02.mq5

Setup sequence (both directions):
  Rule 1  — X% impulse move identifies the peak (HIGH or LOW trough)
  Rule 2  — Minor LOW/HIGH found strictly between peak and pullback peak
             Y% gate ensures it stays minor vs the X move
  Rule 3  — Midpoint TP: 70%*(mid→minor dist) beyond minor point
             SL: tighter of midpoint±2pip or pullbackPeak±2pip
  Rule 4  — Pullback depth + minimum impulse size gates
  Rule 5  — 2-bar momentum confirmation from pullback peak
  Rule 6  — Entry in zone between minor point and pullback peak
  Rule 7  — Big Move Cooldown + Key Level filters (optional)
  Rule 8  — ICT session gate: Asian / London / NY AM + 1hr pre-mkt
  Rule 9  — Post-TP cooldown: 20-min block after TP + big follow-through

NOTE on array direction:
  Python/MT5 arrays are chronological: index 0 = oldest, -1 = most recent.
  This is the OPPOSITE of MQL5 AsSeries. All index comparisons below are
  written in chronological (left=old, right=new) terms.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

from .signals import TradeSetup


# ── Strategy configuration ────────────────────────────────────────────────────

@dataclass
class StrategyConfig:
    # Execution
    symbol:          str   = "XAUUSD"
    timeframe:       str   = "H1"
    manual_confirm:  bool  = False          # False = auto-execute

    # Risk
    risk_pct:        float = 0.15
    min_rr:          float = 0.0            # 0 = disabled
    max_lots:        float = 7.0

    # Strategy
    candle_count:    int   = 20
    big_x_move_pct:  float = 0.3           # X% impulse
    y_max_pct:       float = 600.0         # capped to 90 at runtime
    tp_multiplier:   float = 0.5           # % of mid→minor distance

    # Pullback gates
    min_impulse_pips: float = 5.0
    min_pullback_pct: float = 2.0
    max_pullback_pct: float = 70.0

    # ICT session filter (Rule 8)
    use_session:      bool  = False
    gmt_offset:       int   = 0
    asian_start_h:    int   = 23
    asian_end_h:      int   = 9
    london_start_h:   int   = 7
    london_end_h:     int   = 16
    ny_start_h:       int   = 12
    ny_end_h:         int   = 17

    # Post-TP cooldown (Rule 9)
    use_post_tp_cooldown:   bool  = True
    post_tp_cooldown_mins:  int   = 20

    # Big Move Cooldown (Rule 7)
    use_big_move_cooldown:  bool  = True
    big_move_pct:           float = 1.0
    big_move_cooldown_bars: int   = 20

    # Key Level filter (Rule 7)
    use_key_level:    bool  = True
    key_level_pips:   float = 10.0

    # Trade settings
    magic:    int = 20260412
    slippage: int = 20


# ── Module-level cooldown state ───────────────────────────────────────────────
# Mirrors the MQL5 globals g_lastTPExitTime / g_lastTPExitPrice.

_last_tp_exit_time:  Optional[datetime] = None
_last_tp_exit_price: float              = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pip_size(symbol: str) -> float:
    """Return the pip size for a symbol (handles 3/5-digit and 2/4-digit)."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0001
    return info.point * 10 if info.digits in (3, 5) else info.point


def _in_session_window(h: int, start: int, end: int) -> bool:
    """True if hour h is inside [start, end), handling midnight spans."""
    if start > end:
        return h >= start or h < end
    return start <= h < end


def get_current_session(cfg: StrategyConfig) -> str:
    """Return the name of the active ICT session(s), or 'ALL' if filter off."""
    if not cfg.use_session:
        return "ALL"

    h = (datetime.now(timezone.utc).hour + cfg.gmt_offset) % 24

    parts = []
    if _in_session_window(h, cfg.asian_start_h, cfg.asian_end_h):
        parts.append("PRE-ASIAN" if h == cfg.asian_start_h else "ASIAN")
    if _in_session_window(h, cfg.london_start_h, cfg.london_end_h):
        parts.append("PRE-LONDON" if h == cfg.london_start_h else "LONDON")
    if _in_session_window(h, cfg.ny_start_h, cfg.ny_end_h):
        parts.append("PRE-NY" if h == cfg.ny_start_h else "NY AM")

    return " / ".join(parts) if parts else ""


def is_in_trading_session(cfg: StrategyConfig) -> bool:
    """Rule 8: True if the current time falls in an active ICT session."""
    if not cfg.use_session:
        return True
    return bool(get_current_session(cfg))


# ── Rule 9: Post-TP cooldown ──────────────────────────────────────────────────

def check_and_update_tp_state(cfg: StrategyConfig):
    """
    Scan recent deal history for TP exits belonging to this EA.
    Updates module-level _last_tp_exit_time / _last_tp_exit_price.
    """
    global _last_tp_exit_time, _last_tp_exit_price

    if not cfg.use_post_tp_cooldown:
        return

    now = datetime.now(timezone.utc)
    from_dt = now - timedelta(minutes=cfg.post_tp_cooldown_mins + 5)

    deals = mt5.history_deals_get(from_dt, now)
    if deals is None:
        return

    for d in reversed(deals):               # newest first
        if (d.magic == cfg.magic and
                d.reason == mt5.DEAL_REASON_TP and
                d.entry  == mt5.DEAL_ENTRY_OUT):
            exit_time = datetime.fromtimestamp(d.time, tz=timezone.utc)
            if _last_tp_exit_time is None or exit_time > _last_tp_exit_time:
                _last_tp_exit_time  = exit_time
                _last_tp_exit_price = d.price
            break


def is_post_tp_cooldown(last_close: float, cfg: StrategyConfig) -> bool:
    """
    Rule 9: block a new entry if a TP exit occurred within the cooldown window
    AND price has moved >= big_move_pct% since that exit.
    """
    if not cfg.use_post_tp_cooldown:
        return False
    if _last_tp_exit_time is None or _last_tp_exit_price == 0.0:
        return False

    elapsed = (datetime.now(timezone.utc) - _last_tp_exit_time).total_seconds()
    if elapsed > cfg.post_tp_cooldown_mins * 60:
        return False

    move = abs(last_close - _last_tp_exit_price) / _last_tp_exit_price * 100.0
    return move >= cfg.big_move_pct


# ── Rule 7: Big Move Cooldown ─────────────────────────────────────────────────

def is_big_move_cooldown(direction: str, opens: np.ndarray,
                          closes: np.ndarray, cfg: StrategyConfig) -> bool:
    """
    Block entries if any bar in the last N bars moved >= big_move_pct% on a
    close-vs-open basis in the trade direction (move already exhausted).
    """
    if not cfg.use_big_move_cooldown:
        return False

    threshold = cfg.big_move_pct / 100.0
    lookback  = min(cfg.big_move_cooldown_bars, len(opens))

    for i in range(1, lookback + 1):        # scan from most recent bar back
        o, c = opens[-i], closes[-i]
        if o == 0:
            continue
        move = (c - o) / o
        if direction == "SHORT" and move <= -threshold:
            return True
        if direction == "LONG"  and move >=  threshold:
            return True
    return False


# ── Rule 7: Key Level filter ──────────────────────────────────────────────────

def is_near_key_level(symbol: str, price: float,
                       direction: str, cfg: StrategyConfig) -> bool:
    """Check ATH/ATL (520 W1), Monthly H/L (12), Weekly H/L (52)."""
    if not cfg.use_key_level:
        return False

    pip  = _pip_size(symbol)
    buf  = cfg.key_level_pips * pip

    checks = [
        (mt5.TIMEFRAME_W1,  52),
        (mt5.TIMEFRAME_MN1, 12),
        (mt5.TIMEFRAME_W1,  520),
    ]

    for tf, count in checks:
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            continue
        highs_ = np.array([r["high"] for r in rates])
        lows_  = np.array([r["low"]  for r in rates])
        lvl_h  = float(highs_.max())
        lvl_l  = float(lows_.min())
        if direction == "SHORT" and abs(price - lvl_l) <= buf:
            return True
        if direction == "LONG"  and abs(price - lvl_h) <= buf:
            return True

    return False


# ── Rule 1-4: Setup detection ─────────────────────────────────────────────────
# Python arrays are chronological (index 0 = oldest, -1 = most recent),
# the OPPOSITE of MQL5 AsSeries.  The temporal sequence for SHORT is:
#
#  older ──────────────────────────────────── newer
#  [..] → PEAK (peak_idx) → MINOR LOW (minor_idx) → PB PEAK (pb_idx) → current
#
# So: peak_idx < minor_idx < pb_idx  (unlike MQL5 where peakBar > minorBar > pbBar)


def _find_short_setup(
    highs: np.ndarray, lows: np.ndarray,
    cfg: StrategyConfig, pip: float,
) -> Optional[dict]:
    """
    Locate a SHORT setup structure.
    Returns a dict of key indices/prices or None if not found.
    """
    n = len(highs)
    if n < 6:
        return None

    y_max = min(cfg.y_max_pct, 90.0)

    # Step 1 — PEAK: absolute highest high in lookback
    peak_idx = int(np.argmax(highs))
    peak_px  = float(highs[peak_idx])

    # Need enough bars after peak
    bars_after = n - peak_idx - 1
    if bars_after < 4:
        return None

    # Step 2 — Validate X% UP move (prior low is in bars UP TO and including peak)
    prior_low   = float(np.min(lows[:peak_idx + 1]))
    x_move_px   = peak_px - prior_low
    if x_move_px <= 0 or prior_low == 0:
        return None
    x_move_pct  = x_move_px / prior_low * 100.0
    if x_move_pct < cfg.big_x_move_pct:
        return None

    # Step 3 — PULLBACK PEAK: highest high in bars AFTER peak
    seg = highs[peak_idx + 1:]
    pb_local = int(np.argmax(seg))
    pb_idx   = peak_idx + 1 + pb_local
    pb_px    = float(highs[pb_idx])

    if pb_px >= peak_px:        # must be a lower high
        return None
    if n - pb_idx - 1 < 2:     # need 2 confirmed bars after pb peak
        return None

    # Step 4 — MINOR LOW: lowest low strictly BETWEEN peak and pb peak
    window = lows[peak_idx + 1 : pb_idx]
    if len(window) < 1:
        return None
    minor_local = int(np.argmin(window))
    minor_idx   = peak_idx + 1 + minor_local
    minor_px    = float(lows[minor_idx])

    if minor_px >= pb_px:       # minor must be below pullback peak
        return None

    # Step 5 — Y% gate
    minor_dist = peak_px - minor_px
    if minor_dist <= 0:
        return None
    if minor_dist > (y_max / 100.0) * x_move_px:
        return None

    # Step 6 — Pullback depth
    pb_depth = (pb_px - minor_px) / (peak_px - minor_px) * 100.0
    if not (cfg.min_pullback_pct <= pb_depth <= cfg.max_pullback_pct):
        return None

    # Step 7 — Min impulse size
    if pip > 0 and (minor_dist / pip) < cfg.min_impulse_pips:
        return None

    return dict(peak_idx=peak_idx, peak_px=peak_px,
                minor_idx=minor_idx, minor_px=minor_px,
                pb_idx=pb_idx, pb_px=pb_px,
                x_move_pct=x_move_pct)


def _find_long_setup(
    highs: np.ndarray, lows: np.ndarray,
    cfg: StrategyConfig, pip: float,
) -> Optional[dict]:
    """
    Locate a LONG setup structure (mirror of SHORT).
    Temporal sequence: TROUGH → MINOR HIGH → PB TROUGH → current
    """
    n = len(highs)
    if n < 6:
        return None

    y_max = min(cfg.y_max_pct, 90.0)

    # Step 1 — TROUGH: absolute lowest low
    trough_idx = int(np.argmin(lows))
    trough_px  = float(lows[trough_idx])

    bars_after = n - trough_idx - 1
    if bars_after < 4:
        return None

    # Step 2 — Validate X% DOWN move
    prior_high  = float(np.max(highs[:trough_idx + 1]))
    x_move_px   = prior_high - trough_px
    if x_move_px <= 0 or prior_high == 0:
        return None
    x_move_pct  = x_move_px / prior_high * 100.0
    if x_move_pct < cfg.big_x_move_pct:
        return None

    # Step 3 — PULLBACK TROUGH: lowest low in bars AFTER trough
    seg      = lows[trough_idx + 1:]
    pb_local = int(np.argmin(seg))
    pb_idx   = trough_idx + 1 + pb_local
    pb_px    = float(lows[pb_idx])

    if pb_px <= trough_px:      # must be a higher low
        return None
    if n - pb_idx - 1 < 2:
        return None

    # Step 4 — MINOR HIGH: highest high strictly BETWEEN trough and pb trough
    window = highs[trough_idx + 1 : pb_idx]
    if len(window) < 1:
        return None
    minor_local = int(np.argmax(window))
    minor_idx   = trough_idx + 1 + minor_local
    minor_px    = float(highs[minor_idx])

    if minor_px <= pb_px:       # minor must be above pullback trough
        return None

    # Step 5 — Y% gate
    minor_dist = minor_px - trough_px
    if minor_dist <= 0:
        return None
    if minor_dist > (y_max / 100.0) * x_move_px:
        return None

    # Step 6 — Pullback depth
    pb_depth = (minor_px - pb_px) / (minor_px - trough_px) * 100.0
    if not (cfg.min_pullback_pct <= pb_depth <= cfg.max_pullback_pct):
        return None

    # Step 7 — Min impulse size
    if pip > 0 and (minor_dist / pip) < cfg.min_impulse_pips:
        return None

    return dict(trough_idx=trough_idx, trough_px=trough_px,
                minor_idx=minor_idx, minor_px=minor_px,
                pb_idx=pb_idx, pb_px=pb_px,
                x_move_pct=x_move_pct)


# ── Rule 5: Momentum confirmation ─────────────────────────────────────────────

def _confirm_short_momentum(closes: np.ndarray, pb_idx: int) -> bool:
    """Two declining closes after the pullback peak."""
    if len(closes) - pb_idx - 1 < 2:
        return False
    return closes[-1] < closes[-2] and closes[-2] <= closes[pb_idx]


def _confirm_long_momentum(closes: np.ndarray, pb_idx: int) -> bool:
    """Two rising closes after the pullback trough."""
    if len(closes) - pb_idx - 1 < 2:
        return False
    return closes[-1] > closes[-2] and closes[-2] >= closes[pb_idx]


# ── Data fetching ─────────────────────────────────────────────────────────────

_TF_MAP = {
    "M1": mt5.TIMEFRAME_M1, "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1, "H4":  mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1, "W1":  mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}


def _fetch(symbol: str, tf_str: str, count: int) -> Optional[pd.DataFrame]:
    """Fetch completed OHLC bars (skips forming bar via pos=1)."""
    tf = _TF_MAP.get(tf_str.upper())
    if tf is None:
        return None
    rates = mt5.copy_rates_from_pos(symbol, tf, 1, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.rename(columns={"open": "o", "high": "h",
                        "low": "l", "close": "c"}, inplace=True)
    return df


# ── Gap guard ─────────────────────────────────────────────────────────────────

def _gap_guard(df: pd.DataFrame) -> bool:
    """At daily opens only, block if the current bar opened outside the prior bar's range."""
    if len(df) < 2:
        return False
    if df["time"].iloc[-1].date() == df["time"].iloc[-2].date():
        return True  # intraday bar — gap guard not applied
    o0 = df["o"].iloc[-1]
    h1 = df["h"].iloc[-2]
    l1 = df["l"].iloc[-2]
    return l1 <= o0 <= h1


# ── Core: detect one setup ────────────────────────────────────────────────────

def find_setup(cfg: StrategyConfig) -> Optional[TradeSetup]:
    """
    Fetch bars, run all pre-checks, attempt SHORT then LONG.
    Returns a TradeSetup if found, otherwise None.
    """
    df = _fetch(cfg.symbol, cfg.timeframe, cfg.candle_count)
    if df is None or len(df) < 6:
        return None

    highs  = df["h"].values.astype(float)
    lows   = df["l"].values.astype(float)
    closes = df["c"].values.astype(float)
    opens  = df["o"].values.astype(float)

    # Pre-check 1: gap guard
    if not _gap_guard(df):
        return None

    # Pre-check 2: ICT session filter (Rule 8)
    if not is_in_trading_session(cfg):
        return None

    # Pre-check 3: post-TP cooldown (Rule 9)
    check_and_update_tp_state(cfg)
    if is_post_tp_cooldown(float(closes[-1]), cfg):
        return None

    pip     = _pip_size(cfg.symbol)
    session = get_current_session(cfg)

    tick = mt5.symbol_info_tick(cfg.symbol)
    if tick is None:
        return None

    # ── Try SHORT ─────────────────────────────────────────────────────────────
    s = _find_short_setup(highs, lows, cfg, pip)
    if s and _confirm_short_momentum(closes, s["pb_idx"]):
        cur = float(tick.bid)

        # Rule 6: price in entry zone
        if s["minor_px"] < cur < s["pb_px"]:

            # Rule 7 filters
            if is_big_move_cooldown("SHORT", opens, closes, cfg):
                s = None
            elif is_near_key_level(cfg.symbol, cur, "SHORT", cfg):
                s = None

            if s:
                midpoint     = (s["peak_px"] + s["minor_px"]) / 2.0
                dist         = midpoint - s["minor_px"]           # > 0
                tp_px        = s["minor_px"] - dist * (cfg.tp_multiplier / 100.0)
                sl_opt1      = midpoint      + pip * 2.0
                sl_opt2      = s["pb_px"]    + pip * 2.0
                sl_px        = min(sl_opt1, sl_opt2)

                risk   = sl_px - cur
                reward = cur   - tp_px
                rr     = round(reward / risk, 2) if (risk > 0 and reward > 0) else 0.0

                if rr >= cfg.min_rr:
                    return TradeSetup(
                        symbol=cfg.symbol, timeframe=cfg.timeframe,
                        direction="SHORT",
                        entry=cur, stop_loss=sl_px, target=tp_px,
                        risk_reward=rr,
                        peak_px=s["peak_px"], minor_px=s["minor_px"],
                        pb_peak_px=s["pb_px"], midpoint=midpoint,
                        x_move_pct=s["x_move_pct"],
                        session=session,
                        setup_notes=_build_notes(
                            "SHORT", cur, sl_px, tp_px, rr,
                            s["peak_px"], s["minor_px"],
                            s["pb_px"], midpoint,
                            s["x_move_pct"], session),
                    )

    # ── Try LONG ──────────────────────────────────────────────────────────────
    lg = _find_long_setup(highs, lows, cfg, pip)
    if lg and _confirm_long_momentum(closes, lg["pb_idx"]):
        cur = float(tick.ask)

        if lg["pb_px"] < cur < lg["minor_px"]:

            if is_big_move_cooldown("LONG", opens, closes, cfg):
                lg = None
            elif is_near_key_level(cfg.symbol, cur, "LONG", cfg):
                lg = None

            if lg:
                midpoint = (lg["trough_px"] + lg["minor_px"]) / 2.0
                dist     = lg["minor_px"] - midpoint              # > 0
                tp_px    = lg["minor_px"] + dist * (cfg.tp_multiplier / 100.0)
                sl_opt1  = midpoint      - pip * 2.0
                sl_opt2  = lg["pb_px"]   - pip * 2.0
                sl_px    = max(sl_opt1, sl_opt2)

                risk   = cur   - sl_px
                reward = tp_px - cur
                rr     = round(reward / risk, 2) if (risk > 0 and reward > 0) else 0.0

                if rr >= cfg.min_rr:
                    return TradeSetup(
                        symbol=cfg.symbol, timeframe=cfg.timeframe,
                        direction="LONG",
                        entry=cur, stop_loss=sl_px, target=tp_px,
                        risk_reward=rr,
                        peak_px=lg["trough_px"], minor_px=lg["minor_px"],
                        pb_peak_px=lg["pb_px"], midpoint=midpoint,
                        x_move_pct=lg["x_move_pct"],
                        session=session,
                        setup_notes=_build_notes(
                            "LONG", cur, sl_px, tp_px, rr,
                            lg["trough_px"], lg["minor_px"],
                            lg["pb_px"], midpoint,
                            lg["x_move_pct"], session),
                    )

    return None


# ── Human-readable setup notes ────────────────────────────────────────────────

def _build_notes(
    direction: str,
    entry: float, sl: float, tp: float, rr: float,
    peak_px: float, minor_px: float, pb_px: float,
    midpoint: float, x_move_pct: float,
    session: str,
) -> list:
    peak_label  = "Peak HIGH"     if direction == "SHORT" else "Peak LOW (trough)"
    minor_label = "Minor LOW"     if direction == "SHORT" else "Minor HIGH"
    pb_label    = "Pullback HIGH" if direction == "SHORT" else "Pullback LOW"

    return [
        f"Timezone         : {session}",
        f"Short or Long    : {direction}",
        f"Current Price    : {entry:.5f}",
        f"Take Profit Price: {tp:.5f}",
        f"Stop Loss Price  : {sl:.5f}",
        f"Risk : Reward    : 1:{rr:.2f}",
        f"x% Move ({x_move_pct:.2f}%) — {peak_label}: {peak_px:.5f}",
        f"{minor_label:<17}: {minor_px:.5f}",
        f"Midpoint Price   : {midpoint:.5f}",
        f"{pb_label:<17}: {pb_px:.5f}",
    ]


# ── Dashboard print ───────────────────────────────────────────────────────────

def print_dashboard(setup: Optional[TradeSetup], cfg: StrategyConfig):
    sep = "─" * 62
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{sep}")
    print(f"  Marci Silfrain  —  Measured Move v1.02")
    print(f"  Scan : {now}  |  {cfg.symbol} [{cfg.timeframe}]")
    print(sep)

    if setup is None:
        print("  No setup detected — monitoring...")
        print(sep)
        return

    for note in setup.setup_notes:
        print(f"  {note}")
    print(sep)
