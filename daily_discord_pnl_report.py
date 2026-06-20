#!/usr/bin/env python3

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "btc_5m_state.json"
ENV_PATH = BASE_DIR / ".env"


def utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def fmt_money(value: Any) -> str:
    try:
        return f"${float(value):+.4f}"
    except Exception:
        return str(value)


def fmt_num(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except Exception:
        return str(value)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}

    with STATE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_systemd_status(service_name: str = "polybtc") -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = result.stdout.strip() or result.stderr.strip()
        return status or "unknown"
    except Exception:
        return "unknown"


def count_reconcile_required(open_positions: dict[str, Any]) -> int:
    count = 0
    for pos in open_positions.values():
        if pos.get("reconcile_required") or pos.get("expired_live"):
            count += 1
    return count


def build_message(state: dict[str, Any]) -> str:
    open_positions = state.get("open_positions", {}) or {}
    closed_markets = state.get("closed_markets", {}) or {}
    live_failed_orders = state.get("live_failed_orders", {}) or {}
    live_blocked_orders = state.get("live_blocked_orders", {}) or {}
    live_unfilled_cancelled_orders = state.get("live_unfilled_cancelled_orders", {}) or {}

    daily_pnl = state.get("daily_pnl", 0.0)
    total_pnl = state.get("total_pnl", 0.0)
    last_updated = state.get("last_updated", "unknown")

    reconcile_count = count_reconcile_required(open_positions)
    bot_status = get_systemd_status("polybtc")

    lines = [
        "📊 **BTC5M Daily VM Report**",
        f"Time: `{utc_now_str()}`",
        "",
        f"Daily PnL: **{fmt_money(daily_pnl)}**",
        f"Total PnL: **{fmt_money(total_pnl)}**",
        "",
        f"Open positions: `{len(open_positions)}`",
        f"Closed markets: `{len(closed_markets)}`",
        f"Failed live orders: `{len(live_failed_orders)}`",
        f"Blocked live orders: `{len(live_blocked_orders)}`",
        f"Unfilled/cancelled orders: `{len(live_unfilled_cancelled_orders)}`",
        f"Reconcile/expired warnings: `{reconcile_count}`",
        "",
        f"Bot service status: `{bot_status}`",
        f"State last updated: `{last_updated}`",
    ]

    if reconcile_count > 0:
        lines.extend([
            "",
            "⚠️ **Action needed:** at least one open position has `reconcile_required` or `expired_live`.",
        ])

    if len(open_positions) > 0:
        lines.append("")
        lines.append("Open position summary:")
        for market_id, pos in list(open_positions.items())[:5]:
            question = str(pos.get("question", "unknown"))
            outcome = pos.get("outcome", "unknown")
            entry = pos.get("entry_price", "unknown")
            size = pos.get("size", "unknown")
            rec = pos.get("reconcile_required", False)
            exp = pos.get("expired_live", False)

            if len(question) > 80:
                question = question[:77] + "..."

            lines.append(
                f"- `{outcome}` size `{fmt_num(size)}` entry `{entry}` "
                f"reconcile=`{rec}` expired=`{exp}` | {question}"
            )

        if len(open_positions) > 5:
            lines.append(f"- ...and {len(open_positions) - 5} more open positions")

    message = "\n".join(lines)
    return message[:1900]


def send_discord(message: str) -> None:
    load_dotenv(dotenv_path=ENV_PATH, override=True)

    webhook = os.getenv("BTC_5M_DISCORD_WEBHOOK_URL")
    alerts_enabled = os.getenv("BTC_5M_DISCORD_ALERTS", "false").lower() == "true"

    if not alerts_enabled:
        raise RuntimeError("BTC_5M_DISCORD_ALERTS is not true")

    if not webhook:
        raise RuntimeError("BTC_5M_DISCORD_WEBHOOK_URL is missing")

    response = requests.post(
        webhook,
        json={"content": message},
        timeout=10,
    )

    if response.status_code >= 300:
        raise RuntimeError(
            f"Discord webhook failed: status={response.status_code} body={response.text[:300]}"
        )


def main() -> None:
    state = load_state()
    message = build_message(state)
    send_discord(message)
    print(f"[{utc_now_str()}] Discord daily report sent")


if __name__ == "__main__":
    main()
