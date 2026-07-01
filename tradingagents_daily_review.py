import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from tradingagents_review_schema import validate_review


TRADES_FILE = "btc_5m_trades.csv"
DECISIONS_FILE = "btc_5m_decisions.csv"
ENV_FILE = ".env"
OUTPUT_FILE = "tradingagents_daily_review.json"

CLOSED_ACTIONS = {"CASHOUT", "STOPLOSS", "TIME_EXIT", "PROTECT_EXIT", "TRAIL_EXIT", "EXIT", "RECONCILED_EXIT"}
BAD_EXIT_ACTIONS = {"STOPLOSS", "TIME_EXIT", "PROTECT_EXIT", "EXIT"}
SECRET_MARKERS = {"KEY", "SECRET", "TOKEN", "PASS", "PK", "FUNDER", "WEBHOOK"}
CONFIG_KEYS = [
    "BTC_5M_MODE",
    "BTC_5M_LIVE_ARMED",
    "BTC_5M_ALLOW_REAL_ORDERS",
    "BTC_5M_LOOP_SECONDS",
    "BTC_5M_MIN_EDGE",
    "BTC_5M_MAX_SPREAD",
    "BTC_5M_MIN_DISTANCE_FROM_STRIKE",
    "BTC_5M_MIN_SECONDS_TO_EXPIRY",
    "BTC_5M_MAX_SECONDS_TO_EXPIRY",
    "BTC_5M_NO_TRADE_LAST_SECONDS",
    "BTC_5M_ENABLE_ENTRY_CONFIRMATION",
    "BTC_5M_ENTRY_CONFIRMATION_REQUIRED",
    "BTC_5M_BLOCK_REENTRY_AFTER_STOPLOSS",
    "BTC_5M_STOPLOSS_REENTRY_COOLDOWN_SECONDS",
    "BTC_5M_ENABLE_STOPLOSS",
    "BTC_5M_MAX_NET_LOSS",
    "BTC_5M_HARD_MAX_NET_LOSS",
    "BTC_5M_MIN_NET_PROFIT",
    "BTC_5M_MAX_DAILY_LIVE_LOSS",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        parsed = float(value)
    except Exception:
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def read_csv(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return []

    for row in rows:
        row["_dt"] = parse_time(row.get("timestamp"))
    return rows


def filter_window(rows: list[dict[str, Any]], hours: float) -> list[dict[str, Any]]:
    dated = [row for row in rows if row.get("_dt") is not None]
    if not dated:
        return []
    end = max(row["_dt"] for row in dated)
    start = end - timedelta(hours=hours)
    return [row for row in dated if start <= row["_dt"] <= end]


def load_redacted_env(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {key: "[missing]" for key in CONFIG_KEYS}

    parsed: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        parsed[key.strip()] = value.strip()

    for key in CONFIG_KEYS:
        if key not in parsed:
            values[key] = "[missing]"
        elif any(marker in key.upper() for marker in SECRET_MARKERS):
            values[key] = "[REDACTED]"
        else:
            values[key] = parsed[key]
    return values


def tradingagents_status() -> str:
    try:
        import tradingagents  # type: ignore  # noqa: F401
    except ModuleNotFoundError:
        return "missing_tradingagents_package"
    except Exception as exc:
        return f"tradingagents_import_error:{exc}"
    return "available_unconfigured"


def summarize_metrics(trades: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [row for row in trades if row.get("side") in CLOSED_ACTIONS]
    buys = [row for row in trades if row.get("side") == "BUY"]
    pnls = [parse_float(row.get("pnl")) for row in closed]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    action_counts = Counter(str(row.get("side", "")) for row in closed)
    decision_counts = Counter(str(row.get("action", "")) for row in decisions)
    reason_counts = Counter(str(row.get("reason", "")) for row in decisions)
    buy_markets = Counter(str(row.get("market_id", "")) for row in buys)
    repeated_buy_markets = sum(1 for count in buy_markets.values() if count > 1)

    return {
        "trades_rows": len(trades),
        "decision_rows": len(decisions),
        "buy_count": len(buys),
        "closed_count": len(closed),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "total_pnl": sum(pnls),
        "avg_closed_pnl": sum(pnls) / len(pnls) if pnls else 0.0,
        "largest_win": max(wins) if wins else 0.0,
        "largest_loss": min(losses) if losses else 0.0,
        "closed_action_counts": dict(action_counts),
        "decision_action_counts": dict(decision_counts),
        "top_decision_reasons": dict(reason_counts.most_common(8)),
        "repeated_buy_markets": repeated_buy_markets,
    }


def infer_loss_driver(metrics: dict[str, Any]) -> str:
    action_counts = metrics.get("closed_action_counts", {})
    if action_counts.get("STOPLOSS", 0) > 0:
        return "stoploss_exits"
    if action_counts.get("PROTECT_EXIT", 0) > 0:
        return "profit_protection_giveback_or_thesis_flip"
    if action_counts.get("TIME_EXIT", 0) > 0:
        return "late_time_exits"
    if metrics.get("repeated_buy_markets", 0) > 0:
        return "repeated_same_market_entries"
    if metrics.get("closed_count", 0) < 10:
        return "insufficient_closed_trade_sample"
    return "none_observed"


def infer_regime(decisions: list[dict[str, Any]]) -> str:
    if len(decisions) < 5:
        return "unknown"

    distances = [abs(parse_float(row.get("btc_price")) - parse_float(row.get("strike"))) for row in decisions]
    avg_distance = sum(distances) / len(distances) if distances else 0.0
    skip_reasons = Counter(str(row.get("reason", "")) for row in decisions)
    close_to_strike = skip_reasons.get("too_close_to_strike", 0)

    if close_to_strike / len(decisions) > 0.25:
        return "chop"
    if avg_distance > 25:
        return "trend"
    return "unknown"


def heuristic_review(
    trades: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    redacted_env: dict[str, str],
    hours: float,
) -> dict[str, Any]:
    metrics = summarize_metrics(trades, decisions)
    loss_driver = infer_loss_driver(metrics)
    regime = infer_regime(decisions)
    closed_count = int(metrics.get("closed_count", 0))
    loss_count = int(metrics.get("loss_count", 0))
    total_pnl = float(metrics.get("total_pnl", 0.0))

    recommended_action = "collect_more_data"
    allow_trading = True
    risk_level = "unknown"
    max_size_multiplier = 1.0
    suggested_next_experiment = "keep_collecting_diagnostic_data_until_50_closed_trades"
    confidence = 0.35
    notes = [
        "TradingAgents package is not installed; used local heuristic fallback.",
        "Review is advisory only and must not be consumed by the live bot before Phase 11.",
    ]

    if closed_count == 0:
        risk_level = "unknown"
        suggested_next_experiment = "collect_first_closed_trade_sample"
    elif closed_count < 50:
        risk_level = "medium" if loss_count else "unknown"
        confidence = 0.45
    elif loss_count / closed_count > 0.45 or total_pnl < 0:
        recommended_action = "reduce_risk"
        risk_level = "high"
        max_size_multiplier = 0.5
        suggested_next_experiment = "tighten_entry_quality_filters_before_size_changes"
        confidence = 0.65
    else:
        recommended_action = "keep_trading"
        risk_level = "medium"
        confidence = 0.60

    if loss_driver == "stoploss_exits":
        suggested_next_experiment = "review_same_market_stoploss_reentry_and_entry_confirmation"
    elif loss_driver == "repeated_same_market_entries":
        suggested_next_experiment = "audit_repeated_entries_per_market"

    if redacted_env.get("BTC_5M_MODE") == "live" and redacted_env.get("BTC_5M_ALLOW_REAL_ORDERS") == "true":
        notes.append("Live mode appears armed in redacted config; manually verify risk controls before running.")

    return {
        "schema_version": "1.0",
        "generated_at": utc_now(),
        "review_window_hours": hours,
        "source": "local_heuristic_fallback",
        "tradingagents_status": tradingagents_status(),
        "recommended_action": recommended_action,
        "allow_trading": allow_trading,
        "risk_level": risk_level,
        "regime": regime,
        "max_size_multiplier": max_size_multiplier,
        "main_loss_driver": loss_driver,
        "suggested_next_experiment": suggested_next_experiment,
        "do_not_change": ["order_size", "stoploss", "daily_loss", "live_mode"],
        "confidence": confidence,
        "metrics": metrics,
        "redacted_config": redacted_env,
        "notes": notes,
        "safety": {
            "offline_only": True,
            "does_not_edit_env": True,
            "does_not_edit_state": True,
            "does_not_place_orders": True,
            "live_bot_must_ignore_until_phase_11": True,
        },
    }


def write_json(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write a bounded offline TradingAgents-style daily BTC5M review JSON."
    )
    parser.add_argument("--trades", default=TRADES_FILE, help="Input trades CSV.")
    parser.add_argument("--decisions", default=DECISIONS_FILE, help="Input decisions CSV.")
    parser.add_argument("--env", default=ENV_FILE, help="Input .env path for redacted config fields.")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Output review JSON path.")
    parser.add_argument("--hours", type=float, default=24.0, help="Review window in hours from latest log row.")
    args = parser.parse_args()

    trades = filter_window(read_csv(args.trades), args.hours)
    decisions = filter_window(read_csv(args.decisions), args.hours)
    redacted_env = load_redacted_env(args.env)
    review = heuristic_review(trades, decisions, redacted_env, args.hours)
    review = validate_review(review)
    write_json(args.output, review)

    print(f"Wrote TradingAgents-style daily review to {args.output}")
    print(json.dumps(review, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
