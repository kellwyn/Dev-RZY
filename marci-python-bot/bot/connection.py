"""
MT5 connection management.
Supports multiple parallel MT5 terminals via MT5_PATH in .env.
If MT5 is already open and logged in, initialize() with no args will attach to it.
Credentials in .env are only needed if starting a fresh session.
"""

import os
import MetaTrader5 as mt5


def connect():
    login    = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server   = os.getenv("MT5_SERVER")
    path     = os.getenv("MT5_PATH")

    kwargs = {}
    if path:
        kwargs["path"] = path
    if login and password and server:
        kwargs.update(login=int(login), password=password, server=server)

    ok = mt5.initialize(**kwargs) if kwargs else mt5.initialize()

    if not ok:
        raise RuntimeError(f"MT5 connection failed: {mt5.last_error()}")

    info = mt5.account_info()
    if info is None:
        raise RuntimeError(f"Could not retrieve account info: {mt5.last_error()}")

    print("\n  Connected to MetaTrader 5")
    print(f"  Account  : {info.name}  (#{info.login})")
    print(f"  Server   : {info.server}")
    print(f"  Balance  : {info.balance:,.2f} {info.currency}")
    print(f"  Leverage : 1:{info.leverage}")


def disconnect():
    mt5.shutdown()
    print("\n  Disconnected from MT5.")
