"""
Extended 48-slot market character table.

Adds to the base market_char metrics:
  rsi_avg        — avg RSI(14) value for bars in each slot
  volatility_lbl — HIGH / NORMAL / LOW  (hist_vol_ann percentile within 48 slots)
  volume_lbl     — HIGH / NORMAL / LOW  (rel_volume thresholds)
  pct_ict_vol    — slot avg tick_volume as % of avg ICT-session bar volume
  pct_daily_vol  — slot avg tick_volume as % of overall daily bar mean
  money_spent    — avg(tick_volume × close)  — dollar-turnover proxy per bar
  big_freq       — % of bars that are big-move candles  (alias pct_big)
  tight_freq     — % of bars that are tight-range candles (alias pct_tight)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config   import LabConfig
from periods  import SLOT_LABELS
from market_char import compute_market_char, _atr_series

# ── RSI helper ────────────────────────────────────────────────────────────────

def _rsi_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder-smoothed RSI on close prices."""
    delta = df["c"].diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


# ── Extended slot table ───────────────────────────────────────────────────────

def compute_slot_market_char(df: pd.DataFrame, cfg: LabConfig) -> pd.DataFrame:
    """
    Build a 48-row DataFrame with full market character per 30-min slot.

    Columns returned:
      label, n_bars,
      pct_buy, pct_sell,           directional bias
      bias_score,                  pct_buy − pct_sell
      avg_range_pct, hist_vol_ann, volatility_lbl, rsi_avg,
      avg_volume, rel_volume, volume_lbl,
      pct_ict_vol,                 % of avg ICT-session bar volume
      pct_daily_vol,               % of avg daily bar mean
      money_spent,                 avg(tick_volume × close)
      pct_big, pct_tight,          candle type frequency
      avg_atr, avg_move_pct, liq_proxy
    """
    work = df.copy()
    work["rsi"]     = _rsi_series(work, cfg.rsi_period)
    work["money"]   = work["tick_volume"] * work["c"]   # turnover proxy per bar
    work["slot"]    = work["slot"].astype(int)

    # Base 48-slot aggregation
    base = compute_market_char(df, cfg)

    grp = work.groupby("slot")

    # RSI per slot
    base["rsi_avg"] = grp["rsi"].mean().reindex(range(48)).round(1)

    # Money spent per slot (avg dollar turnover per bar)
    base["money_spent"] = grp["money"].mean().reindex(range(48)).round(0)

    # ── Volume benchmarks ────────────────────────────────────────────────────
    daily_mean = float(work["tick_volume"].mean())   # overall bar mean

    # ICT session mean: bars tagged in Asian, London, or NY (not "Off")
    ict_bars = work[work["session"] != "Off"]
    ict_mean = float(ict_bars["tick_volume"].mean()) if len(ict_bars) > 0 else daily_mean

    base["pct_ict_vol"]   = (base["avg_volume"] / ict_mean   * 100).round(1)
    base["pct_daily_vol"] = (base["avg_volume"] / daily_mean * 100).round(1)

    # ── Labels ───────────────────────────────────────────────────────────────
    # Volatility label: percentile rank of hist_vol_ann within the 48 slots
    hv = base["hist_vol_ann"].fillna(0)
    p25, p75 = hv.quantile(0.25), hv.quantile(0.75)

    def _vol_lbl(v):
        if pd.isna(v): return "—"
        if v >= p75:   return "HIGH"
        if v <= p25:   return "LOW"
        return "NORMAL"

    base["volatility_lbl"] = hv.apply(_vol_lbl)

    # Volume label: relative to overall daily mean
    def _vol_label(rv):
        if pd.isna(rv): return "—"
        if rv >= 1.5:   return "HIGH"
        if rv <= 0.5:   return "LOW"
        return "NORMAL"

    base["volume_lbl"] = base["rel_volume"].apply(_vol_label)

    # Aliases for clarity
    base["big_freq"]   = base["pct_big"]
    base["tight_freq"] = base["pct_tight"]

    return base


# ── Session-filtered view (RTH only) ─────────────────────────────────────────

def compute_rth_slots(df: pd.DataFrame, cfg: LabConfig) -> pd.DataFrame:
    """
    Same as compute_slot_market_char but restricted to RTH-tagged bars.
    Only slots that have at least one RTH bar are returned (variable row count).
    """
    rth = df[df["is_rth"]].copy()
    if rth.empty:
        raise RuntimeError("No RTH bars found — check cfg.rth_start_h / rth_end_h.")
    return compute_slot_market_char(rth, cfg)


# ── Console printer ───────────────────────────────────────────────────────────

def print_slot_market_char(
    char: pd.DataFrame,
    cfg:  LabConfig,
    title: str = "48-SLOT MARKET CHARACTER",
    top_n: int = 48,
    sort_by: str = "avg_volume",
) -> None:
    W = 110
    print("=" * W)
    print(f"  {title}  ·  {cfg.symbol}  [{cfg.analysis_tf}]")
    print("=" * W)

    cols = [
        "label", "n_bars",
        "pct_buy", "pct_sell", "bias_score",
        "volatility_lbl", "rsi_avg",
        "volume_lbl", "avg_volume", "pct_ict_vol", "pct_daily_vol",
        "pct_big", "pct_tight",
        "money_spent",
    ]
    rename = {
        "label":         "Time(UTC)",
        "n_bars":        "N",
        "pct_buy":       "%Buy",
        "pct_sell":      "%Sell",
        "bias_score":    "Bias",
        "volatility_lbl":"VolatLbl",
        "rsi_avg":       "RSI",
        "volume_lbl":    "VolLbl",
        "avg_volume":    "AvgTickVol",
        "pct_ict_vol":   "%ICTVol",
        "pct_daily_vol": "%DailyVol",
        "pct_big":       "%Big",
        "pct_tight":     "%Tight",
        "money_spent":   "MoneySpent",
    }

    show = char.nlargest(top_n, sort_by)[
        [c for c in cols if c in char.columns]
    ].rename(columns=rename).copy()

    # Round numerics for display
    for col in ["%Buy", "%Sell", "Bias", "RSI", "%ICTVol", "%DailyVol", "%Big", "%Tight"]:
        if col in show.columns:
            show[col] = show[col].round(1)
    if "MoneySpent" in show.columns:
        show["MoneySpent"] = show["MoneySpent"].apply(
            lambda x: f"{x:,.0f}" if pd.notna(x) else "—"
        )
    if "AvgTickVol" in show.columns:
        show["AvgTickVol"] = show["AvgTickVol"].round(0).astype("Int64")

    print(show.to_string(index=False))
    print("─" * W)
    print("  VolatLbl: HIGH/NORMAL/LOW = percentile rank of annualised HV across 48 slots")
    print("  VolLbl  : HIGH ≥ 1.5× daily mean  |  LOW ≤ 0.5× daily mean")
    print("  %ICTVol : slot avg tick vol as % of avg ICT-session bar volume")
    print("  %DailyVol: slot avg tick vol as % of overall daily bar mean")
    print("  MoneySpent: avg(tick_volume × close) — dollar-turnover proxy per bar")
    print("=" * W)
