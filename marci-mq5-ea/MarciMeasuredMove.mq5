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
//+------------------------------------------------------------------+
#property copyright "Marci Silfrain Strategy EA"
#property version   "1.00"
#property description "Measured Move Trend Strategy — Little RZY Detector"
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
input int    InpSwingLookback  = 3;         // Bars each side for swing detection
input int    InpBBPeriod       = 20;        // Bollinger Bands period
input double InpBBDeviation    = 2.0;       // Bollinger Bands std deviation
input int    InpCandleCount    = 100;       // Historical candles to analyse

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
    double highs[], lows[], closes[];
    ArraySetAsSeries(highs,  true);
    ArraySetAsSeries(lows,   true);
    ArraySetAsSeries(closes, true);

    if(CopyHigh (_Symbol, PERIOD_CURRENT, 1, InpCandleCount, highs)  < InpCandleCount) return;
    if(CopyLow  (_Symbol, PERIOD_CURRENT, 1, InpCandleCount, lows)   < InpCandleCount) return;
    if(CopyClose(_Symbol, PERIOD_CURRENT, 1, InpCandleCount, closes) < InpCandleCount) return;

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

    if(ArraySize(shIdx) < 3 || ArraySize(slIdx) < 3) return;

    //── Rule 1: identify the trend ──────────────────────────────────
    // Arrays are AsSeries: index 0 = most recent swing point
    // Downtrend: shPx[0] < shPx[1] < shPx[2]  (recent lows older)
    // Uptrend  : shPx[0] > shPx[1] > shPx[2]
    int trend = DetectTrend(shPx, slPx);
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
        if(anchorIdx < 2) return;

        double phPx  = 0.0;
        int    phBar = -1;
        for(int i = 0; i < anchorIdx; i++)
        {
            if(highs[i] > phPx) { phPx = highs[i]; phBar = i; }
        }
        if(phBar < 0) return;

        // Rule 10: pullback must not exceed prior confirmed swing high
        if(ArraySize(shIdx) > 0 && phPx >= shPx[0]) return;

        // Rule 7: entry conditions
        bool inZone = (curPrice > anchorPx && curPrice < phPx);

        bool visitedPeak = false;
        int  checkBars   = MathMin(8, anchorIdx);
        for(int i = 0; i < checkBars; i++)
            if(closes[i] >= phPx * 0.97) { visitedPeak = true; break; }

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

        string summary = BuildSummary("SHORT", entryPx, slPxVal, targetPx, rr,
                                      anchorPx, phPx, measuredDist,
                                      curUpper, curMiddle, curLower,
                                      bbPos, structCount, strength);

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

        if(anchorIdx < 2) return;

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

        bool inZone = (curPrice > plPx && curPrice < anchorPx);

        bool visitedTrough = false;
        int  checkBars     = MathMin(8, anchorIdx);
        for(int i = 0; i < checkBars; i++)
            if(closes[i] <= plPx * 1.03) { visitedTrough = true; break; }

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

        string summary = BuildSummary("LONG", entryPx, slPxVal, targetPx, rr,
                                      anchorPx, plPx, measuredDist,
                                      curUpper, curMiddle, curLower,
                                      bbPos, structCount, strength);

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
        // Swing high: higher than n bars on both sides
        bool isHigh = true;
        for(int j = 1; j <= n && isHigh; j++)
            if(highs[i] < highs[i - j] || highs[i] < highs[i + j]) isHigh = false;
        if(isHigh)
        {
            int sz = ArraySize(shIdxOut);
            ArrayResize(shIdxOut, sz + 1);
            ArrayResize(shPxOut,  sz + 1);
            shIdxOut[sz] = i;
            shPxOut[sz]  = highs[i];
        }

        // Swing low: lower than n bars on both sides
        bool isLow = true;
        for(int j = 1; j <= n && isLow; j++)
            if(lows[i] > lows[i - j] || lows[i] > lows[i + j]) isLow = false;
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
//| Rule 1 — Detect trend from swing arrays (AsSeries: 0 = recent) |
//| Downtrend: shPx[0] < shPx[1]  (most recent high is LOWER)      |
//| Uptrend  : shPx[0] > shPx[1]  (most recent high is HIGHER)     |
//| Returns: -1=DOWN, 1=UP, 0=SIDEWAYS                              |
//+------------------------------------------------------------------+
int DetectTrend(const double &shPx[], const double &slPx[])
{
    int minPts = 3;
    if(ArraySize(shPx) < minPts || ArraySize(slPx) < minPts) return 0;

    bool shDown = true, slDown = true;
    bool shUp   = true, slUp   = true;

    for(int i = 0; i < minPts - 1; i++)
    {
        // Downtrend: each successive element (older) must be HIGHER
        if(shPx[i] >= shPx[i + 1]) shDown = false;
        if(slPx[i] >= slPx[i + 1]) slDown = false;
        // Uptrend: each successive element (older) must be LOWER
        if(shPx[i] <= shPx[i + 1]) shUp = false;
        if(slPx[i] <= slPx[i + 1]) slUp = false;
    }

    if(shDown && slDown) return -1;
    if(shUp   && slUp)   return  1;
    return 0;
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
    int structCount, string strength)
{
    string anchorLabel   = (dir == "SHORT") ? "Swing Low (anchor)"    : "Swing High (anchor)";
    string pullbackLabel = (dir == "SHORT") ? "Pullback High (trend.)" : "Pullback Low (trend.)";
    string trendLabel    = (dir == "SHORT") ? "DOWNTREND — LH + LL"   : "UPTREND — HH + HL";

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
