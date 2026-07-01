import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any


INPUT_FILE = "trade_quality_dataset.csv"
OUTPUT_FILE = "trade_quality_kronos_diagnostics.csv"
REPORT_FILE = "reports/kronos_diagnostic_summary.json"

KronosDiagnostic = dict[str, Any]


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


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def read_csv(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def load_kronos_backend() -> tuple[Any, str]:
    try:
        import kronos  # type: ignore
    except ModuleNotFoundError:
        return None, "missing_kronos_package"
    except Exception as exc:
        return None, f"kronos_import_error:{exc}"

    return kronos, "available_unconfigured"


def trade_direction(row: dict[str, Any]) -> str:
    outcome = str(row.get("outcome", "")).upper()
    if outcome == "YES":
        return "up"
    if outcome == "NO":
        return "down"
    return "unknown"


def unknown_diagnostic(row: dict[str, Any], reason: str) -> KronosDiagnostic:
    return {
        "kronos_direction": "unknown",
        "kronos_confidence": 0.0,
        "kronos_expected_move": 0.0,
        "kronos_agrees_with_trade": "",
        "kronos_available": False,
        "kronos_mode": "diagnostic",
        "kronos_reason": reason,
    }


def heuristic_diagnostic(row: dict[str, Any]) -> KronosDiagnostic:
    """Deterministic placeholder for pipeline tests; not a Kronos model."""
    distance = parse_float(row.get("distance_from_strike"))
    abs_distance = abs(distance)
    direction = "up" if distance > 0 else "down" if distance < 0 else "flat"
    expected_move = distance
    confidence = min(0.75, max(0.0, abs_distance * 1000.0))
    agrees = direction == trade_direction(row)

    return {
        "kronos_direction": direction,
        "kronos_confidence": confidence,
        "kronos_expected_move": expected_move,
        "kronos_agrees_with_trade": agrees,
        "kronos_available": False,
        "kronos_mode": "diagnostic_placeholder",
        "kronos_reason": "placeholder_heuristic_not_kronos_model",
    }


def diagnostic_for_row(
    row: dict[str, Any],
    enabled: bool,
    backend_status: str,
    allow_placeholder: bool,
) -> KronosDiagnostic:
    if not enabled:
        return unknown_diagnostic(row, "disabled_by_config")

    if backend_status != "available_unconfigured":
        if allow_placeholder:
            return heuristic_diagnostic(row)
        return unknown_diagnostic(row, backend_status)

    return unknown_diagnostic(row, "kronos_backend_available_but_no_model_adapter_configured")


def write_csv(path: str, rows: list[dict[str, Any]], original_fieldnames: list[str]) -> None:
    fieldnames = list(original_fieldnames)
    for column in [
        "kronos_direction",
        "kronos_confidence",
        "kronos_expected_move",
        "kronos_agrees_with_trade",
        "kronos_available",
        "kronos_mode",
        "kronos_reason",
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


def summarize(rows: list[dict[str, Any]], enabled: bool, backend_status: str) -> dict[str, Any]:
    direction_counts: dict[str, int] = {}
    agreement_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}

    for row in rows:
        direction = str(row.get("kronos_direction", ""))
        direction_counts[direction] = direction_counts.get(direction, 0) + 1
        agreement = str(row.get("kronos_agrees_with_trade", ""))
        agreement_counts[agreement] = agreement_counts.get(agreement, 0) + 1
        reason = str(row.get("kronos_reason", ""))
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return {
        "rows": len(rows),
        "enabled": enabled,
        "mode": os.getenv("BTC_5M_KRONOS_MODE", "diagnostic"),
        "require_agreement": env_bool("BTC_5M_KRONOS_REQUIRE_AGREEMENT", False),
        "min_confidence": parse_float(os.getenv("BTC_5M_KRONOS_MIN_CONFIDENCE"), 0.60),
        "backend_status": backend_status,
        "direction_counts": direction_counts,
        "agreement_counts": agreement_counts,
        "reason_counts": reason_counts,
        "safety": "diagnostic_only_no_live_blocking",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add Kronos-style diagnostic columns to offline BTC5M candidate rows."
    )
    parser.add_argument("--input", default=INPUT_FILE, help="Input trade-quality dataset CSV.")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Output CSV with Kronos diagnostic columns.")
    parser.add_argument("--report", default=REPORT_FILE, help="Output diagnostic summary JSON.")
    parser.add_argument(
        "--allow-placeholder",
        action="store_true",
        help="Use a deterministic distance-from-strike placeholder when Kronos is unavailable.",
    )
    args = parser.parse_args()

    rows = read_csv(args.input)
    original_fieldnames = list(rows[0].keys()) if rows else []
    enabled = env_bool("BTC_5M_ENABLE_KRONOS", False)
    _, backend_status = load_kronos_backend()

    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        enriched.update(
            diagnostic_for_row(
                row=enriched,
                enabled=enabled,
                backend_status=backend_status,
                allow_placeholder=args.allow_placeholder,
            )
        )
        enriched_rows.append(enriched)

    write_csv(args.output, enriched_rows, original_fieldnames)
    report = summarize(enriched_rows, enabled=enabled, backend_status=backend_status)
    write_json(args.report, report)

    print(f"Wrote {len(enriched_rows)} rows to {args.output}")
    print(f"Wrote summary to {args.report}")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
