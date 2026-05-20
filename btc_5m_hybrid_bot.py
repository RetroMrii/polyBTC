import csv
import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client_v2 import (
    ApiCreds as V2ApiCreds,
    AssetType as V2AssetType,
    BalanceAllowanceParams as V2BalanceAllowanceParams,
    ClobClient as V2ClobClient,
    OrderArgs as V2OrderArgs,
    OrderType as V2OrderType,
    PartialCreateOrderOptions as V2PartialCreateOrderOptions,
    Side as V2Side,
)

from btc_5m_hybrid_strategy import BTC5MHybridStrategy

load_dotenv()

STATE_FILE = "btc_5m_state.json"
DECISIONS_FILE = "btc_5m_decisions.csv"
TRADES_FILE = "btc_5m_trades.csv"

HTTP_SESSION = requests.Session()
_PUBLIC_CLOB_CLIENT: Optional[ClobClient] = None
_LIVE_CLOB_CLIENT_V2: Optional[V2ClobClient] = None

class LiveOrderUnfilledCancelled(RuntimeError):
    """Order was posted, did not fill, and was safely cancelled."""
    pass


class LiveOrderPreCheckBlocked(RuntimeError):
    """Order was blocked before a live order was posted."""
    pass

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {
            "mode": "paper",
            "open_positions": {},
            "closed_markets": {},
            "live_failed_orders": {},
            "live_blocked_orders": {},
            "live_unfilled_cancelled_orders": {},
            "live_reconciliation": {},
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "last_market_id": None,
            "last_updated": None,
        }

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    state.setdefault("open_positions", {})
    state.setdefault("closed_markets", {})
    state.setdefault("live_failed_orders", {})
    state.setdefault("live_blocked_orders", {})
    state.setdefault("live_unfilled_cancelled_orders", {})
    state.setdefault("live_reconciliation", {})
    state.setdefault("daily_pnl", 0.0)
    state.setdefault("total_pnl", 0.0)
    state.setdefault("last_market_id", None)
    state.setdefault("last_updated", None)
    return state


def save_state(state: dict[str, Any]) -> None:
    state["last_updated"] = utc_now()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def log_decision(row: list[Any]) -> None:
    with open(DECISIONS_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)

def ensure_csv_headers() -> None:
    if not os.path.exists(DECISIONS_FILE) or os.path.getsize(DECISIONS_FILE) == 0:
        with open(DECISIONS_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "timestamp", "market_id", "question", "btc_price", "strike",
                "seconds_to_expiry", "yes_bid", "yes_ask", "no_bid", "no_ask",
                "model_probability", "market_probability", "edge", "action", "reason",
            ])

    if not os.path.exists(TRADES_FILE) or os.path.getsize(TRADES_FILE) == 0:
        with open(TRADES_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "timestamp", "mode", "market_id", "side", "outcome", "price",
                "size", "simulated", "reason", "pnl",
            ])

def log_trade(row: list[Any]) -> None:
    with open(TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)

def print_startup_config() -> None:
    keys = [
        "BTC_5M_MODE",
        "BTC_5M_LIVE_ARMED",
        "BTC_5M_ALLOW_REAL_ORDERS",
        "BTC_5M_LOOP_SECONDS",
        "BTC_5M_MIN_EDGE",
        "BTC_5M_MAX_SPREAD",
        "BTC_5M_MIN_DISTANCE_FROM_STRIKE",
        "BTC_5M_LATE_DISTANCE_SECONDS",
        "BTC_5M_LATE_MIN_DISTANCE_FROM_STRIKE",
        "BTC_5M_MIN_SECONDS_TO_EXPIRY",
        "BTC_5M_NO_TRADE_LAST_SECONDS",
        "BTC_5M_MAX_SECONDS_TO_EXPIRY",
        "BTC_5M_REQUIRE_MOMENTUM_CONFIRMATION",
        "BTC_5M_LIVE_ORDER_SIZE",
        "BTC_5M_MIN_LIVE_SHARE_SIZE",
        "BTC_5M_MIN_LIVE_ORDER_VALUE",
        "BTC_5M_MAX_LIVE_ORDER_VALUE",
        "BTC_5M_MAX_DAILY_LIVE_LOSS",
        "BTC_5M_ENTRY_SLIPPAGE",
        "BTC_5M_ENTRY_ORDER_TIMEOUT_SECONDS",
        "BTC_5M_EXIT_ORDER_TIMEOUT_SECONDS",
        "BTC_5M_CASHOUT_EXIT_SLIPPAGE",
        "BTC_5M_STOPLOSS_EXIT_SLIPPAGE",
        "BTC_5M_PROTECT_EXIT_SLIPPAGE",
        "BTC_5M_TRAIL_EXIT_SLIPPAGE",
        "BTC_5M_MIN_NET_PROFIT",
        "BTC_5M_MAX_NET_LOSS",
        "BTC_5M_HARD_MAX_NET_LOSS",
        "BTC_5M_FORCE_EXIT_SECONDS",
        "BTC_5M_FORCE_EXIT_MIN_NET",
        "BTC_5M_FORCE_EXIT_FLAT_NET",
        "BTC_5M_STRONG_THESIS_HOLD_SECONDS",
        "BTC_5M_STRONG_THESIS_MIN_NET",
        "BTC_5M_STRONG_THESIS_MIN_DISTANCE",
        "BTC_5M_ENABLE_PROFIT_PROTECTION",
        "BTC_5M_PROFIT_PROTECT_ARM_NET",
        "BTC_5M_PROFIT_PROTECT_EXIT_NET",
        "BTC_5M_PROFIT_PROTECT_MIN_SECONDS",
        "BTC_5M_PROFIT_PROTECT_THESIS_FLIP_EXIT",
        "BTC_5M_PROFIT_PROTECT_MAX_EXIT_LOSS",
        "BTC_5M_PROFIT_PROTECT_GIVEBACK",
        "BTC_5M_PROFIT_PROTECT_MIN_BEST_NET",
        "BTC_5M_PROFIT_PROTECT_MAX_GIVEBACK_EXIT_LOSS",
        "BTC_5M_ENABLE_TRAILING_PROFIT",
        "BTC_5M_TRAIL_ACTIVATE_NET",
        "BTC_5M_TRAIL_DROP",
        "BTC_5M_TRAIL_MIN_SECONDS_TO_EXPIRY",
        "BTC_5M_TRAIL_FORCE_CASHOUT_NET",
        "BTC_5M_PREVENT_REENTRY_AFTER_CASHOUT",
        "BTC_5M_RECONCILE_ON_STARTUP",
    ]

    print("[BTC5M] active config:")
    for key in keys:
        print(f"[BTC5M]   {key}={os.getenv(key)}")


def live_mode_is_armed() -> bool:
    mode = os.getenv("BTC_5M_MODE", "paper").lower()
    live_armed = os.getenv("BTC_5M_LIVE_ARMED", "false").lower() == "true"
    allow_orders = os.getenv("BTC_5M_ALLOW_REAL_ORDERS", "false").lower() == "true"
    return mode == "live" and live_armed and allow_orders


def get_live_client_v2() -> V2ClobClient:
    global _LIVE_CLOB_CLIENT_V2

    if _LIVE_CLOB_CLIENT_V2 is not None:
        return _LIVE_CLOB_CLIENT_V2

    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    private_key = os.getenv("PK")
    chain_id = int(os.getenv("CHAIN_ID", "137"))
    signature_type = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "1"))
    funder = os.getenv("POLYMARKET_FUNDER") or None

    if not private_key:
        raise RuntimeError("Missing PK in .env")

    creds = V2ApiCreds(
        api_key=os.getenv("CLOB_API_KEY"),
        api_secret=os.getenv("CLOB_SECRET"),
        api_passphrase=os.getenv("CLOB_PASS_PHRASE"),
    )
    missing = [
        name for name, value in {
            "CLOB_API_KEY": creds.api_key,
            "CLOB_SECRET": creds.api_secret,
            "CLOB_PASS_PHRASE": creds.api_passphrase,
        }.items() if not value
    ]
    if missing:
        raise RuntimeError(f"Missing CLOB credentials in .env: {', '.join(missing)}")

    _LIVE_CLOB_CLIENT_V2 = V2ClobClient(
        host=host,
        chain_id=chain_id,
        key=private_key,
        creds=creds,
        signature_type=signature_type,
        funder=funder,
    )
    return _LIVE_CLOB_CLIENT_V2


def get_public_clob_client() -> ClobClient:
    global _PUBLIC_CLOB_CLIENT
    if _PUBLIC_CLOB_CLIENT is None:
        _PUBLIC_CLOB_CLIENT = ClobClient(os.getenv("CLOB_API_URL", "https://clob.polymarket.com"))
    return _PUBLIC_CLOB_CLIENT


def safe_float_from_obj(value: Any, keys: Optional[list[str]] = None, default: float = 0.0) -> float:
    keys = keys or []
    if value is None:
        return default

    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except Exception:
            return default

    if isinstance(value, dict):
        for key in keys:
            if key in value:
                try:
                    return float(value[key])
                except Exception:
                    pass

    for key in keys:
        attr = getattr(value, key, None)
        if attr is not None:
            try:
                return float(attr)
            except Exception:
                pass

    return default


def read_collateral_balance_allowance(client: V2ClobClient) -> dict[str, Any]:
    raw = client.get_balance_allowance(
        params=V2BalanceAllowanceParams(asset_type=V2AssetType.COLLATERAL)
    )

    balance = safe_float_from_obj(
        raw,
        keys=["balance", "available_balance", "availableBalance", "collateral", "amount"],
        default=0.0,
    )
    allowance = safe_float_from_obj(
        raw,
        keys=["allowance", "approved", "approval", "allowance_amount", "allowanceAmount"],
        default=0.0,
    )

    if isinstance(raw, dict) and allowance <= 0:
        allowances = raw.get("allowances")
        if isinstance(allowances, dict) and allowances:
            try:
                allowance = max(float(v) for v in allowances.values())
            except Exception:
                allowance = 0.0

    return {"raw": raw, "balance": balance, "allowance": allowance}


def read_conditional_balance_allowance(client: V2ClobClient, token_id: str) -> dict[str, Any]:
    raw = client.get_balance_allowance(
        params=V2BalanceAllowanceParams(
            asset_type=V2AssetType.CONDITIONAL,
            token_id=str(token_id),
        )
    )

    balance = safe_float_from_obj(
        raw,
        keys=["balance", "available_balance", "availableBalance", "amount"],
        default=0.0,
    )
    allowance = safe_float_from_obj(
        raw,
        keys=["allowance", "approved", "approval", "allowance_amount", "allowanceAmount"],
        default=0.0,
    )

    if isinstance(raw, dict) and allowance <= 0:
        allowances = raw.get("allowances")
        if isinstance(allowances, dict) and allowances:
            try:
                allowance = max(float(v) for v in allowances.values())
            except Exception:
                allowance = 0.0

    return {"raw": raw, "balance": balance, "allowance": allowance}


def normalize_usdc_balance(raw_balance: float) -> float:
    return raw_balance / 1_000_000 if raw_balance > 10_000 else raw_balance


def is_zero_token_balance_error(error_text: str) -> bool:
    text = str(error_text).lower()
    return (
        "not enough balance / allowance" in text
        or "balance is not enough" in text
        or "balance: 0" in text
    )


def get_live_token_balance_for_position(position: dict[str, Any]) -> float:
    token_id = position.get("token_id")
    if not token_id:
        return 0.0

    client = get_live_client_v2()
    info = read_conditional_balance_allowance(client, str(token_id))
    return normalize_usdc_balance(float(info.get("balance", 0.0)))


def ensure_live_balance_for_buy(price: float, size: float, client: Optional[V2ClobClient] = None) -> dict[str, Any]:
    client = client or get_live_client_v2()
    info = read_collateral_balance_allowance(client)

    required = float(price) * float(size)
    balance = normalize_usdc_balance(float(info["balance"]))
    allowance = float(info["allowance"])

    if balance <= 0:
        raise RuntimeError(f"Live BUY blocked: collateral balance appears zero. raw={info['raw']}")
    if balance < required:
        raise RuntimeError(
            f"Live BUY blocked: insufficient collateral balance. "
            f"required={required:.4f}, balance={balance:.4f}, raw={info['raw']}"
        )
    if allowance <= 0:
        raise RuntimeError(f"Live BUY blocked: collateral allowance appears zero. raw={info['raw']}")

    return info


def ensure_live_balance_for_sell(position: dict[str, Any], client: Optional[V2ClobClient] = None) -> dict[str, Any]:
    client = client or get_live_client_v2()
    token_id = position.get("token_id")
    size = float(position["size"])

    if not token_id:
        raise RuntimeError("Live SELL blocked: missing token_id")

    info = read_conditional_balance_allowance(client, str(token_id))
    balance = normalize_usdc_balance(float(info["balance"]))
    allowance = float(info["allowance"])

    if balance < size:
        print(
            f"[BTC5M] WARNING: conditional token balance check low. "
            f"required={size:.4f}, balance={balance:.4f}, raw={info['raw']}"
        )
    if allowance <= 0:
        raise RuntimeError(f"Live SELL blocked: conditional token allowance appears zero. raw={info['raw']}")

    return info


def extract_order_id(response: Any) -> Optional[str]:
    if response is None:
        return None

    keys = ("orderID", "orderId", "id", "order_id", "order_hash", "hash")
    if isinstance(response, dict):
        for key in keys:
            value = response.get(key)
            if value:
                return str(value)
        for nested_key in ("order", "data"):
            nested = response.get(nested_key)
            if isinstance(nested, dict):
                for key in keys:
                    value = nested.get(key)
                    if value:
                        return str(value)

    for attr in keys:
        value = getattr(response, attr, None)
        if value:
            return str(value)

    return None


def extract_order_status_fields(order_info: Any) -> dict[str, Any]:
    if order_info is None:
        return {
            "status": "unknown",
            "filled_size": 0.0,
            "remaining_size": None,
            "avg_fill_price": None,
            "raw": order_info,
        }

    if isinstance(order_info, dict):
        status = str(order_info.get("status") or order_info.get("state") or "unknown").lower()
        filled_size = (
            order_info.get("filled_size")
            or order_info.get("filledSize")
            or order_info.get("filled")
            or order_info.get("matched_size")
            or order_info.get("matchedSize")
            or order_info.get("size_matched")
            or order_info.get("sizeMatched")
            or 0
        )
        remaining_size = order_info.get("remaining_size") or order_info.get("remainingSize") or order_info.get("remaining")
        avg_fill_price = order_info.get("avg_fill_price") or order_info.get("avgFillPrice") or order_info.get("price")
    else:
        status = str(getattr(order_info, "status", None) or getattr(order_info, "state", None) or "unknown").lower()
        filled_size = (
            getattr(order_info, "filled_size", None)
            or getattr(order_info, "filledSize", None)
            or getattr(order_info, "filled", None)
            or getattr(order_info, "matched_size", None)
            or getattr(order_info, "matchedSize", None)
            or getattr(order_info, "size_matched", None)
            or getattr(order_info, "sizeMatched", None)
            or 0
        )
        remaining_size = getattr(order_info, "remaining_size", None) or getattr(order_info, "remainingSize", None) or getattr(order_info, "remaining", None)
        avg_fill_price = getattr(order_info, "avg_fill_price", None) or getattr(order_info, "avgFillPrice", None) or getattr(order_info, "price", None)

    try:
        filled_size = float(filled_size)
    except Exception:
        filled_size = 0.0

    try:
        remaining_size = float(remaining_size) if remaining_size is not None else None
    except Exception:
        remaining_size = None

    try:
        avg_fill_price = float(avg_fill_price) if avg_fill_price is not None else None
    except Exception:
        avg_fill_price = None

    return {
        "status": status,
        "filled_size": filled_size,
        "remaining_size": remaining_size,
        "avg_fill_price": avg_fill_price,
        "raw": order_info,
    }


def extract_buy_fill_from_post_response(response: Any, fallback_price: float) -> Optional[dict[str, Any]]:
    if not isinstance(response, dict):
        return None

    success = response.get("success")
    status = str(response.get("status") or "").lower()
    if success is not True and status not in {"matched", "filled"}:
        return None

    try:
        shares_received = float(response.get("takingAmount") or 0)
    except Exception:
        shares_received = 0.0

    try:
        usdc_paid = float(response.get("makingAmount") or 0)
    except Exception:
        usdc_paid = 0.0

    if shares_received <= 0:
        return None

    avg_price = usdc_paid / shares_received if usdc_paid > 0 else fallback_price
    return {
        "status": status or "matched",
        "filled_size": shares_received,
        "remaining_size": 0.0,
        "avg_fill_price": avg_price,
        "raw": response,
        "fill_state": "filled_from_post_response",
    }


def extract_sell_fill_from_post_response(response: Any, fallback_price: float) -> Optional[dict[str, Any]]:
    if not isinstance(response, dict):
        return None

    success = response.get("success")
    status = str(response.get("status") or "").lower()
    if success is not True and status not in {"matched", "filled"}:
        return None

    try:
        usdc_received = float(response.get("takingAmount") or 0)
    except Exception:
        usdc_received = 0.0

    try:
        shares_sold = float(response.get("makingAmount") or 0)
    except Exception:
        shares_sold = 0.0

    if shares_sold <= 0:
        return None

    avg_price = usdc_received / shares_sold if usdc_received > 0 else fallback_price
    return {
        "status": status or "matched",
        "filled_size": shares_sold,
        "remaining_size": 0.0,
        "avg_fill_price": avg_price,
        "raw": response,
        "fill_state": "filled_from_post_response",
    }


def get_order_info_safe(client: V2ClobClient, order_id: str) -> Any:
    try:
        return client.get_order(order_id)
    except Exception as e:
        print(f"[BTC5M] order status lookup failed for {order_id}: {e}")
        return None


def cancel_order_safe(client: V2ClobClient, order_id: str) -> bool:
    if not order_id:
        return False

    # py-clob-client-v2 cancel_order can expect an object in some versions;
    # cancel_orders([id]) is safer in the observed local client.
    if hasattr(client, "cancel_orders"):
        try:
            client.cancel_orders([order_id])
            print(f"[BTC5M] cancelled stale order {order_id}")
            return True
        except Exception as e:
            print(f"[BTC5M] cancel attempt failed via cancel_orders: {e}")

    if hasattr(client, "cancel_order"):
        try:
            client.cancel_order(order_id)
            print(f"[BTC5M] cancelled stale order {order_id}")
            return True
        except Exception as e:
            print(f"[BTC5M] cancel attempt failed via cancel_order: {e}")

    if hasattr(client, "cancel"):
        try:
            client.cancel(order_id)
            print(f"[BTC5M] cancelled stale order {order_id}")
            return True
        except Exception as e:
            print(f"[BTC5M] cancel attempt failed via cancel: {e}")

    return False


def wait_for_order_fill(client: V2ClobClient, order_id: str, requested_size: float, timeout_seconds: float) -> dict[str, Any]:
    poll_seconds = float(os.getenv("BTC_5M_ORDER_STATUS_POLL_SECONDS", "1"))
    min_filled_size = float(os.getenv("BTC_5M_MIN_FILLED_SIZE", "0.01"))
    cancel_stale = os.getenv("BTC_5M_CANCEL_STALE_ORDERS", "true").lower() == "true"

    deadline = time.time() + float(timeout_seconds)
    last_fields: Optional[dict[str, Any]] = None
    best_partial: Optional[dict[str, Any]] = None

    while time.time() < deadline:
        fields = extract_order_status_fields(get_order_info_safe(client, order_id))
        last_fields = fields

        filled_size = float(fields.get("filled_size", 0.0) or 0.0)
        remaining_size = fields.get("remaining_size")
        status = str(fields.get("status", "unknown")).lower()

        if filled_size >= float(requested_size):
            fields["fill_state"] = "filled"
            fields["cancel_succeeded"] = False
            return fields

        if filled_size >= min_filled_size:
            best_partial = fields.copy()
            best_partial["fill_state"] = "partial_seen"
            if remaining_size is not None and remaining_size <= 0:
                best_partial["fill_state"] = "filled"
                best_partial["cancel_succeeded"] = False
                return best_partial

        if status in {"filled", "matched"}:
            raw = fields.get("raw")
            raw_size_f = 0.0

            if isinstance(raw, dict):
                raw_size = raw.get("size_matched") or raw.get("sizeMatched")
                try:
                    raw_size_f = float(raw_size or 0)
                except Exception:
                    raw_size_f = 0.0

            if raw_size_f > 0:
                fields["filled_size"] = raw_size_f
                if raw_size_f >= float(requested_size):
                    fields["fill_state"] = "filled"
                    fields["cancel_succeeded"] = False
                    return fields

                fields["fill_state"] = "partial_seen"
                best_partial = fields.copy()
                time.sleep(poll_seconds)
                continue

            fields["fill_state"] = "matched_but_size_unknown"
            fields["cancel_succeeded"] = False
            return fields

        if status in {"cancelled", "canceled", "rejected", "expired", "failed"}:
            fields["fill_state"] = status
            fields["cancel_succeeded"] = status in {"cancelled", "canceled"}
            return fields

        time.sleep(poll_seconds)

    cancel_succeeded = False
    if cancel_stale:
        cancel_succeeded = cancel_order_safe(client, order_id)

    if best_partial is not None:
        best_partial["fill_state"] = "partial_after_timeout"
        best_partial["cancel_succeeded"] = cancel_succeeded
        return best_partial

    if last_fields is None:
        last_fields = {
            "status": "timeout",
            "filled_size": 0.0,
            "remaining_size": None,
            "avg_fill_price": None,
            "raw": None,
        }
    last_fields["fill_state"] = "timeout"
    last_fields["cancel_succeeded"] = cancel_succeeded
    return last_fields

def verify_post_cancel_buy_fill(
    client: V2ClobClient,
    order_id: str,
    token_id: str,
    requested_size: float,
    fallback_price: float,
) -> Optional[dict[str, Any]]:
    # Re-check order after cancellation attempt. Some fills appear after the last pre-cancel status.
    order_info = get_order_info_safe(client, order_id)
    fields = extract_order_status_fields(order_info)

    filled_size = float(fields.get("filled_size", 0.0) or 0.0)
    if filled_size > 0:
        fields["fill_state"] = "filled_after_cancel_recheck"
        if fields.get("avg_fill_price") is None:
            fields["avg_fill_price"] = fallback_price
        return fields

    # If get_order is stale/incomplete, check actual conditional token balance.
    try:
        info = read_conditional_balance_allowance(client, str(token_id))
        token_balance = normalize_usdc_balance(float(info.get("balance", 0.0)))

        if token_balance > 0:
            return {
                "status": "filled_by_token_balance",
                "filled_size": min(token_balance, float(requested_size)),
                "remaining_size": 0.0,
                "avg_fill_price": fallback_price,
                "raw": {
                    "order_info": order_info,
                    "token_balance_info": info["raw"],
                },
                "fill_state": "filled_by_token_balance_after_cancel",
            }
    except Exception as e:
        print(f"[BTC5M] post-cancel token balance check failed for {order_id}: {e}")

    return None


def reconcile_buy_fill_with_token_balance(
    client: V2ClobClient,
    token_id: str,
    reported_filled_size: float,
    requested_size: float,
    fallback_price: float,
) -> dict[str, Any]:
    try:
        info = read_conditional_balance_allowance(client, str(token_id))
        token_balance = normalize_usdc_balance(float(info.get("balance", 0.0)))

        if token_balance > reported_filled_size:
            return {
                "filled_size": min(token_balance, float(requested_size)),
                "avg_fill_price": fallback_price,
                "token_balance": token_balance,
                "used_token_balance": True,
                "raw": info["raw"],
            }

        return {
            "filled_size": reported_filled_size,
            "avg_fill_price": fallback_price,
            "token_balance": token_balance,
            "used_token_balance": False,
            "raw": info["raw"],
        }
    except Exception as e:
        print(f"[BTC5M] buy token balance reconciliation failed for token={token_id}: {e}")
        return {
            "filled_size": reported_filled_size,
            "avg_fill_price": fallback_price,
            "token_balance": None,
            "used_token_balance": False,
            "raw": str(e),
        }


def live_daily_loss_exceeded(state: dict[str, Any]) -> bool:
    if os.getenv("BTC_5M_MODE", "paper").lower() != "live":
        return False
    max_daily_loss = float(os.getenv("BTC_5M_MAX_DAILY_LIVE_LOSS", "1.00"))
    daily_pnl = float(state.get("daily_pnl", 0.0))
    return daily_pnl <= -abs(max_daily_loss)


def normalize_open_order(order: Any) -> dict[str, Any]:
    if isinstance(order, dict):
        return {
            "id": order.get("id") or order.get("orderID") or order.get("orderId") or order.get("order_id"),
            "status": order.get("status") or order.get("state"),
            "raw": order,
        }
    return {
        "id": getattr(order, "id", None) or getattr(order, "orderID", None) or getattr(order, "orderId", None) or getattr(order, "order_id", None),
        "status": getattr(order, "status", None) or getattr(order, "state", None),
        "raw": order,
    }


def get_open_orders_safe(client: V2ClobClient) -> list[Any]:
    try:
        orders = client.get_open_orders() if hasattr(client, "get_open_orders") else client.get_orders()
    except TypeError:
        orders = client.get_orders({})

    if orders is None:
        return []
    if isinstance(orders, dict):
        if isinstance(orders.get("data"), list):
            return orders["data"]
        if isinstance(orders.get("orders"), list):
            return orders["orders"]
    if isinstance(orders, list):
        return orders
    return []


def reconcile_live_state_on_startup(state: dict[str, Any]) -> dict[str, Any]:
    should_reconcile = os.getenv("BTC_5M_RECONCILE_ON_STARTUP", "true").lower() == "true"
    mode = os.getenv("BTC_5M_MODE", "paper").lower()
    if mode != "live" or not should_reconcile:
        return state

    print("[BTC5M] live startup reconciliation enabled")
    try:
        client = get_live_client_v2()
    except Exception as e:
        print(f"[BTC5M] live reconciliation skipped: cannot create client: {e}")
        return state

    open_positions = state.setdefault("open_positions", {})
    state.setdefault("live_reconciliation", {})
    state["live_reconciliation"]["last_checked"] = utc_now()

    if open_positions:
        print("[BTC5M] local open positions found on startup:")
        for market_id, position in open_positions.items():
            print(
                f"[BTC5M] local position market={market_id} "
                f"outcome={position.get('outcome')} size={position.get('size')} "
                f"entry={position.get('entry_price')} token_id={position.get('token_id')}"
            )
    else:
        print("[BTC5M] no local open positions on startup")

    try:
        normalized_orders = [normalize_open_order(order) for order in get_open_orders_safe(client)]
        state["live_reconciliation"]["open_orders_count"] = len(normalized_orders)
        state["live_reconciliation"]["open_orders"] = [
            {"id": order["id"], "status": order["status"], "raw": str(order["raw"])}
            for order in normalized_orders[:20]
        ]
        if normalized_orders:
            print(f"[BTC5M] WARNING: {len(normalized_orders)} open CLOB orders found on startup")
            for order in normalized_orders[:5]:
                print(f"[BTC5M] open order id={order['id']} status={order['status']}")
        else:
            print("[BTC5M] no open CLOB orders found on startup")
    except Exception as e:
        print(f"[BTC5M] live reconciliation order query failed: {e}")
        state["live_reconciliation"]["open_orders_error"] = str(e)

    for market_id, position in open_positions.items():
        token_id = position.get("token_id")
        if not token_id:
            continue
        try:
            token_info = read_conditional_balance_allowance(client, str(token_id))
            position["startup_token_balance_raw"] = str(token_info["raw"])
            position["startup_token_balance"] = token_info["balance"]
            position["startup_token_allowance"] = token_info["allowance"]
            print(
                f"[BTC5M] token check market={market_id} "
                f"balance={token_info['balance']} allowance={token_info['allowance']}"
            )
        except Exception as e:
            position["startup_token_balance_error"] = str(e)
            print(f"[BTC5M] token balance check failed for {market_id}: {e}")

    return state


def token_id_for_decision(snapshot: dict[str, Any], decision: Any) -> str:
    if decision.outcome == "YES":
        return str(snapshot["yes_token_id"])
    if decision.outcome == "NO":
        return str(snapshot["no_token_id"])
    raise ValueError(f"Unsupported outcome for live order: {decision.outcome}")


def calculate_live_buy_size(price: float, decision_size: float) -> tuple[float, float]:
    configured_size = float(os.getenv("BTC_5M_LIVE_ORDER_SIZE", str(decision_size)))
    min_order_value = float(os.getenv("BTC_5M_MIN_LIVE_ORDER_VALUE", "2.50"))
    max_order_value = float(os.getenv("BTC_5M_MAX_LIVE_ORDER_VALUE", "4.95"))
    min_live_share_size = float(os.getenv("BTC_5M_MIN_LIVE_SHARE_SIZE", "5"))

    raw_size = max(configured_size, min_order_value / price, min_live_share_size)
    size = math.ceil(raw_size * 100) / 100
    order_value = price * size

    if order_value > max_order_value:
        raise RuntimeError(
            f"Live order blocked by max value: order_value={order_value:.4f}, limit={max_order_value:.4f}"
        )
    return size, order_value


def place_live_limit_buy(snapshot: dict[str, Any], decision: Any) -> dict[str, Any]:
    if not live_mode_is_armed():
        raise LiveOrderPreCheckBlocked(
            "Live order blocked. Require BTC_5M_MODE=live, "
            "BTC_5M_LIVE_ARMED=true, and BTC_5M_ALLOW_REAL_ORDERS=true."
        )

    base_price = float(decision.price)
    entry_slippage = float(os.getenv("BTC_5M_ENTRY_SLIPPAGE", "0.00"))
    price = min(0.99, base_price + entry_slippage)
    if price <= 0 or price >= 1:
        raise LiveOrderPreCheckBlocked(f"Invalid live order price: {price}")

    if decision.edge is not None and entry_slippage > 0:
        adjusted_edge = float(decision.edge) - entry_slippage
        if adjusted_edge < float(os.getenv("BTC_5M_MIN_EDGE", "0.05")):
            raise LiveOrderPreCheckBlocked(
                f"Live BUY blocked: adjusted edge too small after slippage. "
                f"edge={decision.edge:.4f}, slippage={entry_slippage:.4f}, adjusted={adjusted_edge:.4f}"
            )

    size, order_value = calculate_live_buy_size(price, float(decision.size))
    if size <= 0:
        raise LiveOrderPreCheckBlocked(f"Invalid live order size: {size}")

    token_id = token_id_for_decision(snapshot, decision)
    client = get_live_client_v2()
    balance_info = ensure_live_balance_for_buy(price, size, client=client)

    response = client.create_and_post_order(
        order_args=V2OrderArgs(token_id=str(token_id), price=price, side=V2Side.BUY, size=size),
        options=V2PartialCreateOrderOptions(tick_size="0.01"),
        order_type=V2OrderType.GTC,
    )
    order_id = extract_order_id(response)
    if not order_id:
        raise RuntimeError(f"Live BUY posted but no order id found in response: {response}")

    log_trade([
        utc_now(),
        "live",
        snapshot["market_id"],
        "ORDER_POSTED",
        decision.outcome,
        price,
        size,
        False,
        f"live_buy_posted order_id={order_id} response={response}",
        0.0,
    ])

    post_fill = extract_buy_fill_from_post_response(response, price)
    if post_fill is not None:
        fill = post_fill
    else:
        timeout_seconds = float(os.getenv("BTC_5M_ENTRY_ORDER_TIMEOUT_SECONDS", "8"))
        fill = wait_for_order_fill(client, order_id, size, timeout_seconds)

    filled_size = float(fill.get("filled_size", 0.0))
    fill_state = fill.get("fill_state", "unknown")

    if filled_size <= 0:
        fill_status = str(fill.get("status", "")).lower()
        raw = fill.get("raw") if isinstance(fill, dict) else None
        raw_size_matched = None
        if isinstance(raw, dict):
            raw_size_matched = raw.get("size_matched") or raw.get("sizeMatched")

        try:
            raw_size_matched_f = float(raw_size_matched or 0)
        except Exception:
            raw_size_matched_f = 0.0

        cancel_succeeded = bool(fill.get("cancel_succeeded", False))

        if (
            fill_state == "timeout"
            and raw_size_matched_f <= 0
            and fill_status in {"live", "unknown", "timeout"}
        ):
            if not cancel_succeeded:
                raise RuntimeError(
                    f"Live BUY timeout and cancel not confirmed. order_id={order_id} "
                    f"fill={fill} post_response={response}"
                )

            post_cancel_fill = None
            for _ in range(2):
                post_cancel_fill = verify_post_cancel_buy_fill(
                    client=client,
                    order_id=order_id,
                    token_id=str(token_id),
                    requested_size=size,
                    fallback_price=price,
                )
                if post_cancel_fill is not None:
                    break
                time.sleep(1)

            if post_cancel_fill is not None:
                fill = post_cancel_fill
                filled_size = float(fill.get("filled_size", 0.0))
                fill_state = fill.get("fill_state", "filled_after_cancel_recheck")
                fill_status = str(fill.get("status", "")).lower()
                raw_size_matched_f = filled_size

        if filled_size <= 0:
            if (
                fill_state == "timeout"
                and raw_size_matched_f <= 0
                and fill_status in {"live", "unknown", "timeout"}
                and cancel_succeeded
            ):
                log_trade([
                    utc_now(),
                    "live",
                    snapshot["market_id"],
                    "ORDER_UNFILLED_CANCELLED",
                    decision.outcome,
                    price,
                    size,
                    False,
                    f"order_id={order_id} fill={fill} post_response={response}",
                    0.0,
                ])

                raise LiveOrderUnfilledCancelled(
                    f"Live BUY unfilled and cancelled. order_id={order_id} "
                    f"fill_state={fill_state} fill={fill} post_response={response}"
                )

            raise RuntimeError(
                f"Live BUY not filled. order_id={order_id} fill_state={fill_state} "
                f"fill={fill} post_response={response}"
            )

    avg_fill_price = float(fill.get("avg_fill_price") or price)
    actual_shares = filled_size
    actual_cost = avg_fill_price * actual_shares

    raw_fill = fill.get("raw") if isinstance(fill, dict) else None
    if isinstance(raw_fill, dict):
        try:
            if raw_fill.get("takingAmount") not in (None, ""):
                actual_shares = float(raw_fill.get("takingAmount"))
            if raw_fill.get("makingAmount") not in (None, ""):
                actual_cost = float(raw_fill.get("makingAmount"))
            if actual_shares > 0 and actual_cost > 0:
                avg_fill_price = actual_cost / actual_shares
                filled_size = actual_shares
        except Exception as e:
            print(f"[BTC5M] BUY accounting parse warning: {e}")

    reconciled = reconcile_buy_fill_with_token_balance(
        client=client,
        token_id=str(token_id),
        reported_filled_size=filled_size,
        requested_size=size,
        fallback_price=avg_fill_price,
    )

    reconciled_size = float(reconciled["filled_size"])
    if reconciled_size > filled_size:
        print(
            f"[BTC5M] BUY size reconciled from order fill to token balance: "
            f"order_fill={filled_size:.4f} token_balance={reconciled_size:.4f}"
        )
        filled_size = reconciled_size

    actual_shares = filled_size
    actual_cost = avg_fill_price * actual_shares

    return {
        "response": response,
        "order_id": order_id,
        "fill": fill,
        "fill_state": fill_state,
        "token_id": token_id,
        "price": avg_fill_price,
        "limit_price": price,
        "size": filled_size,
        "requested_size": size,
        "order_value": actual_cost,
        "actual_buy_cost": actual_cost,
        "actual_buy_shares": actual_shares,
        "balance_info": str(balance_info["raw"]),
        "token_balance_reconciliation": str(reconciled),
    }


def place_live_limit_sell(position: dict[str, Any], exit_price: float) -> dict[str, Any]:
    if not live_mode_is_armed():
        raise RuntimeError(
            "Live sell blocked. Require BTC_5M_MODE=live, "
            "BTC_5M_LIVE_ARMED=true, and BTC_5M_ALLOW_REAL_ORDERS=true."
        )

    price = float(exit_price)
    size = float(position["size"])
    token_id = position.get("token_id")

    if not token_id:
        raise RuntimeError("Cannot sell live position: missing token_id in position state")
    if price <= 0 or price >= 1:
        raise RuntimeError(f"Invalid live sell price: {price}")
    if size <= 0:
        raise RuntimeError(f"Invalid live sell size: {size}")

    client = get_live_client_v2()
    balance_info = ensure_live_balance_for_sell(position, client=client)

    response = client.create_and_post_order(
        order_args=V2OrderArgs(token_id=str(token_id), price=price, side=V2Side.SELL, size=size),
        options=V2PartialCreateOrderOptions(tick_size="0.01"),
        order_type=V2OrderType.GTC,
    )
    order_id = extract_order_id(response)
    if not order_id:
        raise RuntimeError(f"Live SELL posted but no order id found in response: {response}")

    log_trade([
        utc_now(),
        "live",
        position.get("market_id", "UNKNOWN_MARKET"),
        "EXIT_ORDER_POSTED",
        position["outcome"],
        price,
        size,
        False,
        f"live_sell_posted order_id={order_id} response={response}",
        0.0,
    ])

    post_fill = extract_sell_fill_from_post_response(response, price)
    if post_fill is not None:
        fill = post_fill
    else:
        timeout_seconds = float(os.getenv("BTC_5M_EXIT_ORDER_TIMEOUT_SECONDS", "8"))
        fill = wait_for_order_fill(client, order_id, size, timeout_seconds)

    filled_size = float(fill.get("filled_size", 0.0))
    fill_state = fill.get("fill_state", "unknown")
    if filled_size <= 0:
        raise RuntimeError(
            f"Live SELL not filled. order_id={order_id} fill_state={fill_state} "
            f"cancel_succeeded={fill.get('cancel_succeeded', None)} "
            f"fill={fill} post_response={response}"
        )

    avg_fill_price = float(fill.get("avg_fill_price") or price)
    actual_shares_sold = filled_size
    actual_sell_proceeds = avg_fill_price * actual_shares_sold

    raw_fill = fill.get("raw") if isinstance(fill, dict) else None
    if isinstance(raw_fill, dict):
        try:
            if raw_fill.get("makingAmount") not in (None, ""):
                actual_shares_sold = float(raw_fill.get("makingAmount"))
            if raw_fill.get("takingAmount") not in (None, ""):
                actual_sell_proceeds = float(raw_fill.get("takingAmount"))
            if actual_shares_sold > 0 and actual_sell_proceeds > 0:
                avg_fill_price = actual_sell_proceeds / actual_shares_sold
                filled_size = actual_shares_sold
        except Exception as e:
            print(f"[BTC5M] SELL accounting parse warning: {e}")

    remaining_token_balance = None
    try:
        post_sell_info = read_conditional_balance_allowance(client, str(token_id))
        remaining_token_balance = normalize_usdc_balance(float(post_sell_info.get("balance", 0.0)))
    except Exception as e:
        print(f"[BTC5M] post-sell token balance check failed for token={token_id}: {e}")

    return {
        "response": response,
        "order_id": order_id,
        "fill": fill,
        "fill_state": fill_state,
        "token_id": token_id,
        "price": avg_fill_price,
        "limit_price": price,
        "size": filled_size,
        "actual_sell_proceeds": actual_sell_proceeds,
        "actual_sell_shares": actual_shares_sold,
        "remaining_token_balance": remaining_token_balance,
        "balance_info": str(balance_info["raw"]),
    }


def apply_live_partial_exit(
    state: dict[str, Any],
    market_id: str,
    position: dict[str, Any],
    outcome: str,
    exit_price: float,
    sold_size: float,
    net_pnl: float,
    close_reason: str,
    reason_text: str,
    live_result: dict[str, Any],
    simulated: bool,
) -> bool:
    raw_remaining = live_result.get("remaining_token_balance")
    if raw_remaining is None:
        return False

    try:
        remaining_size = float(raw_remaining)
    except Exception:
        return False

    min_leftover = float(os.getenv("BTC_5M_MIN_FILLED_SIZE", "0.01"))
    if remaining_size < min_leftover:
        return False

    original_size = float(position.get("size", sold_size))
    original_buy_cost = float(position.get("actual_buy_cost", float(position["entry_price"]) * original_size))
    original_buy_shares = float(position.get("actual_buy_shares", original_size))

    if original_buy_shares > 0:
        sold_cost_basis = original_buy_cost * (sold_size / original_buy_shares)
        remaining_cost_basis = max(0.0, original_buy_cost - sold_cost_basis)
    else:
        remaining_cost_basis = float(position["entry_price"]) * remaining_size

    position["size"] = remaining_size
    position["actual_buy_shares"] = remaining_size
    position["actual_buy_cost"] = remaining_cost_basis
    position["partial_exit_last_at"] = utc_now()
    position["partial_exit_last_reason"] = close_reason
    position["partial_exit_last_sold_size"] = sold_size
    position["partial_exit_last_remaining_size"] = remaining_size
    position["partial_exit_last_pnl"] = net_pnl
    position["partial_exit_last_order_id"] = live_result.get("order_id")

    state["daily_pnl"] = float(state.get("daily_pnl", 0.0)) + net_pnl
    state["total_pnl"] = float(state.get("total_pnl", 0.0)) + net_pnl

    log_trade([
        utc_now(),
        os.getenv("BTC_5M_MODE", "paper").lower(),
        market_id,
        "PARTIAL_EXIT",
        outcome,
        exit_price,
        sold_size,
        simulated,
        reason_text + f" remaining_token_balance={remaining_size}",
        net_pnl,
    ])

    print(
        f"[BTC5M] PARTIAL_EXIT {outcome} sold={sold_size:.4f} "
        f"remaining={remaining_size:.4f} net_after_buffer={net_pnl:.4f}"
    )
    return True


def settle_expired_positions(state: dict[str, Any]) -> None:
    open_positions = state.setdefault("open_positions", {})
    if not open_positions:
        return

    now_ts = int(time.time())
    settled_market_ids: list[str] = []

    for market_id, position in list(open_positions.items()):
        if position.get("resolved"):
            continue
        entry_ts_raw = position.get("timestamp")
        if not entry_ts_raw:
            continue

        try:
            entry_dt = datetime.fromisoformat(entry_ts_raw.replace("Z", "+00:00"))
            entry_ts = int(entry_dt.timestamp())
        except Exception:
            continue

        market_start_ts = entry_ts - (entry_ts % 300)
        market_end_ts = market_start_ts + 300
        if now_ts < market_end_ts + 10:
            continue

        try:
            resp = HTTP_SESSION.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "5m",
                    "startTime": market_start_ts * 1000,
                    "endTime": market_end_ts * 1000,
                    "limit": 1,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                print(f"[BTC5M] settlement Binance error {resp.status_code} for {market_id}")
                continue
            candles = resp.json()
            if not candles:
                print(f"[BTC5M] settlement no candle found for {market_id}")
                continue

            candle = candles[0]
            final_price = float(candle[4])
            strike = float(position["strike"])
            outcome = position["outcome"]
            entry_price = float(position["entry_price"])
            size = float(position["size"])

            if state.get("mode") == "live":
                if not position.get("expired_live"):
                    print(f"[BTC5M] live position reached expiry; keeping in state for manual reconciliation {market_id}")
                    position["expired_live"] = True
                    position["expired_at"] = utc_now()
                    position["note"] = "Live expiry reached; manual Polymarket reconciliation required"
                continue

            winning_outcome = "YES" if final_price > strike else "NO"
            won = outcome == winning_outcome
            pnl = (1.0 - entry_price) * size if won else -entry_price * size

            state["daily_pnl"] = float(state.get("daily_pnl", 0.0)) + pnl
            state["total_pnl"] = float(state.get("total_pnl", 0.0)) + pnl
            position.update({
                "resolved": True,
                "final_price": final_price,
                "winning_outcome": winning_outcome,
                "pnl": pnl,
                "settled_at": utc_now(),
            })

            log_trade([
                utc_now(),
                "paper",
                market_id,
                "SETTLE",
                outcome,
                entry_price,
                size,
                True,
                f"final={final_price} strike={strike} winner={winning_outcome}",
                pnl,
            ])
            print(
                f"[BTC5M] SETTLED market={market_id} entry={outcome}@{entry_price} "
                f"final={final_price} strike={strike} winner={winning_outcome} pnl={pnl:.4f}"
            )
            settled_market_ids.append(market_id)
        except Exception as e:
            print(f"[BTC5M] settlement error for {market_id}: {e}")

    for market_id in settled_market_ids:
        open_positions.pop(market_id, None)


def maybe_cashout_profitable_position(state: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    if os.getenv("BTC_5M_ENABLE_CASHOUT", "true").lower() != "true":
        return False

    open_positions = state.setdefault("open_positions", {})
    closed_markets = state.setdefault("closed_markets", {})
    market_id = snapshot["market_id"]
    position = open_positions.get(market_id)
    if not position:
        return False

    if position.get("reconcile_required"):
        print(
            f"[BTC5M] position {market_id} requires manual reconciliation, "
            "skipping automated exit attempts"
        )
        return False

    outcome = position["outcome"]
    entry_price = float(position["entry_price"])
    position_size = float(position["size"])

    bid_key = "yes_bid" if outcome == "YES" else "no_bid" if outcome == "NO" else None
    if bid_key is None:
        return False

    exit_price_raw = snapshot.get(bid_key)
    if exit_price_raw is None:
        print(f"[BTC5M] cannot cashout {market_id}, missing bid for {outcome}")
        return False

    exit_price = float(exit_price_raw)
    min_net_profit = float(os.getenv("BTC_5M_MIN_NET_PROFIT", "0.02"))
    extra_fee_buffer = float(os.getenv("BTC_5M_EXTRA_FEE_BUFFER", "0.01"))
    max_net_loss = float(os.getenv("BTC_5M_MAX_NET_LOSS", "0.75"))
    hard_max_net_loss = float(os.getenv("BTC_5M_HARD_MAX_NET_LOSS", "0"))
    enable_stoploss = os.getenv("BTC_5M_ENABLE_STOPLOSS", "true").lower() == "true"

    enable_profit_protection = os.getenv("BTC_5M_ENABLE_PROFIT_PROTECTION", "false").lower() == "true"
    profit_protect_arm_net = float(os.getenv("BTC_5M_PROFIT_PROTECT_ARM_NET", "0.15"))
    profit_protect_exit_net = float(os.getenv("BTC_5M_PROFIT_PROTECT_EXIT_NET", "0.00"))
    profit_protect_min_seconds = int(os.getenv("BTC_5M_PROFIT_PROTECT_MIN_SECONDS", "90"))
    profit_protect_thesis_flip_exit = (
        os.getenv("BTC_5M_PROFIT_PROTECT_THESIS_FLIP_EXIT", "true").lower() == "true"
    )
    profit_protect_max_exit_loss = float(os.getenv("BTC_5M_PROFIT_PROTECT_MAX_EXIT_LOSS", "0.25"))
    profit_protect_giveback = float(os.getenv("BTC_5M_PROFIT_PROTECT_GIVEBACK", "0.45"))
    profit_protect_min_best_net = float(os.getenv("BTC_5M_PROFIT_PROTECT_MIN_BEST_NET", "0.30"))
    profit_protect_max_giveback_exit_loss = float(
        os.getenv("BTC_5M_PROFIT_PROTECT_MAX_GIVEBACK_EXIT_LOSS", "0.35")
    )

    force_exit_seconds = int(os.getenv("BTC_5M_FORCE_EXIT_SECONDS", "105"))
    force_exit_min_net = float(os.getenv("BTC_5M_FORCE_EXIT_MIN_NET", "-0.20"))
    strong_thesis_hold_seconds = int(os.getenv("BTC_5M_STRONG_THESIS_HOLD_SECONDS", "90"))
    strong_thesis_min_net = float(os.getenv("BTC_5M_STRONG_THESIS_MIN_NET", "0.00"))
    strong_thesis_min_distance = float(os.getenv("BTC_5M_STRONG_THESIS_MIN_DISTANCE", "0.00018"))
    force_exit_flat_net = float(os.getenv("BTC_5M_FORCE_EXIT_FLAT_NET", "0.05"))

    enable_trailing = os.getenv("BTC_5M_ENABLE_TRAILING_PROFIT", "false").lower() == "true"
    trail_activate_net = float(os.getenv("BTC_5M_TRAIL_ACTIVATE_NET", "0.30"))
    trail_drop = float(os.getenv("BTC_5M_TRAIL_DROP", "0.08"))
    trail_min_seconds = int(os.getenv("BTC_5M_TRAIL_MIN_SECONDS_TO_EXPIRY", "90"))
    trail_force_cashout_net = float(os.getenv("BTC_5M_TRAIL_FORCE_CASHOUT_NET", "0.90"))

    gross_pnl = (exit_price - entry_price) * position_size
    fee_buffer_cost = extra_fee_buffer * position_size
    net_pnl = gross_pnl - fee_buffer_cost

    btc_price = float(snapshot["btc_price"])
    strike = float(position["strike"])
    seconds_to_expiry = int(snapshot.get("seconds_to_expiry", 999))

    thesis_valid = (
        (outcome == "YES" and btc_price > strike)
        or (outcome == "NO" and btc_price < strike)
    )
    thesis_invalidated = not thesis_valid
    distance_from_strike = abs(btc_price - strike) / strike if strike > 0 else 0.0
    thesis_weakening = thesis_invalidated or distance_from_strike < strong_thesis_min_distance
    thesis_strong = (
        thesis_valid
        and distance_from_strike >= strong_thesis_min_distance
        and net_pnl >= strong_thesis_min_net
    )

    profit_protection_active = bool(position.get("profit_protection_active", False))
    if enable_profit_protection and seconds_to_expiry >= profit_protect_min_seconds:
        best_net_pnl_seen = max(float(position.get("best_net_pnl_seen", net_pnl)), net_pnl)
        position["best_net_pnl_seen"] = best_net_pnl_seen

        if not profit_protection_active and best_net_pnl_seen >= profit_protect_arm_net:
            profit_protection_active = True
            position["profit_protection_active"] = True
            position["profit_protection_armed_at"] = utc_now()
            position["profit_protection_arm_net"] = best_net_pnl_seen
            print(
                f"[BTC5M] PROFIT_PROTECTION armed {outcome} "
                f"entry={entry_price} bid={exit_price} net={net_pnl:.4f} "
                f"best_net={best_net_pnl_seen:.4f}"
            )

    should_take_profit = net_pnl >= min_net_profit * position_size
    should_stop_loss = enable_stoploss and thesis_invalidated and net_pnl <= -abs(max_net_loss)
    should_hard_stop_loss = (
        enable_stoploss
        and hard_max_net_loss > 0
        and net_pnl <= -abs(hard_max_net_loss)
    )

    should_profit_protect_exit = False
    should_profit_protect_thesis_flip_exit = False
    if enable_profit_protection and profit_protection_active:
        if (
            seconds_to_expiry >= profit_protect_min_seconds
            and thesis_invalidated
            and net_pnl <= profit_protect_exit_net
            and net_pnl >= -abs(profit_protect_max_exit_loss)
        ):
            should_profit_protect_exit = True

        if (
            profit_protect_thesis_flip_exit
            and thesis_invalidated
            and net_pnl >= -abs(profit_protect_max_exit_loss)
        ):
            should_profit_protect_thesis_flip_exit = True

        best_net_pnl_seen = float(position.get("best_net_pnl_seen", net_pnl))
        if (
            best_net_pnl_seen >= profit_protect_min_best_net
            and net_pnl <= best_net_pnl_seen - profit_protect_giveback
            and net_pnl >= -abs(profit_protect_max_giveback_exit_loss)
        ):
            should_profit_protect_exit = True

    should_force_time_exit = False
    if seconds_to_expiry <= force_exit_seconds:
        if seconds_to_expiry <= strong_thesis_hold_seconds:
            should_force_time_exit = net_pnl >= force_exit_min_net
        elif thesis_strong:
            should_force_time_exit = False
        elif net_pnl >= -abs(force_exit_flat_net):
            should_force_time_exit = True
        elif thesis_weakening and net_pnl >= force_exit_min_net:
            should_force_time_exit = True

    trailing_active = bool(position.get("trailing_active", False))
    should_trailing_exit = False
    if (
        enable_trailing
        and not should_stop_loss
        and not should_hard_stop_loss
        and not should_force_time_exit
        and not should_profit_protect_exit
        and not should_profit_protect_thesis_flip_exit
    ):
        if net_pnl >= trail_force_cashout_net:
            should_take_profit = True
        elif seconds_to_expiry <= trail_min_seconds:
            if trailing_active:
                should_trailing_exit = net_pnl >= force_exit_min_net
                should_take_profit = False
        elif net_pnl >= trail_activate_net:
            best_exit_price = max(float(position.get("best_exit_price", exit_price)), exit_price)
            position["trailing_active"] = True
            position["best_exit_price"] = best_exit_price
            position["best_net_pnl"] = max(float(position.get("best_net_pnl", net_pnl)), net_pnl)
            position["trailing_updated_at"] = utc_now()
            print(
                f"[BTC5M] TRAILING {outcome} active "
                f"entry={entry_price} bid={exit_price} "
                f"best_bid={best_exit_price} net={net_pnl:.4f}"
            )
            should_take_profit = False
            should_trailing_exit = exit_price <= best_exit_price - trail_drop
        elif trailing_active:
            best_exit_price = float(position.get("best_exit_price", exit_price))
            should_take_profit = False
            should_trailing_exit = exit_price <= best_exit_price - trail_drop

    if not any([
        should_take_profit,
        should_trailing_exit,
        should_force_time_exit,
        should_profit_protect_exit,
        should_profit_protect_thesis_flip_exit,
        should_stop_loss,
        should_hard_stop_loss,
    ]):
        return False

    if should_hard_stop_loss:
        close_reason = "hard_stop_loss"
        trade_action = "STOPLOSS"
    elif should_stop_loss:
        close_reason = "stop_loss"
        trade_action = "STOPLOSS"
    elif should_profit_protect_thesis_flip_exit:
        close_reason = "profit_protect_thesis_flip"
        trade_action = "PROTECT_EXIT"
    elif should_profit_protect_exit:
        close_reason = "profit_protect"
        trade_action = "PROTECT_EXIT"
    elif should_trailing_exit:
        close_reason = "trailing_profit"
        trade_action = "TRAIL_EXIT"
    elif should_take_profit:
        close_reason = "cashout_profit"
        trade_action = "CASHOUT"
    elif should_force_time_exit:
        close_reason = "time_cashout_profit" if net_pnl > 0 else "force_time_exit"
        trade_action = "CASHOUT" if net_pnl > 0 else "TIME_EXIT"
    else:
        close_reason = "unknown_exit"
        trade_action = "EXIT"

    mode = os.getenv("BTC_5M_MODE", "paper").lower()
    simulated = mode != "live"
    live_result: Optional[dict[str, Any]] = None
    live_response: Any = None

    if mode == "live":
        try:
            live_exit_price = exit_price
            if trade_action == "STOPLOSS" or (trade_action == "TIME_EXIT" and net_pnl < 0):
                live_exit_price = max(0.01, exit_price - float(os.getenv("BTC_5M_STOPLOSS_EXIT_SLIPPAGE", "0.02")))
            elif trade_action == "PROTECT_EXIT":
                live_exit_price = max(0.01, exit_price - float(os.getenv("BTC_5M_PROTECT_EXIT_SLIPPAGE", "0.01")))
            elif trade_action == "CASHOUT":
                live_exit_price = max(0.01, exit_price - float(os.getenv("BTC_5M_CASHOUT_EXIT_SLIPPAGE", "0.01")))
            elif trade_action == "TRAIL_EXIT":
                live_exit_price = max(0.01, exit_price - float(os.getenv("BTC_5M_TRAIL_EXIT_SLIPPAGE", "0.01")))

            live_result = place_live_limit_sell(position, live_exit_price)
            live_response = live_result["response"]
            simulated = False

            actual_exit_price = float(live_result["price"])
            actual_exit_size = float(live_result["size"])
            actual_sell_proceeds = float(
                live_result.get("actual_sell_proceeds", actual_exit_price * actual_exit_size)
            )

            position_buy_cost = float(position.get("actual_buy_cost", entry_price * position_size))
            position_buy_shares = float(position.get("actual_buy_shares", position_size))
            cost_basis_for_sold_size = (
                position_buy_cost * (actual_exit_size / position_buy_shares)
                if position_buy_shares > 0
                else entry_price * actual_exit_size
            )

            gross_pnl = actual_sell_proceeds - cost_basis_for_sold_size
            fee_buffer_cost = extra_fee_buffer * actual_exit_size
            net_pnl = gross_pnl - fee_buffer_cost
            exit_price = actual_exit_price
            position_size = actual_exit_size

        except Exception as e:
            error_text = str(e)
            print(f"[BTC5M] LIVE EXIT FAILED/BLOCKED: {error_text}")

            if is_zero_token_balance_error(error_text):
                try:
                    token_balance = get_live_token_balance_for_position(position)
                except Exception as balance_error:
                    token_balance = -1.0
                    position["reconcile_balance_check_error"] = str(balance_error)

                if 0 <= token_balance < float(os.getenv("BTC_5M_MIN_FILLED_SIZE", "0.01")):
                    actual_buy_cost = float(position.get("actual_buy_cost", entry_price * float(position["size"])))
                    actual_buy_shares = float(position.get("actual_buy_shares", position.get("size", position_size)))
                    estimated_sell_proceeds = exit_price * actual_buy_shares
                    gross_pnl = estimated_sell_proceeds - actual_buy_cost
                    fee_buffer_cost = extra_fee_buffer * actual_buy_shares
                    net_pnl = gross_pnl - fee_buffer_cost

                    state["daily_pnl"] = float(state.get("daily_pnl", 0.0)) + net_pnl
                    state["total_pnl"] = float(state.get("total_pnl", 0.0)) + net_pnl

                    reason_text = (
                        f"zero_token_balance_reconciled_after_sell_error "
                        f"error={error_text} token_balance={token_balance} "
                        f"entry={entry_price} estimated_exit={exit_price} "
                        f"estimated_sell_proceeds={estimated_sell_proceeds:.4f} "
                        f"actual_buy_cost={actual_buy_cost:.4f} "
                        f"gross={gross_pnl:.4f} fee_buffer={fee_buffer_cost:.4f}"
                    )

                    log_trade([
                        utc_now(),
                        mode,
                        market_id,
                        "RECONCILED_EXIT",
                        outcome,
                        exit_price,
                        actual_buy_shares,
                        False,
                        reason_text,
                        net_pnl,
                    ])

                    closed_markets[market_id] = {
                        "timestamp": utc_now(),
                        "reason": "zero_token_balance_reconciled",
                        "outcome": outcome,
                        "entry_price": entry_price,
                        "exit_price": float(exit_price),
                        "size": actual_buy_shares,
                        "net_pnl": net_pnl,
                        "question": snapshot.get("question"),
                    }
                    open_positions.pop(market_id, None)
                    print(
                        f"[BTC5M] RECONCILED_EXIT {outcome} token balance is zero; "
                        f"closing local state. estimated_net={net_pnl:.4f}"
                    )
                    return True

                position["reconcile_required"] = True
                position["reconcile_reason"] = error_text
                position["reconcile_token_balance"] = token_balance
                position["reconcile_at"] = utc_now()
                print(
                    f"[BTC5M] WARNING: position {market_id} marked for manual reconciliation. "
                    f"token_balance={token_balance}. Bot will not retry automated exits."
                )
            return False

    reason_text = (
        f"entry={entry_price} exit={exit_price} "
        f"gross={gross_pnl:.4f} fee_buffer={fee_buffer_cost:.4f} "
        f"best_net_pnl_seen={position.get('best_net_pnl_seen')} "
        f"profit_protection_active={position.get('profit_protection_active')} "
        f"thesis_valid={thesis_valid} thesis_invalidated={thesis_invalidated} "
        f"distance_from_strike={distance_from_strike:.8f}"
    )

    if live_result is not None:
        reason_text += (
            f" actual_sell_proceeds={live_result.get('actual_sell_proceeds')} "
            f"actual_sell_shares={live_result.get('actual_sell_shares')} "
            f"actual_buy_cost={position.get('actual_buy_cost')} "
            f"actual_buy_shares={position.get('actual_buy_shares')} "
            f"remaining_token_balance={live_result.get('remaining_token_balance')} "
            f"exit_order_id={live_result.get('order_id')} "
            f"exit_fill_state={live_result.get('fill_state')} "
            f"live_response={live_response}"
        )

    if live_result is not None and apply_live_partial_exit(
        state=state,
        market_id=market_id,
        position=position,
        outcome=outcome,
        exit_price=exit_price,
        sold_size=position_size,
        net_pnl=net_pnl,
        close_reason=close_reason,
        reason_text=reason_text,
        live_result=live_result,
        simulated=simulated,
    ):
        return True

    state["daily_pnl"] = float(state.get("daily_pnl", 0.0)) + net_pnl
    state["total_pnl"] = float(state.get("total_pnl", 0.0)) + net_pnl

    log_trade([
        utc_now(),
        mode,
        market_id,
        trade_action,
        outcome,
        exit_price,
        position_size,
        simulated,
        reason_text,
        net_pnl,
    ])
    print(
        f"[BTC5M] {trade_action} {outcome} entry={entry_price} exit={exit_price} "
        f"gross={gross_pnl:.4f} net_after_buffer={net_pnl:.4f}"
    )

    closed_markets[market_id] = {
        "timestamp": utc_now(),
        "reason": close_reason,
        "outcome": outcome,
        "entry_price": entry_price,
        "exit_price": float(exit_price),
        "size": position_size,
        "net_pnl": net_pnl,
        "question": snapshot.get("question"),
    }
    open_positions.pop(market_id, None)
    return True

def get_btc_5m_market_snapshot() -> Optional[dict[str, Any]]:
    def parse_json_field(value: Any, fallback: Any) -> Any:
        if value is None:
            return fallback
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return fallback
        return value

    def best_bid_ask(book: Any) -> tuple[Optional[float], Optional[float]]:
        if isinstance(book, dict):
            bids = book.get("bids", [])
            asks = book.get("asks", [])
        else:
            bids = getattr(book, "bids", []) or []
            asks = getattr(book, "asks", []) or []

        def price(level: Any) -> float:
            if isinstance(level, dict):
                return float(level["price"])
            return float(getattr(level, "price"))

        return max([price(b) for b in bids], default=None), min([price(a) for a in asks], default=None)

    now = int(time.time())
    interval_start = now - (now % 300)
    interval_end = interval_start + 300
    seconds_to_expiry = interval_end - now
    slug = f"btc-updown-5m-{interval_start}"

    try:
        event_resp = HTTP_SESSION.get(f"https://gamma-api.polymarket.com/events/slug/{slug}", timeout=10)
        if event_resp.status_code != 200:
            print(f"[BTC5M] Gamma lookup failed: {event_resp.status_code} slug={slug}")
            return None
        event = event_resp.json()
    except Exception as e:
        print(f"[BTC5M] Gamma lookup error: {e}")
        return None

    markets = event.get("markets", [])
    if not markets:
        print(f"[BTC5M] event found but no markets: {slug}")
        return None

    market = markets[0]
    token_ids = parse_json_field(market.get("clobTokenIds"), [])
    if len(token_ids) < 2:
        print("[BTC5M] missing clobTokenIds")
        return None

    up_token = token_ids[0]
    down_token = token_ids[1]

    try:
        kline_resp = HTTP_SESSION.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": "5m", "limit": 1},
            timeout=10,
        )
        if kline_resp.status_code != 200:
            print(f"[BTC5M] Binance kline failed: {kline_resp.status_code}")
            return None
        kline = kline_resp.json()[0]
        strike = float(kline[1])
        btc_price = float(kline[4])
    except Exception as e:
        print(f"[BTC5M] Binance kline error: {e}")
        return None

    momentum_60s = (btc_price - strike) / strike if strike > 0 else 0.0
    volatility_60s = abs(momentum_60s)

    try:
        client = get_public_clob_client()
        up_book = client.get_order_book(up_token)
        down_book = client.get_order_book(down_token)
        up_bid, up_ask = best_bid_ask(up_book)
        down_bid, down_ask = best_bid_ask(down_book)
    except Exception as e:
        print(f"[BTC5M] order book error: {e}")
        return None

    question = market.get("question", "")
    print(
        f"[BTC5M] market={slug} btc={btc_price} strike={strike} "
        f"up_bid={up_bid} up_ask={up_ask} down_bid={down_bid} down_ask={down_ask} "
        f"t={seconds_to_expiry}s"
    )

    return {
        "market_id": market.get("conditionId") or market.get("id") or slug,
        "question": question,
        "btc_price": btc_price,
        "strike": strike,
        "seconds_to_expiry": seconds_to_expiry,
        "yes_bid": up_bid,
        "yes_ask": up_ask,
        "no_bid": down_bid,
        "no_ask": down_ask,
        "momentum_60s": momentum_60s,
        "volatility_60s": volatility_60s,
        "yes_token_id": up_token,
        "no_token_id": down_token,
    }


def build_strategy_from_env() -> BTC5MHybridStrategy:
    return BTC5MHybridStrategy(
        min_edge=float(os.getenv("BTC_5M_MIN_EDGE", "0.05")),
        max_spread=float(os.getenv("BTC_5M_MAX_SPREAD", "0.08")),
        order_size=float(os.getenv("BTC_5M_ORDER_SIZE", "1")),
        no_trade_last_seconds=int(os.getenv("BTC_5M_NO_TRADE_LAST_SECONDS", "120")),
        min_seconds_to_expiry=int(os.getenv("BTC_5M_MIN_SECONDS_TO_EXPIRY", "120")),
        max_seconds_to_expiry=int(os.getenv("BTC_5M_MAX_SECONDS_TO_EXPIRY", "240")),
        min_distance_from_strike=float(os.getenv("BTC_5M_MIN_DISTANCE_FROM_STRIKE", "0.00012")),
        late_distance_seconds=int(os.getenv("BTC_5M_LATE_DISTANCE_SECONDS", "150")),
        late_min_distance_from_strike=float(os.getenv("BTC_5M_LATE_MIN_DISTANCE_FROM_STRIKE", "0.00018")),
        require_momentum_confirmation=os.getenv("BTC_5M_REQUIRE_MOMENTUM_CONFIRMATION", "true").lower() == "true",
    )


def main() -> None:
    mode = os.getenv("BTC_5M_MODE", "paper").lower()
    loop_seconds = int(os.getenv("BTC_5M_LOOP_SECONDS", "10"))
    strategy = build_strategy_from_env()

    ensure_csv_headers()
    state = load_state()
    state["mode"] = mode
    state = reconcile_live_state_on_startup(state)
    save_state(state)

    print(f"[BTC5M] bot started in {mode} mode")
    print_startup_config()
    if mode == "live":
        missing_live_env = [
            name
            for name in ["PK", "CLOB_API_KEY", "CLOB_SECRET", "CLOB_PASS_PHRASE"]
            if not os.getenv(name)
        ]
        if missing_live_env:
            print(f"[BTC5M] LIVE config missing: {', '.join(missing_live_env)}")
        if live_mode_is_armed():
            print("[BTC5M] LIVE MODE ARMED: real orders are enabled")
        else:
            print("[BTC5M] LIVE MODE requested but real orders are blocked by safety flags")

    while True:
        try:
            settle_expired_positions(state)
            save_state(state)

            snapshot = get_btc_5m_market_snapshot()
            if snapshot is None:
                print("[BTC5M] no active BTC 5m market found")
                time.sleep(loop_seconds)
                continue

            if maybe_cashout_profitable_position(state, snapshot):
                save_state(state)
                time.sleep(loop_seconds)
                continue

            decision = strategy.decide(
                btc_price=snapshot["btc_price"],
                strike=snapshot["strike"],
                seconds_to_expiry=snapshot["seconds_to_expiry"],
                yes_bid=snapshot["yes_bid"],
                yes_ask=snapshot["yes_ask"],
                no_bid=snapshot["no_bid"],
                no_ask=snapshot["no_ask"],
                momentum_60s=snapshot.get("momentum_60s", 0.0),
                volatility_60s=snapshot.get("volatility_60s", 0.0),
            )

            log_decision([
                utc_now(),
                snapshot["market_id"],
                snapshot["question"],
                snapshot["btc_price"],
                snapshot["strike"],
                snapshot["seconds_to_expiry"],
                snapshot["yes_bid"],
                snapshot["yes_ask"],
                snapshot["no_bid"],
                snapshot["no_ask"],
                decision.model_probability,
                decision.market_probability,
                decision.edge,
                decision.action,
                decision.reason,
            ])

            if decision.action != "BUY":
                print(f"[BTC5M] {decision.action} reason={decision.reason} edge={decision.edge}")
                save_state(state)
                time.sleep(loop_seconds)
                continue

            market_id = snapshot["market_id"]
            open_positions = state.setdefault("open_positions", {})
            closed_markets = state.setdefault("closed_markets", {})
            live_failed_orders = state.setdefault("live_failed_orders", {})

            if mode == "live" and live_daily_loss_exceeded(state):
                print(f"[BTC5M] live daily loss lockout active. daily_pnl={state.get('daily_pnl')}")
                save_state(state)
                time.sleep(loop_seconds)
                continue

            # Uncertain live failures are always blocked for the rest of that market.
            if market_id in live_failed_orders:
                print(f"[BTC5M] market {market_id} has uncertain live failure, skipping")
                save_state(state)
                time.sleep(loop_seconds)
                continue

            if (
                os.getenv("BTC_5M_PREVENT_REENTRY_AFTER_CASHOUT", "true").lower() == "true"
                and market_id in closed_markets
            ):
                print(f"[BTC5M] market {market_id} already closed, skipping re-entry")
                save_state(state)
                time.sleep(loop_seconds)
                continue

            if market_id in open_positions:
                save_state(state)
                time.sleep(loop_seconds)
                continue

            if mode == "paper":
                open_positions[market_id] = {
                    "timestamp": utc_now(),
                    "market_id": market_id,
                    "outcome": decision.outcome,
                    "side": decision.side,
                    "entry_price": decision.price,
                    "size": decision.size,
                    "question": snapshot["question"],
                    "btc_price_at_entry": snapshot["btc_price"],
                    "strike": snapshot["strike"],
                    "seconds_to_expiry_at_entry": snapshot["seconds_to_expiry"],
                    "reason": decision.reason,
                    "resolved": False,
                }
                log_trade([
                    utc_now(),
                    mode,
                    market_id,
                    decision.side,
                    decision.outcome,
                    decision.price,
                    decision.size,
                    True,
                    decision.reason,
                    0.0,
                ])
                print(f"[BTC5M] paper BUY {decision.outcome} @ {decision.price}")

            elif mode == "live":
                try:
                    live_result = place_live_limit_buy(snapshot, decision)
                    open_positions[market_id] = {
                        "timestamp": utc_now(),
                        "market_id": market_id,
                        "mode": "live",
                        "outcome": decision.outcome,
                        "side": decision.side,
                        "entry_price": live_result["price"],
                        "limit_entry_price": live_result["limit_price"],
                        "size": live_result["size"],
                        "requested_size": live_result["requested_size"],
                        "question": snapshot["question"],
                        "btc_price_at_entry": snapshot["btc_price"],
                        "strike": snapshot["strike"],
                        "seconds_to_expiry_at_entry": snapshot["seconds_to_expiry"],
                        "reason": decision.reason,
                        "token_id": live_result["token_id"],
                        "entry_order_id": live_result["order_id"],
                        "entry_fill_state": live_result["fill_state"],
                        "entry_fill": str(live_result["fill"]),
                        "order_value": live_result["order_value"],
                        "actual_buy_cost": live_result.get("actual_buy_cost", live_result["order_value"]),
                        "actual_buy_shares": live_result.get("actual_buy_shares", live_result["size"]),
                        "live_response": str(live_result["response"]),
                        "resolved": False,
                    }
                    log_trade([
                        utc_now(),
                        mode,
                        market_id,
                        decision.side,
                        decision.outcome,
                        live_result["price"],
                        live_result["size"],
                        False,
                        f"live_buy order_id={live_result['order_id']} fill_state={live_result['fill_state']} response={live_result['response']}",
                        0.0,
                    ])
                    print(
                        f"[BTC5M] LIVE BUY {decision.outcome} @ {live_result['price']} "
                        f"size={live_result['size']} value={live_result['order_value']:.4f}"
                    )
                except Exception as e:
                    error_text = str(e)
                    print(f"[BTC5M] LIVE ORDER BLOCKED/FAILED: {error_text}")

                    if isinstance(e, LiveOrderUnfilledCancelled):
                        state.setdefault("live_unfilled_cancelled_orders", {})[market_id] = {
                            "timestamp": utc_now(),
                            "reason": error_text,
                            "question": snapshot.get("question"),
                            "btc_price": snapshot.get("btc_price"),
                            "strike": snapshot.get("strike"),
                        }

                        # Safe: order was posted, did not fill, and was cancelled.
                        # Do not mark this market as uncertain and do not warn UI check.
                        save_state(state)
                        time.sleep(loop_seconds)
                        continue

                    safety_gate_blocked = isinstance(e, LiveOrderPreCheckBlocked) or (
                        "Live order blocked. Require BTC_5M_MODE=live" in error_text
                        or not live_mode_is_armed()
                    )

                    if safety_gate_blocked:
                        state.setdefault("live_blocked_orders", {})[market_id] = {
                            "timestamp": utc_now(),
                            "reason": error_text,
                            "question": snapshot.get("question"),
                            "btc_price": snapshot.get("btc_price"),
                            "strike": snapshot.get("strike"),
                        }

                        # Do not mark the market as uncertain. No real order was posted.
                        save_state(state)
                        time.sleep(loop_seconds)
                        continue

                    state.setdefault("live_failed_orders", {})[market_id] = {
                        "timestamp": utc_now(),
                        "reason": error_text,
                        "question": snapshot.get("question"),
                        "btc_price": snapshot.get("btc_price"),
                        "strike": snapshot.get("strike"),
                    }

                    print(
                        "[BTC5M] WARNING: live order failed/uncertain after post attempt. "
                        "Check Polymarket UI immediately before continuing."
                    )

                    state.setdefault("closed_markets", {})[market_id] = {
                        "timestamp": utc_now(),
                        "reason": "live_order_failed_or_uncertain",
                        "question": snapshot.get("question"),
                    }

                    save_state(state)

            save_state(state)
            time.sleep(loop_seconds)

        except KeyboardInterrupt:
            print("[BTC5M] stopped by user")
            break
        except Exception as e:
            print(f"[BTC5M] error: {e}")
            time.sleep(loop_seconds)


if __name__ == "__main__":
    main()
