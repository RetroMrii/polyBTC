from typing import Any


ALLOWED_RECOMMENDED_ACTIONS = {
    "keep_trading",
    "pause_trading",
    "collect_more_data",
    "reduce_risk",
    "review_manually",
}
ALLOWED_RISK_LEVELS = {"low", "medium", "high", "unknown"}
ALLOWED_REGIMES = {"trend", "chop", "risk_off", "unknown"}

REQUIRED_FIELDS = {
    "schema_version",
    "generated_at",
    "review_window_hours",
    "source",
    "tradingagents_status",
    "recommended_action",
    "allow_trading",
    "risk_level",
    "regime",
    "max_size_multiplier",
    "main_loss_driver",
    "suggested_next_experiment",
    "do_not_change",
    "confidence",
    "metrics",
    "notes",
    "safety",
}


def clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def validate_review(review: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(REQUIRED_FIELDS - set(review.keys()))
    if missing:
        raise ValueError(f"Review is missing required fields: {', '.join(missing)}")

    if review["recommended_action"] not in ALLOWED_RECOMMENDED_ACTIONS:
        raise ValueError(f"Invalid recommended_action: {review['recommended_action']}")
    if review["risk_level"] not in ALLOWED_RISK_LEVELS:
        raise ValueError(f"Invalid risk_level: {review['risk_level']}")
    if review["regime"] not in ALLOWED_REGIMES:
        raise ValueError(f"Invalid regime: {review['regime']}")
    if not isinstance(review["allow_trading"], bool):
        raise ValueError("allow_trading must be boolean")
    if not isinstance(review["do_not_change"], list):
        raise ValueError("do_not_change must be a list")
    if not isinstance(review["metrics"], dict):
        raise ValueError("metrics must be an object")
    if not isinstance(review["notes"], list):
        raise ValueError("notes must be a list")
    if not isinstance(review["safety"], dict):
        raise ValueError("safety must be an object")

    review["confidence"] = clamp_float(review["confidence"], 0.0, 1.0, 0.0)
    review["max_size_multiplier"] = clamp_float(review["max_size_multiplier"], 0.0, 1.0, 1.0)

    safety = review["safety"]
    required_safety_flags = [
        "offline_only",
        "does_not_edit_env",
        "does_not_edit_state",
        "does_not_place_orders",
        "live_bot_must_ignore_until_phase_11",
    ]
    for flag in required_safety_flags:
        if safety.get(flag) is not True:
            raise ValueError(f"safety.{flag} must be true")

    return review
