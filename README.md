# PolyBTC BTC 5-Minute Polymarket Bot

> [!WARNING]
> ## Archived Implementation
>
> This repository is preserved as a historical version of **PolyBTC**.
>
> It is not the current production implementation and is not intended for live deployment.
>
> This version still relies on the older **Binance-based BTC reference-price logic**. The Polymarket system was later migrated to the **Chainlink BTC reference stream** .
>
> Because of that migration, the pricing, strike, momentum, settlement, and strategy behavior in this repository no longer match the live system.
>
> The code is intentionally left unchanged for project preservation. The current production implementation is not published in this repository.

A Python trading bot for BTC 5-minute up/down prediction markets on Polymarket.

The bot watches active BTC 5-minute markets, reads BTC price data and Polymarket order books, calculates a directional edge, and can run in either **paper mode** or **live mode**.

> **Risk warning:** This project is experimental trading software. It can lose money. Nothing in this repository is financial advice, and no strategy setting guarantees profit.

---

## What the Bot Does

PolyBTC is designed for short-duration BTC prediction markets where each market resolves based on whether BTC closes above or below a strike price during a 5-minute interval.

At a high level, the bot:

1. Finds the current BTC 5-minute Polymarket market.
2. Reads BTC price and strike data.
3. Reads YES/NO order book bid/ask prices.
4. Estimates the probability that BTC finishes above or below the strike.
5. Compares the model probability to market prices.
6. Enters a position only when the estimated edge is large enough.
7. Manages open positions with cashout, stop-loss, time-exit, and profit-protection logic.
8. Logs decisions, trades, and state locally.
9. Optionally sends Discord alerts.
10. Can run continuously as a systemd service on a Linux VM.

---

## Supported Modes

### Paper Mode

Paper mode simulates trades locally.

It does **not** use a real wallet, private key, live CLOB credentials, USDC balance, or Polymarket funds. It writes simulated decisions and trades to local CSV and JSON files.

Paper mode is useful for:

- Testing strategy logic.
- Checking whether the bot can find markets.
- Reviewing entry/exit behavior.
- Running dry-run experiments without risking funds.

Current paper mode does **not** maintain a fake cash wallet. Position sizing is controlled mainly by:

```env
BTC_5M_ORDER_SIZE=5
```

This means the bot simulates 5 shares per paper trade.

### Live Mode

Live mode can place real orders on Polymarket.

Live mode should only be used after the configuration, wallet, CLOB credentials, and risk limits are verified. The bot requires multiple safety flags before it will place real orders:

```env
BTC_5M_MODE=live
BTC_5M_LIVE_ARMED=true
BTC_5M_ALLOW_REAL_ORDERS=true
```

If any of these are not set correctly, live orders are blocked.

---

## Main Files

```text
btc_5m_hybrid_bot.py          Main bot loop, execution, state, logging, live order logic
btc_5m_hybrid_strategy.py     Strategy and signal decision logic
summarize_run.py              Local run-analysis / summary script
daily_discord_pnl_report.py   Optional daily Discord reporting script
.env.example                  Safe example configuration
README.md                     Project documentation
```

Runtime files created by the bot:

```text
btc_5m_state.json             Current bot state
btc_5m_decisions.csv          Every market decision / skip reason
btc_5m_trades.csv             Entries, exits, simulated trades, live trades
```

These runtime files should generally **not** be committed to GitHub.

---

## Requirements

Recommended:

- Python 3.10+
- Internet access
- Polymarket public CLOB access
- Binance public API access
- Optional: Polymarket CLOB credentials for live mode
- Optional: Discord webhook for alerts

Python packages:

```text
python-dotenv
requests
py-clob-client
py-clob-client-v2
```

Even in paper mode, `py-clob-client-v2` should be installed because the bot imports it at startup.

---

## Installation

### Linux / VM

```bash
git clone https://github.com/RetroMrii/polyBTC.git
cd polyBTC

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
pip install python-dotenv requests py-clob-client py-clob-client-v2
```

### Windows PowerShell

```powershell
git clone https://github.com/RetroMrii/polyBTC.git
cd polyBTC

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip setuptools wheel
pip install python-dotenv requests py-clob-client py-clob-client-v2
```

---

## Configuration

Create a local `.env` file from the example:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Then edit `.env`.

---

## Safe Paper Configuration

For paper mode, use:

```env
BTC_5M_MODE=paper
BTC_5M_LIVE_ARMED=false
BTC_5M_ALLOW_REAL_ORDERS=false

CLOB_API_URL=https://clob.polymarket.com

BTC_5M_LOOP_SECONDS=5

BTC_5M_ORDER_SIZE=5
BTC_5M_MIN_EDGE=0.10
BTC_5M_MAX_SPREAD=0.08

BTC_5M_MIN_DISTANCE_FROM_STRIKE=0.00015
BTC_5M_LATE_DISTANCE_SECONDS=150
BTC_5M_LATE_MIN_DISTANCE_FROM_STRIKE=0.00015
BTC_5M_REQUIRE_MOMENTUM_CONFIRMATION=false

BTC_5M_MAX_SECONDS_TO_EXPIRY=270
BTC_5M_MIN_SECONDS_TO_EXPIRY=125
BTC_5M_NO_TRADE_LAST_SECONDS=125

BTC_5M_ENABLE_CASHOUT=true
BTC_5M_MIN_NET_PROFIT=0.10

BTC_5M_USE_DYNAMIC_FEE_BUFFER=true
BTC_5M_TAKER_FEE_RATE=0.07
BTC_5M_EXTRA_FEE_BUFFER=0.01

BTC_5M_ENABLE_STOPLOSS=true
BTC_5M_MAX_NET_LOSS=0.50
BTC_5M_HARD_MAX_NET_LOSS=0.50

BTC_5M_ENABLE_PROFIT_PROTECTION=true
BTC_5M_ENABLE_TRAILING_PROFIT=false

BTC_5M_DISCORD_ALERTS=false
BTC_5M_DISCORD_WEBHOOK_URL=
```

Paper mode does not require:

```env
PK=
CLOB_API_KEY=
CLOB_SECRET=
CLOB_PASS_PHRASE=
POLYMARKET_FUNDER=
POLYMARKET_SIGNATURE_TYPE=
CHAIN_ID=
```

---

## Live Configuration

Live mode requires a real Polymarket wallet and CLOB credentials.

Example live safety flags:

```env
BTC_5M_MODE=live
BTC_5M_LIVE_ARMED=true
BTC_5M_ALLOW_REAL_ORDERS=true
```

Required live credentials:

```env
PK=REPLACE_ME
CLOB_API_KEY=REPLACE_ME
CLOB_SECRET=REPLACE_ME
CLOB_PASS_PHRASE=REPLACE_ME
POLYMARKET_FUNDER=REPLACE_ME
POLYMARKET_SIGNATURE_TYPE=1
CHAIN_ID=137
```

Live sizing and safety settings:

```env
BTC_5M_LIVE_ORDER_SIZE=5
BTC_5M_MIN_LIVE_SHARE_SIZE=5
BTC_5M_MIN_LIVE_ORDER_VALUE=2.50
BTC_5M_MAX_LIVE_ORDER_VALUE=7.00
BTC_5M_MAX_DAILY_LIVE_LOSS=10.00
```

Do not expose `.env` publicly. It may contain private keys, API credentials, and webhook URLs.

---

## Running the Bot

### in Paper Mode

```bash
source .venv/bin/activate
python btc_5m_hybrid_bot.py
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python .\btc_5m_hybrid_bot.py
```

Expected startup:

```text
[BTC5M] bot started in paper mode
```

### in Live Mode

Before live mode, confirm the `.env` file is correct and that you intentionally want real orders enabled.

```bash
source .venv/bin/activate
python btc_5m_hybrid_bot.py
```

Expected startup when live orders are enabled:

```text
[BTC5M] bot started in live mode
[BTC5M] LIVE MODE ARMED: real orders are enabled
```

If you do not see the live armed message, real orders should not be enabled.

---

## Run Summary

Use the summary script to inspect the bot's local results:

```bash
python summarize_run.py --all --decision-context 12 --max-trades 0
```

This can help review:

- Closed trades.
- PnL.
- Win rate.
- Skip reasons.
- Entry/exit behavior.
- Decision context around trades.

---

## Logs and State

The bot writes:

```text
btc_5m_decisions.csv
btc_5m_trades.csv
btc_5m_state.json
```

Typical checks:

```bash
tail -n 20 btc_5m_decisions.csv
tail -n 20 btc_5m_trades.csv
python3 -m json.tool btc_5m_state.json
```

For systemd logs:

```bash
journalctl -u polybtc --since "1 hour ago" --no-pager
```

---

## Running as a systemd Service

Example service:

```ini
[Unit]
Description=PolyBTC BTC5M Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_LINUX_USER
WorkingDirectory=/home/YOUR_LINUX_USER/PolyBTC
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/YOUR_LINUX_USER/PolyBTC/.venv/bin/python /home/YOUR_LINUX_USER/PolyBTC/btc_5m_hybrid_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Install:

```bash
sudo nano /etc/systemd/system/polybtc.service
sudo systemctl daemon-reload
sudo systemctl enable --now polybtc
sudo systemctl status polybtc --no-pager
```

Stop:

```bash
sudo systemctl stop polybtc
```

Restart:

```bash
sudo systemctl restart polybtc
```

---

## Discord Alerts

Discord alerts are optional.

Enable:

```env
BTC_5M_DISCORD_ALERTS=true
BTC_5M_DISCORD_WEBHOOK_URL=REPLACE_ME
```

---

## Strategy Overview

The strategy estimates whether BTC is more likely to finish above or below the market strike.

It considers:

- BTC price vs strike.
- Seconds to expiry.
- Distance from strike.
- Short-term momentum.
- YES/NO bid and ask.
- Spread.
- Estimated edge versus market price.

The bot will skip trades when:

- The market is too early.
- The market is too close to expiry.
- BTC is too close to the strike.
- Order book data is missing.
- Spread is too wide.
- Estimated edge is too small.
- Momentum confirmation fails, if enabled.
- Live daily loss lockout is active.
- There is already an open local position for that market.

---

## Risk Controls

The bot includes several risk controls:

- Minimum edge threshold.
- Max spread filter.
- Distance-from-strike filter.
- Time-to-expiry filters.
- Live daily loss limit.
- Max live order value.
- Stop-loss logic.
- Time-exit logic.
- Profit-protection logic.
- Full-exit confirmation logic.
- Post-timeout live BUY reconciliation.
- Optional startup live-state reconciliation.
- Atomic state saving, if the patched version is used.

Risk controls reduce failure modes but do not eliminate trading risk.

---

---

## Safety Checklist Before Live Mode

Before enabling live trading:

- Confirm `.env` is not `.env.example`.
- Confirm live credentials are present.
- Confirm wallet has only the funds you are willing to risk.
- Confirm `BTC_5M_LIVE_ARMED=true`.
- Confirm `BTC_5M_ALLOW_REAL_ORDERS=true`.
- Confirm `BTC_5M_MAX_LIVE_ORDER_VALUE`.
- Confirm `BTC_5M_MAX_DAILY_LIVE_LOSS`.
- Compile the bot.
- Check `btc_5m_state.json` is valid JSON.
- Start the bot and verify startup logs.
- Watch the first live trade manually.

Compile check:

```bash
python -m py_compile ./btc_5m_hybrid_bot.py
python -m py_compile ./btc_5m_hybrid_strategy.py
python -m py_compile ./summarize_run.py
python -m py_compile ./daily_discord_pnl_report.py
```

State check:

```bash
python3 -m json.tool btc_5m_state.json >/tmp/state_ok.txt && echo "state OK"
```

---

## Disclaimer

This repository is for experimental research and automation. Prediction markets and automated trading involve significant risk. You are responsible for reviewing the code, configuration, credentials, wallet permissions, and all trades before running the bot live.

No part of this project guarantees profit or protects against all market, API, infrastructure, or execution failures.
