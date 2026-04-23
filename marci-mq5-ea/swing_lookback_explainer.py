"""
Visual explainer: InpSwingLookback — realistic M1 failure case.

Scenario: B7 is the VISUAL pullback high (the trendline point).
          B4 is a brief noise spike 3 bars before it.
  Lookback=1 → only checks B6 & B8  → both lower → QUALIFIES ✔
  Lookback=2 → checks B5,B6 & B8,B9 → all lower  → QUALIFIES ✔
  Lookback=3 → checks B4,B5,B6 & B8,B9,B10
               B4 HIGH (noise spike) > B7 HIGH    → REJECTED  ✘
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ── colours ────────────────────────────────────────────────────────────
BG        = "#0d1117"
GRID      = "#1e2530"
CANDLE_UP = "#26a69a"
CANDLE_DN = "#ef5350"
SPIKE_CLR = "#ff6f00"     # the problem noise bar
PIVOT_CLR = "#ffd700"
ARROW_OK  = "#00e676"
ARROW_NO  = "#ff1744"
TEXT_CLR  = "#e0e0e0"
LABEL_CLR = "#90caf9"
DIM_CLR   = "#546e7a"
WIN_OK    = "#00e676"
WIN_NO    = "#ff1744"

# ── candle data (15 bars, B0 = leftmost / oldest) ──────────────────────
#          B0     B1     B2     B3     B4     B5     B6   B7(pivot)
#          B8     B9     B10    B11    B12    B13    B14
highs  = [1.082, 1.087, 1.094, 1.101, 1.122, 1.109, 1.113, 1.120,
           1.107, 1.098, 1.091, 1.083, 1.076, 1.068, 1.061]
lows   = [1.078, 1.082, 1.088, 1.096, 1.105, 1.097, 1.099, 1.104,
           1.095, 1.085, 1.078, 1.071, 1.065, 1.057, 1.052]
opens  = [1.080, 1.084, 1.091, 1.099, 1.107, 1.108, 1.101, 1.106,
           1.118, 1.106, 1.096, 1.088, 1.080, 1.072, 1.065]
closes = [1.084, 1.089, 1.095, 1.103, 1.108, 1.099, 1.110, 1.107,
           1.097, 1.088, 1.080, 1.074, 1.067, 1.060, 1.054]

PIVOT  = 7
N_BARS = len(highs)
xs     = list(range(N_BARS))

# ── helper: draw one candlestick ───────────────────────────────────────
def draw_candle(ax, x, o, h, l, c, alpha=1.0, override_color=None):
    color = override_color if override_color else (CANDLE_UP if c >= o else CANDLE_DN)
    ax.plot([x, x], [l, h], color=color, lw=1.3, alpha=alpha, zorder=2)
    body_lo = min(o, c)
    body_hi = max(o, c)
    rect = plt.Rectangle((x - 0.35, body_lo), 0.7,
                          max(body_hi - body_lo, 0.0002),
                          color=color, alpha=alpha, zorder=3)
    ax.add_patch(rect)

# ── figure: 3 panels ───────────────────────────────────────────────────
fig, axes = plt.subplots(3, 1, figsize=(15, 14), facecolor=BG)
fig.suptitle(
    "InpSwingLookback  —  How a noise spike 3 bars away blocks pivot detection on M1",
    color=TEXT_CLR, fontsize=14, fontweight="bold", y=0.995)

configs = [
    (1, "Lookback = 1  │  Only the immediate neighbour bars checked  →  pivot QUALIFIES  ✔"),
    (2, "Lookback = 2  │  2 bars each side checked  →  pivot QUALIFIES  ✔"),
    (3, "Lookback = 3  │  3 bars each side checked  →  noise spike at B4 blocks it  →  REJECTED  ✘"),
]

for ax, (lb, title) in zip(axes, configs):
    # Check qualification
    left_bars  = list(range(max(0, PIVOT - lb), PIVOT))
    right_bars = list(range(PIVOT + 1, min(N_BARS, PIVOT + lb + 1)))
    qualifies  = all(highs[i] < highs[PIVOT] for i in left_bars + right_bars)
    failing_bars = [i for i in left_bars + right_bars if highs[i] >= highs[PIVOT]]

    # Panel styling
    ax.set_facecolor(BG)
    ax.tick_params(colors=TEXT_CLR, labelsize=7.5)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.yaxis.grid(True, color=GRID, lw=0.5, zorder=0)
    ax.set_xlim(-0.8, N_BARS - 0.2)
    ax.set_ylim(1.042, 1.154)
    ax.set_xticks(xs)
    ax.set_xticklabels([f"B{i}" for i in xs], fontsize=7.5, color=DIM_CLR)
    title_color = LABEL_CLR if qualifies else "#ff8a65"
    ax.set_title(title, color=title_color, fontsize=10.5, pad=5, loc="left", fontweight="bold")

    # Shade lookback window (left and right separately)
    win_color = WIN_OK if qualifies else WIN_NO
    ax.axvspan(PIVOT - lb - 0.45, PIVOT - 0.45, alpha=0.08, color=win_color, zorder=0)
    ax.axvspan(PIVOT + 0.45, PIVOT + lb + 0.45, alpha=0.08, color=win_color, zorder=0)

    # Dashed horizontal at pivot high
    ax.axhline(highs[PIVOT], color=PIVOT_CLR, lw=0.9, ls='--', alpha=0.45, zorder=1)

    # Draw all candles
    for i in xs:
        in_window  = (PIVOT - lb <= i <= PIVOT + lb)
        alpha      = 1.0 if in_window else 0.28
        is_spike   = (i == 4)               # the noise bar
        is_pivot   = (i == PIVOT)
        override   = SPIKE_CLR if (is_spike and in_window) else None
        draw_candle(ax, i, opens[i], highs[i], lows[i], closes[i],
                    alpha=alpha, override_color=override)

    # ── Pivot marker ──────────────────────────────────────────────────
    ax.plot(PIVOT, highs[PIVOT] + 0.0025, marker='v', color=PIVOT_CLR,
            markersize=12, zorder=6)
    ax.text(PIVOT, highs[PIVOT] + 0.0055, "VISUAL\nPIVOT HIGH\n(trendline point)",
            ha='center', va='bottom', color=PIVOT_CLR,
            fontsize=7.5, fontweight='bold', linespacing=1.4)

    # ── Check marks on each bar inside the window ─────────────────────
    for i in left_bars + right_bars:
        if i >= N_BARS:
            continue
        ok     = highs[i] < highs[PIVOT]
        marker = '✔' if ok else '✘'
        color  = ARROW_OK if ok else ARROW_NO
        # dotted line up to pivot high level
        ax.plot([i, i], [highs[i] + 0.001, highs[PIVOT]],
                color=color, lw=0.9, ls=':', alpha=0.7, zorder=1)
        ax.text(i, highs[i] + 0.003, marker,
                ha='center', va='bottom', color=color,
                fontsize=14, fontweight='bold', zorder=7)

    # ── Label the noise spike bar ─────────────────────────────────────
    if 4 in left_bars:            # only annotate when B4 is in the window
        ax.annotate(
            "NOISE SPIKE\n(brief M1 wick)\nhigh > pivot high",
            xy=(4, highs[4] + 0.001),
            xytext=(1.2, highs[4] + 0.012),
            color=SPIKE_CLR, fontsize=8, fontweight='bold',
            arrowprops=dict(arrowstyle='->', color=SPIKE_CLR, lw=1.3),
            zorder=8)

    # ── "n bars each side" bracket labels ─────────────────────────────
    mid_left  = PIVOT - lb / 2 - 0.5
    mid_right = PIVOT + lb / 2 + 0.5
    y_bracket = 1.143
    if lb > 0:
        ax.annotate("", xy=(PIVOT - 0.5, y_bracket),
                    xytext=(PIVOT - lb - 0.45, y_bracket),
                    arrowprops=dict(arrowstyle="<->", color=TEXT_CLR, lw=1.2))
        ax.text(mid_left, y_bracket + 0.001,
                f"{lb} bar{'s' if lb>1 else ''} LEFT",
                ha='center', va='bottom', color=TEXT_CLR, fontsize=8)

        ax.annotate("", xy=(PIVOT + lb + 0.45, y_bracket),
                    xytext=(PIVOT + 0.5, y_bracket),
                    arrowprops=dict(arrowstyle="<->", color=TEXT_CLR, lw=1.2))
        ax.text(mid_right, y_bracket + 0.001,
                f"{lb} bar{'s' if lb>1 else ''} RIGHT",
                ha='center', va='bottom', color=TEXT_CLR, fontsize=8)

    # ── Result badge ──────────────────────────────────────────────────
    badge_color = ARROW_OK if qualifies else ARROW_NO
    badge_text  = "QUALIFIES as swing high ✔" if qualifies else "REJECTED — B4 noise spike blocks qualification ✘"
    ax.text(N_BARS - 0.6, 1.044, badge_text,
            ha='right', va='bottom', color=badge_color, fontsize=10, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.45', facecolor=BG,
                      edgecolor=badge_color, lw=1.8))

# ── bottom note ────────────────────────────────────────────────────────
fig.text(
    0.5, 0.005,
    "The rule: pivot bar high must be STRICTLY GREATER than every bar within the window on BOTH sides.\n"
    "M1 noise — a single wick 3 bars away that equals or exceeds the pivot — silently rejects the entire setup when Lookback = 3.\n"
    "Reducing to Lookback = 1 or 2 lets visually obvious pivots qualify while still filtering pure one-bar spikes.",
    ha='center', va='bottom', color=DIM_CLR, fontsize=8.5, linespacing=1.6)

plt.tight_layout(rect=[0, 0.04, 1, 0.995])
out = r"c:\Users\kellw\OneDrive\Dev-RZY\marci-mq5-ea\swing_lookback_explainer.png"
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor=BG)
print(f"Saved: {out}")
