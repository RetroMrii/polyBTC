import argparse
import csv
import json
import math
import pickle
from pathlib import Path
from typing import Any


DATASET_FILE = "trade_quality_dataset.csv"
MODEL_FILE = "models/lightgbm_trade_quality.pkl"
METRICS_FILE = "reports/lightgbm_trade_quality_metrics.json"

TARGET_COLUMN = "target_good_trade"
TIME_COLUMN = "candidate_timestamp"

FEATURE_COLUMNS = [
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


def read_dataset(path: str) -> list[dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return sorted(rows, key=lambda row: row.get(TIME_COLUMN, ""))


def load_lightgbm():
    try:
        import lightgbm as lgb  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "LightGBM is not installed in this environment. Install it before training, "
            "for example: pip install lightgbm"
        ) from exc
    return lgb


def make_xy(rows: list[dict[str, Any]]) -> tuple[list[list[float]], list[int]]:
    x: list[list[float]] = []
    y: list[int] = []
    for row in rows:
        target_raw = row.get(TARGET_COLUMN)
        if target_raw not in {"0", "1", 0, 1}:
            continue
        x.append([parse_float(row.get(column)) for column in FEATURE_COLUMNS])
        y.append(int(target_raw))
    return x, y


def split_time_ordered(
    rows: list[dict[str, Any]],
    validation_fraction: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(rows) < 2:
        return rows, []

    validation_size = max(1, int(round(len(rows) * validation_fraction)))
    validation_size = min(validation_size, len(rows) - 1)
    split_at = len(rows) - validation_size
    return rows[:split_at], rows[split_at:]


def binary_metrics(y_true: list[int], probabilities: list[float], threshold: float) -> dict[str, Any]:
    predictions = [1 if p >= threshold else 0 for p in probabilities]
    tp = sum(1 for y, p in zip(y_true, predictions) if y == 1 and p == 1)
    tn = sum(1 for y, p in zip(y_true, predictions) if y == 0 and p == 0)
    fp = sum(1 for y, p in zip(y_true, predictions) if y == 0 and p == 1)
    fn = sum(1 for y, p in zip(y_true, predictions) if y == 1 and p == 0)
    total = len(y_true)

    accuracy = (tp + tn) / total if total else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    positive_rate = sum(predictions) / total if total else 0.0

    return {
        "threshold": threshold,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "positive_prediction_rate": positive_rate,
        "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
    }


def log_loss(y_true: list[int], probabilities: list[float]) -> float:
    if not y_true:
        return 0.0

    eps = 1e-15
    total = 0.0
    for y, p in zip(y_true, probabilities):
        p = min(max(float(p), eps), 1.0 - eps)
        total += y * math.log(p) + (1 - y) * math.log(1.0 - p)
    return -total / len(y_true)


def roc_auc_score_fallback(y_true: list[int], probabilities: list[float]) -> float | None:
    positives = [(p, i) for i, (y, p) in enumerate(zip(y_true, probabilities)) if y == 1]
    negatives = [(p, i) for i, (y, p) in enumerate(zip(y_true, probabilities)) if y == 0]
    if not positives or not negatives:
        return None

    pairs = sorted([(p, y) for y, p in zip(y_true, probabilities)], key=lambda item: item[0])
    ranks: list[tuple[float, int]] = []
    idx = 0
    while idx < len(pairs):
        end = idx + 1
        while end < len(pairs) and pairs[end][0] == pairs[idx][0]:
            end += 1
        avg_rank = (idx + 1 + end) / 2.0
        for j in range(idx, end):
            ranks.append((avg_rank, pairs[j][1]))
        idx = end

    rank_sum_positive = sum(rank for rank, y in ranks if y == 1)
    n_pos = len(positives)
    n_neg = len(negatives)
    return (rank_sum_positive - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def class_counts(y: list[int]) -> dict[str, int]:
    return {"0": sum(1 for value in y if value == 0), "1": sum(1 for value in y if value == 1)}


def feature_importance(model: Any) -> list[dict[str, Any]]:
    importances = model.feature_importances_
    pairs = [
        {"feature": feature, "importance": int(importance)}
        for feature, importance in zip(FEATURE_COLUMNS, importances)
    ]
    return sorted(pairs, key=lambda item: item["importance"], reverse=True)


def write_json(path: str, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train a LightGBM trade-quality classifier using a time-ordered validation split."
    )
    parser.add_argument("--dataset", default=DATASET_FILE, help="Input trade-quality dataset CSV.")
    parser.add_argument("--model-output", default=MODEL_FILE, help="Output pickle model path.")
    parser.add_argument("--metrics-output", default=METRICS_FILE, help="Output metrics JSON path.")
    parser.add_argument("--validation-fraction", type=float, default=0.25, help="Fraction of latest rows for validation.")
    parser.add_argument("--threshold", type=float, default=0.5, help="Probability threshold for classification metrics.")
    parser.add_argument("--min-rows", type=int, default=50, help="Minimum dataset rows required to train.")
    args = parser.parse_args()

    rows = read_dataset(args.dataset)
    if len(rows) < args.min_rows:
        raise SystemExit(
            f"Dataset has {len(rows)} rows; need at least {args.min_rows}. "
            "Collect more closed trades or lower --min-rows for a smoke test."
        )

    train_rows, validation_rows = split_time_ordered(rows, args.validation_fraction)
    x_train, y_train = make_xy(train_rows)
    x_validation, y_validation = make_xy(validation_rows)

    if len(set(y_train)) < 2:
        raise SystemExit("Training split must contain both target classes 0 and 1.")
    if not x_validation:
        raise SystemExit("Validation split is empty after filtering labeled rows.")

    lgb = load_lightgbm()
    model = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=200,
        learning_rate=0.03,
        num_leaves=15,
        max_depth=4,
        min_child_samples=10,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(x_train, y_train, feature_name=FEATURE_COLUMNS)

    probabilities = [float(p[1]) for p in model.predict_proba(x_validation)]
    metrics = {
        "dataset": args.dataset,
        "model_output": args.model_output,
        "rows_total": len(rows),
        "rows_train": len(x_train),
        "rows_validation": len(x_validation),
        "validation_fraction": args.validation_fraction,
        "feature_columns": FEATURE_COLUMNS,
        "target_column": TARGET_COLUMN,
        "class_counts_train": class_counts(y_train),
        "class_counts_validation": class_counts(y_validation),
        "validation_log_loss": log_loss(y_validation, probabilities),
        "validation_auc": roc_auc_score_fallback(y_validation, probabilities),
        "validation_metrics": binary_metrics(y_validation, probabilities, args.threshold),
        "feature_importance": feature_importance(model),
    }

    model_path = Path(args.model_output)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    with model_path.open("wb") as f:
        pickle.dump({"model": model, "feature_columns": FEATURE_COLUMNS}, f)

    write_json(args.metrics_output, metrics)

    print(f"Wrote model to {args.model_output}")
    print(f"Wrote metrics to {args.metrics_output}")
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
