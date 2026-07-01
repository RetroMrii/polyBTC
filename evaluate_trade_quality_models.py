import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Optional


SCORED_FILE = "trade_quality_scored.csv"
REPORT_FILE = "reports/trade_quality_model_evaluation.json"

TARGET_COLUMN = "target_good_trade"
PNL_COLUMN = "close_pnl"
PROBABILITY_COLUMNS = [
    "ml_probability_good_trade",
    "lgbm_probability_good_trade",
    "xgb_probability_good_trade",
]


def parse_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        parsed = float(value)
    except Exception:
        return default

    if not math.isfinite(parsed):
        return default

    return parsed


def parse_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def read_csv(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [row for row in rows if parse_int(row.get(TARGET_COLUMN)) in {0, 1}]
    wins = [row for row in labeled if parse_int(row.get(TARGET_COLUMN)) == 1]
    losses = [row for row in labeled if parse_int(row.get(TARGET_COLUMN)) == 0]
    pnls = [parse_float(row.get(PNL_COLUMN), 0.0) or 0.0 for row in labeled]

    return {
        "rows": len(rows),
        "labeled_rows": len(labeled),
        "good_trades": len(wins),
        "bad_trades": len(losses),
        "good_trade_rate": len(wins) / len(labeled) if labeled else 0.0,
        "total_pnl": sum(pnls),
        "avg_pnl": sum(pnls) / len(pnls) if pnls else 0.0,
    }


def threshold_metrics(
    rows: list[dict[str, Any]],
    probability_column: str,
    threshold: float,
) -> dict[str, Any]:
    scored = [
        row
        for row in rows
        if parse_int(row.get(TARGET_COLUMN)) in {0, 1}
        and parse_float(row.get(probability_column), None) is not None
    ]

    approved = [
        row
        for row in scored
        if (parse_float(row.get(probability_column), 0.0) or 0.0) >= threshold
    ]
    rejected = [
        row
        for row in scored
        if (parse_float(row.get(probability_column), 0.0) or 0.0) < threshold
    ]

    def group_stats(group: list[dict[str, Any]]) -> dict[str, Any]:
        good = [row for row in group if parse_int(row.get(TARGET_COLUMN)) == 1]
        bad = [row for row in group if parse_int(row.get(TARGET_COLUMN)) == 0]
        pnls = [parse_float(row.get(PNL_COLUMN), 0.0) or 0.0 for row in group]
        close_actions: dict[str, int] = {}
        for row in group:
            close_action = str(row.get("close_action", ""))
            close_actions[close_action] = close_actions.get(close_action, 0) + 1

        return {
            "rows": len(group),
            "good_trades": len(good),
            "bad_trades": len(bad),
            "good_trade_rate": len(good) / len(group) if group else 0.0,
            "bad_trade_rate": len(bad) / len(group) if group else 0.0,
            "total_pnl": sum(pnls),
            "avg_pnl": sum(pnls) / len(pnls) if pnls else 0.0,
            "close_action_counts": close_actions,
        }

    approved_stats = group_stats(approved)
    rejected_stats = group_stats(rejected)
    return {
        "probability_column": probability_column,
        "threshold": threshold,
        "scored_rows": len(scored),
        "approved": approved_stats,
        "rejected": rejected_stats,
        "approved_minus_rejected_good_trade_rate": (
            approved_stats["good_trade_rate"] - rejected_stats["good_trade_rate"]
        ),
        "approved_minus_rejected_avg_pnl": approved_stats["avg_pnl"] - rejected_stats["avg_pnl"],
    }


def build_report(rows: list[dict[str, Any]], thresholds: list[float]) -> dict[str, Any]:
    report = {
        "input_rows": summarize_rows(rows),
        "probability_columns": {},
        "notes": [],
    }

    for probability_column in PROBABILITY_COLUMNS:
        scored_count = sum(1 for row in rows if parse_float(row.get(probability_column), None) is not None)
        report["probability_columns"][probability_column] = {
            "scored_rows": scored_count,
            "thresholds": [
                threshold_metrics(rows, probability_column, threshold)
                for threshold in thresholds
            ],
        }

    if not any(
        report["probability_columns"][column]["scored_rows"] > 0
        for column in PROBABILITY_COLUMNS
    ):
        report["notes"].append(
            "No model probabilities are available yet. Train LightGBM/XGBoost models, then rerun score_trade_quality.py."
        )

    if report["input_rows"]["labeled_rows"] < 50:
        report["notes"].append(
            "Fewer than 50 labeled rows are available; treat all evaluation numbers as smoke-test diagnostics only."
        )

    return report


def write_json(path: str, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate diagnostic ML trade-quality scores against closed-trade labels."
    )
    parser.add_argument("--input", default=SCORED_FILE, help="Input scored trade-quality CSV.")
    parser.add_argument("--output", default=REPORT_FILE, help="Output evaluation JSON path.")
    parser.add_argument(
        "--thresholds",
        default="0.4,0.5,0.6,0.7",
        help="Comma-separated probability thresholds to evaluate.",
    )
    args = parser.parse_args()

    thresholds = [
        parse_float(part.strip(), None)
        for part in args.thresholds.split(",")
        if part.strip()
    ]
    thresholds = [threshold for threshold in thresholds if threshold is not None]

    rows = read_csv(args.input)
    report = build_report(rows, thresholds)
    write_json(args.output, report)

    print(f"Wrote evaluation report to {args.output}")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
