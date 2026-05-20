# BTC 5-Minute Polymarket Hybrid Bot

A Python trading bot for the Polymarket **Bitcoin Up or Down 5-minute** market. The bot reads the active BTC 5-minute market, estimates directional edge, places live CLOB orders when configured, manages open positions, logs every decision/trade, and keeps local JSON state for reconciliation and PnL tracking.

> **Status:** Experimental live-trading bot. Use small size only until a statistically meaningful sample proves positive expectancy. The code includes safety controls, but it does not guarantee profitability.

---

## 1. What this bot does

The bot loops over the active Polymarket BTC 5-minute market and performs four main jobs:

1. **Market reading**
   - Finds the active BTC 5-minute Polymarket event.
   - Reads YES/NO CLOB order books.
   - Reads the current BTC 5-minute Binance candle.
   - Calculates strike, current BTC price, distance from strike, and seconds to expiry.

2. **Signal generation**
   - Uses `btc_5m_hybrid_strategy.py` to estimate the probability of BTC finishing above/below strike.
   - Compares model probability to Polymarket ask price.
   - Buys only when edge, spread, timing, distance, and momentum filters pass.

3. **Live order execution**
   - Places live CLOB buy orders when live mode is explicitly armed.
   - Waits for fills.
   - Cancels stale unfilled orders.
   - Records live buy cost, shares, fill state, and order IDs.

4. **Position management**
   - Takes profit using cashout rules.
   - Applies stop-loss / hard stop rules.
   - Applies profit-protection logic after a trade becomes green.
   - Applies dynamic force-exit rules near expiry.
   - Handles partial sells and zero-token-balance reconciliation.
   - Writes trade and decision logs to CSV.
   - Maintains state in `btc_5m_state.json`.

---

## 2. Repository layout

Recommended repo structure:

```text
PolyBTC/
├─ btc_5m_hybrid_bot.py          # Main live/paper bot loop and execution logic
├─ btc_5m_hybrid_strategy.py     # Entry signal and edge model
├─ summarize_run.py              # Post-run analysis / summary script
├─ .env                          # Runtime config and credentials; do not commit
├─ .env.example                  # Safe example config; commit this, not .env
├─ btc_5m_state.json             # Runtime state; usually not committed
├─ btc_5m_decisions.csv          # Decision log; usually not committed
├─ btc_5m_trades.csv             # Trade log; usually not committed
└─ README.md
```

Recommended `.gitignore`:

```gitignore
.env
btc_5m_state.json
btc_5m_decisions.csv
btc_5m_trades.csv
archive_*.csv
archive_*.json
__pycache__/
.venv/
```

---

## 3. Core files

### `btc_5m_hybrid_bot.py`

Main runtime file. It handles:

- startup configuration
- CSV header creation
- JSON state loading/saving
- Polymarket Gamma market lookup
- Binance BTC candle lookup
- order book reading
- live buy placement
- live sell placement
- fill verification
- stale order cancellation
- state reconciliation
- cashout / stop-loss / profit protection / time exit logic
- live partial sell handling
- zero-token-balance reconciliation

### `btc_5m_hybrid_strategy.py`

Entry model and trade filter. It decides whether to:

```text
BUY YES
BUY NO
SKIP
```

The strategy uses:

- time-to-expiry filter
- spread filter
- distance-from-strike filter
- late-market distance filter
- momentum confirmation
- simple probability estimate
- model-vs-market edge

### `summarize_run.py`

Analysis helper for `btc_5m_trades.csv` and `btc_5m_decisions.csv`.

It reports:

- total PnL
- win/loss count
- win rate
- average win/loss
- largest win/loss
- breakeven win rate
- execution statistics
- worst/best trades
- decision context around each entry

Example:

```powershell
python .\summarize_run.py --all --decision-context 12 --max-trades 0
```

---

## 4. Installation

### 4.1 Create virtual environment

PowerShell:

```powershell
cd C:\PolyBTC

python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 4.2 Install dependencies

Use your existing project requirements if present. Minimum expected packages:

```powershell
pip install requests python-dotenv py-clob-client py-clob-client-v2
```

If `py-clob-client-v2` is installed differently in your environment, keep using the same package/version that already works locally.

### 4.3 Compile check

Before any live run:

```powershell
python -m py_compile .\btc_5m_hybrid_bot.py
python -m py_compile .\btc_5m_hybrid_strategy.py
python -m py_compile .\summarize_run.py
```

All three must pass.

---

## 5. Credentials and live-mode safety

The bot needs Polymarket credentials in `.env`.

Typical private credential keys:

```env
PK=your_private_key
CLOB_API_KEY=your_clob_api_key
CLOB_SECRET=your_clob_secret
CLOB_PASS_PHRASE=your_clob_passphrase
CLOB_API_URL=https://clob.polymarket.com
CHAIN_ID=137
POLYMARKET_SIGNATURE_TYPE=1
POLYMARKET_FUNDER=your_funder_address_if_required
```

Never commit `.env`.

Live orders are blocked unless all live arming flags are enabled:

```env
BTC_5M_MODE=live
BTC_5M_LIVE_ARMED=true
BTC_5M_ALLOW_REAL_ORDERS=true
```

For paper mode:

```env
BTC_5M_MODE=paper
BTC_5M_LIVE_ARMED=false
BTC_5M_ALLOW_REAL_ORDERS=false
```

---

## 6. Environment configuration

A clean grouped BTC5M `.env` section:

```env
# ============================================================
# BTC 5M HYBRID BOT CONFIG
# ============================================================


# ============================================================
# 1. Mode / Live Order Arming
# ============================================================

BTC_5M_MODE=live
BTC_5M_LIVE_ARMED=true
BTC_5M_ALLOW_REAL_ORDERS=true


# ============================================================
# 2. Main Loop
# ============================================================

BTC_5M_LOOP_SECONDS=5


# ============================================================
# 3. Entry Strategy Filters
# ============================================================

BTC_5M_MIN_EDGE=0.05
BTC_5M_MAX_SPREAD=0.08
BTC_5M_MIN_DISTANCE_FROM_STRIKE=0.00012
BTC_5M_REQUIRE_MOMENTUM_CONFIRMATION=true


# ============================================================
# 4. Entry Timing Window
# ============================================================

BTC_5M_MAX_SECONDS_TO_EXPIRY=270
BTC_5M_MIN_SECONDS_TO_EXPIRY=125
BTC_5M_NO_TRADE_LAST_SECONDS=125


# ============================================================
# 5. Late-Market Entry Distance Filter
# ============================================================

BTC_5M_LATE_DISTANCE_SECONDS=150
BTC_5M_LATE_MIN_DISTANCE_FROM_STRIKE=0.00018


# ============================================================
# 6. Re-entry Control
# ============================================================

BTC_5M_PREVENT_REENTRY_AFTER_CASHOUT=true


# ============================================================
# 7. Live Position Sizing
# ============================================================

BTC_5M_LIVE_ORDER_SIZE=5
BTC_5M_MIN_LIVE_SHARE_SIZE=5
BTC_5M_MIN_LIVE_ORDER_VALUE=2.50
BTC_5M_MAX_LIVE_ORDER_VALUE=7.00


# ============================================================
# 8. Basic Cashout / PnL Buffer
# ============================================================

BTC_5M_ENABLE_CASHOUT=true
BTC_5M_MIN_NET_PROFIT=0.10
BTC_5M_EXTRA_FEE_BUFFER=0.01


# ============================================================
# 9. Stop-Loss / Hard Risk Limits
# ============================================================

BTC_5M_ENABLE_STOPLOSS=true
BTC_5M_MAX_NET_LOSS=0.50
BTC_5M_HARD_MAX_NET_LOSS=0.50


# ============================================================
# 10. Dynamic Force Exit / Late Position Management
# ============================================================

BTC_5M_FORCE_EXIT_SECONDS=105
BTC_5M_FORCE_EXIT_MIN_NET=-0.15
BTC_5M_FORCE_EXIT_FLAT_NET=0.02

BTC_5M_STRONG_THESIS_HOLD_SECONDS=90
BTC_5M_STRONG_THESIS_MIN_NET=0.00
BTC_5M_STRONG_THESIS_MIN_DISTANCE=0.00018


# ============================================================
# 11. Profit Protection
# ============================================================

BTC_5M_ENABLE_PROFIT_PROTECTION=true
BTC_5M_PROFIT_PROTECT_ARM_NET=0.10
BTC_5M_PROFIT_PROTECT_EXIT_NET=0.00
BTC_5M_PROFIT_PROTECT_MIN_SECONDS=90
BTC_5M_PROFIT_PROTECT_THESIS_FLIP_EXIT=true
BTC_5M_PROFIT_PROTECT_MAX_EXIT_LOSS=0.25


# ============================================================
# 12. Profit Protection Giveback Rule
# ============================================================

BTC_5M_PROFIT_PROTECT_GIVEBACK=0.45
BTC_5M_PROFIT_PROTECT_MIN_BEST_NET=0.30
BTC_5M_PROFIT_PROTECT_MAX_GIVEBACK_EXIT_LOSS=0.35


# ============================================================
# 13. Trailing Profit
# Currently disabled. Values kept for future testing.
# ============================================================

BTC_5M_ENABLE_TRAILING_PROFIT=false
BTC_5M_TRAIL_ACTIVATE_NET=0.30
BTC_5M_TRAIL_DROP=0.04
BTC_5M_TRAIL_MIN_SECONDS_TO_EXPIRY=90
BTC_5M_TRAIL_FORCE_CASHOUT_NET=0.90


# ============================================================
# 14. Live Execution Slippage
# ============================================================

BTC_5M_ENTRY_SLIPPAGE=0.01
BTC_5M_CASHOUT_EXIT_SLIPPAGE=0.01
BTC_5M_STOPLOSS_EXIT_SLIPPAGE=0.02
BTC_5M_PROTECT_EXIT_SLIPPAGE=0.01
BTC_5M_TRAIL_EXIT_SLIPPAGE=0.01


# ============================================================
# 15. Live Order Handling / Fill Safety
# ============================================================

BTC_5M_ENTRY_ORDER_TIMEOUT_SECONDS=8
BTC_5M_EXIT_ORDER_TIMEOUT_SECONDS=8
BTC_5M_ORDER_STATUS_POLL_SECONDS=1
BTC_5M_MIN_FILLED_SIZE=0.01
BTC_5M_CANCEL_STALE_ORDERS=true


# ============================================================
# 16. Live Safety / Reconciliation
# ============================================================

BTC_5M_MAX_DAILY_LIVE_LOSS=5.00
BTC_5M_RECONCILE_ON_STARTUP=true
```

---

## 7. Entry logic

The strategy estimates a probability that BTC finishes above strike.

Basic model:

```text
distance = (btc_price - strike) / strike
probability ≈ 0.5 + distance_factor + momentum_factor
```

For YES:

```text
edge = model_probability - yes_ask
```

For NO:

```text
edge = (1 - model_probability) - no_ask
```

The bot buys only when:

```text
edge >= BTC_5M_MIN_EDGE
spread <= BTC_5M_MAX_SPREAD
time-to-expiry is inside allowed window
distance from strike is large enough
momentum confirmation passes
```

### YES entry

Requires:

```text
btc_price > strike
yes_edge >= min_edge
```

### NO entry

Requires:

```text
btc_price < strike
no_edge >= min_edge
```

### Skip reasons

Common skip reasons:

```text
too_early_in_market
too_close_to_expiry
below_min_seconds_to_expiry
too_close_to_strike
yes_allowed_but_edge_too_small
no_allowed_but_edge_too_small
yes_spread_too_wide
no_spread_too_wide
missing_yes_book
missing_no_book
yes_momentum_not_confirmed
no_momentum_not_confirmed
```

---

## 8. Position management

Open positions are managed before the bot considers a new entry.

Exit priority:

```text
1. hard stop-loss
2. normal stop-loss
3. profit-protect thesis flip
4. profit-protect giveback / breakeven
5. trailing exit
6. cashout
7. force-time exit
```

### 8.1 Cashout

Cashout triggers when net PnL reaches:

```text
BTC_5M_MIN_NET_PROFIT × position_size
```

Example:

```text
BTC_5M_MIN_NET_PROFIT=0.10
size=5
cashout target ≈ $0.50 net
```

### 8.2 Stop-loss

There are two stop-loss concepts:

#### Normal stop-loss

Triggers when:

```text
thesis is invalidated
and net_pnl <= -BTC_5M_MAX_NET_LOSS
```

Example:

```text
YES position and BTC <= strike
NO position and BTC >= strike
```

#### Hard stop-loss

Triggers when:

```text
net_pnl <= -BTC_5M_HARD_MAX_NET_LOSS
```

This can trigger even if the thesis is technically still valid. This protects against market repricing while BTC remains on the correct side of the strike.

### 8.3 Dynamic force exit

Near expiry, the bot tries not to hold weak positions too long.

Relevant settings:

```env
BTC_5M_FORCE_EXIT_SECONDS=105
BTC_5M_STRONG_THESIS_HOLD_SECONDS=90
BTC_5M_FORCE_EXIT_MIN_NET=-0.15
BTC_5M_FORCE_EXIT_FLAT_NET=0.02
BTC_5M_STRONG_THESIS_MIN_DISTANCE=0.00018
```

Logic concept:

```text
At <= FORCE_EXIT_SECONDS:
    if thesis is strong and trade is not bad, allow hold.
    if flat/small loss/small profit, exit.
    if thesis weakens, exit if not worse than configured threshold.

At <= STRONG_THESIS_HOLD_SECONDS:
    become more willing to exit unless minimum exit threshold blocks it.
```

### 8.4 Profit protection

Profit protection arms after the trade becomes meaningfully green:

```env
BTC_5M_PROFIT_PROTECT_ARM_NET=0.10
```

Once armed, it can exit if:

1. The thesis flips against the position.
2. The trade gives back too much of its best seen profit.

Example giveback logic:

```env
BTC_5M_PROFIT_PROTECT_MIN_BEST_NET=0.30
BTC_5M_PROFIT_PROTECT_GIVEBACK=0.45
BTC_5M_PROFIT_PROTECT_MAX_GIVEBACK_EXIT_LOSS=0.35
```

Concept:

```text
If best_net_pnl_seen >= 0.30
and current net_pnl <= best_net_pnl_seen - 0.45
and current net_pnl >= -0.35
then exit with PROTECT_EXIT
```

This is designed to reduce cases where a trade is green first, then collapses into full stop-loss.

### 8.5 Trailing profit

Trailing is currently disabled:

```env
BTC_5M_ENABLE_TRAILING_PROFIT=false
```

The settings are retained for future testing. Do not enable it during baseline comparison unless intentionally testing trailing.

---

## 9. Live execution behavior

### 9.1 Buy flow

Live buy sequence:

```text
check live mode is armed
calculate entry slippage
check adjusted edge after slippage
calculate live size
check collateral balance/allowance
post CLOB buy order
extract immediate post response fill if available
otherwise poll order status
cancel stale unfilled order
recheck token balance after cancel
record buy if filled
```

The bot logs:

```text
ORDER_POSTED
BUY
ORDER_UNFILLED_CANCELLED
```

### 9.2 Sell flow

Live sell sequence:

```text
choose current bid for held outcome
apply exit slippage based on exit type
check conditional token balance/allowance
post CLOB sell order
extract immediate post response fill if available
otherwise poll order status
calculate actual sell proceeds
check remaining token balance
close, partially close, or reconcile state
```

The bot logs:

```text
EXIT_ORDER_POSTED
CASHOUT
STOPLOSS
TIME_EXIT
PROTECT_EXIT
TRAIL_EXIT
PARTIAL_EXIT
RECONCILED_EXIT
```

---

## 10. State file

State is stored in:

```text
btc_5m_state.json
```

Important sections:

```json
{
  "mode": "live",
  "open_positions": {},
  "closed_markets": {},
  "live_failed_orders": {},
  "live_blocked_orders": {},
  "live_unfilled_cancelled_orders": {},
  "live_reconciliation": {},
  "daily_pnl": 0.0,
  "total_pnl": 0.0,
  "last_updated": null
}
```

### `open_positions`

Active local positions. In live mode, these should correspond to actual Polymarket token balances.

### `closed_markets`

Markets already closed by the bot. Used to prevent same-market re-entry.

### `live_failed_orders`

Uncertain live failures. If a market enters this bucket, the bot should skip that market because an order outcome may be unclear.

### `live_unfilled_cancelled_orders`

Orders posted but confirmed unfilled and cancelled. These are safer than `live_failed_orders`.

### `live_reconciliation`

Startup reconciliation data such as open orders and token balances.

---

## 11. CSV logs

### 11.1 Decisions CSV

File:

```text
btc_5m_decisions.csv
```

Columns:

```text
timestamp
market_id
question
btc_price
strike
seconds_to_expiry
yes_bid
yes_ask
no_bid
no_ask
model_probability
market_probability
edge
action
reason
```

This is used to inspect the market context around each trade.

### 11.2 Trades CSV

File:

```text
btc_5m_trades.csv
```

Columns:

```text
timestamp
mode
market_id
side
outcome
price
size
simulated
reason
pnl
```

`side` contains both order actions and exit actions:

```text
ORDER_POSTED
BUY
EXIT_ORDER_POSTED
CASHOUT
STOPLOSS
TIME_EXIT
PROTECT_EXIT
TRAIL_EXIT
PARTIAL_EXIT
RECONCILED_EXIT
ORDER_UNFILLED_CANCELLED
SETTLE
```

---

## 12. Run commands

### 12.1 Start bot

```powershell
cd C:\PolyBTC
.\.venv\Scripts\Activate.ps1

python -m py_compile .\btc_5m_hybrid_bot.py
python -m py_compile .\btc_5m_hybrid_strategy.py
python .\btc_5m_hybrid_bot.py
```

### 12.2 Analyze all data

```powershell
python .\summarize_run.py --all --decision-context 12 --max-trades 0
```

### 12.3 Analyze last 3 hours

```powershell
python .\summarize_run.py --last-3h --decision-context 12 --max-trades 0
```

### 12.4 Analyze last 10 hours

```powershell
python .\summarize_run.py --last-10h --decision-context 12 --max-trades 0
```

### 12.5 Save summary to file

```powershell
python .\summarize_run.py --all --decision-context 12 --max-trades 0 | Tee-Object .\summary_latest.txt
```

---

## 13. Reset logs and state

Before a clean test, archive old files and reset state.

PowerShell:

```powershell
Copy-Item .\btc_5m_trades.csv ".\archive_btc_5m_trades_$(Get-Date -Format yyyyMMdd_HHmmss).csv" -ErrorAction SilentlyContinue
Copy-Item .\btc_5m_decisions.csv ".\archive_btc_5m_decisions_$(Get-Date -Format yyyyMMdd_HHmmss).csv" -ErrorAction SilentlyContinue
Copy-Item .\btc_5m_state.json ".\archive_btc_5m_state_$(Get-Date -Format yyyyMMdd_HHmmss).json" -ErrorAction SilentlyContinue

@'
timestamp,market_id,question,btc_price,strike,seconds_to_expiry,yes_bid,yes_ask,no_bid,no_ask,model_probability,market_probability,edge,action,reason
'@ | Set-Content .\btc_5m_decisions.csv

@'
timestamp,mode,market_id,side,outcome,price,size,simulated,reason,pnl
'@ | Set-Content .\btc_5m_trades.csv

@'
{
  "mode": "live",
  "open_positions": {},
  "closed_markets": {},
  "live_failed_orders": {},
  "live_blocked_orders": {},
  "live_unfilled_cancelled_orders": {},
  "live_reconciliation": {},
  "daily_pnl": 0.0,
  "total_pnl": 0.0,
  "last_market_id": null,
  "last_updated": null
}
'@ | Set-Content .\btc_5m_state.json
```

Only reset when there are no unresolved live positions in the UI.

---

## 14. Interpreting logs

Example live buy:

```text
[BTC5M] LIVE BUY YES @ 0.45 size=5.44 value=2.4480
```

Meaning:

```text
Bought YES shares at average fill price 0.45
Size 5.44 shares
Cost about $2.4480
```

Example protection arming:

```text
[BTC5M] PROFIT_PROTECTION armed YES entry=0.45 bid=0.48 net=0.1088 best_net=0.1088
```

Meaning:

```text
Position was green enough to activate protection.
Protection is now a backup exit rule.
It does not necessarily close immediately.
```

Example cashout:

```text
[BTC5M] CASHOUT YES entry=0.45 exit=0.56 gross=0.5984 net_after_buffer=0.5440
```

Meaning:

```text
The bot sold at 0.56.
Gross profit was 0.5984.
After buffer, net was 0.5440.
```

Example stop-loss:

```text
[BTC5M] STOPLOSS NO entry=0.39 exit=0.13 gross=-1.5496 net_after_buffer=-1.6092
```

Meaning:

```text
The market repriced sharply against the held NO token.
Hard/normal stop-loss exited the trade.
```

Example already closed:

```text
market ... already closed, skipping re-entry
```

Meaning:

```text
The bot already closed this 5-minute market and refuses to enter it again.
```

---

## 15. Troubleshooting

### 15.1 Compile errors

Run:

```powershell
python -m py_compile .\btc_5m_hybrid_bot.py
python -m py_compile .\btc_5m_hybrid_strategy.py
python -m py_compile .\summarize_run.py
```

Fix syntax before running live.

### 15.2 Live order blocked

Possible causes:

```text
BTC_5M_MODE is not live
BTC_5M_LIVE_ARMED is not true
BTC_5M_ALLOW_REAL_ORDERS is not true
missing PK or CLOB credentials
insufficient collateral balance
insufficient allowance
adjusted edge too small after slippage
order value above max
```

### 15.3 Order posted but unfilled

Common log:

```text
ORDER_UNFILLED_CANCELLED
```

This means the order was posted, did not fill, and was cancelled.

This is not the same as a dangerous failed order. It usually means no trader filled your limit order during the timeout.

### 15.4 UI shows position but JSON does not

This indicates a state mismatch. Stop the bot and reconcile manually before continuing.

Potential causes:

```text
partial sell handling failed
manual UI trade was made
bot state reset while position was open
API returned incomplete fill state
```

### 15.5 JSON shows open position but UI has zero shares

This indicates stale local state. The bot now has zero-token-balance reconciliation for some sell-failure cases, but manual reconciliation may still be required if state was edited/reset.

### 15.6 `not enough balance / allowance: balance: 0`

For sells, this may mean:

```text
The shares were already sold
or
The bot state thinks it owns shares it no longer owns
```

The bot attempts to confirm token balance and reconcile the local state.

---

## 16. Testing methodology

### Short test

Use 3 hours to check:

```text
does it run without crashes?
are fills tracked correctly?
does UI match JSON?
are partial/reconciled exits handled?
```

### Serious test

Use 10–12 hours to evaluate strategy behavior:

```text
total PnL
closed trade count
avg win vs avg loss
largest loss
STOPLOSS count
PROTECT_EXIT count
CASHOUT count
trades once green but closed red
state/UI mismatches
```

A 3-hour test with 3–5 trades is not enough to judge edge.

---

## 17. Baseline vs latest comparison

Because overengineering is a real risk, maintain two `.env` profiles:

```text
.env.latest_giveback
.env.baseline
```

### Latest version

Uses:

```text
hard stop
thesis-flip protection
giveback protection
dynamic force exit
late distance filter
```

### Baseline version

Recommended baseline disables the giveback behavior while keeping infrastructure safety:

```env
BTC_5M_ENABLE_TRAILING_PROFIT=false
BTC_5M_HARD_MAX_NET_LOSS=0.50

BTC_5M_ENABLE_PROFIT_PROTECTION=true
BTC_5M_PROFIT_PROTECT_ARM_NET=0.10
BTC_5M_PROFIT_PROTECT_EXIT_NET=0.00
BTC_5M_PROFIT_PROTECT_MIN_SECONDS=90
BTC_5M_PROFIT_PROTECT_THESIS_FLIP_EXIT=true
BTC_5M_PROFIT_PROTECT_MAX_EXIT_LOSS=0.25

BTC_5M_PROFIT_PROTECT_GIVEBACK=999
BTC_5M_PROFIT_PROTECT_MIN_BEST_NET=999
```

Switch profiles:

```powershell
Copy-Item .\.env.latest_giveback .\.env -Force
```

or:

```powershell
Copy-Item .\.env.baseline .\.env -Force
```

Always compile before running.

---

## 18. Future Kronos experiment

Kronos should not replace the live BTC reader or Polymarket order book reader.

Potential use:

```text
shadow signal module
forecast short-horizon BTC candle/path
log forecast direction/probability
compare against actual settlement and bot decisions
```

Recommended first step:

```text
Do not use Kronos for live decisions.
Add Kronos as a shadow logger.
Collect 100–300 markets.
Check whether it improves filtering before promoting it to live logic.
```

---

## 19. Safety rules

1. Do not run live if compile fails.
2. Do not run live with unresolved UI/JSON mismatch.
3. Do not reset state while a live position is open.
4. Do not raise size until state, fill, and PnL accounting are stable.
5. Treat every live failed/uncertain order as requiring UI inspection.
6. Judge strategy only after enough closed trades, not after one trade.

---

## 20. Current project philosophy

The bot separates two layers:

### Infrastructure safety

These are necessary and should remain:

```text
fill verification
stale cancel
zero-balance reconciliation
partial sell handling
actual cashflow accounting
daily loss lockout
startup reconciliation
state consistency
```

### Strategy/risk tuning

These should be tested carefully because they can overfit:

```text
profit-protection giveback
trailing
dynamic force exit
late distance filter
hard stop thresholds
```

The goal is not to add endless rules. The goal is to keep the bot state truthful, keep losses bounded, and test whether the entry model has real edge.
