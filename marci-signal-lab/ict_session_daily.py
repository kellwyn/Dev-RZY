"""
ICT RTH daily session analysis — last 20 calendar days with 30-day rolling baselines.

For each trading day in the last 20 days, aggregates RTH-only bars to produce:
  session_vol        — total tick_volume for RTH bars that day
  daily_vol          — total tick_volume for ALL bars that day
  money_spent        — sum(tick_volume × close) for RTH bars (dollar-turnover proxy)
  pct_buyers         — % of RTH bars that closed up
  pct_sellers        — % of RTH bars that closed down
  avg_rsi            — avg RSI(14) across RTH bars
  avg_range_pct      — avg H-L % across RTH bars (raw volatility)
  volatility_lbl     — HIGH / NORMAL / LOW vs 30-day rolling mean ± std

Baseline columns (30-day rolling):
  session_vol_30d    — 30-day rolling mean of session_vol
  daily_vol_30d      — 30-day rolling mean of daily_vol
  pct_vs_session     — session_vol / session_vol_30d × 100
  pct_vs_daily       — daily_vol / daily_vol_30d × 100

Anomaly flag:
  anomaly            — comma-separated list of metrics that deviate > 1.5 σ
                       from their 30-day rolling mean
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

from config  import LabConfig
from periods import SLOT_LABELS
from slot_market_char import _rsi_series

_ANOMALY_THRESHOLD = 1.5   # σ multiplier for anomaly flagging


# ── RSI bar tags ──────────────────────────────────────────────────────────────

def _add_rsi(df: pd.DataFrame, period: int) -> pd.DataFrame:
    df = df.copy()
    df["rsi"] = _rsi_series(df, period)
    return df


# ── Daily aggregation ─────────────────────────────────────────────────────────

def build_ict_session_daily(df: pd.DataFrame, cfg: LabConfig) -> pd.DataFrame:
    """
    Build a per-day DataFrame covering the last 20 calendar days,
    with 30-day rolling baselines and anomaly detection.

    Args:
        df: Full OHLCV DataFrame from fetch_ohlcv (must include is_rth, session,
            tick_volume, move_pct, range_pct, is_buy, is_sell, is_big, is_tight,
            log_ret columns).
        cfg: LabConfig (uses rsi_period, big_move_pct, tight_range_pct).

    Returns:
        DataFrame with one row per trading day (most recent last), sorted ascending.
        Filtered to last 20 days for display, with 30-day rolling baselines computed
        across the full window.
    """
    work = _add_rsi(df, cfg.rsi_period)
    work["date"] = work["time"].dt.date

    # ── Aggregate ALL bars per day (for daily_vol) ────────────────────────────
    all_daily = (
        work.groupby("date")
        .agg(
            daily_vol   = ("tick_volume", "sum"),
            n_bars_all  = ("c", "count"),
        )
        .reset_index()
    )

    # ── Aggregate RTH bars per day ─────────────────────────────────────────────
    rth = work[work["is_rth"]].copy()
    if rth.empty:
        raise RuntimeError(
            "No RTH bars found. Verify cfg.rth_start_h / rth_end_h match server time."
        )

    def _agg_rth(g):
        n         = len(g)
        n_buy     = g["is_buy"].sum()
        n_sell    = g["is_sell"].sum()
        n_big     = g["is_big"].sum()
        n_tight   = g["is_tight"].sum()
        avg_price = g["c"].mean()
        return pd.Series({
            "session_vol":    g["tick_volume"].sum(),
            "money_spent":    (g["tick_volume"] * g["c"]).sum(),
            "n_rth_bars":     n,
            "pct_buyers":     round(n_buy  / n * 100, 1) if n > 0 else 0.0,
            "pct_sellers":    round(n_sell / n * 100, 1) if n > 0 else 0.0,
            "avg_rsi":        round(g["rsi"].mean(), 1),
            "avg_range_pct":  round(g["range_pct"].mean(), 4),
            "pct_big":        round(n_big   / n * 100, 1) if n > 0 else 0.0,
            "pct_tight":      round(n_tight / n * 100, 1) if n > 0 else 0.0,
            "rth_slots":      ", ".join(
                sorted({SLOT_LABELS[s] for s in g["slot"].astype(int).tolist()})
            ),
        })

    rth_daily = rth.groupby("date").apply(_agg_rth).reset_index()

    # ── Merge all-day + RTH ────────────────────────────────────────────────────
    merged = all_daily.merge(rth_daily, on="date", how="inner")
    merged = merged.sort_values("date").reset_index(drop=True)

    # ── 30-day rolling baselines ───────────────────────────────────────────────
    # Compute on the full history, not just last 20 days
    roll = merged.set_index("date")

    for col, base_col, std_col in [
        ("session_vol", "session_vol_30d", "session_vol_30d_std"),
        ("daily_vol",   "daily_vol_30d",   "daily_vol_30d_std"),
    ]:
        merged[base_col] = (
            roll[col].rolling(30, min_periods=5).mean().values
        )
        merged[std_col] = (
            roll[col].rolling(30, min_periods=5).std().values
        )

    # Rolling range baseline for volatility classification
    merged["range_30d_mean"] = (
        roll["avg_range_pct"].rolling(30, min_periods=5).mean().values
    )
    merged["range_30d_std"] = (
        roll["avg_range_pct"].rolling(30, min_periods=5).std().values
    )

    # ── % vs baselines ─────────────────────────────────────────────────────────
    merged["pct_vs_session"] = (
        merged["session_vol"] / merged["session_vol_30d"].replace(0, np.nan) * 100
    ).round(1)
    merged["pct_vs_daily"] = (
        merged["daily_vol"] / merged["daily_vol_30d"].replace(0, np.nan) * 100
    ).round(1)

    # ── Volatility label ───────────────────────────────────────────────────────
    def _vol_lbl(row):
        mu, sigma = row["range_30d_mean"], row["range_30d_std"]
        if pd.isna(mu) or pd.isna(sigma) or sigma == 0:
            return "NORMAL"
        z = (row["avg_range_pct"] - mu) / sigma
        if z >= _ANOMALY_THRESHOLD:  return "HIGH"
        if z <= -_ANOMALY_THRESHOLD: return "LOW"
        return "NORMAL"

    merged["volatility_lbl"] = merged.apply(_vol_lbl, axis=1)

    # ── Anomaly detection ─────────────────────────────────────────────────────
    anomaly_checks = {
        "session_vol":   ("session_vol_30d", "session_vol_30d_std"),
        "daily_vol":     ("daily_vol_30d",   "daily_vol_30d_std"),
        "avg_rsi":       (None, None),   # rsi: flag if > 70 or < 30
        "pct_buyers":    (None, None),   # flag if extreme (> 70% or < 30%)
    }

    def _detect_anomalies(row) -> str:
        flags = []
        # Volume anomalies
        for col, (mean_col, std_col) in [
            ("session_vol", ("session_vol_30d", "session_vol_30d_std")),
            ("daily_vol",   ("daily_vol_30d",   "daily_vol_30d_std")),
        ]:
            mu, sigma = row.get(mean_col, np.nan), row.get(std_col, np.nan)
            if pd.notna(mu) and pd.notna(sigma) and sigma > 0:
                z = (row[col] - mu) / sigma
                if abs(z) >= _ANOMALY_THRESHOLD:
                    direction = "↑" if z > 0 else "↓"
                    flags.append(f"{col}{direction}({z:+.1f}σ)")
        # RSI extremes
        rsi = row.get("avg_rsi", 50)
        if rsi >= 70:  flags.append(f"RSI↑({rsi:.0f})")
        if rsi <= 30:  flags.append(f"RSI↓({rsi:.0f})")
        # Directional bias extreme
        if row.get("pct_buyers",  50) >= 70: flags.append("BUYER_DOM")
        if row.get("pct_sellers", 50) >= 70: flags.append("SELLER_DOM")
        # Volatility
        if row.get("volatility_lbl") == "HIGH": flags.append("VOL↑")
        if row.get("volatility_lbl") == "LOW":  flags.append("VOL↓")
        return ", ".join(flags)

    merged["anomaly"] = merged.apply(_detect_anomalies, axis=1)

    # ── Trim to last 20 days for final output ──────────────────────────────────
    cutoff_20 = merged["date"].max() - timedelta(days=20)
    result = merged[merged["date"] > cutoff_20].copy().reset_index(drop=True)

    return result


# ── Console printer ───────────────────────────────────────────────────────────

def print_ict_session_daily(df_result: pd.DataFrame, cfg: LabConfig) -> None:
    W = 130
    print("=" * W)
    print(f"  ICT RTH SESSION ANALYSIS — LAST 20 DAYS  ·  {cfg.symbol}  "
          f"  RTH window: {cfg.rth_start_h:02d}:{cfg.rth_start_m:02d}–"
          f"{cfg.rth_end_h:02d}:{cfg.rth_end_m:02d} UTC")
    print("=" * W)

    if df_result.empty:
        print("  No data for the last 20 days.")
        print("=" * W)
        return

    show_cols = [
        "date",
        "session_vol", "session_vol_30d", "pct_vs_session",
        "daily_vol",   "daily_vol_30d",   "pct_vs_daily",
        "money_spent",
        "pct_buyers", "pct_sellers",
        "avg_rsi", "volatility_lbl",
        "anomaly",
    ]
    rename = {
        "date":             "Date",
        "session_vol":      "SessVol",
        "session_vol_30d":  "30dSessBaseline",
        "pct_vs_session":   "%vsSess",
        "daily_vol":        "DailyVol",
        "daily_vol_30d":    "30dDailyBaseline",
        "pct_vs_daily":     "%vsDaily",
        "money_spent":      "MoneySpent",
        "pct_buyers":       "%Buyers",
        "pct_sellers":      "%Sellers",
        "avg_rsi":          "AvgRSI",
        "volatility_lbl":   "Volat",
        "anomaly":          "Anomalies",
    }

    out = df_result[[c for c in show_cols if c in df_result.columns]].copy()
    out = out.rename(columns=rename)

    # Format integers
    for col in ["SessVol", "30dSessBaseline", "DailyVol", "30dDailyBaseline"]:
        if col in out.columns:
            out[col] = out[col].apply(
                lambda x: f"{int(x):,}" if pd.notna(x) else "—"
            )
    if "MoneySpent" in out.columns:
        out["MoneySpent"] = out["MoneySpent"].apply(
            lambda x: f"{x:,.0f}" if pd.notna(x) else "—"
        )

    # Highlight anomaly rows
    rows = out.to_string(index=False).split("\n")
    anomaly_idx = list(out.columns).index("Anomalies") if "Anomalies" in out.columns else -1
    header_printed = False
    for i, line in enumerate(rows):
        if not header_printed:
            print(line)
            print("─" * W)
            header_printed = True
            continue
        # Check if this data row has anomalies
        row_data = df_result.iloc[i - 2] if i - 2 < len(df_result) else None
        if row_data is not None and row_data.get("anomaly", ""):
            print(f"  *** {line.strip()}")   # flag anomaly rows
        else:
            print(f"  {line.strip()}")

    print("─" * W)
    n_anomalies = df_result["anomaly"].apply(bool).sum()
    print(f"  Anomalies detected: {n_anomalies} / {len(df_result)} days  "
          f"(threshold: ±{_ANOMALY_THRESHOLD}σ from 30-day rolling baseline)")
    print()
    print("  Columns:")
    print("    SessVol        : total tick_volume across all RTH bars that day")
    print("    30dSessBaseline: 30-day rolling mean of SessVol")
    print("    %vsSess        : SessVol / 30dBaseline × 100")
    print("    DailyVol       : total tick_volume across ALL bars that day")
    print("    MoneySpent     : Σ(tick_volume × close) for RTH bars — dollar-turnover proxy")
    print("    Volat          : HIGH/NORMAL/LOW vs 30-day rolling avg_range_pct ± 1.5σ")
    print("    *** row        : one or more metrics flagged as anomalous")
    print("=" * W)
