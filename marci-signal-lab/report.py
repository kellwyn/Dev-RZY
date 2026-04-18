"""
Console report printers for the Signal Lab.
All print_* functions write directly to stdout.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import LabConfig
from market_char import overall_bias, overall_volatility
from periods import SLOT_LABELS
from slot_drill import slot_aggregate

W = 74   # console width


def _sep(char: str = "─") -> None:
    print(char * W)


def _header(title: str) -> None:
    _sep("═")
    print(f"  {title}")
    _sep("═")


def _section(title: str) -> None:
    print(f"\n  ── {title} {'─' * max(0, W - len(title) - 6)}")


# ── Market overview ───────────────────────────────────────────────────────────

def print_market_overview(df: pd.DataFrame, cfg: LabConfig, duration_key: str) -> None:
    _header(f"MARKET CHARACTER  ·  {cfg.symbol}  [{cfg.analysis_tf}]  ·  {duration_key}"
            + ("  [RTH]" if cfg.use_rth else ""))

    t0 = df["time"].iloc[0].strftime("%Y-%m-%d")
    t1 = df["time"].iloc[-1].strftime("%Y-%m-%d")
    print(f"  Bars analysed  : {len(df):,}  ({t0} → {t1})")
    print(f"  Overall bias   : {overall_bias(df)}")

    v = overall_volatility(df, cfg)
    print(f"  Avg ATR        : {v['avg_atr']:.4f}  ({v['avg_atr_pct']:.3f}% of price)")
    print(f"  HV annualised  : {v['hv_annualised']:.1f}%")
    print(f"  Avg move/bar   : {v['avg_move_pct']:.3f}%  (body)")
    print(f"  Avg range/bar  : {v['avg_range_pct']:.3f}%  (H-L)")
    print(f"  Big moves      : {v['pct_big_moves']:.1f}% of bars  "
          f"(>={cfg.big_move_pct}%)  "
          f"buy={v['big_buy_count']}  sell={v['big_sell_count']}")
    print(f"  Tight ranges   : {v['pct_tight']:.1f}% of bars  "
          f"(<{cfg.tight_range_pct}% H-L)")
    print(f"  Avg tick vol   : {v['avg_tick_volume']:.0f}")
    _sep()


# ── 48-period character table ─────────────────────────────────────────────────

def print_period_table(
    char_df: pd.DataFrame,
    top_n: int = 20,
    sort_by: str = "avg_volume",
) -> None:
    valid_sorts = ["avg_volume", "avg_move_pct", "pct_big", "bias_score",
                   "avg_atr", "hist_vol_ann", "rel_volume"]
    if sort_by not in char_df.columns:
        sort_by = "avg_volume"

    _header(f"48-PERIOD CHARACTER TABLE  ·  TOP {top_n} SLOTS  BY  {sort_by.upper()}")

    show = char_df.nlargest(top_n, sort_by)[
        ["label", "n_bars", "avg_move_pct", "avg_range_pct",
         "pct_buy", "pct_sell", "pct_big", "pct_tight",
         "avg_volume", "rel_volume", "bias_score", "hist_vol_ann"]
    ].copy()
    show.columns = [
        "Time(UTC)", "N", "Body%", "Range%",
        "%Buy", "%Sell", "%Big", "%Tight",
        "TickVol", "RelVol", "Bias", "HV%pa"
    ]
    for col in ["Body%", "Range%", "%Buy", "%Sell", "%Big", "%Tight", "RelVol", "Bias", "HV%pa"]:
        show[col] = show[col].round(2)
    show["TickVol"] = show["TickVol"].round(0).astype("Int64")
    print(show.to_string(index=False))
    _sep()


def print_big_move_profile(big_df: pd.DataFrame, cfg: LabConfig) -> None:
    if big_df.empty:
        print("  No big-move candles found.")
        return
    _header(f"BIG-MOVE CANDLE PROFILE  ·  >={cfg.big_move_pct}%  BY SLOT")
    show = big_df[["label", "big_buy", "big_sell", "total_big", "avg_big_pct"]].head(20)
    show.columns = ["Time(UTC)", "BigBuy", "BigSell", "Total", "Avg%"]
    show["Avg%"] = show["Avg%"].round(3)
    print(show.to_string(index=False))
    _sep()


# ── Strategy scan results ─────────────────────────────────────────────────────

def print_setup_summary(
    outcomes: pd.DataFrame,
    slot_df:  pd.DataFrame,
    sess_df:  pd.DataFrame,
    dir_df:   pd.DataFrame,
    x_df:     pd.DataFrame,
) -> None:
    decided   = outcomes[outcomes["outcome"] >= 0] if not outcomes.empty else pd.DataFrame()
    n_total   = len(outcomes)
    n_decided = len(decided)
    n_wins    = int(decided["outcome"].sum()) if not decided.empty else 0
    wr        = n_wins / n_decided * 100 if n_decided > 0 else 0

    _header("STRATEGY SCAN  ·  MM v1.02  HISTORICAL SETUPS  (Rules 1–6)")
    print(f"  Total setups fired  : {n_total}")
    print(f"  Decided (TP or SL)  : {n_decided}")
    print(f"  Overall win rate    : {n_wins}/{n_decided}  ({wr:.1f}%)")
    if n_decided > 0:
        avg_rr = decided[decided["outcome"] == 1]["rr"].mean()
        avg_bars = decided["bars_held"].mean()
        print(f"  Avg R:R on wins     : 1:{avg_rr:.2f}" if not np.isnan(avg_rr) else "")
        print(f"  Avg bars to outcome : {avg_bars:.1f}  "
              f"({avg_bars * 0.5:.1f} hours at M30)")

    if not dir_df.empty:
        _section("Direction breakdown")
        print(dir_df.to_string())

    if not sess_df.empty:
        _section("Session breakdown")
        print(sess_df.to_string())

    if not x_df.empty:
        _section("X% impulse bucket breakdown")
        print(x_df.to_string())

    if not slot_df.empty:
        _section("Top 12 slots by win rate")
        top = slot_df.head(12)[["label", "n_setups", "n_wins", "win_rate", "avg_rr", "avg_bars"]]
        top.columns = ["Time(UTC)", "Setups", "Wins", "WinRate%", "AvgRR", "AvgBars"]
        print(top.to_string(index=False))
    _sep()


# ── Indicator correlations ────────────────────────────────────────────────────

def print_correlations(
    corr_df:     pd.DataFrame,
    dir_corr:    dict,
    direction:   str = "ALL",
) -> None:
    _header(f"INDICATOR CORRELATIONS  ·  TP HIT  ({direction})")

    def _print_table(df: pd.DataFrame, label: str) -> None:
        if df.empty:
            print(f"  {label}: not enough data (need >= 5 decided setups).")
            return
        print(f"\n  {label}  (Pearson r with outcome 1=TP, 0=SL  |  n={df['n'].iloc[0]})\n")
        for _, row in df.head(12).iterrows():
            bar   = "█" * int(row["abs_corr"] * 25)
            sign  = "+" if row["correlation"] > 0 else "-"
            hint  = "higher→better" if row["correlation"] > 0 else "lower→better"
            print(f"  {row['indicator']:<18} {sign}{row['abs_corr']:.3f}  {bar:<26}  {hint}")

    _print_table(corr_df, "ALL setups")

    for d in ("SHORT", "LONG"):
        df = dir_corr.get(d, pd.DataFrame())
        _print_table(df, f"{d} setups")
    _sep()


# ── Insights & recommendations ────────────────────────────────────────────────

def print_insights(
    outcomes:  pd.DataFrame,
    corr_df:   pd.DataFrame,
    char_df:   pd.DataFrame,
    cfg:       LabConfig,
    duration:  str,
) -> None:
    _header(f"STRATEGY INSIGHTS  ·  {cfg.symbol}  {duration}")

    decided = outcomes[outcomes["outcome"] >= 0] if not outcomes.empty else pd.DataFrame()
    if decided.empty:
        print("  No decided setups — try a longer duration.")
        _sep()
        return

    # ── Favoured direction ────────────────────────────────────────────────────
    by_dir = (
        decided.groupby("direction")["outcome"]
        .agg(wins="sum", total="count")
        .assign(wr=lambda x: x["wins"] / x["total"] * 100)
    )
    if not by_dir.empty:
        best_dir = by_dir["wr"].idxmax()
        print(f"  Favoured direction : {best_dir}  "
              f"({by_dir.loc[best_dir, 'wr']:.1f}% win rate, "
              f"{int(by_dir.loc[best_dir, 'total'])} setups)")

    # ── Favoured session ──────────────────────────────────────────────────────
    by_sess = (
        decided.groupby("session")["outcome"]
        .agg(wins="sum", total="count")
        .assign(wr=lambda x: x["wins"] / x["total"] * 100)
    )
    if not by_sess.empty:
        best_sess = by_sess["wr"].idxmax()
        print(f"  Favoured session   : {best_sess}  "
              f"({by_sess.loc[best_sess, 'wr']:.1f}% win rate, "
              f"{int(by_sess.loc[best_sess, 'total'])} setups)")

    # ── Top TP time slots ─────────────────────────────────────────────────────
    slot_wins  = decided[decided["outcome"] == 1].groupby("slot").size()
    slot_total = decided.groupby("slot").size()
    slot_wr    = (slot_wins / slot_total * 100).fillna(0)
    top_slots  = slot_wr.nlargest(5)
    print(f"\n  Top 5 TP time slots (UTC):")
    for slot_id, wr in top_slots.items():
        tot = int(slot_total.get(slot_id, 0))
        lbl = SLOT_LABELS[slot_id]
        print(f"    {lbl}  —  {wr:.1f}% win rate  ({tot} setups)")

    # ── Highest-vol slots (context) ───────────────────────────────────────────
    top_vol = char_df.nlargest(5, "avg_volume")
    print(f"\n  Highest-volume slots (most active — potential liquidity):")
    for _, row in top_vol.iterrows():
        print(f"    {row['label']}  —  avg tick vol {row['avg_volume']:.0f}"
              f"  ({row['session'] if 'session' in row else ''})")

    # ── Indicator hints ───────────────────────────────────────────────────────
    if not corr_df.empty:
        print(f"\n  Top correlated indicators (r >= 0.05):")
        shown = corr_df[corr_df["abs_corr"] >= 0.05].head(6)
        for _, row in shown.iterrows():
            hint = "higher = more wins" if row["correlation"] > 0 else "lower = more wins"
            print(f"    {row['indicator']:<18}  r={row['correlation']:+.3f}  {hint}")

    # ── TP multiplier hint ────────────────────────────────────────────────────
    wins = decided[decided["outcome"] == 1]
    if not wins.empty:
        avg_bars_win = wins["bars_held"].mean()
        avg_rr_win   = wins["rr"].mean()
        print(f"\n  Avg holding time on wins  : {avg_bars_win:.1f} bars "
              f"({avg_bars_win * 0.5:.1f} hrs at M30)")
        print(f"  Avg R:R on winning trades : 1:{avg_rr_win:.2f}")
        print(f"  Current TP multiplier     : {cfg.tp_multiplier}%")
        if avg_rr_win < 0.5:
            print("  Hint: consider increasing TP_MULTIPLIER to extend targets.")
        elif avg_rr_win > 2.0:
            print("  Hint: TP is being hit comfortably — current multiplier is well-sized.")

    _sep()


# ── Slot drill-down ───────────────────────────────────────────────────────────

def print_slot_drill(
    table:   pd.DataFrame,
    slot_id: int,
    days:    int,
    cfg:     LabConfig,
) -> None:
    """
    Print a day-by-day table for one 30-min slot over the last `days` days.
    Rows are sorted most-recent first. Setup and TP/SL outcome are included
    where a MM v1.02 setup fired in that slot on that date.
    """
    label = SLOT_LABELS[slot_id]
    _header(f"SLOT DRILL-DOWN  ·  {label} UTC  (slot {slot_id})  ·  "
            f"Last {days} days  ·  {cfg.symbol}")

    if table.empty:
        print(f"  No {label} UTC bars in the selected range.")
        _sep()
        return

    # ── Aggregate summary ─────────────────────────────────────────────────────
    agg = slot_aggregate(table, slot_id)
    print(f"  Days with data  : {agg['n_days']}")
    print(f"  Avg body%       : {agg['avg_body_pct']}%   "
          f"avg range%: {agg['avg_range_pct']}%")
    print(f"  %BUY  / %SELL   : {agg['pct_buy']}%  /  {agg['pct_sell']}%")
    print(f"  Big moves       : {agg['pct_big']}% of days"
          f"  |  Tight ranges: {agg['pct_tight']}% of days")
    print(f"  Avg tick vol    : {agg['avg_tick_vol']:.0f}")
    if agg["n_setups"] > 0:
        wr_str = f"  win rate {agg['win_rate']}%  ({agg['n_wins']}W / {agg['n_losses']}L)" \
                 if agg["win_rate"] is not None else ""
        print(f"  MM v1.02 setups : {agg['n_setups']}{wr_str}")
    _sep("─")

    # ── Daily table ───────────────────────────────────────────────────────────
    show = table.copy()

    # Format numeric columns for display
    for col in ("open", "high", "low", "close"):
        show[col] = show[col].apply(lambda x: f"{x:.3f}")
    show["body%"]   = show["body%"].apply(lambda x: f"{x:.3f}")
    show["range%"]  = show["range%"].apply(lambda x: f"{x:.3f}")
    show["rel_vol"] = show["rel_vol"].apply(lambda x: f"{x:.2f}x")
    show["rr"]      = show["rr"].apply(
        lambda x: f"1:{x:.2f}" if isinstance(x, (int, float)) and x != "" else ""
    )

    # Rename for compact column headers
    show = show.rename(columns={
        "tick_vol": "tickVol",
        "rel_vol":  "relVol",
        "session":  "sess",
    })

    # Column order
    cols = ["date", "open", "high", "low", "close",
            "body%", "range%", "dir", "big", "tight",
            "tickVol", "relVol", "sess", "setup", "rr", "result"]
    show = show[[c for c in cols if c in show.columns]]

    print(show.to_string(index=False))
    _sep()
