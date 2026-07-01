import argparse
import csv
import json
from pathlib import Path
from typing import Any


BASE_FILE = "trade_quality_dataset.csv"
ML_FILE = "trade_quality_scored.csv"
KRONOS_FILE = "trade_quality_kronos_diagnostics.csv"
TIMESFM_FILE = "trade_quality_timesfm_diagnostics.csv"
CHRONOS_FILE = "trade_quality_chronos_diagnostics.csv"
OUTPUT_FILE = "trade_quality_combined_diagnostics.csv"
REPORT_FILE = "reports/combined_diagnostics_summary.json"

KEY_COLUMNS = ["candidate_timestamp", "market_id", "outcome"]

ML_COLUMNS = [
    "lgbm_probability_good_trade",
    "xgb_probability_good_trade",
    "ml_probability_good_trade",
    "ml_trade_quality_decision",
    "ml_scoring_mode",
]
KRONOS_COLUMNS = [
    "kronos_direction",
    "kronos_confidence",
    "kronos_expected_move",
    "kronos_agrees_with_trade",
    "kronos_available",
    "kronos_mode",
    "kronos_reason",
]
TIMESFM_COLUMNS = [
    "timesfm_direction",
    "timesfm_confidence",
    "timesfm_expected_move",
    "timesfm_agrees_with_trade",
    "timesfm_available",
    "timesfm_mode",
    "timesfm_reason",
]
CHRONOS_COLUMNS = [
    "chronos_direction",
    "chronos_confidence",
    "chronos_expected_move",
    "chronos_agrees_with_trade",
    "chronos_available",
    "chronos_mode",
    "chronos_reason",
]


def read_csv(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return tuple(str(row.get(column, "")) for column in KEY_COLUMNS)  # type: ignore[return-value]


def index_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        indexed[row_key(row)] = row
    return indexed


def add_columns(
    target: dict[str, Any],
    source_index: dict[tuple[str, str, str], dict[str, Any]],
    columns: list[str],
) -> bool:
    source = source_index.get(row_key(target))
    if source is None:
        for column in columns:
            target[column] = ""
        return False

    for column in columns:
        target[column] = source.get(column, "")
    return True


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def count_values(rows: list[dict[str, Any]], column: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(column, ""))
        counts[value] = counts.get(value, 0) + 1
    return counts


def agreement_count(row: dict[str, Any]) -> int:
    return sum(
        1
        for column in [
            "kronos_agrees_with_trade",
            "timesfm_agrees_with_trade",
            "chronos_agrees_with_trade",
        ]
        if truthy(row.get(column))
    )


def add_ensemble_columns(row: dict[str, Any]) -> None:
    row["forecast_agreement_count"] = agreement_count(row)
    row["forecast_agreement_available_count"] = sum(
        1
        for column in [
            "kronos_agrees_with_trade",
            "timesfm_agrees_with_trade",
            "chronos_agrees_with_trade",
        ]
        if str(row.get(column, "")) != ""
    )
    row["diagnostic_only"] = "true"


def combine_rows(
    base_rows: list[dict[str, Any]],
    ml_rows: list[dict[str, Any]],
    kronos_rows: list[dict[str, Any]],
    timesfm_rows: list[dict[str, Any]],
    chronos_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    ml_index = index_rows(ml_rows)
    kronos_index = index_rows(kronos_rows)
    timesfm_index = index_rows(timesfm_rows)
    chronos_index = index_rows(chronos_rows)
    match_counts = {
        "ml": 0,
        "kronos": 0,
        "timesfm": 0,
        "chronos": 0,
    }

    combined: list[dict[str, Any]] = []
    for base_row in base_rows:
        row = dict(base_row)
        if add_columns(row, ml_index, ML_COLUMNS):
            match_counts["ml"] += 1
        if add_columns(row, kronos_index, KRONOS_COLUMNS):
            match_counts["kronos"] += 1
        if add_columns(row, timesfm_index, TIMESFM_COLUMNS):
            match_counts["timesfm"] += 1
        if add_columns(row, chronos_index, CHRONOS_COLUMNS):
            match_counts["chronos"] += 1
        add_ensemble_columns(row)
        combined.append(row)

    return combined, match_counts


def write_csv(path: str, rows: list[dict[str, Any]], base_fieldnames: list[str]) -> None:
    fieldnames = list(base_fieldnames)
    for column in (
        ML_COLUMNS
        + KRONOS_COLUMNS
        + TIMESFM_COLUMNS
        + CHRONOS_COLUMNS
        + [
            "forecast_agreement_count",
            "forecast_agreement_available_count",
            "diagnostic_only",
        ]
    ):
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


def summarize(rows: list[dict[str, Any]], match_counts: dict[str, int]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "match_counts": match_counts,
        "ml_decision_counts": count_values(rows, "ml_trade_quality_decision"),
        "kronos_direction_counts": count_values(rows, "kronos_direction"),
        "timesfm_direction_counts": count_values(rows, "timesfm_direction"),
        "chronos_direction_counts": count_values(rows, "chronos_direction"),
        "forecast_agreement_count_distribution": count_values(rows, "forecast_agreement_count"),
        "forecast_agreement_available_count_distribution": count_values(
            rows,
            "forecast_agreement_available_count",
        ),
        "safety": "diagnostic_only_no_live_blocking",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combine offline ML and forecast diagnostics into one BTC5M research table."
    )
    parser.add_argument("--base", default=BASE_FILE, help="Base trade-quality dataset CSV.")
    parser.add_argument("--ml", default=ML_FILE, help="ML-scored diagnostics CSV.")
    parser.add_argument("--kronos", default=KRONOS_FILE, help="Kronos diagnostics CSV.")
    parser.add_argument("--timesfm", default=TIMESFM_FILE, help="TimesFM diagnostics CSV.")
    parser.add_argument("--chronos", default=CHRONOS_FILE, help="Chronos diagnostics CSV.")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Output combined diagnostics CSV.")
    parser.add_argument("--report", default=REPORT_FILE, help="Output combined summary JSON.")
    args = parser.parse_args()

    base_rows = read_csv(args.base)
    base_fieldnames = list(base_rows[0].keys()) if base_rows else []
    combined_rows, match_counts = combine_rows(
        base_rows=base_rows,
        ml_rows=read_csv(args.ml),
        kronos_rows=read_csv(args.kronos),
        timesfm_rows=read_csv(args.timesfm),
        chronos_rows=read_csv(args.chronos),
    )

    write_csv(args.output, combined_rows, base_fieldnames)
    report = summarize(combined_rows, match_counts)
    write_json(args.report, report)

    print(f"Wrote {len(combined_rows)} rows to {args.output}")
    print(f"Wrote summary to {args.report}")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
