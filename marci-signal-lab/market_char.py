"""
Market character analysis — aggregates per 30-min slot:
  - Directional bias (% buy, % sell, net bias score)
  - Volatility (ATR, annualised HV, avg move %)
  - Tick volume (avg, relative)
  - Liquidity proxy (volume / range)
  - Big-move candle frequency
  - Tight-range candle frequency
  - Average % move size
  - Price increase / decrease / tight-range classification per slot

Also provides overall-period summary stats.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import LabConfig
from periods import SLOT_LABELS


# ── Indicator helpers ─────────────────────────────────────────────────────────

def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    prev_c = df["c"].shift(1)
    tr = pd.concat([
        df["h"] - df["l"],
        (df["h"] - prev_c).abs(),
        (df["l"] - prev_c).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


# ── Per-slot aggregation ──────────────────────────────────────────────────────

def compute_market_char(df: pd.DataFrame, cfg: LabConfig) -> pd.DataFrame:
    """
    Aggregate per-slot statistics across all bars in df.
    Returns a 48-row DataFrame indexed by slot (0–47) containing:

      label          — '00:00', '00:30', … '23:30'
      n_bars         — total bars observed in this slot
      avg_move_pct   — avg absolute body % (open→close)
      avg_range_pct  — avg H-L % (volatility proxy)
      pct_buy        — % of bars that closed up
      pct_sell       — % of bars that closed down
      pct_big        — % of bars with body >= big_move_pct
      pct_tight      — % of bars with range < tight_range_pct
      pct_up         — % of bars where close > open  (same as pct_buy, included for clarity)
      pct_down       — same as pct_sell
      pct_range      — % of bars where close ≈ open (doji / flat)
      avg_volume     — avg MT5 tick_volume
      rel_volume     — avg tick_volume relative to overall daily mean
      avg_atr        — avg ATR value
      bias_score     — pct_buy − pct_sell  (−100 to +100, + = bullish)
      liq_proxy      — volume / (range × price)  (higher = more liquid)
      hist_vol_ann   — annualised realised vol for this slot (%)
    """
    work = df.copy()
    work["atr"] = _atr_series(work, cfg.atr_period)
    work["slot"] = work["slot"].astype(int)

    daily_vol_mean = work["tick_volume"].mean()

    grp = work.groupby("slot")

    r = pd.DataFrame(index=range(48))
    r.index.name = "slot"
    r["label"]         = SLOT_LABELS

    count = grp["c"].count().reindex(range(48), fill_value=0)
    r["n_bars"]        = count

    r["avg_move_pct"]  = grp["move_pct"].mean().reindex(range(48))
    r["avg_range_pct"] = grp["range_pct"].mean().reindex(range(48))

    buy_sum  = grp["is_buy"].sum().reindex(range(48), fill_value=0)
    sell_sum = grp["is_sell"].sum().reindex(range(48), fill_value=0)
    doji_sum = count - buy_sum - sell_sum

    r["pct_buy"]   = (buy_sum  / count.clip(lower=1) * 100).round(1)
    r["pct_sell"]  = (sell_sum / count.clip(lower=1) * 100).round(1)
    r["pct_up"]    = r["pct_buy"]
    r["pct_down"]  = r["pct_sell"]
    r["pct_range"] = (doji_sum / count.clip(lower=1) * 100).round(1)

    big_sum   = grp["is_big"].sum().reindex(range(48), fill_value=0)
    tight_sum = grp["is_tight"].sum().reindex(range(48), fill_value=0)
    r["pct_big"]   = (big_sum   / count.clip(lower=1) * 100).round(1)
    r["pct_tight"] = (tight_sum / count.clip(lower=1) * 100).round(1)

    r["avg_volume"] = grp["tick_volume"].mean().reindex(range(48))
    r["rel_volume"] = (r["avg_volume"] / daily_vol_mean).round(2) if daily_vol_mean > 0 else np.nan

    r["avg_atr"]   = grp["atr"].mean().reindex(range(48))

    # Bias: positive = more buy bars, negative = more sell bars
    r["bias_score"] = (r["pct_buy"] - r["pct_sell"]).round(1)

    # Liquidity proxy: tick_volume / (H-L range in price terms)
    avg_price = float(work["c"].mean()) if len(work) > 0 else 1.0
    hl_range_abs = grp.apply(
        lambda g: (g["range_pct"] * g["o"] / 100.0).mean()
    ).reindex(range(48))
    r["liq_proxy"] = (r["avg_volume"] / hl_range_abs.clip(lower=0.001)).round(1)

    # Annualised HV per slot (M30 bars/year ≈ 48 * 252)
    bars_per_year = 48 * 252
    log_std = grp["log_ret"].std().reindex(range(48))
    r["hist_vol_ann"] = (log_std * np.sqrt(bars_per_year) * 100).round(2)

    return r


# ── Overall period summaries ──────────────────────────────────────────────────

def overall_bias(df: pd.DataFrame) -> str:
    """Compare first and last 20% of closes to determine directional bias."""
    n = len(df)
    if n < 10:
        return "NEUTRAL  (insufficient data)"
    seg = max(1, n // 5)
    early = df["c"].iloc[:seg].mean()
    late  = df["c"].iloc[-seg:].mean()
    pct   = (late - early) / early * 100
    if pct > 0.5:
        return f"BULLISH  ({pct:+.2f}% over period)"
    if pct < -0.5:
        return f"BEARISH  ({pct:+.2f}% over period)"
    return f"NEUTRAL  ({pct:+.2f}% over period)"


def overall_volatility(df: pd.DataFrame, cfg: LabConfig) -> dict:
    """Overall volatility stats for the analysis period."""
    atr       = _atr_series(df, cfg.atr_period)
    avg_price = float(df["c"].mean()) if len(df) > 0 else 1.0
    log_ret   = np.log(df["c"] / df["c"].shift(1)).dropna()
    hv_ann    = float(log_ret.std() * np.sqrt(48 * 252) * 100)

    big_buy  = df[df["is_big"] & df["is_buy"]].shape[0]
    big_sell = df[df["is_big"] & df["is_sell"]].shape[0]

    return {
        "avg_atr":         float(atr.mean()),
        "avg_atr_pct":     float(atr.mean() / avg_price * 100) if avg_price else 0,
        "hv_annualised":   hv_ann,
        "avg_move_pct":    float(df["move_pct"].mean()),
        "avg_range_pct":   float(df["range_pct"].mean()),
        "pct_big_moves":   float(df["is_big"].mean() * 100),
        "big_buy_count":   big_buy,
        "big_sell_count":  big_sell,
        "pct_tight":       float(df["is_tight"].mean() * 100),
        "avg_tick_volume": float(df["tick_volume"].mean()),
    }


def big_move_profile(df: pd.DataFrame, cfg: LabConfig) -> pd.DataFrame:
    """
    For each slot: count of big buy candles, big sell candles, avg size when big.
    Useful for identifying when large directional moves tend to occur.
    """
    work = df.copy()
    work["slot"] = work["slot"].astype(int)
    big = work[work["is_big"]].copy()
    if big.empty:
        return pd.DataFrame()

    grp = big.groupby("slot")
    out = pd.DataFrame(index=range(48))
    out["label"]       = SLOT_LABELS
    out["big_buy"]     = big[big["is_buy"]].groupby("slot").size().reindex(range(48), fill_value=0)
    out["big_sell"]    = big[big["is_sell"]].groupby("slot").size().reindex(range(48), fill_value=0)
    out["avg_big_pct"] = grp["move_pct"].mean().reindex(range(48))
    out["total_big"]   = out["big_buy"] + out["big_sell"]
    return out[out["total_big"] > 0].sort_values("total_big", ascending=False)
