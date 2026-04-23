# Credential Vault — Dev-RZY

Credentials are stored in **Windows Credential Manager** (built into Windows — no extra software).  
The Python bots read them via the `keyring` library instead of plaintext `.env` files.

This means `.env` holds only non-sensitive config (symbol, timeframe, risk settings).  
Passwords and login tokens never touch disk in plaintext.

---

## 1. Install keyring

```bash
pip install keyring
```

Add to `requirements.txt`:
```
keyring
```

---

## 2. Store credentials (one-time setup)

Run these commands once in a terminal. Windows will store them in Credential Manager, protected by your Windows login.

### MetaQuotes Demo
```bash
python -c "import keyring; keyring.set_password('mt5', 'metaquotes_login',    '105714861')"
python -c "import keyring; keyring.set_password('mt5', 'metaquotes_password',  'YOUR_PASSWORD')"
python -c "import keyring; keyring.set_password('mt5', 'metaquotes_server',    'MetaQuotes-Demo')"
```

### BlackBull Demo
```bash
python -c "import keyring; keyring.set_password('mt5', 'blackbull_login',    'YOUR_LOGIN')"
python -c "import keyring; keyring.set_password('mt5', 'blackbull_password',  'YOUR_PASSWORD')"
python -c "import keyring; keyring.set_password('mt5', 'blackbull_server',    'BlackBullMarkets-Demo')"
```

### Anthropic API Key
```bash
python -c "import keyring; keyring.set_password('anthropic', 'api_key', 'sk-ant-api03-...')"
```

> **Tip:** Open **Windows Credential Manager** (Start → search "Credential Manager" → Windows Credentials tab)  
> to view, edit, or delete any stored entry via the GUI.

---

## 3. Update connection.py to read from keyring

Replace the credential block in `bot/connection.py`:

```python
import keyring

def connect():
    path     = os.getenv("MT5_PATH")
    profile  = os.getenv("KEYRING_PROFILE")   # e.g. "metaquotes" or "blackbull"

    # Pull from keyring if a profile is set, fall back to .env
    if profile:
        login    = keyring.get_password("mt5", f"{profile}_login")
        password = keyring.get_password("mt5", f"{profile}_password")
        server   = keyring.get_password("mt5", f"{profile}_server")
    else:
        login    = os.getenv("MT5_LOGIN")
        password = os.getenv("MT5_PASSWORD")
        server   = os.getenv("MT5_SERVER")
    ...
```

Set `KEYRING_PROFILE` per broker profile in `.env`:

```bash
PROFILE_METAQUOTES_KEYRING_PROFILE=metaquotes
PROFILE_BLACKBULL_SPOT_KEYRING_PROFILE=blackbull
PROFILE_BLACKBULL_FUTURES_KEYRING_PROFILE=blackbull
```

---

## 4. .env after migration

Once credentials are in the vault, `.env` becomes safe to version-control (still add to `.gitignore` as a habit):

```bash
# No passwords here — stored in Windows Credential Manager
PROFILE_METAQUOTES_SYMBOL=XAUUSD
PROFILE_METAQUOTES_MT5_PATH=C:/MT5_MetaQuotes/terminal64.exe
PROFILE_METAQUOTES_KEYRING_PROFILE=metaquotes

PROFILE_BLACKBULL_SPOT_SYMBOL=XAUUSDp
PROFILE_BLACKBULL_SPOT_MT5_PATH=C:/MT5_BlackBull/terminal64.exe
PROFILE_BLACKBULL_SPOT_KEYRING_PROFILE=blackbull
```

---

## 5. Verify stored credentials

```bash
python -c "
import keyring
for key in ['metaquotes_login', 'metaquotes_server', 'blackbull_login', 'blackbull_server']:
    val = keyring.get_password('mt5', key)
    print(f'{key:30s}: {\"SET\" if val else \"NOT SET\"}')"
```

---

## 6. Delete a credential

```bash
python -c "import keyring; keyring.delete_password('mt5', 'metaquotes_password')"
```

Or use the Windows Credential Manager GUI → select the entry → **Remove**.

---

## Credential inventory

| Service     | Key name               | What it stores            |
|-------------|------------------------|---------------------------|
| `mt5`       | `metaquotes_login`     | MetaQuotes account number |
| `mt5`       | `metaquotes_password`  | MetaQuotes password       |
| `mt5`       | `metaquotes_server`    | MetaQuotes server name    |
| `mt5`       | `blackbull_login`      | BlackBull account number  |
| `mt5`       | `blackbull_password`   | BlackBull password        |
| `mt5`       | `blackbull_server`     | BlackBull server name     |
| `anthropic` | `api_key`              | Anthropic API key         |

---

## Why not HashiCorp Vault?

HashiCorp Vault is the industry standard for team/production secrets but requires running a server process, token management, and policy configuration. Windows Credential Manager achieves the same protection for a single-user local setup with zero infrastructure.

If this project ever moves to a cloud VM or shared server, migrate to Vault or AWS Secrets Manager at that point.
