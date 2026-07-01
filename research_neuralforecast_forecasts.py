import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


DECISIONS_FILE = "btc_5m_decisions.csv"
REPORT_FILE = "reports/neuralforecast_report.json"


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


def read_decisions(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return []
    return sorted(rows, key=lambda row: row.get("timestamp", ""))


def package_status() -> str:
    try:
        import neuralforecast  # type: ignore  # noqa: F401
    except ModuleNotFoundError:
        return "missing_neuralforecast_package"
    except Exception as exc:
        return f"neuralforecast_import_error:{exc}"
    return "available_unconfigured"


def sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def direction_label(value: int) -> str:
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def build_series(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    series: list[dict[str, Any]] = []
    for row in rows:
        btc_price = parse_float(row.get("btc_price"))
        strike = parse_float(row.get("strike"))
        if btc_price <= 0:
            continue
        series.append(
            {
                "timestamp": row.get("timestamp", ""),
                "btc_price": btc_price,
                "strike": strike,
                "distance_from_strike": ((btc_price - strike) / strike) if strike > 0 else 0.0,
            }
        )
    return series


def rolling_mean_baseline(series: list[dict[str, Any]], window: int) -> dict[str, Any]:
    if len(series) <= window + 1:
        return {
            "model": f"rolling_mean_delta_window_{window}",
            "evaluated_steps": 0,
            "direction_accuracy": 0.0,
            "mae_next_delta": 0.0,
            "notes": [f"Need more than {window + 1} observations for this benchmark."],
        }

    hits = 0
    evaluated = 0
    absolute_errors: list[float] = []
    prediction_counts: dict[str, int] = {}
    actual_counts: dict[str, int] = {}

    deltas = [
        series[idx]["btc_price"] - series[idx - 1]["btc_price"]
        for idx in range(1, len(series))
    ]

    for delta_idx in range(window, len(deltas)):
        predicted_delta = sum(deltas[delta_idx - window : delta_idx]) / window
        actual_delta = deltas[delta_idx]
        predicted_direction = sign(predicted_delta)
        actual_direction = sign(actual_delta)

        if actual_direction == 0:
            continue

        evaluated += 1
        hits += int(predicted_direction == actual_direction)
        absolute_errors.append(abs(predicted_delta - actual_delta))
        prediction_label = direction_label(predicted_direction)
        actual_label = direction_label(actual_direction)
        prediction_counts[prediction_label] = prediction_counts.get(prediction_label, 0) + 1
        actual_counts[actual_label] = actual_counts.get(actual_label, 0) + 1

    return {
        "model": f"rolling_mean_delta_window_{window}",
        "evaluated_steps": evaluated,
        "direction_accuracy": hits / evaluated if evaluated else 0.0,
        "mae_next_delta": sum(absolute_errors) / len(absolute_errors) if absolute_errors else 0.0,
        "prediction_direction_counts": prediction_counts,
        "actual_direction_counts": actual_counts,
        "notes": [
            "This is a local naive benchmark, not a NeuralForecast model.",
            "Use it as a minimum baseline before adding neural models.",
        ],
    }


def write_json(path: str, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline NeuralForecast research benchmark for BTC5M drift forecasting."
    )
    parser.add_argument("--decisions", default=DECISIONS_FILE, help="Input decisions CSV.")
    parser.add_argument("--report", default=REPORT_FILE, help="Output NeuralForecast report JSON.")
    parser.add_argument("--window", type=int, default=3, help="Rolling delta window for the local baseline.")
    args = parser.parse_args()

    rows = read_decisions(args.decisions)
    series = build_series(rows)
    report = {
        "input": args.decisions,
        "rows_read": len(rows),
        "series_points": len(series),
        "package_status": package_status(),
        "mode": "offline_research_only",
        "safety": "no_live_trading_no_order_placement",
        "target": "next_observed_btc_price_delta_direction",
        "baseline": rolling_mean_baseline(series, window=max(1, args.window)),
        "future_neuralforecast_models": [
            "NBEATS",
            "NHITS",
            "TFT",
            "PatchTST",
            "iTransformer",
        ],
    }
    write_json(args.report, report)

    print(f"Wrote NeuralForecast research report to {args.report}")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
