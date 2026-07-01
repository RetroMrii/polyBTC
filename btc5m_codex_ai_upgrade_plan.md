# Codex Prompt and Project Plan: Hybrid AI Upgrades for the BTC5M Polymarket Bot

## Purpose

This document converts the existing BTC5M hybrid-AI notes into a Codex-ready project prompt and phased implementation plan.

The goal is to upgrade the current BTC5M Polymarket bot safely with:

- LightGBM trade-quality classification
- XGBoost baseline research
- Kronos diagnostic financial candle forecasting
- TimesFM diagnostic time-series forecasting
- Chronos diagnostic time-series forecasting
- Darts offline forecasting/backtesting research
- Nixtla NeuralForecast offline neural forecasting research
- TradingAgents daily review, risk committee, and regime classification

The current bot must remain the deterministic execution and safety layer. No external AI system should place live Polymarket orders directly.

---

## Current Project Opinion

The current BTC5M Polymarket bot is technically viable as a live trading framework, but the signal layer is not yet proven profitable.

The execution layer is the strong part:

- It can authenticate with Polymarket.
- It can read BTC 5-minute markets.
- It can post live orders.
- It can exit positions.
- It logs decisions and trades.
- It supports summaries and diagnostics.
- It has live safety controls such as max order value, daily loss limits, slippage checks, and state tracking.

The weak part is the signal layer. The bot finds real winners, but stoploss frequency remains too high. The next phase should focus on reducing false entries, repeated same-market losses, and weak edge/distance conditions.

Practical verdict:

```text
Do not abandon the project.
Do not scale it further yet.
Do not loosen stoploss first.
Do not change many variables at once.
Treat the next phase as signal validation, not profit scaling.
```

---

## Best Hybrid Architecture

Do not replace the current bot. Keep it as the executor, state manager, and risk controller. Add AI/ML layers above or beside it.

```text
Layer 1: Current deterministic strategy
- edge
- spread
- timing
- distance from strike
- momentum
- YES/NO side permission
- 2-confirmation rule

Layer 2: Trade-quality model
- LightGBM baseline classifier
- XGBoost baseline classifier
- target: CASHOUT-before-STOPLOSS probability

Layer 3: Financial/time-series model diagnostics
- Kronos financial K-line/candle diagnostics
- TimesFM short-horizon drift diagnostics
- Chronos comparative forecast diagnostics
- Darts / NeuralForecast offline research benchmarks

Layer 4: LLM review and governance
- TradingAgents daily strategy reviewer
- TradingAgents risk committee
- TradingAgents market regime classifier
- structured JSON recommendations only

Layer 5: Execution safety
- max order value
- daily loss
- slippage
- balance checks
- state reconciliation
- live order isolation
```

---

# Repository Reviews and Recommended Use

## 1. LightGBM

Repository:

```text
https://github.com/lightgbm-org/LightGBM
```

### What LightGBM is

LightGBM is a fast, distributed, high-performance gradient boosting framework based on decision-tree algorithms. It is commonly used for classification, ranking, regression, and other supervised machine-learning tasks.

### My opinion for the BTC5M bot

LightGBM is the most practical near-term ML upgrade for this bot.

The correct question is not:

```text
Will BTC go up or down?
```

The better question is:

```text
If the current deterministic strategy enters here, will this trade cash out before stoploss?
```

### Best role

Use LightGBM as a trade-quality classifier.

Target:

```text
1 = CASHOUT
0 = STOPLOSS / bad PROTECT_EXIT / bad TIME_EXIT
```

Features:

```text
edge
side YES/NO
outcome YES/NO
entry price
time to expiry
distance from strike
spread
BTC momentum 5s / 15s / 30s / 60s
market probability
model probability
previous BUY count in same market
same market prior stoploss
same-side repeated entries
time since last entry
```

### Where it should be used first

Diagnostic/backtest only.

Initial flow:

```text
Current strategy says BUY
Write candidate BUY row
Train LightGBM offline
Score historical candidates
Compare approved vs rejected trades
Only later consider live blocking
```

### Where it should not be used yet

Do not let LightGBM block live trades until:

```text
at least 50 closed trades or 72 hours of post-patch data exist
approved trades outperform rejected trades
STOPLOSS rate is materially lower in approved trades
the validation split is time-based, not randomly shuffled
```

---

## 2. XGBoost / Quantitative Trading Strategy Based on Machine Learning

Repository supplied:

```text
https://github.com/majiajue/Quantitative-Trading-Strategy-Based-on-Machine-Learning
```

### What this repository is

This is not the official XGBoost library repository. It is a quantitative trading strategy project that uses factor analysis and an XGBoost classification model to predict stock profitability over a monthly horizon.

### My opinion for the BTC5M bot

This repo is useful as a conceptual example, not as code to directly merge.

The useful ideas are:

```text
factor construction
IC / IR style feature evaluation
correlation filtering
backtesting before deployment
classification target based on profitability
```

But the time horizon is very different:

```text
repo project: monthly stock profitability
BTC5M bot: seconds-to-minutes binary-market execution
```

### Best role

Use this repo as a reference for:

```text
feature evaluation
feature importance
classification framing
backtest discipline
```

Do not copy its strategy logic directly into the BTC5M bot.

### Recommended BTC5M adaptation

Use XGBoost as a second baseline classifier beside LightGBM:

```text
LightGBM probability_good_trade
XGBoost probability_good_trade
Compare time-split validation performance
Prefer whichever is more stable and less overfit
```

---

## 3. Kronos

Repository:

```text
https://github.com/shiyu-coder/Kronos
```

### What Kronos is

Kronos is an open-source foundation model for financial candlesticks, also called K-lines. It is specifically aimed at financial-market sequence modeling.

### My opinion for the BTC5M bot

Kronos is the strongest direct foundation-model candidate because it is built for financial candle sequences rather than generic time series.

The BTC5M bot is strike-relative and market-price-sensitive, so Kronos should not replace the current edge model. It should provide a direction/confidence diagnostic.

### Best role

Diagnostic financial candle filter.

Input:

```text
recent BTC candles
recent BTC micro-momentum
current strike
current bot side
```

Output:

```json
{
  "kronos_direction": "up|down|flat|unknown",
  "kronos_confidence": 0.0,
  "kronos_expected_move": 0.0,
  "kronos_agrees_with_trade": true
}
```

### Initial config

```env
BTC_5M_ENABLE_KRONOS=false
BTC_5M_KRONOS_MODE=diagnostic
BTC_5M_KRONOS_REQUIRE_AGREEMENT=false
BTC_5M_KRONOS_MIN_CONFIDENCE=0.60
```

### Validation

Log diagnostic columns first:

```text
kronos_direction
kronos_confidence
kronos_expected_move
kronos_agrees_with_trade
```

Then evaluate:

```text
PnL when Kronos agreed
PnL when Kronos disagreed
STOPLOSS rate when Kronos agreed
CASHOUT rate when Kronos agreed
```

Only after validation should Kronos be allowed to block or boost trades.

---

## 4. TimesFM

Repository:

```text
https://github.com/google-research/timesfm
```

### What TimesFM is

TimesFM is a pretrained time-series foundation model from Google Research for forecasting. It is general-purpose rather than finance-specific.

### My opinion for the BTC5M bot

TimesFM can be useful as a secondary short-horizon drift model, but it should not be the main signal.

The BTC5M market depends on short bursts, strike distance, Polymarket pricing, liquidity, and timing windows. TimesFM may help detect local directional drift, but it does not understand the Polymarket binary payout structure by default.

### Best role

Diagnostic short-horizon drift filter.

Use case:

```text
Predict next 30-90 seconds BTC drift.
If bot wants YES but TimesFM expects downward drift, mark disagreement.
If bot wants NO but TimesFM expects upward drift, mark disagreement.
```

### Output fields

```text
timesfm_direction
timesfm_confidence
timesfm_expected_move
timesfm_agrees_with_trade
```

### Initial mode

Diagnostic only. Do not block trades.

---

## 5. Chronos / Chronos-2

Repository:

```text
https://github.com/amazon-science/chronos-forecasting
```

### What Chronos is

Chronos provides pretrained models for time-series forecasting. Chronos-2 is a newer model line with deployment paths through AWS tooling.

### My opinion for the BTC5M bot

Chronos is useful as a comparative diagnostic model against Kronos and TimesFM.

It is not finance-specific in the same way as Kronos, but it can provide an independent forecast opinion. The value is in ensemble comparison, not standalone authority.

### Best role

Benchmark and diagnostic ensemble member.

Possible ensemble diagnostics:

```text
kronos_direction
timesfm_direction
chronos_direction
bot_side
```

Later rule, only if validated:

```text
Allow trade only when at least 2 of 3 external forecast models agree with the bot side.
```

Do not implement that blocking rule until diagnostic logs prove that agreement improves outcomes.

---

## 6. Darts

Repository:

```text
https://github.com/unit8co/darts
```

### What Darts is

Darts is a Python library for forecasting and anomaly detection on time series. It provides a common fit/predict interface across many model types, supports backtesting, model combinations, and external covariates.

### My opinion for the BTC5M bot

Darts is best for offline research, not live execution.

It is useful because it lets the project compare multiple forecasting approaches with one consistent workflow.

### Best role

Offline benchmark framework.

Use it to test:

```text
ARIMA / baseline statistical models
N-BEATS
N-HiTS
TCN
TFT
PatchTST-style models when available through dependencies
```

Possible tasks:

```text
forecast BTC drift
forecast volatility regime
forecast probability of crossing strike
generate candidate features for trade-quality classifier
```

### Where it should not be used

Do not call Darts models inside the 5-second live loop at first. Keep it offline until a specific model proves value.

---

## 7. Nixtla NeuralForecast

Repository:

```text
https://github.com/nixtla/neuralforecast
```

### What NeuralForecast is

NeuralForecast is a neural time-series forecasting library with many neural forecasting architectures, including recurrent networks, convolutional models, N-BEATS, N-HiTS, TFT, PatchTST, iTransformer, and other modern models.

### My opinion for the BTC5M bot

NeuralForecast is useful for offline model research and benchmark comparison.

It is more complex than LightGBM and should come after the trade-quality dataset exists. The first useful task is to compare whether any neural forecast feature improves the LightGBM/XGBoost trade-quality model.

### Best role

Offline neural benchmark and feature generator.

Possible output fields:

```text
nf_direction
nf_expected_move
nf_volatility_forecast
nf_cross_strike_probability
```

### Where it should not be used

Do not integrate NeuralForecast directly into live execution until:

```text
offline forecasts are stable
inference latency is measured
added features improve trade-quality validation
fallback behavior is safe
```

---

## 8. TradingAgents

Repository:

```text
https://github.com/TauricResearch/TradingAgents
```

### What TradingAgents is

TradingAgents is a multi-agent LLM financial trading framework. It attempts to emulate a trading firm by using specialized agents such as:

```text
fundamental analyst
sentiment analyst
news analyst
technical analyst
bull researcher
bear researcher
trader
risk manager
portfolio manager
```

The framework uses LLM-powered debate and structured decision-making to evaluate market conditions and trading decisions.

### My opinion for the BTC5M bot

TradingAgents is interesting, but it is not the best direct merge for the BTC5M live execution loop.

It is better suited for:

```text
stock analysis
daily/medium-horizon decisions
news + fundamentals + sentiment
LLM reasoning workflows
research reports
portfolio-style risk discussion
```

The BTC5M bot is different:

```text
BTC 5-minute binary markets
seconds-to-minutes decisions
microstructure-sensitive movement
strike-relative probability
fast order execution
strict stoploss/cashout timing
```

TradingAgents should not make every live 5-second entry decision. It is too slow, too text-heavy, and too non-deterministic if used naively.

### Best role

Use TradingAgents as:

```text
offline daily strategy reviewer
risk committee
regime classifier
automated research note generator
```

Do not use TradingAgents as:

```text
real-time entry engine
order placer
direct Polymarket executor
unrestricted config editor
```

### Output file

```text
tradingagents_daily_review.json
```

Example:

```json
{
  "recommended_action": "keep_trading",
  "risk_level": "medium",
  "main_loss_driver": "same_market_reentry_after_stoploss",
  "suggested_next_experiment": "enable_2_confirmation",
  "do_not_change": ["order_size", "stoploss", "daily_loss"],
  "confidence": 0.72
}
```

The live bot should eventually consume only simple bounded fields:

```text
regime = trend / chop / risk_off
allow_trading = true / false
max_size_multiplier = 1.0 / 0.5 / 0.0
```

But first phase must be review-only.

---

# Recommended Ranking for This Bot

```text
1. Keep/verify two-confirmation entry rule
2. Build candidate BUY trade-quality dataset
3. Train LightGBM baseline classifier
4. Train XGBoost baseline classifier
5. Compare model performance using time-based validation
6. Add Kronos diagnostic columns
7. Add TimesFM / Chronos diagnostic columns
8. Use Darts / NeuralForecast for offline benchmark research
9. Add TradingAgents daily reviewer / risk committee
10. Only later consider bounded regime/risk consumption by live bot
11. Full multi-agent live trading logic: not recommended unless future evidence strongly supports it
```

---

# Implementation Roadmap

## Phase 0: Inspect current project only

Goal: inspect safely. No edits.

Codex should inspect:

```text
current file list
important .env keys with secrets redacted
strategy constructor
decision logging block
trade logging block
state schema
CSV headers
summary script output
systemd service status
```

Do not modify files in Phase 0.

## Phase 1: Stabilize deterministic entry behavior

Verify or add:

```env
BTC_5M_ENABLE_ENTRY_CONFIRMATION=true
BTC_5M_ENTRY_CONFIRMATION_REQUIRED=2
BTC_5M_ENTRY_CONFIRMATION_MAX_AGE_SECONDS=25
BTC_5M_ENTRY_CONFIRMATION_REQUIRE_SAME_REASON=true
```

Verify timing-skip CSV throttle only affects logging, not strategy logic.

## Phase 2: Add same-market anti-reentry after stoploss

Config:

```env
BTC_5M_BLOCK_REENTRY_AFTER_STOPLOSS=true
BTC_5M_STOPLOSS_REENTRY_COOLDOWN_SECONDS=300
```

Behavior:

```text
If market had STOPLOSS, block future BUYs in same market for cooldown period.
Do not block all markets.
Log reason: same_market_stoploss_reentry_blocked
```

## Phase 3: Build candidate BUY dataset

Add:

```text
build_trade_quality_dataset.py
```

Output:

```text
trade_quality_dataset.csv
```

Target:

```text
1 = CASHOUT before STOPLOSS
0 = STOPLOSS / bad PROTECT_EXIT / bad TIME_EXIT
```

## Phase 4: Train LightGBM baseline

Add:

```text
train_lightgbm_trade_quality.py
```

Output:

```text
models/lightgbm_trade_quality.pkl
reports/lightgbm_trade_quality_metrics.json
```

Validation must be time-based, not random.

## Phase 5: Train XGBoost baseline

Add:

```text
train_xgboost_trade_quality.py
```

Output:

```text
models/xgboost_trade_quality.pkl
reports/xgboost_trade_quality_metrics.json
```

Compare against LightGBM.

## Phase 6: Add model scoring in diagnostic mode

Add:

```text
score_trade_quality.py
```

Output columns:

```text
lgbm_probability_good_trade
xgb_probability_good_trade
ml_trade_quality_decision
```

Do not block live trades yet.

## Phase 7: Add Kronos diagnostic adapter

Add:

```text
kronos_adapter.py
```

Config:

```env
BTC_5M_ENABLE_KRONOS=false
BTC_5M_KRONOS_MODE=diagnostic
BTC_5M_KRONOS_REQUIRE_AGREEMENT=false
BTC_5M_KRONOS_MIN_CONFIDENCE=0.60
```

Output columns:

```text
kronos_direction
kronos_confidence
kronos_expected_move
kronos_agrees_with_trade
```

## Phase 8: Add TimesFM / Chronos diagnostic adapters

Add only after Kronos diagnostic is stable.

Files:

```text
timesfm_adapter.py
chronos_adapter.py
```

Output columns:

```text
timesfm_direction
timesfm_confidence
timesfm_expected_move
timesfm_agrees_with_trade

chronos_direction
chronos_confidence
chronos_expected_move
chronos_agrees_with_trade
```

## Phase 9: Add Darts / NeuralForecast offline benchmark scripts

Files:

```text
research_darts_forecasts.py
research_neuralforecast_forecasts.py
```

Output:

```text
reports/darts_forecast_report.json
reports/neuralforecast_report.json
```

Keep offline only.

## Phase 10: Add TradingAgents daily reviewer

Files:

```text
tradingagents_daily_review.py
tradingagents_review_schema.py
```

Output:

```text
tradingagents_daily_review.json
```

It must:

```text
read btc_5m_trades.csv
read btc_5m_decisions.csv
read current redacted .env settings
summarize last 24h
optionally call TradingAgents if installed
fall back to local heuristic review if TradingAgents is not installed
write bounded JSON
never edit .env
never edit state
never place orders
```

## Phase 11: Optional bounded live consumption

Not now.

Only after multiple days of validated reviews should the live bot read:

```text
tradingagents_regime.json
```

Allowed fields:

```text
allow_trading
risk_level
regime
max_size_multiplier
confidence
```

Safe default:

```json
{
  "allow_trading": true,
  "max_size_multiplier": 1.0,
  "risk_level": "unknown",
  "regime": "unknown",
  "confidence": 0.0
}
```

---

# Codex Master Prompt

Paste the following into Codex.

```text
You are working on my BTC5M Polymarket trading bot project.

Project path:
~/PolyBTC

Main files:
- btc_5m_hybrid_bot.py
- btc_5m_hybrid_strategy.py
- btc_5m_state.json
- btc_5m_decisions.csv
- btc_5m_trades.csv
- summarize_run.py
- daily_discord_pnl_report.py
- .env

Systemd service:
polybtc.service

Use Bash on Ubuntu.
Use python3, not python.

Critical rules:
1. Do not rewrite entire files unless explicitly necessary.
2. Prefer targeted patches.
3. For every patch, specify exact file and exact insertion/replacement location.
4. Back up every file before editing.
5. Do not expose secrets from .env.
6. Do not let any AI/ML/LLM system place live orders directly.
7. The existing bot remains the only live executor.
8. All new AI systems start diagnostic/offline only.
9. Do not make broad strategy changes without asking.
10. Do not change order size, daily loss, stoploss, or live mode as part of AI integration.
11. Run compile and state checks after changes.
12. Restart polybtc only if live bot files changed.

Current architecture goal:
Keep btc_5m_hybrid_bot.py as the deterministic execution and safety layer.
Add AI/ML systems as offline diagnostics first:
- LightGBM trade-quality classifier
- XGBoost trade-quality classifier
- Kronos financial candle diagnostics
- TimesFM short-horizon drift diagnostics
- Chronos comparative forecast diagnostics
- Darts offline forecast benchmarks
- Nixtla NeuralForecast offline neural forecast benchmarks
- TradingAgents daily reviewer / risk committee / regime classifier

Repository roles:
- LightGBM: primary trade-quality classifier
- XGBoost project: conceptual baseline for classification/backtesting discipline, plus optional XGBoost baseline
- Kronos: financial K-line/candle diagnostic filter
- TimesFM: general time-series drift diagnostic
- Chronos: comparative time-series forecast diagnostic
- Darts: offline forecasting/backtesting framework
- NeuralForecast: offline neural forecasting benchmark
- TradingAgents: offline reviewer, risk committee, and regime classifier only

Do not use:
- TradingAgents as a 5-second live entry engine
- TradingAgents as an order placer
- Kronos/TimesFM/Chronos as live blockers until diagnostic results are validated
- LightGBM/XGBoost as live blockers until time-split validation proves value

Phase 0 request:
Start by inspecting only. Do not edit files yet.

Give me commands that show:
1. file list
2. git status if repo exists
3. redacted .env important settings
4. current CSV headers
5. current state schema keys
6. current strategy constructor
7. current decision logging block
8. current trade logging block
9. current entry confirmation logic
10. current stoploss and reentry-related logic
11. current summarize_run.py output
12. current polybtc service status and recent logs

After inspection, propose a phased patch plan:
Phase 1: verify entry confirmation and timing-skip logging throttle
Phase 2: add same-market anti-reentry after stoploss
Phase 3: add build_trade_quality_dataset.py
Phase 4: add LightGBM baseline training
Phase 5: add XGBoost baseline training
Phase 6: add ML scoring in diagnostic mode
Phase 7: add Kronos diagnostic adapter
Phase 8: add TimesFM/Chronos diagnostic stubs
Phase 9: add Darts/NeuralForecast offline research scripts
Phase 10: add TradingAgents daily reviewer
Phase 11: optional bounded live regime consumption only after validation

Safety checks for every code patch:
source .venv/bin/activate
python3 -m py_compile btc_5m_hybrid_bot.py btc_5m_hybrid_strategy.py summarize_run.py daily_discord_pnl_report.py
python3 -m json.tool btc_5m_state.json >/tmp/state_ok.txt && echo "state OK"

If live bot files changed:
sudo systemctl restart polybtc
sleep 10
sudo systemctl status polybtc --no-pager
journalctl -u polybtc --since "1 minute ago" --no-pager | tail -n 100

Begin with Phase 0 inspection commands only.
```

---

# Phase 0 Inspection Commands for Codex to Start With

```bash
cd ~/PolyBTC

echo "=== FILE LIST ==="
find . -maxdepth 2 -type f | sort | sed 's#^./##' | head -n 200

echo
echo "=== GIT STATUS IF PRESENT ==="
if [ -d .git ]; then git status --short; else echo "No .git directory"; fi

echo
echo "=== IMPORTANT .env SETTINGS REDACTED ==="
python3 - <<'PY'
from pathlib import Path

keys = [
    "BTC_5M_MODE",
    "BTC_5M_LIVE_ARMED",
    "BTC_5M_ALLOW_REAL_ORDERS",
    "BTC_5M_LOOP_SECONDS",
    "BTC_5M_ALLOW_YES",
    "BTC_5M_ALLOW_NO",
    "BTC_5M_MIN_EDGE",
    "BTC_5M_YES_MIN_EDGE",
    "BTC_5M_NO_MIN_EDGE",
    "BTC_5M_MAX_SPREAD",
    "BTC_5M_MIN_DISTANCE_FROM_STRIKE",
    "BTC_5M_LATE_MIN_DISTANCE_FROM_STRIKE",
    "BTC_5M_STRONG_THESIS_MIN_DISTANCE",
    "BTC_5M_MAX_SECONDS_TO_EXPIRY",
    "BTC_5M_MIN_SECONDS_TO_EXPIRY",
    "BTC_5M_NO_TRADE_LAST_SECONDS",
    "BTC_5M_ENABLE_ENTRY_CONFIRMATION",
    "BTC_5M_ENTRY_CONFIRMATION_REQUIRED",
    "BTC_5M_ENTRY_CONFIRMATION_MAX_AGE_SECONDS",
    "BTC_5M_ENTRY_CONFIRMATION_REQUIRE_SAME_REASON",
    "BTC_5M_ORDER_SIZE",
    "BTC_5M_LIVE_ORDER_SIZE",
    "BTC_5M_MAX_LIVE_ORDER_VALUE",
    "BTC_5M_MAX_DAILY_LIVE_LOSS",
]

env = {}
for line in Path(".env").read_text(errors="ignore").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    env[k.strip()] = v.strip()

for k in keys:
    print(f"{k}={env.get(k, '<missing>')}")
PY

echo
echo "=== CSV HEADERS ==="
python3 - <<'PY'
import csv
from pathlib import Path
for name in ["btc_5m_decisions.csv", "btc_5m_trades.csv"]:
    p = Path(name)
    print(f"--- {name} ---")
    if not p.exists():
        print("missing")
        continue
    with p.open(errors="ignore") as f:
        reader = csv.reader(f)
        try:
            print(next(reader))
        except StopIteration:
            print("empty")
PY

echo
echo "=== STATE TOP-LEVEL KEYS ==="
python3 - <<'PY'
import json
from pathlib import Path
p = Path("btc_5m_state.json")
if not p.exists():
    print("state missing")
else:
    data = json.loads(p.read_text())
    for k in sorted(data.keys()):
        print(k)
PY

echo
echo "=== STRATEGY CONSTRUCTOR ==="
grep -n "def __init__" -A80 btc_5m_hybrid_strategy.py | head -n 120

echo
echo "=== MAIN DECISION AREA ==="
grep -n "decision = strategy.decide" -A90 btc_5m_hybrid_bot.py | head -n 140

echo
echo "=== ENTRY CONFIRMATION LOGIC ==="
grep -n "def entry_signal_confirmed" -A120 btc_5m_hybrid_bot.py | head -n 160

echo
echo "=== STOPLOSS / REENTRY RELATED LOGIC ==="
grep -nEi "stoploss|reentry|re-entry|cooldown|closed_markets|blocked" btc_5m_hybrid_bot.py btc_5m_hybrid_strategy.py | head -n 200

echo
echo "=== SUMMARY OUTPUT ==="
source .venv/bin/activate
python3 summarize_run.py || true

echo
echo "=== SERVICE STATUS ==="
sudo systemctl status polybtc --no-pager || true

echo
echo "=== RECENT LOGS ==="
journalctl -u polybtc --since "10 minutes ago" --no-pager | tail -n 120 || true
```

---

# Validation Rule Before Any Live Blocking

No new model may block live trades until this exists:

```text
50+ closed trades or 72h of post-patch data
time-based validation split
approved-vs-rejected candidate trade analysis
STOPLOSS rate comparison
CASHOUT rate comparison
PnL comparison
latency measurement
safe fallback behavior
```

Default fallback:

```text
if model unavailable:
    do not block trade
    log diagnostic unavailable
```

---

# Final Opinion

The correct upgrade order is:

```text
current bot safety and deterministic strategy
anti-reentry and clean logging
trade-quality dataset
LightGBM/XGBoost classifier
Kronos diagnostics
TimesFM/Chronos diagnostics
Darts/NeuralForecast offline research
TradingAgents daily reviewer
bounded live regime/risk consumption only much later
```

This keeps the live bot stable while adding AI systems where they are most useful: filtering bad entries, improving diagnostics, and preventing overfit human/LLM narratives from controlling live execution.
