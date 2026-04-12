"""
Manual confirmation gate + order execution.

The bot NEVER fires a trade automatically.
Every setup is presented in full — strategy checklist, price levels,
position size, risk amount — and the user types y/n before anything is sent.
"""

import MetaTrader5 as mt5

from .signals import TradeSetup

# ── Lot size calculator ───────────────────────────────────────────────────────

def calc_lot_size(symbol: str, entry: float, stop_loss: float,
                  risk_pct: float, balance: float) -> float:
    """
    Risk-based position sizing.
    Clamps result to the broker's min/max/step for the symbol.
    """
    sym = mt5.symbol_info(symbol)
    if sym is None:
        return 0.01

    risk_amount = balance * risk_pct / 100.0
    sl_distance = abs(entry - stop_loss)
    if sl_distance == 0:
        return sym.volume_min

    tick_value = sym.trade_tick_value   # USD value of one tick per lot
    tick_size  = sym.trade_tick_size    # minimum price increment

    if tick_size == 0 or tick_value == 0:
        return sym.volume_min

    # Value per full price unit per lot
    value_per_point = tick_value / tick_size

    lot = risk_amount / (sl_distance * value_per_point)

    # Clamp and snap to valid step
    lot  = max(sym.volume_min, min(sym.volume_max, lot))
    step = sym.volume_step
    if step > 0:
        lot = round(round(lot / step) * step, 8)

    return lot

# ── Order execution ───────────────────────────────────────────────────────────

def send_order(setup: TradeSetup, lots: float) -> bool:
    """Send a market order to MT5. Returns True on success."""
    tick = mt5.symbol_info_tick(setup.symbol)
    if tick is None:
        print(f"\n  ERROR: Could not get tick for {setup.symbol}")
        return False

    if setup.direction == "SHORT":
        order_type = mt5.ORDER_TYPE_SELL
        price      = tick.bid
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price      = tick.ask

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       setup.symbol,
        "volume":       lots,
        "type":         order_type,
        "price":        price,
        "sl":           setup.stop_loss,
        "tp":           setup.target,
        "deviation":    20,
        "magic":        20260412,           # EA identifier
        "comment":      "Marci_MeasuredMove",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result is None:
        print(f"\n  ORDER FAILED: {mt5.last_error()}")
        return False

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"\n  ORDER FAILED  retcode={result.retcode}  {result.comment}")
        return False

    sep = "=" * 62
    print(f"\n{sep}")
    print(f"  ORDER EXECUTED")
    print(f"  Ticket  : #{result.order}")
    print(f"  Symbol  : {setup.symbol}  [{setup.timeframe}]")
    print(f"  Type    : {setup.direction}")
    print(f"  Volume  : {lots} lots")
    print(f"  Price   : {result.price:.5f}")
    print(f"  Stop    : {setup.stop_loss:.5f}")
    print(f"  Target  : {setup.target:.5f}")
    print(sep)
    return True

# ── Manual confirmation gate ──────────────────────────────────────────────────

def confirm_and_execute(setup: TradeSetup, risk_pct: float = 1.0):
    """
    Display the full strategy checklist for this setup, ask the user to
    confirm, and only then send the order to MT5.

    Inputs:
      y  — execute the trade
      n  — skip this setup
      q  — quit the bot
    """
    account = mt5.account_info()
    if account is None:
        print("  Could not retrieve account info — skipping.")
        return

    balance  = account.balance
    currency = account.currency
    lots     = calc_lot_size(setup.symbol, setup.entry, setup.stop_loss, risk_pct, balance)
    risk_amt = balance * risk_pct / 100.0

    sep  = "=" * 62
    sep2 = "-" * 62

    print(f"\n{sep}")
    print(f"  *** MANUAL CONFIRMATION REQUIRED ***")
    print(f"  Strategy : Marci Silfrain — Measured Move Trend")
    print(f"  Signal   : {setup.signal_strength} CONFIDENCE")
    print(sep)

    print(f"\n  STRATEGY RULES VERIFIED:")
    for note in setup.setup_notes:
        print(f"    [OK] {note}")

    print(f"\n{sep2}")
    print(f"  TRADE DETAILS")
    print(sep2)
    print(f"  Symbol      : {setup.symbol}")
    print(f"  Timeframe   : {setup.timeframe}")
    print(f"  Direction   : {setup.direction}")
    print(f"  Confidence  : {setup.signal_strength}")

    print(f"\n  PRICE LEVELS")
    print(f"  Entry       : {setup.entry:.5f}")
    print(f"  Stop Loss   : {setup.stop_loss:.5f}")
    print(f"  Target      : {setup.target:.5f}")
    print(f"  Risk:Reward : 1:{setup.risk_reward}")

    print(f"\n  MEASURED MOVE BREAKDOWN")
    if setup.direction == "SHORT":
        print(f"  Swing Low   : {setup.anchor_price:.5f}  (impulse endpoint)")
        print(f"  Pullback Hi : {setup.pullback_extreme:.5f}  (trendline reference)")
    else:
        print(f"  Swing High  : {setup.anchor_price:.5f}  (impulse endpoint)")
        print(f"  Pullback Lo : {setup.pullback_extreme:.5f}  (trendline reference)")
    print(f"  Distance    : {setup.measured_distance:.5f}")
    print(f"  Projection  : {setup.target:.5f}")

    print(f"\n  BOLLINGER BAND CONTEXT")
    print(f"  Upper       : {setup.bb_upper:.5f}")
    print(f"  Middle      : {setup.bb_middle:.5f}")
    print(f"  Lower       : {setup.bb_lower:.5f}")
    print(f"  Price at    : {setup.bb_position}")

    print(f"\n  POSITION SIZING")
    print(f"  Balance     : {balance:,.2f} {currency}")
    print(f"  Risk        : {risk_pct}%  =  {risk_amt:.2f} {currency}")
    print(f"  Lot size    : {lots}")

    print(f"\n  INVALIDATION")
    print(f"  Exit / skip if price closes beyond: {setup.invalidation_price:.5f}")

    print(f"\n{sep}")

    # Prompt loop
    while True:
        try:
            ans = input("  Execute trade?  [y = yes / n = skip / q = quit bot]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return

        if ans == "y":
            print(f"\n  Executing {setup.direction} on {setup.symbol}...")
            send_order(setup, lots)
            break
        elif ans == "n":
            print("  Setup skipped.")
            break
        elif ans == "q":
            print("  Shutting down bot.")
            raise SystemExit(0)
        else:
            print("  Enter  y  n  or  q")
