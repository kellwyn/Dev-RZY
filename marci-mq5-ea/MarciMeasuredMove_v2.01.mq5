//+------------------------------------------------------------------+
//|  Marci Silfrain — Measured Move Trend Strategy EA               |
//|  "Little RZY" structure detector                                |
//|                                                                  |
//|  SETUP SEQUENCE (both directions)                               |
//|   1. X% impulse move identifies the peak (HIGH or LOW)         |
//|   2. Exhaustion/expansion: minor LOW or HIGH forms near peak    |
//|   3. Pullback peak forms (lower HIGH / higher LOW than peak)    |
//|   4. Midpoint + TP/SL levels calculated from peak & minor pt   |
//|   5. Confirm price resuming from pullback toward minor point    |
//|   6. Enter in zone between minor point and pullback peak        |
//|   7. Optional: Key level + Big Move Cooldown filters            |
//|   8. ICT session gate: Asian / London / NY AM only             |
//|   9. Post-TP cooldown: 20-min block if big move follows TP     |
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
//|    · Gap guard — skips daily open if outside prior bar range    |
//|                                                                  |
//|  v1.01  2026-04-14  — Big Move Cooldown filter                  |
//|    · Block SHORT for N bars after price drops >= X%            |
//|    · Block LONG  for N bars after price rises >= X%            |
//|    · Configurable threshold (1-10%+) and cooldown bar count    |
//|    · Toggle on/off via InpUseBigMoveCooldown                   |
//|                                                                  |
//|  v1.02  2026-04-14  — Full strategy rewrite                     |
//|    · Rule 1: X% impulse detects peak; exhaustion/expansion     |
//|    · Rule 2: Minor point searched strictly BETWEEN peak and     |
//|              pullback peak (not globally after peak); Y% gate   |
//|              ensures move stays minor vs the X% impulse         |
//|    · Rule 3: Midpoint-based TP (70% of mid→minor dist)        |
//|              SL = tighter of midpoint±2pip / pbPeak±2pip       |
//|    · Rule 4: Pullback strength gates (depth + min impulse)     |
//|    · Rule 5: Zone candle gate + immediate entry at minor low    |
//|              (replaces 2-bar momentum confirmation)             |
//|    · Rule 6: Entry zone between minor point and pullback peak   |
//|    · Rule 7: Key level + Big Move Cooldown filters (opt)       |
//|    · Rule 8: ICT session filter (Asian/London/NY AM + pre-mkt) |
//|    · Rule 9: Post-TP cooldown (20 min if big move follows TP)  |
//|    · Detailed alert output with all key price levels            |
//|                                                                  |
//|  v2.01  2026-04-28  — Rule changes                              |
//|    · Rule 1: X% threshold lowered to 0.1% (InpBigXMovePct)     |
//|    · Rule 2: Minor dist must be >= 25% of X move (InpYMinPct)   |
//|              M1 minor timing window expanded to 10 bars          |
//|              (InpM1StructureBars); all other TFs stay 5 bars     |
//|    · Rule 3: M1 pullback timing window expanded to 10 bars;      |
//|              all other TFs stay 5 bars (same gate as Rule 2)     |
//+------------------------------------------------------------------+
#property copyright "Marci Silfrain Strategy EA"
#property version   "2.01"
#property description "Measured Move Trend Strategy — Little RZY Detector v2.01"
#property strict

#include <Trade\Trade.mqh>

//── Inputs ────────────────────────────────────────────────────────

// Default settings profile: v102_settings_xauone (XAUUSD)
input group "=== Execution Mode ==="
input bool   InpManualConfirm     = false;  // true = Alert only | false = Auto-execute (backtest)

input group "=== Risk Management ==="
input double InpRiskPercent       = 0.15;   // Risk per trade (% of account balance)
input double InpMinRR             = 0;      // Minimum acceptable risk:reward (0 = disabled)
input double InpMaxLots           = 7.0;    // Hard cap on position size — never exceeded regardless of risk calc

input group "=== Strategy Parameters ==="
input int    InpCandleCount       = 20;     // Historical bars to analyse
input double InpBigXMovePct       = 0.1;    // X% — impulse move size that defines the peak
                                            //   Forex: 1-2%  |  Indices: 2-4%  |  Crypto: 5%+
input double InpYMaxPct           = 600.0;  // Y% max — max minor dist as % of X move (hard cap 90%)
input double InpYMinPct           = 25.0;   // Y% min — minor dist must be >= this % of X move
input double InpTPMultiplier      = 0.5;    // TP = this% × (midpoint → minor point distance)

input group "=== Pullback Strength Gates ==="
input double InpMinImpulsePips    = 5.0;    // Minimum impulse size (pips) — filters noise
input double InpMinPullbackPct    = 2.0;    // Min pullback retracement % of peak→minor distance
input double InpMaxPullbackPct    = 70.0;   // Max pullback retracement % (deeper = weakening)

input group "=== Entry Zone Candle Gate (Rule 5) ==="
input int    InpMaxZoneCandles    = 3;      // Max candles allowed to close between minor low and pb high

input group "=== Structure Timing Gates (Rules 2-3) ==="
input int    InpMaxStructureBars  = 5;      // Minor/pb timing window — non-M1 timeframes
input int    InpM1StructureBars   = 10;     // Minor/pb timing window — M1 timeframe only

input group "=== ICT Session Filter (Rule 8) ==="
input bool   InpUseSessionFilter  = false;  // Only trade during active ICT sessions
input int    InpGMTOffset         = 0;      // Broker server offset from GMT (e.g. +2 = EET)
// Asian session — includes 1 hr pre-market
input int    InpAsianStartH       = 23;     // 23:00 GMT = 1hr before Tokyo open
input int    InpAsianEndH         = 9;      // 09:00 GMT = Tokyo/Sydney close
// London session — includes 1 hr pre-market
input int    InpLondonStartH      = 7;      // 07:00 GMT = 1hr before London open
input int    InpLondonEndH        = 16;     // 16:00 GMT = London close
// New York AM RTH — includes 1 hr pre-market
input int    InpNYStartH          = 12;     // 12:00 GMT ≈ 1hr before NY open (09:30 ET)
input int    InpNYEndH            = 17;     // 17:00 GMT = NY AM session end

input group "=== Post-TP Cooldown (Rule 9) ==="
input bool   InpUsePostTPCooldown = true;   // Block new trades after TP + big follow-through
input int    InpPostTPCooldownMins= 20;     // Minutes to block after TP exit triggers cooldown

input group "=== Big Move Cooldown Filter (Rule 7) ==="
input bool   InpUseBigMoveCooldown  = true; // Block entries when a sharp bar move is recent
input double InpBigMovePct          = 1.0;  // Single-bar move >= this % triggers cooldown
                                            //   Forex: 1-2%  |  Indices/Crypto: 3-5%+
input int    InpBigMoveCooldownBars = 20;   // Bars to stay blocked after trigger

input group "=== Key Level Filter (Rule 7) ==="
input bool   InpUseKeyLevelFilter   = true; // Block trades within X pips of ATH/ATL, W1/MN1 pivots
input double InpKeyLevelPips        = 10.0; // Key level proximity buffer (pips)

input group "=== Trade Settings ==="
input int    InpMagicNumber       = 20260412;
input int    InpSlippage          = 20;

input group "=== Display ==="
input bool   InpDrawObjects = true;           // Draw structure and order levels on chart
input color  InpXMoveColor  = clrSteelBlue;   // X% peak highlight (40% opacity fill)
input color  InpMinorColor  = clrOrange;       // Minor low / minor high dotted line
input color  InpPBColor     = clrGold;         // Pullback peak / trough dotted line

//── Globals ───────────────────────────────────────────────────────
CTrade   Trade;
datetime g_lastTPExitTime  = 0;
double   g_lastTPExitPrice = 0.0;
double   g_execShortPeakPx = 0.0;   // peak of last executed SHORT — reset when structure expires
double   g_execLongTrPx    = 0.0;   // trough of last executed LONG — reset when structure expires
int      g_drawCount       = 0;     // increments each trade so object names stay unique
int      g_activeDrawCount = 0;    // draw group of the currently open trade (0 = none)

//+------------------------------------------------------------------+
//| Initialisation                                                   |
//+------------------------------------------------------------------+
int OnInit()
{
    Trade.SetExpertMagicNumber(InpMagicNumber);
    Trade.SetDeviationInPoints(InpSlippage);

    if(InpYMaxPct > 90.0)
        Print("WARN: InpYMaxPct capped at 90% of X move — adjusting at runtime");

    string mode = InpManualConfirm ? "MANUAL CONFIRM (live)" : "AUTO-EXECUTE (backtest)";
    Print("Marci MM v2.01 ready  |  ", _Symbol, "  ",
          EnumToString(Period()), "  |  ", mode);
    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Cleanup                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    ObjectsDeleteAll(0, "RZY_");
    ObjectsDeleteAll(0, "Marci_");
    Comment("");
}

//+------------------------------------------------------------------+
//| New-bar tick gate                                                |
//+------------------------------------------------------------------+
void OnTick()
{
    static datetime lastBar = 0;
    datetime curBar = iTime(_Symbol, PERIOD_CURRENT, 0);
    if(curBar == lastBar) return;
    lastBar = curBar;

    if(HasOpenPosition()) return;
    RunStrategy();
}

//+------------------------------------------------------------------+
//| Trade close handler — Rule 9 cooldown + drawing trim            |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest     &request,
                        const MqlTradeResult      &result)
{
    if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
    if(!HistoryDealSelect(trans.deal))           return;

    ulong  magic      = (ulong)HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
    if(magic != (ulong)InpMagicNumber)           return;

    ENUM_DEAL_ENTRY entryType = (ENUM_DEAL_ENTRY) HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
    ENUM_DEAL_REASON why      = (ENUM_DEAL_REASON)HistoryDealGetInteger(trans.deal, DEAL_REASON);
    datetime dealTime         = (datetime)         HistoryDealGetInteger(trans.deal, DEAL_TIME);
    double   dealPrice        =                    HistoryDealGetDouble (trans.deal, DEAL_PRICE);

    //── Rule 9: Post-TP cooldown ──────────────────────────────────
    if(InpUsePostTPCooldown && why == DEAL_REASON_TP)
    {
        g_lastTPExitTime  = dealTime;
        g_lastTPExitPrice = dealPrice;
    }

    //── Drawing: trim lines to close bar on any exit ──────────────
    // Catches TP, SL, and manual close — stops drawings at trade end.
    if(InpDrawObjects && entryType == DEAL_ENTRY_OUT && g_activeDrawCount > 0)
    {
        string sfx   = IntegerToString(g_activeDrawCount);
        string names[6] = {"RZY_Minor_","RZY_PBPeak_","RZY_Entry_","RZY_SL_","RZY_TP_","RZY_BaseLine_"};
        for(int i = 0; i < 6; i++)
        {
            string n = names[i] + sfx;
            if(ObjectFind(0, n) >= 0)
                ObjectSetInteger(0, n, OBJPROP_TIME, 1, dealTime);
        }
        g_activeDrawCount = 0;
    }
}

//+------------------------------------------------------------------+
//| Own open-position check                                         |
//+------------------------------------------------------------------+
bool HasOpenPosition()
{
    for(int i = PositionsTotal() - 1; i >= 0; i--)
        if(PositionGetTicket(i) > 0)
            if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
               (ulong)PositionGetInteger(POSITION_MAGIC) == (ulong)InpMagicNumber)
                return true;
    return false;
}

//+------------------------------------------------------------------+
//| CORE STRATEGY                                                    |
//+------------------------------------------------------------------+
void RunStrategy()
{
    //── Fetch completed OHLC (pos=1 skips forming bar) ─────────────
    double highs[], lows[], closes[], opens[];
    ArraySetAsSeries(highs,  true); ArraySetAsSeries(lows,   true);
    ArraySetAsSeries(closes, true); ArraySetAsSeries(opens,  true);

    if(CopyHigh (_Symbol, PERIOD_CURRENT, 1, InpCandleCount, highs)  < InpCandleCount) return;
    if(CopyLow  (_Symbol, PERIOD_CURRENT, 1, InpCandleCount, lows)   < InpCandleCount) return;
    if(CopyClose(_Symbol, PERIOD_CURRENT, 1, InpCandleCount, closes) < InpCandleCount) return;
    if(CopyOpen (_Symbol, PERIOD_CURRENT, 1, InpCandleCount, opens)  < InpCandleCount) return;

    //── Pre-check 1: Gap guard (daily open only) ────────────────────
    datetime t_curr = iTime(_Symbol, PERIOD_CURRENT, 1);
    datetime t_prev = iTime(_Symbol, PERIOD_CURRENT, 2);
    bool is_new_day = (MathFloor((double)t_curr / 86400) != MathFloor((double)t_prev / 86400));
    if(is_new_day && (opens[0] > highs[1] || opens[0] < lows[1])) return;

    //── Pre-check 2: ICT session filter (Rule 8) ───────────────────
    if(!IsInTradingSession()) return;

    //── Pre-check 3: Post-TP cooldown (Rule 9) ─────────────────────
    if(IsPostTPCooldown(closes)) return;

    double pipVal    = ((_Digits == 5 || _Digits == 3) ? _Point * 10.0 : _Point);
    double yMaxPct   = MathMin(InpYMaxPct, 90.0);  // hard cap
    // Rule 2-3: M1 uses wider timing window than higher timeframes
    int    structBars = (Period() == PERIOD_M1) ? InpM1StructureBars : InpMaxStructureBars;

    bool shortFired = false;

    //══════════════════════════════════════════════════════════════
    // SHORT SETUP
    // Sequence: X% UP → HIGH peak → minor LOW (exhaustion)
    //           → pullback HIGH (lower than peak)
    //           → price declining toward minor low → ENTRY
    //══════════════════════════════════════════════════════════════
    {
        int    peakBar  = -1; double peakPx  = 0;
        int    minorBar = -1; double minorPx = 0;
        int    pbBar    = -1; double pbPx    = 0;
        double effectivePbPx = 0;

        bool shortFound = FindShortSetup(highs, lows, opens, closes,
                                          InpCandleCount, InpBigXMovePct,
                                          yMaxPct, InpYMinPct,
                                          InpMinPullbackPct, InpMaxPullbackPct,
                                          pipVal, InpMinImpulsePips, structBars,
                                          peakBar, peakPx, minorBar, minorPx, pbBar, pbPx);

        // Reset 1-trade guard when structure expires; skip same structure if already traded
        if(!shortFound) g_execShortPeakPx = 0.0;
        if(shortFound && MathAbs(peakPx - g_execShortPeakPx) < pipVal * 2) shortFound = false;

        if(shortFound
           && ConfirmShortEntry(closes, highs, lows, pbBar, peakPx, minorPx,
                                InpMaxPullbackPct, InpMaxZoneCandles, effectivePbPx))
        {
            double curPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);
            bool filtered = (InpUseBigMoveCooldown && IsBigMoveCooldown("SHORT", opens, closes, InpCandleCount))
                         || (InpUseKeyLevelFilter  && IsNearKeyLevel(curPrice, "SHORT"));

            if(!filtered)
            {
                // Rule 3: calculate TP and SL using effectivePbPx
                double midpoint     = (peakPx + minorPx) / 2.0;
                double distMidMinor = midpoint - minorPx;
                double tpPx         = minorPx - distMidMinor * (InpTPMultiplier / 100.0);
                double slOpt1       = midpoint       + pipVal * 2.0;
                double slOpt2       = effectivePbPx  + pipVal * 2.0;
                double slPx         = MathMin(slOpt1, slOpt2);

                double risk   = slPx    - curPrice;
                double reward = curPrice - tpPx;
                double rr     = (risk > 0 && reward > 0) ? reward / risk : 0;

                if(rr >= InpMinRR)
                {
                    double lots    = CalcLots(curPrice, slPx);
                    string summary = BuildSummary("SHORT", curPrice, slPx, tpPx, rr,
                                                  peakPx, minorPx, effectivePbPx, midpoint, lots);
                    // Find prior body low (base of X% move) — oldest bar beyond peak
                    double priorBodLow_s = DBL_MAX; int priorBodBar_s = peakBar + 1;
                    for(int j = peakBar + 1; j < InpCandleCount; j++)
                    {
                        double bLow = MathMin(opens[j], closes[j]);
                        if(bLow < priorBodLow_s) { priorBodLow_s = bLow; priorBodBar_s = j; }
                    }
                    if(priorBodLow_s == DBL_MAX) { priorBodLow_s = minorPx; priorBodBar_s = peakBar + 1; }
                    DrawRZYSetup(peakBar, minorPx, peakPx,
                                 priorBodBar_s, priorBodLow_s,
                                 minorBar, pbBar,
                                 minorPx, effectivePbPx,
                                 curPrice, slPx, tpPx, rr, "SHORT");
                    Comment(summary);

                    if(InpManualConfirm)
                        Alert("MARCI EA  >>>  SHORT SETUP on ", _Symbol, "\n\n", summary);
                    else if(lots > 0)
                        if(!Trade.Sell(lots, _Symbol, curPrice, slPx, tpPx, "Marci_MM_SHORT"))
                            Print("Order failed: ", Trade.ResultRetcodeDescription());

                    g_execShortPeakPx = peakPx;  // mark structure as traded; reset on structure expiry
                    shortFired = true;
                }
            }
        }
    }

    if(shortFired) return;
    //══════════════════════════════════════════════════════════════
    // LONG SETUP
    // Sequence: X% DOWN → LOW trough → minor HIGH (expansion)
    //           → pullback LOW (higher than trough)
    //           → price rising toward minor high → ENTRY
    //══════════════════════════════════════════════════════════════
    {
        int    troughBar = -1; double troughPx = 0;
        int    minorBar  = -1; double minorPx  = 0;
        int    pbBar     = -1; double pbPx     = 0;
        double effectivePbPx = 0;

        bool longFound = FindLongSetup(highs, lows, opens, closes,
                                        InpCandleCount, InpBigXMovePct,
                                        yMaxPct, InpYMinPct,
                                        InpMinPullbackPct, InpMaxPullbackPct,
                                        pipVal, InpMinImpulsePips, structBars,
                                        troughBar, troughPx, minorBar, minorPx, pbBar, pbPx);

        if(!longFound) g_execLongTrPx = 0.0;
        if(longFound && MathAbs(troughPx - g_execLongTrPx) < pipVal * 2) longFound = false;

        if(longFound
           && ConfirmLongEntry(closes, highs, lows, pbBar, troughPx, minorPx,
                               InpMaxPullbackPct, InpMaxZoneCandles, effectivePbPx))
        {
            double curPrice = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

            if(InpUseBigMoveCooldown && IsBigMoveCooldown("LONG", opens, closes, InpCandleCount))
                return;
            if(InpUseKeyLevelFilter  && IsNearKeyLevel(curPrice, "LONG"))
                return;

            double midpoint     = (troughPx + minorPx) / 2.0;
            double distMidMinor = minorPx - midpoint;
            double tpPx         = minorPx + distMidMinor * (InpTPMultiplier / 100.0);
            double slOpt1       = midpoint      - pipVal * 2.0;
            double slOpt2       = effectivePbPx - pipVal * 2.0;
            double slPx         = MathMax(slOpt1, slOpt2);

            double risk   = curPrice - slPx;
            double reward = tpPx     - curPrice;
            if(risk <= 0 || reward <= 0) return;
            double rr = reward / risk;
            if(rr < InpMinRR) return;

            double lots    = CalcLots(curPrice, slPx);
            string summary = BuildSummary("LONG", curPrice, slPx, tpPx, rr,
                                          troughPx, minorPx, effectivePbPx, midpoint, lots);

            // Find prior body high (base of X% move) — oldest bar beyond trough
            double priorBodHigh_l = 0.0; int priorBodBar_l = troughBar + 1;
            for(int j = troughBar + 1; j < InpCandleCount; j++)
            {
                double bHigh = MathMax(opens[j], closes[j]);
                if(bHigh > priorBodHigh_l) { priorBodHigh_l = bHigh; priorBodBar_l = j; }
            }
            if(priorBodHigh_l == 0.0) { priorBodHigh_l = minorPx; priorBodBar_l = troughBar + 1; }
            DrawRZYSetup(troughBar, troughPx, minorPx,
                         priorBodBar_l, priorBodHigh_l,
                         minorBar, pbBar,
                         minorPx, effectivePbPx,
                         curPrice, slPx, tpPx, rr, "LONG");
            Comment(summary);

            if(InpManualConfirm)
                Alert("MARCI EA  >>>  LONG SETUP on ", _Symbol, "\n\n", summary);
            else
            {
                if(lots > 0)
                    if(!Trade.Buy(lots, _Symbol, curPrice, slPx, tpPx, "Marci_MM_LONG"))
                        Print("Order failed: ", Trade.ResultRetcodeDescription());
            }
            g_execLongTrPx = troughPx;  // mark structure as traded; reset on structure expiry
        }
    }
}

//+------------------------------------------------------------------+
//| Rule 1-4: Find SHORT setup                                      |
//|                                                                  |
//| Temporal sequence (AsSeries — index 0 = most recent bar):      |
//|                                                                  |
//|  [X% UP move] → PEAK (highest HIGH)                            |
//|      ↓  price drops from peak                                   |
//|  MINOR LOW (lowest point of the initial drop)                  |
//|      ↑  price bounces back up (but lower than peak)            |
//|  PULLBACK PEAK (lower high — the retest)                       |
//|      ↓  price declines again → ENTRY zone                      |
//|                                                                  |
//| Index order in AsSeries: peakBar > minorBar > pbBar > 0        |
//|                                                                  |
//| Algorithm — order matters:                                      |
//|  1. Find PEAK (X% UP move validated)                           |
//|  2. Find PULLBACK PEAK first (highest high after peak, <peak)  |
//|  3. Find MINOR LOW strictly BETWEEN peak and pullback peak      |
//|     — minor low can sit anywhere in that window                 |
//|     — must be less than Y% of the X move (stays "minor")       |
//|     — must be below the pullback peak (confirms the dip)       |
//|  4. Validate pullback depth and minimum impulse size            |
//+------------------------------------------------------------------+
bool FindShortSetup(
    const double &highs[], const double &lows[],
    const double &opens[], const double &closes[],
    int bars, double xPct, double yMaxPct, double yMinPct,
    double minPbPct, double maxPbPct,
    double pipVal, double minImpPips, int maxStructBars,
    int &peakBar, double &peakPx,
    int &minorBar, double &minorPx,
    int &pbBar, double &pbPx)
{
    // Iterate candidate peaks from most recent (small AsSeries index) to oldest.
    // For each peak meeting the X% gate, minor low must form within maxStructBars
    // bars and pullback peak within maxStructBars bars of the minor. If either
    // timing constraint fails, discard that peak and re-evaluate from step 1.
    //
    // AsSeries convention: index 0 = most recent, higher index = older.
    // "After peak" (chronologically) = smaller index than peak.

    int minPeakIdx = maxStructBars * 2 + 2;  // need room for minor + pb + 2 confirmation bars

    for(int pk = minPeakIdx; pk < bars; pk++)
    {
        double pkPx = highs[pk];

        //── Step 1: X% UP move (body-to-body) ──────────────────────
        double pkBody      = MathMax(opens[pk], closes[pk]);  // top of peak candle body
        double priorBodLow = DBL_MAX;
        for(int i = pk + 1; i < bars; i++)
        {
            double bLow = MathMin(opens[i], closes[i]);
            if(bLow < priorBodLow) priorBodLow = bLow;
        }
        if(priorBodLow == DBL_MAX || priorBodLow == 0) continue;
        double xMove = pkBody - priorBodLow;
        if(xMove <= 0) continue;
        if(xMove / priorBodLow * 100.0 < xPct) continue;

        //── Step 2: MINOR LOW within maxStructBars bars after peak ──
        // In AsSeries, "after peak" = indices pk-1 down to pk-maxStructBars
        int mnStart = MathMax(0, pk - maxStructBars);
        int mnCount = pk - mnStart;          // number of bars to search
        if(mnCount < 1) continue;
        int mnBar = ArrayMinimum(lows, mnStart, mnCount);
        double mnPx = lows[mnBar];

        //── Step 3: PULLBACK PEAK within maxStructBars bars after minor
        int pbStart = MathMax(2, mnBar - maxStructBars);  // index >= 2 for confirmation
        int pbCount = mnBar - pbStart;
        if(pbCount < 1) continue;
        int pbBar_c = ArrayMaximum(highs, pbStart, pbCount);
        double pbPx_c = highs[pbBar_c];

        //── Structural validity ──────────────────────────────────────
        if(pbPx_c >= pkPx)  continue;  // not a lower high
        if(mnPx   >= pbPx_c) continue; // minor must be below pb
        if(pbBar_c < 2)      continue; // need 2 confirmation bars

        //── Step 4: Y% gate (min and max) ───────────────────────────
        double mnDist = pkPx - mnPx;
        if(mnDist <= 0) continue;
        if(mnDist > (yMaxPct / 100.0) * xMove) continue;   // too large — not a minor move
        if(mnDist < (yMinPct / 100.0) * xMove) continue;   // too small — not a meaningful drop

        //── Step 5: Pullback depth ───────────────────────────────────
        double pbDepth = (pbPx_c - mnPx) / (pkPx - mnPx) * 100.0;
        if(pbDepth < minPbPct || pbDepth > maxPbPct) continue;

        //── Step 6: Minimum impulse ──────────────────────────────────
        if(pipVal > 0 && mnDist / pipVal < minImpPips) continue;

        // Valid — assign outputs
        peakBar  = pk;     peakPx  = pkPx;
        minorBar = mnBar;  minorPx = mnPx;
        pbBar    = pbBar_c; pbPx   = pbPx_c;
        return true;
    }
    return false;
}

//+------------------------------------------------------------------+
//| Rule 1-4: Find LONG setup (mirror of SHORT)                     |
//|                                                                  |
//| Temporal sequence:                                              |
//|                                                                  |
//|  [X% DOWN move] → TROUGH (lowest LOW)                          |
//|      ↑  price rises from trough                                 |
//|  MINOR HIGH (highest point of the initial rise)                |
//|      ↓  price pulls back (but higher than trough)              |
//|  PULLBACK TROUGH (higher low — the retest)                     |
//|      ↑  price rises again → ENTRY zone                         |
//|                                                                  |
//| Index order in AsSeries: troughBar > minorBar > pbBar > 0      |
//|                                                                  |
//| Algorithm:                                                      |
//|  1. Find TROUGH (X% DOWN move validated)                       |
//|  2. Find PULLBACK TROUGH first (lowest low after trough,>trough)|
//|  3. Find MINOR HIGH strictly BETWEEN trough and pullback trough |
//|  4. Validate Y% gate, pullback depth, minimum impulse size      |
//+------------------------------------------------------------------+
bool FindLongSetup(
    const double &highs[], const double &lows[],
    const double &opens[], const double &closes[],
    int bars, double xPct, double yMaxPct, double yMinPct,
    double minPbPct, double maxPbPct,
    double pipVal, double minImpPips, int maxStructBars,
    int &troughBar, double &troughPx,
    int &minorBar,  double &minorPx,
    int &pbBar,     double &pbPx)
{
    // Mirror of FindShortSetup. Iterates candidate troughs from most recent
    // to oldest. Minor high must form within maxStructBars bars of trough;
    // pullback trough within maxStructBars bars of minor high.

    int minTroughIdx = maxStructBars * 2 + 2;

    for(int tr = minTroughIdx; tr < bars; tr++)
    {
        double trPx = lows[tr];

        //── Step 1: X% DOWN move (body-to-body) ─────────────────────
        double trBody       = MathMin(opens[tr], closes[tr]);  // bottom of trough candle body
        double priorBodHigh = 0;
        for(int i = tr + 1; i < bars; i++)
        {
            double bHigh = MathMax(opens[i], closes[i]);
            if(bHigh > priorBodHigh) priorBodHigh = bHigh;
        }
        if(priorBodHigh == 0 || trBody == 0) continue;
        double xMove = priorBodHigh - trBody;
        if(xMove <= 0) continue;
        if(xMove / priorBodHigh * 100.0 < xPct) continue;

        //── Step 2: MINOR HIGH within maxStructBars bars after trough
        int mnStart = MathMax(0, tr - maxStructBars);
        int mnCount = tr - mnStart;
        if(mnCount < 1) continue;
        int mnBar = ArrayMaximum(highs, mnStart, mnCount);
        double mnPx = highs[mnBar];

        //── Step 3: PULLBACK TROUGH within maxStructBars bars after minor
        int pbStart = MathMax(2, mnBar - maxStructBars);
        int pbCount = mnBar - pbStart;
        if(pbCount < 1) continue;
        int pbBar_c = ArrayMinimum(lows, pbStart, pbCount);
        double pbPx_c = lows[pbBar_c];

        //── Structural validity ──────────────────────────────────────
        if(pbPx_c <= trPx)   continue;  // must be higher low
        if(mnPx   <= pbPx_c) continue;  // minor must be above pb
        if(pbBar_c < 2)      continue;

        //── Step 4: Y% gate (min and max) ───────────────────────────
        double mnDist = mnPx - trPx;
        if(mnDist <= 0) continue;
        if(mnDist > (yMaxPct / 100.0) * xMove) continue;   // too large — not a minor move
        if(mnDist < (yMinPct / 100.0) * xMove) continue;   // too small — not a meaningful rise

        //── Step 5: Pullback depth ───────────────────────────────────
        double pbDepth = (mnPx - pbPx_c) / (mnPx - trPx) * 100.0;
        if(pbDepth < minPbPct || pbDepth > maxPbPct) continue;

        //── Step 6: Minimum impulse ──────────────────────────────────
        if(pipVal > 0 && mnDist / pipVal < minImpPips) continue;

        // Valid — assign outputs
        troughBar = tr;      troughPx = trPx;
        minorBar  = mnBar;   minorPx  = mnPx;
        pbBar     = pbBar_c; pbPx     = pbPx_c;
        return true;
    }
    return false;
}

//+------------------------------------------------------------------+
//| Rule 5: Confirm SHORT entry from pullback peak                  |
//|                                                                  |
//| Scans every completed bar after the pb peak (indices pbBar-1    |
//| down to 0 in AsSeries order):                                   |
//|   - Close > effectivePbPx: new higher pb peak. Recalculate      |
//|     depth; if within maxPbPct promote effectivePbPx, else fail. |
//|   - Close < minorPx: structure broken — fail.                   |
//|   - Otherwise: zone candle; fail if count > maxZoneCandles.     |
//|                                                                  |
//| Then checks live Bid:                                           |
//|   - Bid ≤ minorPx  → immediate entry (bar declined to minor).   |
//|   - minorPx < Bid < effectivePbPx → standard entry zone.       |
//+------------------------------------------------------------------+
bool ConfirmShortEntry(
    const double &closes[],
    const double &highs[],
    const double &lows[],
    int pbBar, double peakPx, double minorPx,
    double maxPbPct, int maxZoneCandles,
    double &effectivePbPx)
{
    effectivePbPx = highs[pbBar];
    int zoneCount = 0;

    for(int i = pbBar - 1; i >= 0; i--)
    {
        double c = closes[i];
        double h = highs[i];

        if(c > effectivePbPx)
        {
            double denom    = peakPx - minorPx;
            double newDepth = (denom > 0) ? (h - minorPx) / denom * 100.0 : 0.0;
            if(newDepth > maxPbPct) return false;
            effectivePbPx = h;
        }
        else if(c < minorPx)
        {
            return false;
        }
        else
        {
            zoneCount++;
            if(zoneCount > maxZoneCandles) return false;
        }
    }

    double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
    if(bid <= minorPx)              return true;
    return (bid > minorPx && bid < effectivePbPx);
}

//+------------------------------------------------------------------+
//| Rule 5: Confirm LONG entry from pullback trough (mirror)        |
//+------------------------------------------------------------------+
bool ConfirmLongEntry(
    const double &closes[],
    const double &highs[],
    const double &lows[],
    int pbBar, double troughPx, double minorPx,
    double maxPbPct, int maxZoneCandles,
    double &effectivePbPx)
{
    effectivePbPx = lows[pbBar];
    int zoneCount = 0;

    for(int i = pbBar - 1; i >= 0; i--)
    {
        double c = closes[i];
        double l = lows[i];

        if(c < effectivePbPx)
        {
            double denom    = minorPx - troughPx;
            double newDepth = (denom > 0) ? (minorPx - l) / denom * 100.0 : 0.0;
            if(newDepth > maxPbPct) return false;
            effectivePbPx = l;
        }
        else if(c > minorPx)
        {
            return false;
        }
        else
        {
            zoneCount++;
            if(zoneCount > maxZoneCandles) return false;
        }
    }

    double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
    if(ask >= minorPx)              return true;
    return (ask < minorPx && ask > effectivePbPx);
}

//+------------------------------------------------------------------+
//| Rule 8: ICT session gate                                        |
//| Active windows (GMT, including 1hr pre-market each):            |
//|   Asian : InpAsianStartH  → InpAsianEndH   (spans midnight)    |
//|   London: InpLondonStartH → InpLondonEndH                      |
//|   NY AM : InpNYStartH     → InpNYEndH                          |
//+------------------------------------------------------------------+
bool IsInTradingSession()
{
    if(!InpUseSessionFilter) return true;

    MqlDateTime dt;
    TimeToStruct(TimeGMT(), dt);
    int h = (dt.hour + InpGMTOffset + 24) % 24;

    // Asian can span midnight (start > end)
    bool inAsian;
    if(InpAsianStartH > InpAsianEndH)
        inAsian = (h >= InpAsianStartH || h < InpAsianEndH);
    else
        inAsian = (h >= InpAsianStartH && h < InpAsianEndH);

    bool inLondon = (h >= InpLondonStartH && h < InpLondonEndH);
    bool inNY     = (h >= InpNYStartH     && h < InpNYEndH);

    return inAsian || inLondon || inNY;
}

//── Returns the active session name(s) for the alert summary ──────
string GetCurrentSessionName()
{
    MqlDateTime dt;
    TimeToStruct(TimeGMT(), dt);
    int h = (dt.hour + InpGMTOffset + 24) % 24;

    bool inAsian;
    if(InpAsianStartH > InpAsianEndH)
        inAsian = (h >= InpAsianStartH || h < InpAsianEndH);
    else
        inAsian = (h >= InpAsianStartH && h < InpAsianEndH);
    bool inLondon = (h >= InpLondonStartH && h < InpLondonEndH);
    bool inNY     = (h >= InpNYStartH     && h < InpNYEndH);

    string s = "";
    if(inAsian)
        s += (h >= InpAsianStartH && h < (InpAsianStartH + 1) % 24) ? "PRE-ASIAN " : "ASIAN ";
    if(inLondon)
        s += (h == InpLondonStartH) ? "PRE-LONDON " : "LONDON ";
    if(inNY)
        s += (h == InpNYStartH) ? "PRE-NY " : "NY AM ";
    if(s == "") s = "ALL";
    return s;
}

//+------------------------------------------------------------------+
//| Rule 9: Post-TP cooldown                                        |
//| Returns true (block trade) if:                                   |
//|   - A TP exit occurred within the last InpPostTPCooldownMins    |
//|   AND price has moved >= InpBigMovePct% since that exit         |
//+------------------------------------------------------------------+
bool IsPostTPCooldown(const double &closes[])
{
    if(!InpUsePostTPCooldown)  return false;
    if(g_lastTPExitTime == 0)  return false;

    int elapsedSec = (int)(TimeCurrent() - g_lastTPExitTime);
    if(elapsedSec > InpPostTPCooldownMins * 60) return false;

    if(g_lastTPExitPrice == 0) return false;
    double moveSinceTP = MathAbs(closes[0] - g_lastTPExitPrice) / g_lastTPExitPrice * 100.0;
    return (moveSinceTP >= InpBigMovePct);
}

//+------------------------------------------------------------------+
//| Rule 7: Big move cooldown                                       |
//| Scans last InpBigMoveCooldownBars for a bar that moved >= X%   |
//| on a close-vs-open basis                                        |
//+------------------------------------------------------------------+
bool IsBigMoveCooldown(const string dir,
                       const double &opens[], const double &closes[],
                       int bars)
{
    if(!InpUseBigMoveCooldown) return false;

    double threshold = InpBigMovePct / 100.0;
    int    lookback  = MathMin(InpBigMoveCooldownBars, bars - 1);

    for(int i = 0; i < lookback; i++)
    {
        if(opens[i] == 0.0) continue;
        double barMove = (closes[i] - opens[i]) / opens[i];
        if(dir == "SHORT" && barMove <= -threshold) return true;
        if(dir == "LONG"  && barMove >=  threshold) return true;
    }
    return false;
}

//+------------------------------------------------------------------+
//| Rule 7: Key level proximity filter                              |
//| Checks ATH/ATL (520 W1 bars), Monthly H/L (12 bars),           |
//| Weekly H/L (52 bars)                                            |
//+------------------------------------------------------------------+
bool IsNearKeyLevel(double price, string dir)
{
    double pipVal = ((_Digits == 5 || _Digits == 3) ? _Point * 10.0 : _Point);
    double buf    = InpKeyLevelPips * pipVal;

    // Weekly H/L (52 weeks)
    {
        double wH[], wL[];
        int n = MathMin(52, (int)iBars(_Symbol, PERIOD_W1));
        if(n > 0 &&
           CopyHigh(_Symbol, PERIOD_W1, 0, n, wH) == n &&
           CopyLow (_Symbol, PERIOD_W1, 0, n, wL) == n)
        {
            double wkH = wH[ArrayMaximum(wH, 0, WHOLE_ARRAY)];
            double wkL = wL[ArrayMinimum(wL, 0, WHOLE_ARRAY)];
            if(dir == "SHORT" && MathAbs(price - wkL) <= buf) return true;
            if(dir == "LONG"  && MathAbs(price - wkH) <= buf) return true;
        }
    }

    // Monthly H/L (12 months)
    {
        double mH[], mL[];
        int n = MathMin(12, (int)iBars(_Symbol, PERIOD_MN1));
        if(n > 0 &&
           CopyHigh(_Symbol, PERIOD_MN1, 0, n, mH) == n &&
           CopyLow (_Symbol, PERIOD_MN1, 0, n, mL) == n)
        {
            double mnH = mH[ArrayMaximum(mH, 0, WHOLE_ARRAY)];
            double mnL = mL[ArrayMinimum(mL, 0, WHOLE_ARRAY)];
            if(dir == "SHORT" && MathAbs(price - mnL) <= buf) return true;
            if(dir == "LONG"  && MathAbs(price - mnH) <= buf) return true;
        }
    }

    // All-time H/L (520 weekly bars ≈ 10 years)
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

    return false;
}

//+------------------------------------------------------------------+
//| Risk-based lot sizing                                           |
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

    double lot     = riskAmt / (slDist * (tickVal / tickSize));
    double maxLot  = MathMin(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX), InpMaxLots);
    double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

    lot = MathMax(minLot, MathMin(maxLot, lot));
    if(lotStep > 0) lot = MathRound(lot / lotStep) * lotStep;
    return lot;
}

//+------------------------------------------------------------------+
//| Alert and Comment summary — all key levels in one block         |
//+------------------------------------------------------------------+
string BuildSummary(
    string dir,
    double entry, double sl, double tp, double rr,
    double peakPx, double minorPx, double pbPx, double midpoint,
    double lots)
{
    string session  = GetCurrentSessionName();
    double pipVal   = ((_Digits == 5 || _Digits == 3) ? _Point * 10.0 : _Point);

    // X% move: from base to peak
    double xMoveDist = MathAbs(peakPx - minorPx);
    // Rough X% relative to entry for display
    double xPctDisp  = (entry > 0) ? xMoveDist / entry * 100.0 : 0;

    string peakLabel  = (dir == "SHORT") ? "Peak HIGH" : "Peak LOW (trough)";
    string minorLabel = (dir == "SHORT") ? "Minor LOW" : "Minor HIGH";

    string s = "";
    s += "═══ MARCI SILFRAIN — MEASURED MOVE v1.02 ═══\n";
    s += StringFormat("Timezone         : %s (GMT%+d)\n",   session, InpGMTOffset);
    s += StringFormat("Instrument       : %s\n",             _Symbol);
    s += StringFormat("Short or Long    : %s\n",             dir);
    s += StringFormat("Current Price    : %s\n",             DoubleToString(entry,    _Digits));
    s += StringFormat("Take Profit Price: %s\n",             DoubleToString(tp,       _Digits));
    s += StringFormat("Stop Loss Price  : %s\n",             DoubleToString(sl,       _Digits));
    s += StringFormat("Risk : Reward    : 1:%.2f\n",         rr);
    s += StringFormat("Lot Size         : %.2f\n",           lots);
    s += "\n";
    s += StringFormat("x%% Move (%.2f%%)  : %s at %s\n",
                       xPctDisp,
                       (dir == "SHORT") ? "UP impulse" : "DOWN impulse",
                       DoubleToString(peakPx, _Digits));
    s += StringFormat("%-17s: %s\n", peakLabel,             DoubleToString(peakPx,   _Digits));
    s += StringFormat("%-17s: %s\n", minorLabel,            DoubleToString(minorPx,  _Digits));
    s += StringFormat("Midpoint Price   : %s\n",             DoubleToString(midpoint, _Digits));
    s += StringFormat("Pullback Peak    : %s\n",             DoubleToString(pbPx,     _Digits));
    return s;
}

//+------------------------------------------------------------------+
//| Chart drawing — RZY structure + order levels                    |
//+------------------------------------------------------------------+

// Bulk-delete all objects whose name starts with prefix
void DeleteObjects(string prefix)
{
    for(int i = ObjectsTotal(0) - 1; i >= 0; i--)
    {
        string name = ObjectName(0, i);
        if(StringFind(name, prefix) == 0) ObjectDelete(0, name);
    }
}

// Filled rectangle — used for the X% peak highlight (40% opacity)
void DrawZone(string name, datetime t1, double price1,
              datetime t2, double price2, color clr)
{
    if(!InpDrawObjects) return;
    if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, price1, t2, price2);
    ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
    ObjectSetInteger(0, name, OBJPROP_FILL,       true);
    ObjectSetInteger(0, name, OBJPROP_BACK,       true);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

// Bounded horizontal line from t1 to t2 (OBJ_TREND, no rays).
// t2 is set far in the future at draw time; OnTradeTransaction trims it to
// the actual close bar when the trade exits.
void DrawHLine(string name, datetime t1, datetime t2, double price,
               color clr, int width, ENUM_LINE_STYLE style)
{
    if(!InpDrawObjects) return;
    if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_TREND, 0, t1, price, t2, price);
    ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
    ObjectSetInteger(0, name, OBJPROP_WIDTH,      width);
    ObjectSetInteger(0, name, OBJPROP_STYLE,      style);
    ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT,  false);
    ObjectSetInteger(0, name, OBJPROP_RAY_LEFT,   false);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
    ObjectSetString (0, name, OBJPROP_TOOLTIP,    name + ": " + DoubleToString(price, _Digits));
}

// Arrow marker at a single bar/price (OBJ_ARROW_UP or OBJ_ARROW_DOWN)
void DrawArrow(string name, datetime t, double price, bool pointUp, color clr, int width)
{
    if(!InpDrawObjects) return;
    if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
    ENUM_OBJECT arrowType = pointUp ? OBJ_ARROW_UP : OBJ_ARROW_DOWN;
    ObjectCreate(0, name, arrowType, 0, t, price);
    ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
    ObjectSetInteger(0, name, OBJPROP_WIDTH,      width);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

// Text label at a specific bar/price
void DrawLabel(string name, datetime t, double price, string text, color clr)
{
    if(!InpDrawObjects) return;
    if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_TEXT, 0, t, price);
    ObjectSetString (0, name, OBJPROP_TEXT,       text);
    ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
    ObjectSetInteger(0, name, OBJPROP_FONTSIZE,   8);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

// Draw all RZY chart objects for a confirmed setup.
//   xBar          — peak (SHORT) or trough (LONG) bar index
//   xLow/xHigh    — XZone rectangle price range
//   priorBodBar   — bar of the prior body low (SHORT) / body high (LONG) — X% base
//   priorBodPx    — price of that body extreme — dotted white reference line
//   minorBarIdx   — bar of the minor low (SHORT) / minor high (LONG) — white up/down arrow
//   pbBarIdx      — bar of the pullback peak (SHORT) / trough (LONG) — white down/up arrow
//   minorPx       — exhaustion level (entry zone floor / TP reference)
//   pbPx          — effective pullback level (entry zone ceiling / SL reference)
void DrawRZYSetup(
    int    xBar,         double xLow,       double xHigh,
    int    priorBodBar,  double priorBodPx,
    int    minorBarIdx,  int    pbBarIdx,
    double minorPx,      double pbPx,
    double entry,        double sl,         double tp,
    double rr,           string direction)
{
    if(!InpDrawObjects) return;

    g_drawCount++;
    g_activeDrawCount = g_drawCount;
    string sfx = IntegerToString(g_drawCount);

    // t1 = entry bar time; t2 = far future (trimmed to close bar by OnTradeTransaction)
    datetime t1 = iTime(_Symbol, PERIOD_CURRENT, 0);
    datetime t2 = t1 + (datetime)(86400 * 3650);

    // Arrow offset: 3 pips below lows / above highs so arrows don't overlap wicks
    double pVal   = ((_Digits == 5 || _Digits == 3) ? _Point * 10.0 : _Point);
    double offset = pVal * 3;
    bool   isShort = (direction == "SHORT");

    // ── X% peak/trough zone ─────────────────────────────────────────
    datetime tLeft  = iTime(_Symbol, PERIOD_CURRENT, xBar + 1);
    datetime tRight = iTime(_Symbol, PERIOD_CURRENT, xBar);
    DrawZone("RZY_XZone_" + sfx, tLeft, xLow, tRight, xHigh, InpXMoveColor);

    // ── X% base candle marker ────────────────────────────────────────
    // White dotted reference line at the prior body low/high (base of X% move)
    DrawHLine("RZY_BaseLine_" + sfx, t1, t2, priorBodPx, clrWhite, 1, STYLE_DOT);

    // White arrow at the base candle:
    //   SHORT: prior body LOW → up arrow below the bar
    //   LONG:  prior body HIGH → down arrow above the bar
    datetime tBase = iTime(_Symbol, PERIOD_CURRENT, priorBodBar);
    double arrowBase = isShort ? iLow (_Symbol, PERIOD_CURRENT, priorBodBar) - offset
                                : iHigh(_Symbol, PERIOD_CURRENT, priorBodBar) + offset;
    DrawArrow("RZY_BaseMark_" + sfx, tBase, arrowBase, isShort, clrWhite, 2);

    // ── Minor low/high candle marker ─────────────────────────────────
    // White arrow: SHORT → up arrow below bar;  LONG → down arrow above bar
    datetime tMinor = iTime(_Symbol, PERIOD_CURRENT, minorBarIdx);
    double arrowMinor = isShort ? iLow (_Symbol, PERIOD_CURRENT, minorBarIdx) - offset
                                 : iHigh(_Symbol, PERIOD_CURRENT, minorBarIdx) + offset;
    DrawArrow("RZY_MinorMark_" + sfx, tMinor, arrowMinor, isShort, clrWhite, 2);

    // ── Pullback peak/trough candle marker ───────────────────────────
    // White arrow: SHORT → down arrow above bar;  LONG → up arrow below bar
    datetime tPB = iTime(_Symbol, PERIOD_CURRENT, pbBarIdx);
    double arrowPB = isShort ? iHigh(_Symbol, PERIOD_CURRENT, pbBarIdx) + offset
                              : iLow (_Symbol, PERIOD_CURRENT, pbBarIdx) - offset;
    DrawArrow("RZY_PBMark_" + sfx, tPB, arrowPB, !isShort, clrWhite, 2);

    // ── Structure levels (bounded, trimmed on close) ─────────────────
    DrawHLine("RZY_Minor_"  + sfx, t1, t2, minorPx, InpMinorColor, 1, STYLE_DOT);
    DrawHLine("RZY_PBPeak_" + sfx, t1, t2, pbPx,    InpPBColor,    1, STYLE_DOT);

    // ── Order levels (bounded, trimmed on close) ─────────────────────
    DrawHLine("RZY_Entry_" + sfx, t1, t2, entry, clrDodgerBlue, 2, STYLE_SOLID);
    DrawHLine("RZY_SL_"    + sfx, t1, t2, sl,    clrRed,        1, STYLE_DASH);
    DrawHLine("RZY_TP_"    + sfx, t1, t2, tp,    clrLime,       1, STYLE_DASH);

    // ── Label ────────────────────────────────────────────────────────
    color lblClr = isShort ? clrOrange : clrLimeGreen;
    DrawLabel("RZY_Lbl_" + sfx, t1, entry,
              StringFormat(" %s#%d  SL:%.2f  TP:%.2f  RR:1:%.1f", direction, g_drawCount, sl, tp, rr),
              lblClr);
}
