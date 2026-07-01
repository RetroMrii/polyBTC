import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


DECISIONS_FILE = "btc_5m_decisions.csv"
TRADES_FILE = "btc_5m_trades.csv"
OUTPUT_FILE = "trade_quality_dataset.csv"
REPORT_FILE = "reports/trade_quality_dataset_summary.json"

GOOD_CLOSE_ACTIONS = {"CASHOUT"}
BAD_CLOSE_ACTIONS = {"STOPLOSS", "PROTECT_EXIT", "TIME_EXIT", "EXIT", "EXIT_INCOMPLETE"}
CLOSED_ACTIONS = GOOD_CLOSE_ACTIONS | BAD_CLOSE_ACTIONS | {"TRAIL_EXIT", "RECONCILED_EXIT", "SETTLE"}


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
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def add_dt(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        row2 = dict(row)
        row2["_dt"] = parse_time(row.get("timestamp"))
        out.append(row2)
    return out


def infer_candidate_outcome(row: dict[str, Any]) -> Optional[str]:
    reason = str(row.get("reason", "")).lower()
    if reason.startswith("yes_") or " yes_" in reason:
        return "YES"
    if reason.startswith("no_") or " no_" in reason:
        return "NO"

    btc_price = parse_float(row.get("btc_price"))
    strike = parse_float(row.get("strike"))
    if strike <= 0 or btc_price == strike:
        return None
    return "YES" if btc_price > strike else "NO"


def selected_book_features(row: dict[str, Any], outcome: str) -> dict[str, float]:
    yes_bid = parse_float(row.get("yes_bid"))
    yes_ask = parse_float(row.get("yes_ask"))
    no_bid = parse_float(row.get("no_bid"))
    no_ask = parse_float(row.get("no_ask"))

    yes_spread = max(0.0, yes_ask - yes_bid)
    no_spread = max(0.0, no_ask - no_bid)

    if outcome == "YES":
        selected_bid = yes_bid
        selected_ask = yes_ask
        selected_spread = yes_spread
        opposite_bid = no_bid
        opposite_ask = no_ask
        opposite_spread = no_spread
    else:
        selected_bid = no_bid
        selected_ask = no_ask
        selected_spread = no_spread
        opposite_bid = yes_bid
        opposite_ask = yes_ask
        opposite_spread = yes_spread

    return {
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "yes_spread": yes_spread,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "no_spread": no_spread,
        "selected_bid": selected_bid,
        "selected_ask": selected_ask,
        "selected_spread": selected_spread,
        "opposite_bid": opposite_bid,
        "opposite_ask": opposite_ask,
        "opposite_spread": opposite_spread,
    }


def reason_flags(reason: str) -> dict[str, int]:
    reason_lower = reason.lower()
    return {
        "reason_yes_positive_edge_with_trend": int(reason_lower == "yes_positive_edge_with_trend"),
        "reason_no_positive_edge_with_trend": int(reason_lower == "no_positive_edge_with_trend"),
        "reason_same_market_stoploss_reentry_blocked": int(
            reason_lower == "same_market_stoploss_reentry_blocked"
        ),
    }


def extract_reason_number(reason: str, name: str) -> float:
    match = re.search(rf"\b{re.escape(name)}=([-+]?\d+(?:\.\d+)?)", reason)
    if not match:
        return 0.0
    return parse_float(match.group(1))


def find_next_close(
    close_trades: list[dict[str, Any]],
    market_id: str,
    outcome: str,
    after_dt: datetime,
) -> Optional[dict[str, Any]]:
    candidates = [
        trade
        for trade in close_trades
        if trade.get("market_id") == market_id
        and trade.get("outcome") == outcome
        and trade.get("_dt") is not None
        and trade["_dt"] >= after_dt
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda trade: trade["_dt"])


def find_nearby_entry(
    buy_trades: list[dict[str, Any]],
    market_id: str,
    outcome: str,
    candidate_dt: datetime,
    close_dt: datetime,
    tolerance_seconds: float,
) -> Optional[dict[str, Any]]:
    candidates = [
        trade
        for trade in buy_trades
        if trade.get("market_id") == market_id
        and trade.get("outcome") == outcome
        and trade.get("_dt") is not None
        and candidate_dt <= trade["_dt"] <= close_dt
        and abs((trade["_dt"] - candidate_dt).total_seconds()) <= tolerance_seconds
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda trade: abs((trade["_dt"] - candidate_dt).total_seconds()))


def prior_market_stoploss(close_trades: list[dict[str, Any]], market_id: str, before_dt: datetime) -> bool:
    return any(
        trade.get("market_id") == market_id
        and trade.get("side") == "STOPLOSS"
        and trade.get("_dt") is not None
        and trade["_dt"] < before_dt
        for trade in close_trades
    )


def make_dataset_rows(
    decisions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    entry_match_tolerance_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    decisions = sorted(add_dt(decisions), key=lambda row: row.get("_dt") or datetime.min.replace(tzinfo=timezone.utc))
    trades = sorted(add_dt(trades), key=lambda row: row.get("_dt") or datetime.min.replace(tzinfo=timezone.utc))

    buy_trades = [row for row in trades if row.get("side") == "BUY" and row.get("_dt") is not None]
    close_trades = [row for row in trades if row.get("side") in CLOSED_ACTIONS and row.get("_dt") is not None]

    rows: list[dict[str, Any]] = []
    skipped = Counter()
    seen_buy_count_by_market: Counter[str] = Counter()
    seen_buy_count_by_market_outcome: Counter[tuple[str, str]] = Counter()
    last_buy_dt_by_market: dict[str, datetime] = {}
    last_buy_dt_by_market_outcome: dict[tuple[str, str], datetime] = {}

    for decision in decisions:
        decision_dt = decision.get("_dt")
        if decision.get("action") != "BUY":
            continue
        if decision_dt is None:
            skipped["missing_candidate_timestamp"] += 1
            continue

        market_id = str(decision.get("market_id", ""))
        if not market_id:
            skipped["missing_market_id"] += 1
            continue

        outcome = infer_candidate_outcome(decision)
        if outcome not in {"YES", "NO"}:
            skipped["could_not_infer_outcome"] += 1
            continue

        close = find_next_close(close_trades, market_id, outcome, decision_dt)
        if close is None:
            skipped["no_later_close"] += 1
            continue

        close_action = str(close.get("side", ""))
        pnl = parse_float(close.get("pnl"))
        if close_action in GOOD_CLOSE_ACTIONS and pnl > 0:
            target = 1
        elif close_action in BAD_CLOSE_ACTIONS or pnl < 0:
            target = 0
        else:
            skipped[f"neutral_close_{close_action or 'unknown'}"] += 1
            continue

        close_dt = close["_dt"]
        entry = find_nearby_entry(
            buy_trades=buy_trades,
            market_id=market_id,
            outcome=outcome,
            candidate_dt=decision_dt,
            close_dt=close_dt,
            tolerance_seconds=entry_match_tolerance_seconds,
        )

        btc_price = parse_float(decision.get("btc_price"))
        strike = parse_float(decision.get("strike"))
        distance_from_strike = ((btc_price - strike) / strike) if strike > 0 else 0.0
        book = selected_book_features(decision, outcome)
        reason = str(decision.get("reason", ""))
        market_key = (market_id, outcome)

        previous_market_buy_count = seen_buy_count_by_market[market_id]
        previous_same_side_buy_count = seen_buy_count_by_market_outcome[market_key]
        last_market_dt = last_buy_dt_by_market.get(market_id)
        last_same_side_dt = last_buy_dt_by_market_outcome.get(market_key)

        row = {
            "candidate_timestamp": decision.get("timestamp", ""),
            "market_id": market_id,
            "question": decision.get("question", ""),
            "outcome": outcome,
            "target_good_trade": target,
            "close_action": close_action,
            "close_timestamp": close.get("timestamp", ""),
            "close_pnl": pnl,
            "hold_seconds_to_close": (close_dt - decision_dt).total_seconds(),
            "entry_trade_timestamp": entry.get("timestamp", "") if entry else "",
            "is_entry_trade_row": int(entry is not None),
            "entry_trade_price": parse_float(entry.get("price")) if entry else 0.0,
            "entry_trade_size": parse_float(entry.get("size")) if entry else 0.0,
            "candidate_price": book["selected_ask"],
            "btc_price": btc_price,
            "strike": strike,
            "distance_from_strike": distance_from_strike,
            "abs_distance_from_strike": abs(distance_from_strike),
            "seconds_to_expiry": parse_float(decision.get("seconds_to_expiry")),
            "model_probability": parse_float(decision.get("model_probability")),
            "market_probability": parse_float(decision.get("market_probability")),
            "edge": parse_float(decision.get("edge")),
            "reason": reason,
            "outcome_yes": int(outcome == "YES"),
            "outcome_no": int(outcome == "NO"),
            "previous_buy_count_same_market": previous_market_buy_count,
            "previous_buy_count_same_market_outcome": previous_same_side_buy_count,
            "same_market_prior_stoploss": int(prior_market_stoploss(close_trades, market_id, decision_dt)),
            "seconds_since_last_buy_same_market": (
                (decision_dt - last_market_dt).total_seconds() if last_market_dt else -1.0
            ),
            "seconds_since_last_buy_same_market_outcome": (
                (decision_dt - last_same_side_dt).total_seconds() if last_same_side_dt else -1.0
            ),
            "reason_cooldown_remaining_seconds": extract_reason_number(reason, "cooldown_remaining"),
        }
        row.update(book)
        row.update(reason_flags(reason))
        rows.append(row)

        seen_buy_count_by_market[market_id] += 1
        seen_buy_count_by_market_outcome[market_key] += 1
        last_buy_dt_by_market[market_id] = decision_dt
        last_buy_dt_by_market_outcome[market_key] = decision_dt

    summary = {
        "candidate_buy_decisions": sum(1 for row in decisions if row.get("action") == "BUY"),
        "dataset_rows": len(rows),
        "target_counts": dict(Counter(str(row["target_good_trade"]) for row in rows)),
        "close_action_counts": dict(Counter(str(row["close_action"]) for row in rows)),
        "skipped": dict(skipped),
    }
    return rows, summary


def write_csv(path: str, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "candidate_timestamp",
        "market_id",
        "question",
        "outcome",
        "target_good_trade",
        "close_action",
        "close_timestamp",
        "close_pnl",
        "hold_seconds_to_close",
        "entry_trade_timestamp",
        "is_entry_trade_row",
        "entry_trade_price",
        "entry_trade_size",
        "candidate_price",
        "btc_price",
        "strike",
        "distance_from_strike",
        "abs_distance_from_strike",
        "seconds_to_expiry",
        "model_probability",
        "market_probability",
        "edge",
        "yes_bid",
        "yes_ask",
        "yes_spread",
        "no_bid",
        "no_ask",
        "no_spread",
        "selected_bid",
        "selected_ask",
        "selected_spread",
        "opposite_bid",
        "opposite_ask",
        "opposite_spread",
        "outcome_yes",
        "outcome_no",
        "previous_buy_count_same_market",
        "previous_buy_count_same_market_outcome",
        "same_market_prior_stoploss",
        "seconds_since_last_buy_same_market",
        "seconds_since_last_buy_same_market_outcome",
        "reason_yes_positive_edge_with_trend",
        "reason_no_positive_edge_with_trend",
        "reason_same_market_stoploss_reentry_blocked",
        "reason_cooldown_remaining_seconds",
        "reason",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: str, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build an offline BTC5M trade-quality dataset from decision and trade CSV logs."
    )
    parser.add_argument("--decisions", default=DECISIONS_FILE, help="Input decisions CSV path.")
    parser.add_argument("--trades", default=TRADES_FILE, help="Input trades CSV path.")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Output dataset CSV path.")
    parser.add_argument("--report", default=REPORT_FILE, help="Output summary JSON path.")
    parser.add_argument(
        "--entry-match-tolerance-seconds",
        type=float,
        default=10.0,
        help="Mark a candidate as the actual entry row if a BUY trade follows within this many seconds.",
    )
    args = parser.parse_args()

    rows, summary = make_dataset_rows(
        decisions=read_csv(args.decisions),
        trades=read_csv(args.trades),
        entry_match_tolerance_seconds=args.entry_match_tolerance_seconds,
    )

    write_csv(args.output, rows)
    write_json(args.report, summary)

    print(f"Wrote {len(rows)} rows to {args.output}")
    print(f"Wrote summary to {args.report}")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
