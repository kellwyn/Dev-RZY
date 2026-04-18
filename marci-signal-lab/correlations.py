"""
Indicator computation + correlation analysis.

For each setup bar we compute a set of technical indicators, then
correlate their values with the binary TP-hit outcome (1 = win, 0 = loss).
Pearson r identifies which market conditions most favour the strategy.

Indicators computed (all at the setup bar, using only data up to that bar):
  atr_pct      — ATR as % of close (volatility level)
  rsi          — RSI(14)  (momentum / overbought-oversold)
  adx          — ADX(14)  (trend strength)
  pdi          — +DI(14)  (up-trend pressure)
  ndi          — -DI(14)  (down-trend pressure)
  di_spread    — pdi - ndi  (directional dominance)
  above_ema20  — 1 if close > EMA(20)
  above_ema50  — 1 if close > EMA(50)
  rel_vol      — tick_volume / rolling-mean volume  (relative activity)
  range_pct    — H-L range as % of open  (bar-level volatility)
  move_pct     — body size as % of open
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy_scan import HistSetup
from config import LabConfig


# ── Indicator computation ─────────────────────────────────────────────────────

def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    pc = df["c"].shift(1)
    tr = pd.concat([
        df["h"] - df["l"],
        (df["h"] - pc).abs(),
        (df["l"] - pc).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _rsi(df: pd.DataFrame, period: int) -> pd.Series:
    delta = df["c"].diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
    loss  = (-delta).clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _adx_components(df: pd.DataFrame, period: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (adx, pdi, ndi) series."""
    ph = df["h"].shift(1)
    pl = df["l"].shift(1)
    pc = df["c"].shift(1)

    tr = pd.concat([
        df["h"] - df["l"],
        (df["h"] - pc).abs(),
        (df["l"] - pc).abs(),
    ], axis=1).max(axis=1)
    atr_s = tr.ewm(span=period, adjust=False).mean()

    up   = df["h"] - ph
    down = pl - df["l"]
    pdm  = pd.Series(np.where((up > down) & (up > 0),   up,   0.0), index=df.index)
    ndm  = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)

    pdi = 100 * pdm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, np.nan)
    ndi = 100 * ndm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, np.nan)
    dx  = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx, pdi.fillna(0), ndi.fillna(0)


def build_indicator_df(df: pd.DataFrame, cfg: LabConfig) -> pd.DataFrame:
    """
    Compute all indicators for every bar in df.
    Returns a DataFrame with the same index as df.
    """
    ind = pd.DataFrame(index=df.index)

    atr_s         = _atr(df, cfg.atr_period)
    ind["atr_pct"]  = (atr_s / df["c"] * 100).round(4)
    ind["rsi"]      = _rsi(df, cfg.rsi_period).round(2)

    adx_s, pdi_s, ndi_s = _adx_components(df, cfg.adx_period)
    ind["adx"]       = adx_s.round(2)
    ind["pdi"]       = pdi_s.round(2)
    ind["ndi"]       = ndi_s.round(2)
    ind["di_spread"] = (pdi_s - ndi_s).round(2)

    ema20 = _ema(df["c"], 20)
    ema50 = _ema(df["c"], 50)
    ind["above_ema20"] = (df["c"] > ema20).astype(float)
    ind["above_ema50"] = (df["c"] > ema50).astype(float)

    vol_ma = df["tick_volume"].rolling(cfg.vol_ma_period, min_periods=1).mean()
    ind["rel_vol"]   = (df["tick_volume"] / vol_ma.replace(0, np.nan)).round(3)
    ind["range_pct"] = df["range_pct"].round(4)
    ind["move_pct"]  = df["move_pct"].round(4)

    return ind


# ── Correlation engine ────────────────────────────────────────────────────────

def correlate_with_outcome(
    setups: list[HistSetup],
    outcomes: pd.DataFrame,
    indicator_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    For each decided setup, extract indicator values at the setup bar and
    compute Pearson correlation with TP-hit outcome (1=win, 0=loss).

    Returns a DataFrame sorted by |correlation| descending:
      indicator   — indicator name
      correlation — Pearson r  (positive = higher value → more wins)
      abs_corr    — |r|  (used for ranking)
      n           — number of setups used
    """
    decided = outcomes[outcomes["outcome"] >= 0].copy()
    if len(decided) < 5:
        return pd.DataFrame(columns=["indicator", "correlation", "abs_corr", "n"])

    # Build lookup: (time, direction) -> bar_idx
    setup_lookup: dict[tuple, int] = {
        (s.time, s.direction): s.bar_idx for s in setups
    }

    rows = []
    for _, row in decided.iterrows():
        key = (row["time"], row["direction"])
        bar_idx = setup_lookup.get(key)
        if bar_idx is None or bar_idx >= len(indicator_df):
            continue
        rec = {"outcome": row["outcome"]}
        rec.update(indicator_df.iloc[bar_idx].to_dict())
        rows.append(rec)

    if len(rows) < 5:
        return pd.DataFrame(columns=["indicator", "correlation", "abs_corr", "n"])

    data = pd.DataFrame(rows).dropna()
    if data.empty or "outcome" not in data.columns:
        return pd.DataFrame(columns=["indicator", "correlation", "abs_corr", "n"])

    corr = data.corr(numeric_only=True)["outcome"].drop("outcome", errors="ignore")
    n    = len(data)

    result = (
        corr
        .dropna()
        .reset_index()
        .rename(columns={"index": "indicator", "outcome": "correlation"})
    )
    result["abs_corr"] = result["correlation"].abs()
    result["n"]        = n
    result = result.sort_values("abs_corr", ascending=False).reset_index(drop=True)
    result["correlation"] = result["correlation"].round(3)
    result["abs_corr"]    = result["abs_corr"].round(3)
    return result


def direction_correlation(
    setups: list[HistSetup],
    outcomes: pd.DataFrame,
    indicator_df: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """
    Run correlate_with_outcome separately for SHORT and LONG setups.
    Returns dict {'SHORT': df, 'LONG': df}.
    """
    result = {}
    for direction in ("SHORT", "LONG"):
        sub_setups   = [s for s in setups if s.direction == direction]
        sub_outcomes = outcomes[outcomes["direction"] == direction].copy()
        result[direction] = correlate_with_outcome(sub_setups, sub_outcomes, indicator_df)
    return result
