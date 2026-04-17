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
//|    · Gap guard — skips bar if open outside prior bar range      |
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
//|    · Rule 5: Momentum confirmation toward minor point           |
//|    · Rule 6: Entry zone between minor point and pullback peak   |
//|    · Rule 7: Key level + Big Move Cooldown filters (opt)       |
//|    · Rule 8: ICT session filter (Asian/London/NY AM + pre-mkt) |
//|    · Rule 9: Post-TP cooldown (20 min if big move follows TP)  |
//|    · Detailed alert output with all key price levels            |
//+------------------------------------------------------------------+
#property copyright "Marci Silfrain Strategy EA"
#property version   "1.02"
#property description "Measured Move Trend Strategy — Little RZY Detector v1.02"
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
input double InpBigXMovePct       = 0.5;    // X% — impulse move size that defines the peak
                                            //   Forex: 1-2%  |  Indices: 2-4%  |  Crypto: 5%+
input double InpYMaxPct           = 600.0;  // Y% — max distance (minor pt → peak) as % of X move
                                            //   Hard cap at runtime: 90%. Set high to effectively disable.
input double InpTPMultiplier      = 0.5;    // TP = this% × (midpoint → minor point distance)

input group "=== Pullback Strength Gates ==="
input double InpMinImpulsePips    = 5.0;    // Minimum impulse size (pips) — filters noise
input double InpMinPullbackPct    = 2.0;    // Min pullback retracement % of peak→minor distance
input double InpMaxPullbackPct    = 70.0;   // Max pullback retracement % (deeper = weakening)

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

//── Globals ───────────────────────────────────────────────────────
CTrade   Trade;
datetime g_lastTPExitTime  = 0;
double   g_lastTPExitPrice = 0.0;

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
    Print("Marci MM v1.02 ready  |  ", _Symbol, "  ",
          EnumToString(Period()), "  |  ", mode);
    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Cleanup                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
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
//| Rule 9 — detect TP exits via trade transaction stream           |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest     &request,
                        const MqlTradeResult      &result)
{
    if(!InpUsePostTPCooldown)           return;
    if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;

    if(HistoryDealSelect(trans.deal))
    {
        ulong magic  = (ulong)HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
        ENUM_DEAL_REASON why = (ENUM_DEAL_REASON)HistoryDealGetInteger(trans.deal, DEAL_REASON);
        if(magic == (ulong)InpMagicNumber && why == DEAL_REASON_TP)
        {
            g_lastTPExitTime  = (datetime)HistoryDealGetInteger(trans.deal, DEAL_TIME);
            g_lastTPExitPrice = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
        }
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

    //── Pre-check 1: Gap guard ──────────────────────────────────────
    if(opens[0] > highs[1] || opens[0] < lows[1]) return;

    //── Pre-check 2: ICT session filter (Rule 8) ───────────────────
    if(!IsInTradingSession()) return;

    //── Pre-check 3: Post-TP cooldown (Rule 9) ─────────────────────
    if(IsPostTPCooldown(closes)) return;

    double pipVal = ((_Digits == 5 || _Digits == 3) ? _Point * 10.0 : _Point);
    double yMaxPct = MathMin(InpYMaxPct, 90.0);  // hard cap Rule 2

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

        if(FindShortSetup(highs, lows, InpCandleCount, InpBigXMovePct,
                          yMaxPct, InpMinPullbackPct, InpMaxPullbackPct,
                          pipVal, InpMinImpulsePips,
                          peakBar, peakPx, minorBar, minorPx, pbBar, pbPx)
           && ConfirmShortMomentum(closes, pbBar))
        {
            double curPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);

            // Rule 6: price must be inside the entry zone
            bool inZone   = (curPrice > minorPx && curPrice < pbPx);
            bool filtered = (InpUseBigMoveCooldown && IsBigMoveCooldown("SHORT", opens, closes, InpCandleCount))
                         || (InpUseKeyLevelFilter  && IsNearKeyLevel(curPrice, "SHORT"));

            if(inZone && !filtered)
            {
                // Rule 3: calculate TP and SL
                double midpoint     = (peakPx + minorPx) / 2.0;
                double distMidMinor = midpoint - minorPx;
                double tpPx         = minorPx - distMidMinor * (InpTPMultiplier / 100.0);
                double slOpt1       = midpoint + pipVal * 2.0;
                double slOpt2       = pbPx     + pipVal * 2.0;
                double slPx         = MathMin(slOpt1, slOpt2);

                double risk   = slPx    - curPrice;
                double reward = curPrice - tpPx;
                double rr     = (risk > 0 && reward > 0) ? reward / risk : 0;

                if(rr >= InpMinRR)
                {
                    double lots    = CalcLots(curPrice, slPx);
                    string summary = BuildSummary("SHORT", curPrice, slPx, tpPx, rr,
                                                  peakPx, minorPx, pbPx, midpoint, lots);
                    DrawLevels(curPrice, slPx, tpPx, "SHORT");
                    Comment(summary);

                    if(InpManualConfirm)
                        Alert("MARCI EA  >>>  SHORT SETUP on ", _Symbol, "\n\n", summary);
                    else if(lots > 0)
                        if(!Trade.Sell(lots, _Symbol, curPrice, slPx, tpPx, "Marci_MM_SHORT"))
                            Print("Order failed: ", Trade.ResultRetcodeDescription());

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

        if(FindLongSetup(highs, lows, InpCandleCount, InpBigXMovePct,
                         yMaxPct, InpMinPullbackPct, InpMaxPullbackPct,
                         pipVal, InpMinImpulsePips,
                         troughBar, troughPx, minorBar, minorPx, pbBar, pbPx))
        {
            if(ConfirmLongMomentum(closes, pbBar))
            {
                double curPrice = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

                if(curPrice < minorPx && curPrice > pbPx)
                {
                    if(InpUseBigMoveCooldown && IsBigMoveCooldown("LONG", opens, closes, InpCandleCount))
                        return;
                    if(InpUseKeyLevelFilter  && IsNearKeyLevel(curPrice, "LONG"))
                        return;

                    double midpoint     = (troughPx + minorPx) / 2.0;
                    double distMidMinor = minorPx - midpoint;             // > 0 for LONG
                    double tpPx         = minorPx + distMidMinor * (InpTPMultiplier / 100.0);
                    double slOpt1       = midpoint  - pipVal * 2.0;
                    double slOpt2       = pbPx      - pipVal * 2.0;
                    double slPx         = MathMax(slOpt1, slOpt2);        // tighter (higher) stop

                    double risk   = curPrice - slPx;
                    double reward = tpPx     - curPrice;
                    if(risk <= 0 || reward <= 0) return;
                    double rr = reward / risk;
                    if(rr < InpMinRR) return;

                    double lots    = CalcLots(curPrice, slPx);
                    string summary = BuildSummary("LONG", curPrice, slPx, tpPx, rr,
                                                  troughPx, minorPx, pbPx, midpoint, lots);

                    DrawLevels(curPrice, slPx, tpPx, "LONG");
                    Comment(summary);

                    if(InpManualConfirm)
                        Alert("MARCI EA  >>>  LONG SETUP on ", _Symbol, "\n\n", summary);
                    else
                    {
                        if(lots > 0)
                            if(!Trade.Buy(lots, _Symbol, curPrice, slPx, tpPx, "Marci_MM_LONG"))
                                Print("Order failed: ", Trade.ResultRetcodeDescription());
                    }
                }
            }
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
    int bars, double xPct, double yMaxPct,
    double minPbPct, double maxPbPct,
    double pipVal,   double minImpPips,
    int &peakBar, double &peakPx,
    int &minorBar, double &minorPx,
    int &pbBar, double &pbPx)
{
    //── Step 1: Highest high in lookback (PEAK) ─────────────────────
    peakBar = ArrayMaximum(highs, 0, bars);
    if(peakBar < 4) return false;   // need enough bars after peak
    peakPx  = highs[peakBar];

    //── Step 2: Validate X% UP move ─────────────────────────────────
    // Prior low = lowest low in bars OLDER than the peak
    double priorLow = DBL_MAX;
    for(int i = peakBar; i < bars; i++)
        if(lows[i] < priorLow) priorLow = lows[i];
    if(priorLow == DBL_MAX || priorLow == 0) return false;

    double xMovePrice = peakPx - priorLow;
    if(xMovePrice <= 0) return false;
    if(xMovePrice / priorLow * 100.0 < xPct) return false;

    //── Step 3: PULLBACK PEAK — highest high in bars after peak ─────
    // Search all bars more recent than peak (indices 0..peakBar-1)
    pbBar = ArrayMaximum(highs, 0, peakBar);
    if(pbBar < 0) return false;
    pbPx  = highs[pbBar];

    // Must be a LOWER high than the original peak
    if(pbPx >= peakPx) return false;
    // Need at least 2 bars between pb peak and current bar for confirmation
    if(pbBar < 2) return false;

    //── Step 4: MINOR LOW — lowest low strictly BETWEEN peak & pb ───
    // In AsSeries: the window is indices (pbBar+1) to (peakBar-1)
    // That window = bars that are more recent than peak but older than pb peak
    int windowSize = peakBar - pbBar - 1;
    if(windowSize < 1) return false;  // peak and pb peak are adjacent — no room

    minorBar = ArrayMinimum(lows, pbBar + 1, windowSize);
    if(minorBar < 0) return false;
    minorPx  = lows[minorBar];

    // Minor low must be genuinely below the pullback peak
    if(minorPx >= pbPx) return false;

    //── Step 5: Y% gate — minor low must be "minor" ─────────────────
    // The drop from peak to minor low must not exceed Y% of the X move.
    // If it does, the move has reversed enough to be a new trend — not minor.
    double minorDist = peakPx - minorPx;
    if(minorDist > (yMaxPct / 100.0) * xMovePrice) return false;
    if(minorDist <= 0) return false;

    //── Step 6: Pullback depth gate ─────────────────────────────────
    // How far did price retrace from minor low back up to pullback peak?
    // (pbPx - minorPx) / (peakPx - minorPx) × 100 = retracement %
    double pbDepthPct = (pbPx - minorPx) / (peakPx - minorPx) * 100.0;
    if(pbDepthPct < minPbPct || pbDepthPct > maxPbPct) return false;

    //── Step 7: Minimum impulse size (peak → minor low, in pips) ────
    double impulsePips = (pipVal > 0) ? minorDist / pipVal : 0;
    if(impulsePips < minImpPips) return false;

    return true;
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
    int bars, double xPct, double yMaxPct,
    double minPbPct, double maxPbPct,
    double pipVal,   double minImpPips,
    int &troughBar, double &troughPx,
    int &minorBar,  double &minorPx,
    int &pbBar,     double &pbPx)
{
    //── Step 1: Lowest low in lookback (TROUGH) ─────────────────────
    troughBar = ArrayMinimum(lows, 0, bars);
    if(troughBar < 4) return false;
    troughPx  = lows[troughBar];

    //── Step 2: Validate X% DOWN move ───────────────────────────────
    double priorHigh = 0;
    for(int i = troughBar; i < bars; i++)
        if(highs[i] > priorHigh) priorHigh = highs[i];
    if(priorHigh == 0 || troughPx == 0) return false;

    double xMovePrice = priorHigh - troughPx;
    if(xMovePrice <= 0) return false;
    if(xMovePrice / priorHigh * 100.0 < xPct) return false;

    //── Step 3: PULLBACK TROUGH — lowest low in bars after trough ───
    pbBar = ArrayMinimum(lows, 0, troughBar);
    if(pbBar < 0) return false;
    pbPx  = lows[pbBar];

    // Must be a HIGHER low than the original trough
    if(pbPx <= troughPx) return false;
    if(pbBar < 2) return false;

    //── Step 4: MINOR HIGH — highest high strictly BETWEEN trough & pb
    int windowSize = troughBar - pbBar - 1;
    if(windowSize < 1) return false;

    minorBar = ArrayMaximum(highs, pbBar + 1, windowSize);
    if(minorBar < 0) return false;
    minorPx  = highs[minorBar];

    // Minor high must be genuinely above the pullback trough
    if(minorPx <= pbPx) return false;

    //── Step 5: Y% gate — minor high must be "minor" ────────────────
    double minorDist = minorPx - troughPx;
    if(minorDist > (yMaxPct / 100.0) * xMovePrice) return false;
    if(minorDist <= 0) return false;

    //── Step 6: Pullback depth gate ─────────────────────────────────
    double pbDepthPct = (minorPx - pbPx) / (minorPx - troughPx) * 100.0;
    if(pbDepthPct < minPbPct || pbDepthPct > maxPbPct) return false;

    //── Step 7: Minimum impulse size (trough → minor high, in pips) ─
    double impulsePips = (pipVal > 0) ? minorDist / pipVal : 0;
    if(impulsePips < minImpPips) return false;

    return true;
}

//+------------------------------------------------------------------+
//| Rule 5: Confirm SHORT momentum from pullback peak               |
//| Requires at least 2 closed bars after the pullback peak         |
//| and declining closes since then                                 |
//+------------------------------------------------------------------+
bool ConfirmShortMomentum(const double &closes[], int pbBar)
{
    if(pbBar < 2) return false;
    // Most recent 2 bars closing lower; current close below pb close level
    return (closes[0] < closes[1] && closes[1] <= closes[pbBar]);
}

//+------------------------------------------------------------------+
//| Rule 5: Confirm LONG momentum from pullback trough              |
//+------------------------------------------------------------------+
bool ConfirmLongMomentum(const double &closes[], int pbBar)
{
    if(pbBar < 2) return false;
    return (closes[0] > closes[1] && closes[1] >= closes[pbBar]);
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
//| Draw Entry / SL / TP horizontal lines on chart                  |
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
