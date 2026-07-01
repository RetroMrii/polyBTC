import argparse
import csv
import json
from pathlib import Path
from typing import Any


DATASET_FILE = "trade_quality_dataset.csv"
REVIEW_FILE = "tradingagents_daily_review.json"
OUTPUT_FILE = "phase11_readiness_report.json"


def read_csv(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def read_json(path: str) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {"_error": "invalid_json"}


def count_targets(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"0": 0, "1": 0}
    for row in rows:
        target = str(row.get("target_good_trade", ""))
        if target in counts:
            counts[target] += 1
    return counts


def build_report(dataset_rows: list[dict[str, Any]], review: dict[str, Any]) -> dict[str, Any]:
    target_counts = count_targets(dataset_rows)
    closed_count = int(review.get("metrics", {}).get("closed_count", 0) or 0)
    review_confidence = float(review.get("confidence", 0.0) or 0.0)
    tradingagents_status = str(review.get("tradingagents_status", "missing_review"))
    source = str(review.get("source", "missing_review"))

    checks = {
        "has_at_least_50_labeled_rows": len(dataset_rows) >= 50,
        "has_both_target_classes": target_counts["0"] > 0 and target_counts["1"] > 0,
        "has_at_least_50_closed_trades_in_review": closed_count >= 50,
        "review_confidence_at_least_0_60": review_confidence >= 0.60,
        "review_safety_flags_present": all(
            review.get("safety", {}).get(flag) is True
            for flag in [
                "offline_only",
                "does_not_edit_env",
                "does_not_edit_state",
                "does_not_place_orders",
                "live_bot_must_ignore_until_phase_11",
            ]
        ),
        "tradingagents_or_fallback_available": tradingagents_status != "missing_review",
    }

    blockers = [name for name, passed in checks.items() if not passed]
    ready = not blockers

    return {
        "phase": "phase_11_bounded_live_regime_consumption",
        "ready": ready,
        "recommendation": "do_not_integrate_live_consumption_yet" if not ready else "manual_review_before_integration",
        "checks": checks,
        "blockers": blockers,
        "dataset_rows": len(dataset_rows),
        "target_counts": target_counts,
        "review_closed_count": closed_count,
        "review_confidence": review_confidence,
        "review_source": source,
        "tradingagents_status": tradingagents_status,
        "safe_default_regime": {
            "allow_trading": True,
            "max_size_multiplier": 1.0,
            "risk_level": "unknown",
            "regime": "unknown",
            "confidence": 0.0,
        },
        "safety": "readiness_check_only_no_live_bot_changes",
    }


def write_json(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether Phase 11 bounded live regime consumption is ready.")
    parser.add_argument("--dataset", default=DATASET_FILE, help="Input trade-quality dataset CSV.")
    parser.add_argument("--review", default=REVIEW_FILE, help="Input daily review JSON.")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Output readiness report JSON.")
    args = parser.parse_args()

    report = build_report(read_csv(args.dataset), read_json(args.review))
    write_json(args.output, report)
    print(f"Wrote Phase 11 readiness report to {args.output}")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
