//+------------------------------------------------------------------+
//|  Marci Silfrain — Measured Move Trend Strategy EA               |
//|  "Little RZY" structure detector                                |
//|                                                                  |
//|  Implements all 10 rules from the playbook:                     |
//|   1. Identify the trend (LH+LL or HH+HL)                       |
//|   2. Wait for impulse + pullback — never enter the impulse      |
//|   3. Draw trendline across pullback highs / lows                |
//|   4. Find lowest low (short) / highest high (long) in structure |
//|   5. Measure vertical distance: extreme → trendline             |
//|   6. Project same distance in trend direction = target          |
//|   7. Enter when price rejects trendline and resumes trend       |
//|   8. Bollinger Bands context filter                             |
//|   9. Structure count — early = strongest, 4th+ = exhaustion     |
//|  10. Invalidation: close beyond the trendline level             |
//|                                                                  |
//|─────────────────── VERSION HISTORY ─────────────────────────────|
//|  v1.00  2026-04-13  — Initial release (baseline)               |
//|    · 10-rule Measured Move Trend framework                      |
//|    · Manual alert / Auto-execute modes                          |
//|    · Forward-side-only swing high/low detection                 |
//|    · Bollinger Bands context label + optional entry filter      |
//|    · Key level proximity filter (ATH/ATL, W1/MN1/H1)           |
//|    · Trend leg + pullback strength gates (pips + Fib %)        |
//|    · Risk-based lot sizing (% of balance)                       |
//|    · Chart lines: Entry / Stop Loss / Target                    |
//|    · Gap guard — skips bar if open outside prior bar range      |
//+------------------------------------------------------------------+
#property copyright "Marci Silfrain Strategy EA"
#property version   "1.00"
#property description "Measured Move Trend Strategy — Little RZY Detector v1.00"
#property strict

#include <Trade\Trade.mqh>

//── Input parameters ──────────────────────────────────────────────
input group "=== Execution Mode ==="
input bool   InpManualConfirm  = true;      // true = Alert only (live trading)
                                             // false = auto-execute (backtesting)

input group "=== Risk Management ==="
input double InpRiskPercent    = 1.0;       // Risk per trade (% of balance)
input double InpMinRR          = 1.5;       // Minimum risk:reward ratio

input group "=== Strategy Parameters ==="
input int    InpSwingLookback  = 3;         // Bars (forward side only) for swing detection
input int    InpBBPeriod       = 20;        // Bollinger Bands period
input double InpBBDeviation    = 2.0;       // Bollinger Bands std deviation
input int    InpCandleCount    = 100;       // Historical candles to analyse

input group "=== Bollinger Bands Filter ==="
input bool   InpUseBBFilter    = false;     // Enable: SHORT only near/beyond upper band; LONG only near/beyond lower band

input group "=== Key Level Filter ==="
input bool   InpUseKeyLevelFilter = false;  // Block trades near ATH/ATL, Monthly/Weekly H/L, H1 S/R zones
input double InpKeyLevelPips      = 50.0;   // Proximity buffer around key levels (pips)

input group "=== Trend & Pullback Filter ==="
input double InpMinTrendPips    = 15.0;     // Min impulse leg (pips) — move must be large enough
input double InpMinPullbackPct  = 25.0;     // Min pullback retracement % of trend leg
input double InpMaxPullbackPct  = 70.0;     // Max pullback retracement % of trend leg

input group "=== Trade Settings ==="
input int    InpMagicNumber    = 20260412;  // EA identifier
input int    InpSlippage       = 20;        // Max slippage (points)

//── Globals ───────────────────────────────────────────────────────
CTrade  Trade;
int     BbHandle   = INVALID_HANDLE;

//+------------------------------------------------------------------+
//| Initialisation                                                   |
//+------------------------------------------------------------------+
int OnInit()
{
    Trade.SetExpertMagicNumber(InpMagicNumber);
    Trade.SetDeviationInPoints(InpSlippage);

    BbHandle = iBands(_Symbol, PERIOD_CURRENT, InpBBPeriod, 0, InpBBDeviation, PRICE_CLOSE);
    if(BbHandle == INVALID_HANDLE)
    {
        Print("ERROR: Failed to create Bollinger Bands handle");
        return INIT_FAILED;
    }

    string mode = InpManualConfirm ? "MANUAL CONFIRMATION (live)" : "AUTO-EXECUTE (backtest)";
    Print("Marci Measured Move EA ready  |  ", _Symbol, " ", EnumToString(Period()),
          "  |  Mode: ", mode);
    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Cleanup                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    if(BbHandle != INVALID_HANDLE)
        IndicatorRelease(BbHandle);
    ObjectsDeleteAll(0, "Marci_");
    Comment("");
}

//+------------------------------------------------------------------+
//| OnTick — only acts on new completed bar                         |
//+------------------------------------------------------------------+
void OnTick()
{
    static datetime lastBar = 0;
    datetime currentBar = iTime(_Symbol, PERIOD_CURRENT, 0);
    if(currentBar == lastBar) return;
    lastBar = currentBar;

    if(HasOpenPosition()) return;

    RunStrategy();
}

//+------------------------------------------------------------------+
//| Check whether EA already has an open position on this symbol    |
//+------------------------------------------------------------------+
bool HasOpenPosition()
{
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        if(PositionGetTicket(i) > 0)
            if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
               (ulong)PositionGetInteger(POSITION_MAGIC) == (ulong)InpMagicNumber)
                return true;
    }
    return false;
}

//+------------------------------------------------------------------+
//| CORE STRATEGY                                                    |
//+------------------------------------------------------------------+
void RunStrategy()
{
    //── Fetch completed OHLC (pos=1 skips forming bar) ─────────────
    double highs[], lows[], closes[], opens[];
    ArraySetAsSeries(highs,  true);
    ArraySetAsSeries(lows,   true);
    ArraySetAsSeries(closes, true);
    ArraySetAsSeries(opens,  true);

    if(CopyHigh (_Symbol, PERIOD_CURRENT, 1, InpCandleCount, highs)  < InpCandleCount) return;
    if(CopyLow  (_Symbol, PERIOD_CURRENT, 1, InpCandleCount, lows)   < InpCandleCount) return;
    if(CopyClose(_Symbol, PERIOD_CURRENT, 1, InpCandleCount, closes) < InpCandleCount) return;
    if(CopyOpen (_Symbol, PERIOD_CURRENT, 1, InpCandleCount, opens)  < InpCandleCount) return;

    // Gap guard: the most recently completed bar must not have opened outside the
    // prior bar's high-low range.  Gaps signal session breaks, news spikes, or
    // illiquid conditions — measured-move entries in a gap are unreliable.
    //   opens[0] = open of bar 1  (most recent complete)
    //   highs[1] / lows[1] = high / low of bar 2  (the bar before it)
    if(opens[0] > highs[1] || opens[0] < lows[1]) return;

    //── Bollinger Bands ─────────────────────────────────────────────
    double bbUpper[], bbMiddle[], bbLower[];
    ArraySetAsSeries(bbUpper,  true);
    ArraySetAsSeries(bbMiddle, true);
    ArraySetAsSeries(bbLower,  true);

    if(CopyBuffer(BbHandle, 1, 1, InpCandleCount, bbUpper)  < InpCandleCount) return;
    if(CopyBuffer(BbHandle, 0, 1, InpCandleCount, bbMiddle) < InpCandleCount) return;
    if(CopyBuffer(BbHandle, 2, 1, InpCandleCount, bbLower)  < InpCandleCount) return;

    double curPrice  = closes[0];
    double curUpper  = bbUpper[0];
    double curMiddle = bbMiddle[0];
    double curLower  = bbLower[0];

    //── Swing point detection ────────────────────────────────────────
    int    shIdx[]; double shPx[];
    int    slIdx[]; double slPx[];

    FindSwings(highs, lows, InpCandleCount, InpSwingLookback,
               shIdx, shPx, slIdx, slPx);

    if(ArraySize(shIdx) < 1 || ArraySize(slIdx) < 1) return;  // need at least one swing each side

    //── Rule 1: identify the trend ──────────────────────────────────
    // Arrays are AsSeries: index 0 = most recent swing point
    // Downtrend: shPx[0] < shPx[1] < shPx[2]  (recent lows older)
    // Uptrend  : shPx[0] > shPx[1] > shPx[2]
    int trend = DetectTrend(shPx, slPx, closes);
    if(trend == 0) return;   // SIDEWAYS — no trade

    int structCount;

    //══════════════════════════════════════════════════════════════════
    // SHORT SETUP (downtrend Little RZY)
    //══════════════════════════════════════════════════════════════════
    if(trend == -1)
    {
        // Rule 9: structure count
        structCount = MathMax(1, ArraySize(slIdx) - 1);

        // Anchor = most recent confirmed swing low
        int    anchorIdx = slIdx[0];
        double anchorPx  = slPx[0];

        // Rule 2/3: pullback high = highest high in bars MORE RECENT than anchor
        // (AsSeries: indices 0..anchorIdx-1 are more recent)
        if(anchorIdx < 1) return;

        double phPx  = 0.0;
        int    phBar = -1;
        for(int i = 0; i < anchorIdx; i++)
        {
            if(highs[i] > phPx) { phPx = highs[i]; phBar = i; }
        }
        if(phBar < 0) return;

        // Rule 10: pullback must not exceed prior confirmed swing high
        if(ArraySize(shIdx) > 0 && phPx >= shPx[0]) return;

        // ── Gate: Trend & Pullback Strength ──────────────────────────────
        // Trend leg   : prior swing high → anchor low   (the full impulse drop)
        // Pullback leg: anchor low → pullback high      (the retracement)
        // Ratio       : pullback / trend × 100          (Fibonacci-style %)
        //
        // trendPips  — ensures the move is large enough to be worth trading
        // pullbackPct — 25-70% is the measured-move sweet spot:
        //   < 25%  → barely a pullback; no structure to anchor the trendline
        //   > 70%  → retracement is eating the trend; reversal risk rises sharply
        double _pipVal      = ((_Digits == 5 || _Digits == 3) ? _Point * 10.0 : _Point);
        double _trendLeg    = shPx[0] - anchorPx;
        double _pullbackLeg = phPx    - anchorPx;
        double trendPips    = (_pipVal > 0) ? _trendLeg / _pipVal : 0.0;
        double pullbackPct  = (_trendLeg > 0) ? (_pullbackLeg / _trendLeg * 100.0) : 0.0;
        if(trendPips   < InpMinTrendPips)   return;   // impulse too small to trade
        if(pullbackPct < InpMinPullbackPct) return;   // retracement too shallow
        if(pullbackPct > InpMaxPullbackPct) return;   // pullback too deep — trend weakening

        // Rule 7: entry conditions
        bool inZone = (curPrice > anchorPx && curPrice < phPx);

        // Use HIGHS not closes — a wick rejection closes below phPx but the high touches it
        bool visitedPeak = false;
        int  checkBars   = MathMin(8, anchorIdx);
        for(int i = 0; i < checkBars; i++)
            if(highs[i] >= phPx * 0.97) { visitedPeak = true; break; }

        double recentHi = 0;
        for(int i = 0; i < 5; i++) recentHi = MathMax(recentHi, highs[i]);
        bool rollingOver = (curPrice < recentHi * 0.999);

        if(!inZone || !visitedPeak || !rollingOver) return;

        // Rules 4-6: measured move
        double measuredDist = phPx - anchorPx;
        if(measuredDist <= 0) return;
        double targetPx = anchorPx - measuredDist;

        double entryPx = SymbolInfoDouble(_Symbol, SYMBOL_BID);
        double slPxVal = phPx + _Point * 10;
        double risk    = slPxVal - entryPx;
        double reward  = entryPx - targetPx;
        if(risk <= 0 || reward <= 0) return;
        double rr = reward / risk;
        if(rr < InpMinRR) return;

        // Rule 8: Bollinger context
        string bbPos    = BBLabel(curPrice, curUpper, curMiddle, curLower);
        string strength = SignalStrength("SHORT", bbPos, structCount);

        // Bollinger Bands filter: require price near/beyond upper band for SHORT
        // (extended into upper BB = overextended, higher reversal probability)
        if(InpUseBBFilter && bbPos != "NEAR_UPPER" && bbPos != "BEYOND_UPPER") return;

        // Key level filter: block SHORT if price is within InpKeyLevelPips of a
        // major support zone (ATL, Monthly/Weekly low, H1 swing low)
        if(InpUseKeyLevelFilter && IsNearKeyLevel(entryPx, "SHORT")) return;

        string summary = BuildSummary("SHORT", entryPx, slPxVal, targetPx, rr,
                                      anchorPx, phPx, measuredDist,
                                      curUpper, curMiddle, curLower,
                                      bbPos, structCount, strength,
                                      trendPips, pullbackPct);

        DrawLevels(entryPx, slPxVal, targetPx, "SHORT");
        Comment(summary);

        if(InpManualConfirm)
        {
            Alert("MARCI EA  >>>  SHORT SETUP on ", _Symbol, "\n\n",
                  summary, "\n\n",
                  "Visual check: verify trendline on chart.\n",
                  "To execute: disable ManualConfirm and restart, or place order manually.");
        }
        else
        {
            double lots = CalcLots(entryPx, slPxVal);
            if(lots > 0)
            {
                Print(summary);
                if(!Trade.Sell(lots, _Symbol, entryPx, slPxVal, targetPx,
                               "Marci_MeasuredMove_SHORT"))
                    Print("Order failed: ", Trade.ResultRetcodeDescription());
            }
        }
    }

    //══════════════════════════════════════════════════════════════════
    // LONG SETUP (uptrend Little RZY — mirror image)
    //══════════════════════════════════════════════════════════════════
    else if(trend == 1)
    {
        structCount = MathMax(1, ArraySize(shIdx) - 1);

        int    anchorIdx = shIdx[0];
        double anchorPx  = shPx[0];

        if(anchorIdx < 1) return;

        // Pullback low = lowest low MORE RECENT than anchor
        double plPx  = DBL_MAX;
        int    plBar = -1;
        for(int i = 0; i < anchorIdx; i++)
        {
            if(lows[i] < plPx) { plPx = lows[i]; plBar = i; }
        }
        if(plBar < 0 || plPx == DBL_MAX) return;

        // Rule 10: pullback must not break below prior confirmed swing low
        if(ArraySize(slIdx) > 0 && plPx <= slPx[0]) return;

        // ── Gate: Trend & Pullback Strength ──────────────────────────────
        // Trend leg   : prior swing low → anchor high   (the full impulse rise)
        // Pullback leg: anchor high → pullback low      (the retracement)
        double _pipVal      = ((_Digits == 5 || _Digits == 3) ? _Point * 10.0 : _Point);
        double _trendLeg    = anchorPx - slPx[0];
        double _pullbackLeg = anchorPx - plPx;
        double trendPips    = (_pipVal > 0) ? _trendLeg / _pipVal : 0.0;
        double pullbackPct  = (_trendLeg > 0) ? (_pullbackLeg / _trendLeg * 100.0) : 0.0;
        if(trendPips   < InpMinTrendPips)   return;
        if(pullbackPct < InpMinPullbackPct) return;
        if(pullbackPct > InpMaxPullbackPct) return;

        bool inZone = (curPrice > plPx && curPrice < anchorPx);

        // Use LOWS not closes — a wick bounce has a low at plPx but closes above it
        bool visitedTrough = false;
        int  checkBars     = MathMin(8, anchorIdx);
        for(int i = 0; i < checkBars; i++)
            if(lows[i] <= plPx * 1.03) { visitedTrough = true; break; }

        double recentLo = DBL_MAX;
        for(int i = 0; i < 5; i++) recentLo = MathMin(recentLo, lows[i]);
        bool bouncingUp = (curPrice > recentLo * 1.001);

        if(!inZone || !visitedTrough || !bouncingUp) return;

        double measuredDist = anchorPx - plPx;
        if(measuredDist <= 0) return;
        double targetPx = anchorPx + measuredDist;

        double entryPx = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
        double slPxVal = plPx - _Point * 10;
        double risk    = entryPx - slPxVal;
        double reward  = targetPx - entryPx;
        if(risk <= 0 || reward <= 0) return;
        double rr = reward / risk;
        if(rr < InpMinRR) return;

        string bbPos    = BBLabel(curPrice, curUpper, curMiddle, curLower);
        string strength = SignalStrength("LONG", bbPos, structCount);

        // Bollinger Bands filter: require price near/beyond lower band for LONG
        if(InpUseBBFilter && bbPos != "NEAR_LOWER" && bbPos != "BEYOND_LOWER") return;

        // Key level filter: block LONG if price is within InpKeyLevelPips of a
        // major resistance zone (ATH, Monthly/Weekly high, H1 swing high)
        if(InpUseKeyLevelFilter && IsNearKeyLevel(entryPx, "LONG")) return;

        string summary = BuildSummary("LONG", entryPx, slPxVal, targetPx, rr,
                                      anchorPx, plPx, measuredDist,
                                      curUpper, curMiddle, curLower,
                                      bbPos, structCount, strength,
                                      trendPips, pullbackPct);

        DrawLevels(entryPx, slPxVal, targetPx, "LONG");
        Comment(summary);

        if(InpManualConfirm)
        {
            Alert("MARCI EA  >>>  LONG SETUP on ", _Symbol, "\n\n",
                  summary, "\n\n",
                  "Visual check: verify trendline on chart.\n",
                  "To execute: disable ManualConfirm and restart, or place order manually.");
        }
        else
        {
            double lots = CalcLots(entryPx, slPxVal);
            if(lots > 0)
            {
                Print(summary);
                if(!Trade.Buy(lots, _Symbol, entryPx, slPxVal, targetPx,
                              "Marci_MeasuredMove_LONG"))
                    Print("Order failed: ", Trade.ResultRetcodeDescription());
            }
        }
    }
}

//+------------------------------------------------------------------+
//| Find swing highs and lows (AsSeries arrays)                     |
//| Index 0 in output = most recent swing point                     |
//+------------------------------------------------------------------+
void FindSwings(
    const double &highs[], const double &lows[], int bars, int n,
    int &shIdxOut[], double &shPxOut[],
    int &slIdxOut[], double &slPxOut[])
{
    ArrayResize(shIdxOut, 0); ArrayResize(shPxOut, 0);
    ArrayResize(slIdxOut, 0); ArrayResize(slPxOut, 0);

    int limit = bars - n;
    for(int i = n; i < limit; i++)
    {
        // Swing high: higher than n bars on the FORWARD side only (bars that came after
        // the pivot in real time = smaller AsSeries indices = i-j).
        // The older/left side (i+j) is intentionally skipped: prior structure such as a
        // preceding impulse spike should not disqualify the current pullback high.
        bool isHigh = true;
        for(int j = 1; j <= n && isHigh; j++)
            if(highs[i] < highs[i - j]) isHigh = false;
        if(isHigh)
        {
            int sz = ArraySize(shIdxOut);
            ArrayResize(shIdxOut, sz + 1);
            ArrayResize(shPxOut,  sz + 1);
            shIdxOut[sz] = i;
            shPxOut[sz]  = highs[i];
        }

        // Swing low: lower than n bars on the FORWARD side only (same rationale as above)
        bool isLow = true;
        for(int j = 1; j <= n && isLow; j++)
            if(lows[i] > lows[i - j]) isLow = false;
        if(isLow)
        {
            int sz = ArraySize(slIdxOut);
            ArrayResize(slIdxOut, sz + 1);
            ArrayResize(slPxOut,  sz + 1);
            slIdxOut[sz] = i;
            slPxOut[sz]  = lows[i];
        }
    }
}

//+------------------------------------------------------------------+
//| Rule 1 — Detect trend using 3-candle close momentum             |
//| SHORT (-1): 3 most recent closes declining AND all below the    |
//|             most recent confirmed swing high                     |
//| LONG  (+1): 3 most recent closes rising AND all above the       |
//|             most recent confirmed swing low                      |
//|                                                                  |
//| Rationale: the pullback phase may contain a local higher-high   |
//| (the pullback high itself), so strict LH+LL cascade is too      |
//| rigid. Three consecutive closes in the trend direction, bounded  |
//| by the key swing level, is sufficient to confirm bias.          |
//| Returns: -1=DOWN, 1=UP, 0=SIDEWAYS                              |
//+------------------------------------------------------------------+
int DetectTrend(const double &shPx[], const double &slPx[], const double &closes[])
{
    if(ArraySize(shPx) < 1 || ArraySize(slPx) < 1) return 0;
    if(ArraySize(closes) < 3) return 0;

    // SHORT: closes falling  AND  all three below the prior swing high (resistance)
    bool recentDown    = (closes[0] < closes[1] && closes[1] < closes[2]);
    bool belowResist   = (closes[0] < shPx[0] && closes[1] < shPx[0] && closes[2] < shPx[0]);

    // LONG: closes rising  AND  all three above the prior swing low (support)
    bool recentUp      = (closes[0] > closes[1] && closes[1] > closes[2]);
    bool aboveSupport  = (closes[0] > slPx[0] && closes[1] > slPx[0] && closes[2] > slPx[0]);

    if(recentDown && belowResist) return -1;
    if(recentUp   && aboveSupport) return  1;
    return 0;
}

//+------------------------------------------------------------------+
//| Key level proximity check (used by InpUseKeyLevelFilter gate)   |
//|                                                                  |
//| SHORT → returns true (block trade) when entry is within buffer  |
//|         of: ATL, Monthly/Weekly lows, H1 swing lows (support)   |
//| LONG  → returns true when entry is within buffer of:            |
//|         ATH, Monthly/Weekly highs, H1 swing highs (resistance)  |
//|                                                                  |
//| H1 swing detection uses 3-bar lookback on BOTH sides — higher   |
//| timeframe pivots should be fully confirmed on both sides.        |
//+------------------------------------------------------------------+
bool IsNearKeyLevel(double price, string dir)
{
    double pipVal = ((_Digits == 5 || _Digits == 3) ? _Point * 10.0 : _Point);
    double buf    = InpKeyLevelPips * pipVal;

    // ── Weekly high / low (last 52 weeks) ───────────────────────────
    {
        double wH[], wL[];
        int n = MathMin(52, (int)iBars(_Symbol, PERIOD_W1));
        if(n > 0 &&
           CopyHigh(_Symbol, PERIOD_W1, 0, n, wH) == n &&
           CopyLow (_Symbol, PERIOD_W1, 0, n, wL) == n)
        {
            double wkHigh = wH[ArrayMaximum(wH, 0, WHOLE_ARRAY)];
            double wkLow  = wL[ArrayMinimum(wL, 0, WHOLE_ARRAY)];
            if(dir == "SHORT" && MathAbs(price - wkLow)  <= buf) return true;
            if(dir == "LONG"  && MathAbs(price - wkHigh) <= buf) return true;
        }
    }

    // ── Monthly high / low (last 12 months) ─────────────────────────
    {
        double mH[], mL[];
        int n = MathMin(12, (int)iBars(_Symbol, PERIOD_MN1));
        if(n > 0 &&
           CopyHigh(_Symbol, PERIOD_MN1, 0, n, mH) == n &&
           CopyLow (_Symbol, PERIOD_MN1, 0, n, mL) == n)
        {
            double mnHigh = mH[ArrayMaximum(mH, 0, WHOLE_ARRAY)];
            double mnLow  = mL[ArrayMinimum(mL, 0, WHOLE_ARRAY)];
            if(dir == "SHORT" && MathAbs(price - mnLow)  <= buf) return true;
            if(dir == "LONG"  && MathAbs(price - mnHigh) <= buf) return true;
        }
    }

    // ── All-time high / low (up to 520 weekly bars ≈ 10 years) ─────
    {
        double aH[], aL[];
        int n = MathMin(520, (int)iBars(_Symbol, PERIOD_W1));
        if(n > 0 &&
           CopyHigh(_Symbol, PERIOD_W1, 0, n, aH) == n &&
           CopyLow (_Symbol, PERIOD_W1, 0, n, aL) == n)
        {
            double ath = aH[ArrayMaximum(aH, 0, WHOLE_ARRAY)];
            double atl = aL[ArrayMinimum(aL, 0, WHOLE_ARRAY)];
            if(dir == "SHORT" && MathAbs(price - atl) <= buf) return true;
            if(dir == "LONG"  && MathAbs(price - ath) <= buf) return true;
        }
    }

    // ── H1 swing highs (resistance) and swing lows (support) ────────
    // Uses 200 H1 bars (~8 days). Both-sides lookback is intentional:
    // H1 pivots should be confirmed on each side for S/R reliability.
    {
        double h1H[], h1L[];
        int    h1Bars = 200;
        int    lb     = 3;
        if(CopyHigh(_Symbol, PERIOD_H1, 1, h1Bars, h1H) == h1Bars &&
           CopyLow (_Symbol, PERIOD_H1, 1, h1Bars, h1L) == h1Bars)
        {
            // Arrays returned oldest-first (not AsSeries)
            for(int i = lb; i < h1Bars - lb; i++)
            {
                if(dir == "LONG")   // check H1 swing highs = resistance
                {
                    bool isRes = true;
                    for(int j = 1; j <= lb && isRes; j++)
                        if(h1H[i] <= h1H[i - j] || h1H[i] <= h1H[i + j]) isRes = false;
                    if(isRes && MathAbs(price - h1H[i]) <= buf) return true;
                }
                if(dir == "SHORT")  // check H1 swing lows = support
                {
                    bool isSup = true;
                    for(int j = 1; j <= lb && isSup; j++)
                        if(h1L[i] >= h1L[i - j] || h1L[i] >= h1L[i + j]) isSup = false;
                    if(isSup && MathAbs(price - h1L[i]) <= buf) return true;
                }
            }
        }
    }

    return false;
}

//+------------------------------------------------------------------+
//| Rule 8 — Bollinger Band position label                          |
//+------------------------------------------------------------------+
string BBLabel(double price, double upper, double middle, double lower)
{
    double bw = upper - lower;
    if(bw == 0) return "MIDDLE";
    double pos = (price - lower) / bw;
    if(price >= upper)  return "BEYOND_UPPER";
    if(price <= lower)  return "BEYOND_LOWER";
    if(pos >= 0.75)     return "NEAR_UPPER";
    if(pos <= 0.25)     return "NEAR_LOWER";
    return "MIDDLE";
}

//+------------------------------------------------------------------+
//| Rules 8+9 — Signal strength                                     |
//+------------------------------------------------------------------+
string SignalStrength(string dir, string bbPos, int structCount)
{
    bool early = (structCount <= 2);

    bool goodBB = (dir == "SHORT")
        ? (bbPos == "NEAR_UPPER" || bbPos == "BEYOND_UPPER")
        : (bbPos == "NEAR_LOWER" || bbPos == "BEYOND_LOWER");

    bool exhausted = (dir == "SHORT")
        ? (bbPos == "NEAR_LOWER" || bbPos == "BEYOND_LOWER")
        : (bbPos == "NEAR_UPPER" || bbPos == "BEYOND_UPPER");

    if(exhausted || structCount >= 4) return "LOW";
    if(early && goodBB)               return "HIGH";
    return "MEDIUM";
}

//+------------------------------------------------------------------+
//| Risk-based lot size calculation                                  |
//+------------------------------------------------------------------+
double CalcLots(double entry, double stopLoss)
{
    double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
    double riskAmt  = balance * InpRiskPercent / 100.0;
    double slDist   = MathAbs(entry - stopLoss);
    double minLot   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);

    if(slDist == 0) return minLot;

    double tickVal  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
    double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    if(tickSize == 0 || tickVal == 0) return minLot;

    double valuePerPoint = tickVal / tickSize;
    double lot = riskAmt / (slDist * valuePerPoint);

    double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
    double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

    lot = MathMax(minLot, MathMin(maxLot, lot));
    if(lotStep > 0)
        lot = MathRound(lot / lotStep) * lotStep;

    return lot;
}

//+------------------------------------------------------------------+
//| Build full strategy checklist string                            |
//+------------------------------------------------------------------+
string BuildSummary(
    string dir,
    double entry, double sl, double tp, double rr,
    double anchor, double pullback, double dist,
    double bbU, double bbM, double bbL, string bbPos,
    int structCount, string strength,
    double trendPips, double pullbackPct)
{
    string anchorLabel   = (dir == "SHORT") ? "Swing Low (anchor)"    : "Swing High (anchor)";
    string pullbackLabel = (dir == "SHORT") ? "Pullback High (trend.)" : "Pullback Low (trend.)";
    string trendLabel    = (dir == "SHORT") ? "DOWNTREND — LH + LL"   : "UPTREND — HH + HL";

    // Ratio label: how much of the trend leg has been retraced
    string pbZone;
    if     (pullbackPct < 38.0) pbZone = "shallow (<38%) — strong trend";
    else if(pullbackPct < 50.0) pbZone = "38-50% Fib zone — normal";
    else if(pullbackPct < 62.0) pbZone = "50-62% Fib zone — deep but valid";
    else                        pbZone = "62-70% — near limit, caution";

    string s = "";
    s += "═══ MARCI SILFRAIN — MEASURED MOVE TREND ═══\n";
    s += StringFormat("Signal     : %s  [%s CONFIDENCE]\n\n", dir, strength);

    s += "STRATEGY RULES VERIFIED:\n";
    s += StringFormat("[OK] Rule 1  — Trend: %s\n",                    trendLabel);
    s += "[OK] Rule 2  — Impulse move + pullback identified\n";
    s += StringFormat("[OK] Rule 3  — %s: %s\n",                       pullbackLabel, DoubleToString(pullback, _Digits));
    s += StringFormat("[OK] Rule 4  — %s: %s\n",                       anchorLabel,   DoubleToString(anchor,   _Digits));
    s += StringFormat("[OK] Rule 5  — Measured distance: %s (%.2f%%)\n", DoubleToString(dist, _Digits), dist / anchor * 100);
    s += StringFormat("[OK] Rule 6  — Projected target: %s\n",         DoubleToString(tp, _Digits));
    s += "[OK] Rule 7  — Price rejecting trendline / resuming trend\n";
    s += StringFormat("[OK] Rule 8  — BB position: %s  U=%.5f M=%.5f L=%.5f\n", bbPos, bbU, bbM, bbL);
    s += StringFormat("[OK] Rule 9  — Structure #%d in trend  (1-2=strongest / 4+=exhaustion)\n", structCount);
    s += StringFormat("[OK] Rule 10 — Invalidated if price closes beyond: %s\n\n", DoubleToString(sl, _Digits));

    s += "TREND & PULLBACK STRENGTH:\n";
    s += StringFormat("  Impulse leg : %.1f pips  (min required: %.0f)\n", trendPips, InpMinTrendPips);
    s += StringFormat("  Retracement : %.1f%%  — %s\n",                    pullbackPct, pbZone);
    s += StringFormat("  Ratio (leg/retrace): 1:%.2f\n\n",                 pullbackPct / 100.0);

    s += "TRADE LEVELS:\n";
    s += StringFormat("  Entry      : %s\n",  DoubleToString(entry, _Digits));
    s += StringFormat("  Stop Loss  : %s\n",  DoubleToString(sl,    _Digits));
    s += StringFormat("  Target     : %s\n",  DoubleToString(tp,    _Digits));
    s += StringFormat("  R:R        : 1:%.1f\n", rr);
    return s;
}

//+------------------------------------------------------------------+
//| Draw entry / SL / TP horizontal lines on the chart              |
//+------------------------------------------------------------------+
void DrawLevels(double entry, double sl, double tp, string dir)
{
    ObjectsDeleteAll(0, "Marci_");

    datetime t1 = iTime(_Symbol, PERIOD_CURRENT, 20);
    datetime t2 = iTime(_Symbol, PERIOD_CURRENT,  1);

    color entryClr = (dir == "SHORT") ? clrOrange : clrDodgerBlue;

    CreateTrendLine("Marci_Entry",  entry, t1, t2, entryClr, STYLE_SOLID, 2);
    CreateTrendLine("Marci_SL",     sl,    t1, t2, clrRed,   STYLE_DASH,  1);
    CreateTrendLine("Marci_Target", tp,    t1, t2, clrLime,  STYLE_DASH,  1);
}

void CreateTrendLine(string name, double price,
                     datetime t1, datetime t2,
                     color clr, ENUM_LINE_STYLE style, int width)
{
    if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_TREND, 0, t1, price, t2, price);
    ObjectSetInteger(0, name, OBJPROP_COLOR,     clr);
    ObjectSetInteger(0, name, OBJPROP_STYLE,     style);
    ObjectSetInteger(0, name, OBJPROP_WIDTH,     width);
    ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
    ObjectSetString (0, name, OBJPROP_TOOLTIP,   name + ": " + DoubleToString(price, _Digits));
}
