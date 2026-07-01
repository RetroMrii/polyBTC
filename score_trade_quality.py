import argparse
import csv
import json
import math
import pickle
from pathlib import Path
from typing import Any, Optional


INPUT_FILE = "trade_quality_dataset.csv"
OUTPUT_FILE = "trade_quality_scored.csv"
REPORT_FILE = "reports/trade_quality_scoring_summary.json"
LIGHTGBM_MODEL_FILE = "models/lightgbm_trade_quality.pkl"
XGBOOST_MODEL_FILE = "models/xgboost_trade_quality.pkl"

DEFAULT_FEATURE_COLUMNS = [
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
]


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
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_model(path: str) -> tuple[Optional[Any], list[str], str]:
    model_path = Path(path)
    if not model_path.exists():
        return None, DEFAULT_FEATURE_COLUMNS, "missing_model"

    try:
        with model_path.open("rb") as f:
            payload = pickle.load(f)
    except Exception as exc:
        return None, DEFAULT_FEATURE_COLUMNS, f"load_error:{exc}"

    if isinstance(payload, dict) and "model" in payload:
        model = payload["model"]
        feature_columns = list(payload.get("feature_columns") or DEFAULT_FEATURE_COLUMNS)
    else:
        model = payload
        feature_columns = DEFAULT_FEATURE_COLUMNS

    return model, feature_columns, "ok"


def make_x(rows: list[dict[str, Any]], feature_columns: list[str]) -> list[list[float]]:
    return [
        [parse_float(row.get(column)) for column in feature_columns]
        for row in rows
    ]


def predict_probabilities(model: Any, rows: list[dict[str, Any]], feature_columns: list[str]) -> list[Optional[float]]:
    if model is None:
        return [None for _ in rows]

    x = make_x(rows, feature_columns)
    try:
        raw_probabilities = model.predict_proba(x)
    except Exception:
        return [None for _ in rows]

    probabilities: list[Optional[float]] = []
    for value in raw_probabilities:
        try:
            probabilities.append(float(value[1]))
        except Exception:
            probabilities.append(None)
    return probabilities


def format_probability(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.8f}"


def diagnostic_decision(lgbm_probability: Optional[float], xgb_probability: Optional[float], threshold: float) -> str:
    values = [value for value in [lgbm_probability, xgb_probability] if value is not None]
    if not values:
        return "no_model"

    avg_probability = sum(values) / len(values)
    return "diagnostic_approve" if avg_probability >= threshold else "diagnostic_reject"


def write_csv(path: str, rows: list[dict[str, Any]], original_fieldnames: list[str]) -> None:
    fieldnames = list(original_fieldnames)
    for column in [
        "lgbm_probability_good_trade",
        "xgb_probability_good_trade",
        "ml_probability_good_trade",
        "ml_trade_quality_decision",
        "ml_scoring_mode",
    ]:
        if column not in fieldnames:
            fieldnames.append(column)

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
        description="Score trade-quality rows offline with trained ML models in diagnostic-only mode."
    )
    parser.add_argument("--input", default=INPUT_FILE, help="Input trade-quality dataset CSV.")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Output scored CSV path.")
    parser.add_argument("--report", default=REPORT_FILE, help="Output scoring summary JSON path.")
    parser.add_argument("--lightgbm-model", default=LIGHTGBM_MODEL_FILE, help="LightGBM model pickle path.")
    parser.add_argument("--xgboost-model", default=XGBOOST_MODEL_FILE, help="XGBoost model pickle path.")
    parser.add_argument("--threshold", type=float, default=0.5, help="Diagnostic approve/reject threshold.")
    args = parser.parse_args()

    rows = read_csv(args.input)
    original_fieldnames = list(rows[0].keys()) if rows else []

    lgbm_model, lgbm_features, lgbm_status = load_model(args.lightgbm_model)
    xgb_model, xgb_features, xgb_status = load_model(args.xgboost_model)

    lgbm_probabilities = predict_probabilities(lgbm_model, rows, lgbm_features)
    xgb_probabilities = predict_probabilities(xgb_model, rows, xgb_features)

    decisions = []
    for row, lgbm_probability, xgb_probability in zip(rows, lgbm_probabilities, xgb_probabilities):
        values = [value for value in [lgbm_probability, xgb_probability] if value is not None]
        avg_probability = (sum(values) / len(values)) if values else None
        decision = diagnostic_decision(lgbm_probability, xgb_probability, args.threshold)
        decisions.append(decision)

        row["lgbm_probability_good_trade"] = format_probability(lgbm_probability)
        row["xgb_probability_good_trade"] = format_probability(xgb_probability)
        row["ml_probability_good_trade"] = format_probability(avg_probability)
        row["ml_trade_quality_decision"] = decision
        row["ml_scoring_mode"] = "diagnostic_only"

    write_csv(args.output, rows, original_fieldnames)

    report = {
        "input": args.input,
        "output": args.output,
        "rows_scored": len(rows),
        "mode": "diagnostic_only",
        "threshold": args.threshold,
        "lightgbm_model": args.lightgbm_model,
        "lightgbm_status": lgbm_status,
        "xgboost_model": args.xgboost_model,
        "xgboost_status": xgb_status,
        "decision_counts": {decision: decisions.count(decision) for decision in sorted(set(decisions))},
    }
    write_json(args.report, report)

    print(f"Wrote {len(rows)} scored rows to {args.output}")
    print(f"Wrote summary to {args.report}")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
