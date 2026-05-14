# file: state_store.py

import json
import os
from datetime import datetime, timezone


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def make_json_safe(value):
    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            str(k): make_json_safe(v)
            for k, v in value.items()
        }

    if isinstance(value, list):
        return [make_json_safe(v) for v in value]

    if isinstance(value, tuple):
        return [make_json_safe(v) for v in value]

    if isinstance(value, set):
        return [make_json_safe(v) for v in value]

    return value


def load_state(path):
    if not os.path.exists(path):
        return {
            "updated_at": None,
            "positions": {},
            "avg_prices": {},
            "open_orders": [],
            "seen_trade_ids": [],
            "realized_pnl": 0,
        }

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(
    path,
    positions,
    avg_prices,
    open_orders,
    seen_trade_ids,
    realized_pnl,
):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    state = {
        "updated_at": utc_now_iso(),
        "positions": make_json_safe(positions),
        "avg_prices": make_json_safe(avg_prices),
        "open_orders": make_json_safe(open_orders),
        "seen_trade_ids": make_json_safe(list(seen_trade_ids)),
        "realized_pnl": realized_pnl,
    }

    tmp_path = f"{path}.tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    os.replace(tmp_path, path)

    return state