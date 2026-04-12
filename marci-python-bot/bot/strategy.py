"""
Marci Silfrain — Measured Move Trend Strategy
Detects "Little RZY" structures and generates TradeSetup signals.

Strategy rules (from playbook):
  1.  Identify the trend first (LH+LL = downtrend, HH+HL = uptrend)
  2.  Wait for the initial impulse move + pullback — never enter the impulse
  3.  Draw trendline across pullback highs (downtrend) / lows (uptrend)
  4.  Find the lowest low (short) or highest high (long) in the pullback structure
  5.  Measure vertical distance from that point to the trendline
  6.  Project that distance in the trend direction = target
  7.  Enter when price rejects the trendline and resumes the trend
  8.  Stop above pullback high (short) / below pullback low (long)
  9.  Use Bollinger Bands as a context filter (near upper BB = better shorts)
  10. First/second structures are strongest; 4th+ shows exhaustion
"""

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime
from typing import List, Optional, Tuple

from .signals import TradeSetup

# ── Timeframe map ─────────────────────────────────────────────────────────────

TF_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
    "W1":  mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}

# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_candles(symbol: str, tf_str: str, count: int = 200) -> Optional[pd.DataFrame]:
    """
    Fetch completed OHLC candles from MT5.
    Starts at position 1 to skip the currently forming bar.
    """
    tf = TF_MAP.get(tf_str.upper())
    if tf is None:
        print(f"  Unknown timeframe: {tf_str}")
        return None

    rates = mt5.copy_rates_from_pos(symbol, tf, 1, count)
    if rates is None or len(rates) == 0:
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c"}, inplace=True)
    return df

# ── Bollinger Bands ───────────────────────────────────────────────────────────

def calc_bollinger(
    closes: np.ndarray, period: int = 20, std_dev: float = 2.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (upper, middle, lower) Bollinger Band arrays."""
    s   = pd.Series(closes)
    mid = s.rolling(period).mean().values
    std = s.rolling(period).std().values
    return mid + std_dev * std, mid, mid - std_dev * std


def bb_position_label(price: float, upper: float, middle: float, lower: float) -> str:
    """Classify price position relative to Bollinger Bands."""
    band_width = upper - lower
    if band_width == 0:
        return "MIDDLE"
    pos = (price - lower) / band_width   # 0 = at lower, 1 = at upper
    if price >= upper:
        return "BEYOND_UPPER"
    elif price <= lower:
        return "BEYOND_LOWER"
    elif pos >= 0.75:
        return "NEAR_UPPER"
    elif pos <= 0.25:
        return "NEAR_LOWER"
    else:
        return "MIDDLE"

# ── Swing point detection ─────────────────────────────────────────────────────

def find_swing_highs(highs: np.ndarray, n: int = 3) -> List[Tuple[int, float]]:
    """
    Returns (index, price) for confirmed swing highs.
    A swing high requires n bars of lower highs on both sides.
    """
    result = []
    for i in range(n, len(highs) - n):
        if (all(highs[i] >= highs[i - j] for j in range(1, n + 1)) and
                all(highs[i] >= highs[i + j] for j in range(1, n + 1))):
            result.append((i, float(highs[i])))
    return result


def find_swing_lows(lows: np.ndarray, n: int = 3) -> List[Tuple[int, float]]:
    """
    Returns (index, price) for confirmed swing lows.
    A swing low requires n bars of higher lows on both sides.
    """
    result = []
    for i in range(n, len(lows) - n):
        if (all(lows[i] <= lows[i - j] for j in range(1, n + 1)) and
                all(lows[i] <= lows[i + j] for j in range(1, n + 1))):
            result.append((i, float(lows[i])))
    return result

# ── Trend detection ───────────────────────────────────────────────────────────

def detect_trend(
    swing_highs: List[Tuple[int, float]],
    swing_lows: List[Tuple[int, float]],
    min_pts: int = 3,
) -> str:
    """
    Rule 1 from playbook: confirm the trend using swing structure.
    Returns 'DOWN', 'UP', or 'SIDEWAYS'.
    Requires min_pts consecutive swing points all moving the same direction.
    """
    if len(swing_highs) < min_pts or len(swing_lows) < min_pts:
        return "SIDEWAYS"

    sh = [p for _, p in swing_highs[-min_pts:]]
    sl = [p for _, p in swing_lows[-min_pts:]]

    sh_down = all(sh[i] > sh[i + 1] for i in range(len(sh) - 1))
    sl_down = all(sl[i] > sl[i + 1] for i in range(len(sl) - 1))
    sh_up   = all(sh[i] < sh[i + 1] for i in range(len(sh) - 1))
    sl_up   = all(sl[i] < sl[i + 1] for i in range(len(sl) - 1))

    if sh_down and sl_down:
        return "DOWN"
    elif sh_up and sl_up:
        return "UP"
    return "SIDEWAYS"

# ── Structure count ───────────────────────────────────────────────────────────

def count_structures(
    swing_highs: List[Tuple[int, float]],
    swing_lows: List[Tuple[int, float]],
    direction: str,
) -> int:
    """
    Rule 9 from playbook: count how many Little RZY structures have already
    formed in this trend.  1 = first (strongest), 4+ = exhaustion zone.
    """
    if direction == "DOWN":
        return max(1, len(swing_lows) - 1)
    elif direction == "UP":
        return max(1, len(swing_highs) - 1)
    return 1

# ── Signal strength ───────────────────────────────────────────────────────────

def assess_signal_strength(direction: str, bb_pos: str, struct_count: int) -> str:
    """
    Rule 8 + 9 combined:
      HIGH   = early structure (1-2) + BB in favorable zone
      MEDIUM = early structure OR favorable BB, but not both
      LOW    = late structure (4+) OR price at exhausted BB extreme
    """
    early = struct_count <= 2

    if direction == "SHORT":
        good_bb      = bb_pos in ("NEAR_UPPER", "BEYOND_UPPER")
        exhausted_bb = bb_pos in ("NEAR_LOWER", "BEYOND_LOWER")
    else:
        good_bb      = bb_pos in ("NEAR_LOWER", "BEYOND_LOWER")
        exhausted_bb = bb_pos in ("NEAR_UPPER", "BEYOND_UPPER")

    if exhausted_bb or struct_count >= 4:
        return "LOW"
    elif early and good_bb:
        return "HIGH"
    else:
        return "MEDIUM"

# ── Little RZY setup detection ────────────────────────────────────────────────

def find_rzy_setup(
    df: pd.DataFrame,
    symbol: str,
    tf_str: str,
    swing_n: int = 3,
    min_rr: float = 1.5,
) -> Optional[TradeSetup]:
    """
    Core detector.  Implements all 10 rules from the Marci Silfrain playbook.

    For a SHORT in a downtrend:
      • anchor_price     = most recent swing low (SL)   — impulse endpoint
      • pullback_extreme = highest high after SL (PH)   — trendline reference
      • measured_distance = PH - SL
      • target           = SL - measured_distance
      • stop             = PH + small buffer

    For a LONG in an uptrend: mirror image.
    """
    if len(df) < 50:
        return None

    highs  = df["h"].values
    lows   = df["l"].values
    closes = df["c"].values

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    bb_upper_arr, bb_mid_arr, bb_lower_arr = calc_bollinger(closes)
    last_bb_upper  = bb_upper_arr[-1]
    last_bb_mid    = bb_mid_arr[-1]
    last_bb_lower  = bb_lower_arr[-1]

    if np.isnan(last_bb_upper):
        return None

    current_price = float(closes[-1])
    bb_pos = bb_position_label(current_price, last_bb_upper, last_bb_mid, last_bb_lower)

    # ── Swing points ──────────────────────────────────────────────────────────
    sw_highs = find_swing_highs(highs, swing_n)
    sw_lows  = find_swing_lows(lows, swing_n)

    if not sw_highs or not sw_lows:
        return None

    # ── Trend (Rule 1) ────────────────────────────────────────────────────────
    trend = detect_trend(sw_highs, sw_lows)
    if trend == "SIDEWAYS":
        return None

    struct_count = count_structures(sw_highs, sw_lows, trend)

    # ── Tick data for live price ──────────────────────────────────────────────
    tick     = mt5.symbol_info_tick(symbol)
    sym_info = mt5.symbol_info(symbol)
    if tick is None or sym_info is None:
        return None

    # ════════════════════════════════════════════════════════════════════════
    # SHORT SETUP  (downtrend "Little RZY")
    # ════════════════════════════════════════════════════════════════════════
    if trend == "DOWN":
        # Rule 2: wait for impulse + pullback
        # Anchor = most recent swing low (bottom of impulse)
        sl_idx, sl_price = sw_lows[-1]

        # Find pullback high: highest high in candles after the swing low
        seg_highs = highs[sl_idx:]
        if len(seg_highs) < 2:
            return None

        ph_local_idx = int(np.argmax(seg_highs))
        ph_price     = float(seg_highs[ph_local_idx])
        ph_idx       = sl_idx + ph_local_idx

        # Sanity: pullback must not exceed the prior swing high (would break trend)
        # Rule 10 invalidation check
        if sw_highs and ph_price >= sw_highs[-1][1]:
            return None

        # Rule 3/4: entry conditions — price in pullback zone and rolling over
        in_zone = sl_price < current_price < ph_price

        # Has price recently visited the upper part of the pullback (near trendline)?
        recent_closes = closes[max(0, len(closes) - 8):]
        visited_peak  = any(c >= ph_price * 0.97 for c in recent_closes)

        # Bearish momentum: current price has pulled back from the recent high
        recent_hi = float(np.max(highs[max(0, len(highs) - 5):]))
        rolling_over = current_price < recent_hi * 0.999

        if not (in_zone and visited_peak and rolling_over):
            return None

        # Rule 4/5: measured distance and target
        measured_distance = ph_price - sl_price
        if measured_distance <= 0:
            return None

        target = sl_price - measured_distance

        # Rule 6: entry + stop
        entry     = float(tick.bid)                          # short = sell at bid
        buffer    = sym_info.point * 10
        stop_loss = ph_price + buffer

        risk   = stop_loss - entry
        reward = entry - target
        if risk <= 0 or reward <= 0:
            return None

        rr = round(reward / risk, 2)
        if rr < min_rr:
            return None

        strength = assess_signal_strength("SHORT", bb_pos, struct_count)

        notes = [
            f"Rule 1  — Trend: DOWNTREND  (lower highs + lower lows confirmed)",
            f"Rule 2  — Waited for impulse move + pullback  (not entering impulse)",
            f"Rule 3  — Trendline reference (pullback high): {ph_price:.5f}",
            f"Rule 4  — Lowest low of structure (anchor): {sl_price:.5f}",
            f"Rule 5  — Measured distance: {measured_distance:.5f}  "
            f"({measured_distance / sl_price * 100:.2f}%)",
            f"Rule 6  — Projected target: {target:.5f}",
            f"Rule 7  — Entry on trendline rejection: price rolling over near {ph_price:.5f}",
            f"Rule 8  — Bollinger Band position: {bb_pos}  "
            f"(upper={last_bb_upper:.5f}  mid={last_bb_mid:.5f}  lower={last_bb_lower:.5f})",
            f"Rule 9  — Structure #{struct_count} in trend  "
            f"(1-2 = strongest, 4+ = exhaustion risk)",
            f"Rule 10 — Setup valid while price stays below trendline ({ph_price:.5f})",
        ]

        return TradeSetup(
            symbol=symbol,
            timeframe=tf_str,
            direction="SHORT",
            entry=entry,
            stop_loss=stop_loss,
            target=target,
            risk_reward=rr,
            anchor_price=sl_price,
            pullback_extreme=ph_price,
            measured_distance=measured_distance,
            bb_upper=last_bb_upper,
            bb_middle=last_bb_mid,
            bb_lower=last_bb_lower,
            bb_position=bb_pos,
            structure_count=struct_count,
            signal_strength=strength,
            setup_notes=notes,
            invalidation_price=stop_loss,
        )

    # ════════════════════════════════════════════════════════════════════════
    # LONG SETUP  (uptrend "Little RZY" — mirror image of short)
    # ════════════════════════════════════════════════════════════════════════
    elif trend == "UP":
        # Anchor = most recent swing high (top of impulse)
        sh_idx, sh_price = sw_highs[-1]

        # Find pullback low: lowest low in candles after the swing high
        seg_lows = lows[sh_idx:]
        if len(seg_lows) < 2:
            return None

        pl_local_idx = int(np.argmin(seg_lows))
        pl_price     = float(seg_lows[pl_local_idx])
        pl_idx       = sh_idx + pl_local_idx

        # Sanity: pullback must not break below the prior swing low (would break trend)
        if sw_lows and pl_price <= sw_lows[-1][1]:
            return None

        in_zone = pl_price < current_price < sh_price

        recent_closes = closes[max(0, len(closes) - 8):]
        visited_trough = any(c <= pl_price * 1.03 for c in recent_closes)

        recent_lo   = float(np.min(lows[max(0, len(lows) - 5):]))
        bouncing_up = current_price > recent_lo * 1.001

        if not (in_zone and visited_trough and bouncing_up):
            return None

        measured_distance = sh_price - pl_price
        if measured_distance <= 0:
            return None

        target = sh_price + measured_distance

        entry     = float(tick.ask)                          # long = buy at ask
        buffer    = sym_info.point * 10
        stop_loss = pl_price - buffer

        risk   = entry - stop_loss
        reward = target - entry
        if risk <= 0 or reward <= 0:
            return None

        rr = round(reward / risk, 2)
        if rr < min_rr:
            return None

        strength = assess_signal_strength("LONG", bb_pos, struct_count)

        notes = [
            f"Rule 1  — Trend: UPTREND  (higher highs + higher lows confirmed)",
            f"Rule 2  — Waited for impulse move + pullback  (not entering impulse)",
            f"Rule 3  — Trendline reference (pullback low): {pl_price:.5f}",
            f"Rule 4  — Highest high of structure (anchor): {sh_price:.5f}",
            f"Rule 5  — Measured distance: {measured_distance:.5f}  "
            f"({measured_distance / sh_price * 100:.2f}%)",
            f"Rule 6  — Projected target: {target:.5f}",
            f"Rule 7  — Entry on trendline bounce: price recovering from {pl_price:.5f}",
            f"Rule 8  — Bollinger Band position: {bb_pos}  "
            f"(upper={last_bb_upper:.5f}  mid={last_bb_mid:.5f}  lower={last_bb_lower:.5f})",
            f"Rule 9  — Structure #{struct_count} in trend  "
            f"(1-2 = strongest, 4+ = exhaustion risk)",
            f"Rule 10 — Setup valid while price stays above trendline ({pl_price:.5f})",
        ]

        return TradeSetup(
            symbol=symbol,
            timeframe=tf_str,
            direction="LONG",
            entry=entry,
            stop_loss=stop_loss,
            target=target,
            risk_reward=rr,
            anchor_price=sh_price,
            pullback_extreme=pl_price,
            measured_distance=measured_distance,
            bb_upper=last_bb_upper,
            bb_middle=last_bb_mid,
            bb_lower=last_bb_lower,
            bb_position=bb_pos,
            structure_count=struct_count,
            signal_strength=strength,
            setup_notes=notes,
            invalidation_price=stop_loss,
        )

    return None

# ── Full scan ─────────────────────────────────────────────────────────────────

def scan_all(
    symbols: List[str],
    timeframes: List[str],
    candles: int = 200,
    swing_n: int = 3,
    min_rr: float = 1.5,
) -> List[TradeSetup]:
    """Scan every symbol × timeframe combination for setups."""
    setups = []
    for symbol in symbols:
        for tf in timeframes:
            df = fetch_candles(symbol, tf, candles)
            if df is None:
                continue
            setup = find_rzy_setup(df, symbol, tf, swing_n, min_rr)
            if setup:
                setups.append(setup)
    return setups

# ── Console dashboard ─────────────────────────────────────────────────────────

def print_dashboard(setups: List[TradeSetup], symbols: List[str], timeframes: List[str]):
    """Print a clean scan summary to the terminal."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "─" * 62

    print(f"\n{sep}")
    print(f"  Marci Silfrain  —  Measured Move Trend Strategy EA")
    print(f"  Scan      : {now}")
    print(f"  Watching  : {', '.join(symbols)}")
    print(f"  Timeframes: {', '.join(timeframes)}")
    print(sep)

    if not setups:
        print("  No setups detected — monitoring for Little RZY structures...")
        print(sep)
        return

    for s in setups:
        icon = {"HIGH": "[>>>]", "MEDIUM": "[ >>]", "LOW": "[  >]"}[s.signal_strength]
        print(f"\n  {icon}  {s.signal_strength} CONFIDENCE  |  {s.direction}  "
              f"{s.symbol}  [{s.timeframe}]")
        print(f"         Entry    : {s.entry:.5f}")
        print(f"         Stop     : {s.stop_loss:.5f}")
        print(f"         Target   : {s.target:.5f}")
        print(f"         R:R      : 1:{s.risk_reward}")
        print(f"         BB Pos   : {s.bb_position}")
        print(f"         Struct # : {s.structure_count}  (in current trend)")
    print(sep)
