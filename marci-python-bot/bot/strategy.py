"""
Marci Silfrain — Measured Move Trend Strategy  v2.01
Python implementation mirroring MarciMeasuredMove_v2.01.mq5

Setup sequence (both directions):
  Rule 1  — X% impulse move identifies the peak (HIGH or LOW trough)
  Rule 2  — Minor LOW/HIGH found strictly between peak and pullback peak
             Y% gate ensures it stays minor vs the X move
  Rule 3  — Midpoint TP: 70%*(mid→minor dist) beyond minor point
             SL: tighter of midpoint±2pip or pullbackPeak±2pip
  Rule 4  — Pullback depth + minimum impulse size gates
  Rule 5  — Entry confirmation: zone candle gate + immediate entry at minor low
  Rule 6  — Entry zone: price between minor point and pullback peak
  Rule 7  — Big Move Cooldown + Key Level filters (optional)
  Rule 8  — ICT session gate: Asian / London / NY AM + 1hr pre-mkt
  Rule 9  — Post-TP cooldown: 20-min block after TP + big follow-through

NOTE on array direction:
  Python/MT5 arrays are chronological: index 0 = oldest, -1 = most recent.
  This is the OPPOSITE of MQL5 AsSeries. All index comparisons below are
  written in chronological (left=old, right=new) terms.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

from .signals import TradeSetup


# ── Logger ────────────────────────────────────────────────────────────────────

_log = logging.getLogger("marci")


def setup_logging(level: str = "INFO") -> None:
    """
    Configure console logging for the Marci bot.
    Call once from main.py before the scan loop starts.
    """
    lvl = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        fmt="  %(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger = logging.getLogger("marci")
    logger.setLevel(lvl)
    if not logger.handlers:
        logger.addHandler(handler)


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
    big_x_move_pct:  float = 0.1           # X% impulse threshold (v2.01: lowered to 0.1)
    minor_max_pips:  float = 5000.0        # R2 hard cap: minor dist must not exceed N pips
                                           #   XAUUSDp: 5000 pips = $50  — set per instrument
    y_min_pct:       float = 25.0          # R2 floor: minor dist >= this % of X move
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

    # Entry zone candle limit (Rule 5)
    max_zone_candles: int = 3

    # Structure timing gates (Rules 2-3)
    max_structure_bars:  int = 5    # non-M1 timeframes
    m1_structure_bars:   int = 10   # M1 only — wider window for faster timeframe

    # Trade settings
    magic:    int = 20260412
    slippage: int = 20


# ── Module-level cooldown state ───────────────────────────────────────────────

_last_tp_exit_time:  Optional[datetime] = None
_last_tp_exit_price: float              = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pip_size(symbol: str) -> float:
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0001
    return info.point * 10 if info.digits in (3, 5) else info.point


def _in_session_window(h: int, start: int, end: int) -> bool:
    if start > end:
        return h >= start or h < end
    return start <= h < end


def get_current_session(cfg: StrategyConfig) -> str:
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
    if not cfg.use_session:
        return True
    return bool(get_current_session(cfg))


# ── Rule 9: Post-TP cooldown ──────────────────────────────────────────────────

def check_and_update_tp_state(cfg: StrategyConfig):
    global _last_tp_exit_time, _last_tp_exit_price
    if not cfg.use_post_tp_cooldown:
        return
    now = datetime.now(timezone.utc)
    from_dt = now - timedelta(minutes=cfg.post_tp_cooldown_mins + 5)
    deals = mt5.history_deals_get(from_dt, now)
    if deals is None:
        return
    for d in reversed(deals):
        if (d.magic == cfg.magic and
                d.reason == mt5.DEAL_REASON_TP and
                d.entry  == mt5.DEAL_ENTRY_OUT):
            exit_time = datetime.fromtimestamp(d.time, tz=timezone.utc)
            if _last_tp_exit_time is None or exit_time > _last_tp_exit_time:
                _last_tp_exit_time  = exit_time
                _last_tp_exit_price = d.price
            break


def is_post_tp_cooldown(last_close: float, cfg: StrategyConfig) -> bool:
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
    if not cfg.use_big_move_cooldown:
        return False
    threshold = cfg.big_move_pct / 100.0
    lookback  = min(cfg.big_move_cooldown_bars, len(opens))
    for i in range(1, lookback + 1):
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
#
# Python arrays are chronological (index 0 = oldest, -1 = most recent).
# For SHORT: peak_idx < minor_idx < pb_idx  (opposite of MQL5 AsSeries)
#
# verbose=True emits a log line for every rule pass and the first failure
# encountered on the most recently seen R1 candidate.


def _find_short_setup(
    highs: np.ndarray, lows: np.ndarray,
    opens: np.ndarray, closes: np.ndarray,
    cfg: StrategyConfig, pip: float,
    *,
    verbose: bool = False,
) -> Optional[dict]:
    n     = len(highs)
    if n < 6:
        return None
    # M1 uses wider timing window (10 bars); all other timeframes use 5
    max_s = cfg.m1_structure_bars if cfg.timeframe.upper() == "M1" else cfg.max_structure_bars

    _r1_logged = False   # log only the first R1 candidate per scan

    for peak_idx in range(n - 1, -1, -1):
        if peak_idx < 1:
            continue

        # ── Rule 1: X% UP move (body-to-body) ────────────────────────
        peak_body      = float(max(opens[peak_idx], closes[peak_idx]))
        prior_body_low = float(min(
            np.min(opens[:peak_idx]),
            np.min(closes[:peak_idx])
        ))
        if prior_body_low == 0:
            continue
        x_move_px  = peak_body - prior_body_low
        if x_move_px <= 0:
            continue
        x_move_pct = x_move_px / prior_body_low * 100.0
        if x_move_pct < cfg.big_x_move_pct:
            continue

        peak_px = float(highs[peak_idx])

        if verbose and not _r1_logged:
            _log.info(
                "[SHORT] R1 ✓  X%% UP %.2f%%  |  peak body=%.2f  prior base=%.2f  "
                "(bar -%d)",
                x_move_pct, peak_body, prior_body_low, n - 1 - peak_idx,
            )
            _r1_logged = True

        # ── Rule 2: MINOR LOW within max_s bars after peak ────────────
        minor_end = min(peak_idx + 1 + max_s, n)
        if minor_end <= peak_idx + 1:
            if verbose and _r1_logged:
                _log.warning(
                    "[SHORT] R2 ✗  no room for minor low after peak (need %d bars)", max_s
                )
            continue
        minor_local = int(np.argmin(lows[peak_idx + 1 : minor_end]))
        minor_idx   = peak_idx + 1 + minor_local
        minor_px    = float(lows[minor_idx])

        if verbose and _r1_logged:
            _log.info(
                "[SHORT] R2 ✓  Minor LOW=%.2f  |  %d bar(s) after peak",
                minor_px, minor_idx - peak_idx,
            )

        # ── Rule 3: PULLBACK PEAK within max_s bars after minor ───────
        pb_end = min(minor_idx + 1 + max_s, n)
        if pb_end <= minor_idx + 1:
            if verbose and _r1_logged:
                _log.warning(
                    "[SHORT] R3 ✗  no room for pullback after minor (need %d bars)", max_s
                )
            continue
        pb_seg = highs[minor_idx + 1 : pb_end]
        if len(pb_seg) == 0:
            if verbose and _r1_logged:
                _log.warning("[SHORT] R3 ✗  empty pullback window")
            continue
        pb_local = int(np.argmax(pb_seg))
        pb_idx   = minor_idx + 1 + pb_local
        pb_px    = float(highs[pb_idx])

        if verbose and _r1_logged:
            _log.info(
                "[SHORT] R3 ✓  Pullback HIGH=%.2f  |  %d bar(s) after minor",
                pb_px, pb_idx - minor_idx,
            )

        # ── Rule 4: structural validity ───────────────────────────────
        if pb_px >= peak_px:
            if verbose and _r1_logged:
                _log.warning(
                    "[SHORT] R4 ✗  pb %.2f >= peak %.2f — not a lower high",
                    pb_px, peak_px,
                )
            continue
        if minor_px >= pb_px:
            if verbose and _r1_logged:
                _log.warning(
                    "[SHORT] R4 ✗  minor %.2f >= pb %.2f — minor not below pullback",
                    minor_px, pb_px,
                )
            continue
        if n - pb_idx - 1 < 2:
            if verbose and _r1_logged:
                _log.warning("[SHORT] R4 ✗  fewer than 2 confirmation bars after pullback")
            continue

        minor_dist = peak_px - minor_px
        if minor_dist <= 0:
            continue
        # Hard pip cap — instrument-configurable (XAUUSDp: 5000 pips = $50)
        if pip > 0 and minor_dist > cfg.minor_max_pips * pip:
            if verbose and _r1_logged:
                _log.warning(
                    "[SHORT] R4 ✗  minor dist %.2f exceeds pip cap %.0f pips (%.2f)",
                    minor_dist, cfg.minor_max_pips, cfg.minor_max_pips * pip,
                )
            continue
        # Floor — minor must be a meaningful drop relative to the impulse
        if minor_dist < (cfg.y_min_pct / 100.0) * x_move_px:
            if verbose and _r1_logged:
                _log.warning(
                    "[SHORT] R4 ✗  minor dist %.2f < %.0f%% floor of X move %.2f",
                    minor_dist, cfg.y_min_pct, x_move_px,
                )
            continue

        pb_depth = (pb_px - minor_px) / (peak_px - minor_px) * 100.0
        if not (cfg.min_pullback_pct <= pb_depth <= cfg.max_pullback_pct):
            if verbose and _r1_logged:
                _log.warning(
                    "[SHORT] R4 ✗  pb depth %.1f%% outside [%.0f%%–%.0f%%]",
                    pb_depth, cfg.min_pullback_pct, cfg.max_pullback_pct,
                )
            continue

        if pip > 0 and (minor_dist / pip) < cfg.min_impulse_pips:
            if verbose and _r1_logged:
                _log.warning(
                    "[SHORT] R4 ✗  impulse %.1f pips < min %.0f pips",
                    minor_dist / pip, cfg.min_impulse_pips,
                )
            continue

        if verbose:
            _log.info(
                "[SHORT] R4 ✓  depth=%.1f%%  impulse=%.1f pips  |  "
                "peak=%.2f  minor=%.2f  pb=%.2f",
                pb_depth, minor_dist / pip, peak_px, minor_px, pb_px,
            )

        return dict(
            peak_idx=peak_idx, peak_px=peak_px,
            minor_idx=minor_idx, minor_px=minor_px,
            pb_idx=pb_idx, pb_px=pb_px,
            x_move_pct=x_move_pct,
        )

    return None


def _find_long_setup(
    highs: np.ndarray, lows: np.ndarray,
    opens: np.ndarray, closes: np.ndarray,
    cfg: StrategyConfig, pip: float,
    *,
    verbose: bool = False,
) -> Optional[dict]:
    n     = len(highs)
    if n < 6:
        return None
    max_s = cfg.m1_structure_bars if cfg.timeframe.upper() == "M1" else cfg.max_structure_bars

    _r1_logged = False

    for trough_idx in range(n - 1, -1, -1):
        if trough_idx < 1:
            continue

        # ── Rule 1: X% DOWN move (body-to-body) ──────────────────────
        trough_body     = float(min(opens[trough_idx], closes[trough_idx]))
        prior_body_high = float(max(
            np.max(opens[:trough_idx]),
            np.max(closes[:trough_idx])
        ))
        if prior_body_high == 0:
            continue
        x_move_px  = prior_body_high - trough_body
        if x_move_px <= 0:
            continue
        x_move_pct = x_move_px / prior_body_high * 100.0
        if x_move_pct < cfg.big_x_move_pct:
            continue

        trough_px = float(lows[trough_idx])

        if verbose and not _r1_logged:
            _log.info(
                "[LONG]  R1 ✓  X%% DOWN %.2f%%  |  trough body=%.2f  prior base=%.2f  "
                "(bar -%d)",
                x_move_pct, trough_body, prior_body_high, n - 1 - trough_idx,
            )
            _r1_logged = True

        # ── Rule 2: MINOR HIGH within max_s bars after trough ─────────
        minor_end = min(trough_idx + 1 + max_s, n)
        if minor_end <= trough_idx + 1:
            if verbose and _r1_logged:
                _log.warning(
                    "[LONG]  R2 ✗  no room for minor high after trough (need %d bars)", max_s
                )
            continue
        minor_local = int(np.argmax(highs[trough_idx + 1 : minor_end]))
        minor_idx   = trough_idx + 1 + minor_local
        minor_px    = float(highs[minor_idx])

        if verbose and _r1_logged:
            _log.info(
                "[LONG]  R2 ✓  Minor HIGH=%.2f  |  %d bar(s) after trough",
                minor_px, minor_idx - trough_idx,
            )

        # ── Rule 3: PULLBACK TROUGH within max_s bars after minor ─────
        pb_end = min(minor_idx + 1 + max_s, n)
        if pb_end <= minor_idx + 1:
            if verbose and _r1_logged:
                _log.warning(
                    "[LONG]  R3 ✗  no room for pullback after minor (need %d bars)", max_s
                )
            continue
        pb_seg = lows[minor_idx + 1 : pb_end]
        if len(pb_seg) == 0:
            if verbose and _r1_logged:
                _log.warning("[LONG]  R3 ✗  empty pullback window")
            continue
        pb_local = int(np.argmin(pb_seg))
        pb_idx   = minor_idx + 1 + pb_local
        pb_px    = float(lows[pb_idx])

        if verbose and _r1_logged:
            _log.info(
                "[LONG]  R3 ✓  Pullback LOW=%.2f  |  %d bar(s) after minor",
                pb_px, pb_idx - minor_idx,
            )

        # ── Rule 4: structural validity ───────────────────────────────
        if pb_px <= trough_px:
            if verbose and _r1_logged:
                _log.warning(
                    "[LONG]  R4 ✗  pb %.2f <= trough %.2f — not a higher low",
                    pb_px, trough_px,
                )
            continue
        if minor_px <= pb_px:
            if verbose and _r1_logged:
                _log.warning(
                    "[LONG]  R4 ✗  minor %.2f <= pb %.2f — minor not above pullback",
                    minor_px, pb_px,
                )
            continue
        if n - pb_idx - 1 < 2:
            if verbose and _r1_logged:
                _log.warning("[LONG]  R4 ✗  fewer than 2 confirmation bars after pullback")
            continue

        minor_dist = minor_px - trough_px
        if minor_dist <= 0:
            continue
        if pip > 0 and minor_dist > cfg.minor_max_pips * pip:
            if verbose and _r1_logged:
                _log.warning(
                    "[LONG]  R4 ✗  minor dist %.2f exceeds pip cap %.0f pips (%.2f)",
                    minor_dist, cfg.minor_max_pips, cfg.minor_max_pips * pip,
                )
            continue
        if minor_dist < (cfg.y_min_pct / 100.0) * x_move_px:
            if verbose and _r1_logged:
                _log.warning(
                    "[LONG]  R4 ✗  minor dist %.2f < %.0f%% floor of X move %.2f",
                    minor_dist, cfg.y_min_pct, x_move_px,
                )
            continue

        pb_depth = (minor_px - pb_px) / (minor_px - trough_px) * 100.0
        if not (cfg.min_pullback_pct <= pb_depth <= cfg.max_pullback_pct):
            if verbose and _r1_logged:
                _log.warning(
                    "[LONG]  R4 ✗  pb depth %.1f%% outside [%.0f%%–%.0f%%]",
                    pb_depth, cfg.min_pullback_pct, cfg.max_pullback_pct,
                )
            continue

        if pip > 0 and (minor_dist / pip) < cfg.min_impulse_pips:
            if verbose and _r1_logged:
                _log.warning(
                    "[LONG]  R4 ✗  impulse %.1f pips < min %.0f pips",
                    minor_dist / pip, cfg.min_impulse_pips,
                )
            continue

        if verbose:
            _log.info(
                "[LONG]  R4 ✓  depth=%.1f%%  impulse=%.1f pips  |  "
                "trough=%.2f  minor=%.2f  pb=%.2f",
                pb_depth, minor_dist / pip, trough_px, minor_px, pb_px,
            )

        return dict(
            trough_idx=trough_idx, trough_px=trough_px,
            minor_idx=minor_idx, minor_px=minor_px,
            pb_idx=pb_idx, pb_px=pb_px,
            x_move_pct=x_move_pct,
        )

    return None


# ── Rule 5: Entry confirmation ────────────────────────────────────────────────

def _confirm_short_entry(
    s: dict,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    bid: float,
    cfg: StrategyConfig,
) -> Tuple[bool, float]:
    """Returns (enter_now, effective_pb_px)."""
    pb_px    = s["pb_px"]
    minor_px = s["minor_px"]
    peak_px  = s["peak_px"]
    pb_idx   = s["pb_idx"]
    n        = len(closes)
    zone_count = 0

    for i in range(pb_idx + 1, n):
        c = closes[i]
        h = highs[i]
        if c > pb_px:
            new_depth = (h - minor_px) / (peak_px - minor_px) * 100.0 \
                        if (peak_px - minor_px) > 0 else 0.0
            if new_depth > cfg.max_pullback_pct:
                return False, pb_px
            pb_px = h
        elif c < minor_px:
            return False, pb_px
        else:
            zone_count += 1
            if zone_count > cfg.max_zone_candles:
                return False, pb_px

    if bid <= minor_px:
        return True, pb_px
    if minor_px < bid < pb_px:
        return True, pb_px
    return False, pb_px


def _confirm_long_entry(
    s: dict,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    ask: float,
    cfg: StrategyConfig,
) -> Tuple[bool, float]:
    """Returns (enter_now, effective_pb_px). Mirror of _confirm_short_entry."""
    pb_px     = s["pb_px"]
    minor_px  = s["minor_px"]
    trough_px = s["trough_px"]
    pb_idx    = s["pb_idx"]
    n         = len(closes)
    zone_count = 0

    for i in range(pb_idx + 1, n):
        c = closes[i]
        l = lows[i]
        if c < pb_px:
            new_depth = (minor_px - l) / (minor_px - trough_px) * 100.0 \
                        if (minor_px - trough_px) > 0 else 0.0
            if new_depth > cfg.max_pullback_pct:
                return False, pb_px
            pb_px = l
        elif c > minor_px:
            return False, pb_px
        else:
            zone_count += 1
            if zone_count > cfg.max_zone_candles:
                return False, pb_px

    if ask >= minor_px:
        return True, pb_px
    if pb_px < ask < minor_px:
        return True, pb_px
    return False, pb_px


# ── Data fetching ─────────────────────────────────────────────────────────────

_TF_MAP = {
    "M1": mt5.TIMEFRAME_M1, "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1, "H4":  mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1, "W1":  mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}


def _fetch(symbol: str, tf_str: str, count: int) -> Optional[pd.DataFrame]:
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
    if len(df) < 2:
        return False
    if df["time"].iloc[-1].date() == df["time"].iloc[-2].date():
        return True
    o0 = df["o"].iloc[-1]
    h1 = df["h"].iloc[-2]
    l1 = df["l"].iloc[-2]
    return l1 <= o0 <= h1


# ── Core: detect one setup ────────────────────────────────────────────────────

def find_setup(
    cfg: StrategyConfig,
    *,
    bar_provider=None,   # Optional[Callable[[], pd.DataFrame]] — injected in replay
    tick_provider=None,  # Optional[Callable[[], tick-like]]    — injected in replay
) -> Optional[TradeSetup]:
    """
    Fetch bars, run all pre-checks, attempt SHORT then LONG.
    Logs every rule pass and the first failure encountered.

    bar_provider / tick_provider: when supplied (replay mode), these callables
    replace the two live MT5 calls (_fetch and symbol_info_tick).  When None
    (default), live MT5 behaviour is used unchanged.

    Returns a TradeSetup if found, otherwise None.
    """
    # live=True  → full R1-R7 logging in the terminal
    # live=False → replay mode; ReplayEngine logs [TRADE] lines instead
    _live = bar_provider is None

    if _live:
        df = _fetch(cfg.symbol, cfg.timeframe, cfg.candle_count)
    else:
        df = bar_provider()
    if df is None or len(df) < 6:
        return None

    highs  = df["h"].values.astype(float)
    lows   = df["l"].values.astype(float)
    closes = df["c"].values.astype(float)
    opens  = df["o"].values.astype(float)

    # Pre-check 1: gap guard
    if not _gap_guard(df):
        if _live:
            _log.warning("[GATE] Gap guard BLOCKED — daily open outside prior bar range")
        return None

    # Pre-check 2: ICT session filter (Rule 8)
    if not is_in_trading_session(cfg):
        if _live:
            _log.warning("[GATE] Session filter BLOCKED — outside active ICT session (%s)",
                         get_current_session(cfg) or "none")
        return None

    # Pre-check 3: post-TP cooldown (Rule 9) — skipped in replay (no MT5 deal history)
    if _live:
        check_and_update_tp_state(cfg)
    if is_post_tp_cooldown(float(closes[-1]), cfg):
        if _live:
            _log.warning("[GATE] Post-TP cooldown BLOCKED — waiting for cooldown to expire")
        return None

    pip     = _pip_size(cfg.symbol)
    session = get_current_session(cfg)

    tick = tick_provider() if tick_provider is not None else mt5.symbol_info_tick(cfg.symbol)
    if tick is None:
        return None

    # ── Try SHORT ─────────────────────────────────────────────────────────────
    s = _find_short_setup(highs, lows, opens, closes, cfg, pip, verbose=_live)
    if s:
        enter, pb_px = _confirm_short_entry(s, highs, lows, closes, float(tick.bid), cfg)
        if enter:
            if _live:
                _log.info("[SHORT] R5 ✓  Entry zone confirmed  |  bid=%.2f  zone: %.2f–%.2f",
                          tick.bid, s["minor_px"], pb_px)
            cur = float(tick.bid)

            if is_big_move_cooldown("SHORT", opens, closes, cfg):
                if _live:
                    _log.warning("[SHORT] R7 ✗  Big move cooldown BLOCKED")
                s = None
            elif is_near_key_level(cfg.symbol, cur, "SHORT", cfg):
                if _live:
                    _log.warning("[SHORT] R7 ✗  Key level filter BLOCKED — within %.0f pips",
                                 cfg.key_level_pips)
                s = None
            elif _live:
                _log.info("[SHORT] R7 ✓  All filters clear")

            if s:
                midpoint     = (s["peak_px"] + s["minor_px"]) / 2.0
                dist         = midpoint - s["minor_px"]
                tp_px        = s["minor_px"] - dist * (cfg.tp_multiplier / 100.0)
                sl_opt1      = midpoint + pip * 2.0
                sl_opt2      = pb_px    + pip * 2.0
                sl_px        = min(sl_opt1, sl_opt2)

                risk   = sl_px - cur
                reward = cur   - tp_px
                rr     = round(reward / risk, 2) if (risk > 0 and reward > 0) else 0.0

                if rr >= cfg.min_rr:
                    lots = _calc_lots(cur, sl_px, cfg)
                    if _live:
                        _log.info("[SHORT] ▶▶▶ SIGNAL  entry=%.2f  SL=%.2f  TP=%.2f  "
                                  "RR=1:%.2f  lots=%.2f  [%s]",
                                  cur, sl_px, tp_px, rr, lots, session)
                    return TradeSetup(
                        symbol=cfg.symbol, timeframe=cfg.timeframe,
                        direction="SHORT",
                        entry=cur, stop_loss=sl_px, target=tp_px,
                        risk_reward=rr,
                        peak_px=s["peak_px"], minor_px=s["minor_px"],
                        pb_peak_px=pb_px, midpoint=midpoint,
                        x_move_pct=s["x_move_pct"],
                        session=session,
                        setup_notes=_build_notes(
                            "SHORT", cur, sl_px, tp_px, rr,
                            s["peak_px"], s["minor_px"],
                            pb_px, midpoint, s["x_move_pct"], session),
                    )
                elif _live:
                    _log.warning("[SHORT] RR %.2f < min %.2f — skipping", rr, cfg.min_rr)
        elif _live:
            _log.warning("[SHORT] R5 ✗  Entry zone rejected  |  bid=%.2f  "
                         "(minor=%.2f  eff_pb=%.2f)",
                         tick.bid, s["minor_px"], pb_px)

    # ── Try LONG ──────────────────────────────────────────────────────────────
    lg = _find_long_setup(highs, lows, opens, closes, cfg, pip, verbose=_live)
    if lg:
        enter, pb_px = _confirm_long_entry(lg, highs, lows, closes, float(tick.ask), cfg)
        if enter:
            if _live:
                _log.info("[LONG]  R5 ✓  Entry zone confirmed  |  ask=%.2f  zone: %.2f–%.2f",
                          tick.ask, pb_px, lg["minor_px"])
            cur = float(tick.ask)

            if is_big_move_cooldown("LONG", opens, closes, cfg):
                if _live:
                    _log.warning("[LONG]  R7 ✗  Big move cooldown BLOCKED")
                lg = None
            elif is_near_key_level(cfg.symbol, cur, "LONG", cfg):
                if _live:
                    _log.warning("[LONG]  R7 ✗  Key level filter BLOCKED — within %.0f pips",
                                 cfg.key_level_pips)
                lg = None
            elif _live:
                _log.info("[LONG]  R7 ✓  All filters clear")

            if lg:
                midpoint = (lg["trough_px"] + lg["minor_px"]) / 2.0
                dist     = lg["minor_px"] - midpoint
                tp_px    = lg["minor_px"] + dist * (cfg.tp_multiplier / 100.0)
                sl_opt1  = midpoint - pip * 2.0
                sl_opt2  = pb_px    - pip * 2.0
                sl_px    = max(sl_opt1, sl_opt2)

                risk   = cur   - sl_px
                reward = tp_px - cur
                rr     = round(reward / risk, 2) if (risk > 0 and reward > 0) else 0.0

                if rr >= cfg.min_rr:
                    lots = _calc_lots(cur, sl_px, cfg)
                    if _live:
                        _log.info("[LONG]  ▶▶▶ SIGNAL  entry=%.2f  SL=%.2f  TP=%.2f  "
                                  "RR=1:%.2f  lots=%.2f  [%s]",
                                  cur, sl_px, tp_px, rr, lots, session)
                    return TradeSetup(
                        symbol=cfg.symbol, timeframe=cfg.timeframe,
                        direction="LONG",
                        entry=cur, stop_loss=sl_px, target=tp_px,
                        risk_reward=rr,
                        peak_px=lg["trough_px"], minor_px=lg["minor_px"],
                        pb_peak_px=pb_px, midpoint=midpoint,
                        x_move_pct=lg["x_move_pct"],
                        session=session,
                        setup_notes=_build_notes(
                            "LONG", cur, sl_px, tp_px, rr,
                            lg["trough_px"], lg["minor_px"],
                            pb_px, midpoint, lg["x_move_pct"], session),
                    )
                elif _live:
                    _log.warning("[LONG]  RR %.2f < min %.2f — skipping", rr, cfg.min_rr)
        elif _live:
            _log.warning("[LONG]  R5 ✗  Entry zone rejected  |  ask=%.2f  "
                         "(eff_pb=%.2f  minor=%.2f)",
                         tick.ask, pb_px, lg["minor_px"])

    return None


# ── Lot sizing ────────────────────────────────────────────────────────────────

def _calc_lots(entry: float, stop_loss: float, cfg: StrategyConfig) -> float:
    info = mt5.symbol_info(cfg.symbol)
    if info is None:
        return info.volume_min if info else 0.01
    balance  = mt5.account_info().balance
    risk_amt = balance * cfg.risk_pct / 100.0
    sl_dist  = abs(entry - stop_loss)
    if sl_dist == 0 or info.trade_tick_size == 0 or info.trade_tick_value == 0:
        return info.volume_min
    lot = risk_amt / (sl_dist * (info.trade_tick_value / info.trade_tick_size))
    max_lot  = min(info.volume_max, cfg.max_lots)
    lot = max(info.volume_min, min(max_lot, lot))
    if info.volume_step > 0:
        lot = round(lot / info.volume_step) * info.volume_step
    return lot


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
