# file: live_executor.py

import os
import time
from datetime import datetime, timezone

from py_clob_client_v2 import (
    ClobClient as ClobClientV2,
    OrderArgs,
    OrderType,
    PartialCreateOrderOptions,
    Side,
    OrderPayload,
)

from py_clob_client.client import ClobClient as ClobClientV1
from py_clob_client.clob_types import (
    BalanceAllowanceParams,
    AssetType,
)

from config import (
    LIVE_TRADING_ENABLED,
    LIVE_ORDER_SIZE,
    MAX_LIVE_ORDER_SIZE,
    MAX_LIVE_ORDER_VALUE,
    POLYMARKET_HOST,
    POLYMARKET_CHAIN_ID,
    POLYMARKET_PRIVATE_KEY_ENV,
    POLYMARKET_FUNDER_ENV,
    POLYMARKET_SIGNATURE_TYPE,
    LIVE_ORDER_TYPE,
    LIVE_TICK_SIZE,
    LIVE_ADOPT_OPEN_ORDERS,
    LIVE_REFUSE_START_WITH_OPEN_ORDERS,
    LIVE_API_MAX_RETRIES,
    LIVE_API_RETRY_SLEEP_SECONDS,
)


class LiveExecutor:
    """
    Live executor using py-clob-client-v2 for order placement/cancellation.

    Interface expected by mm_loop.py:
    - place_order(...)
    - cancel_order(order)
    - cancel_all_for_token(token_id)
    - cancel_all_orders()
    - get_open_orders()
    - check_fills(market_rows)
    - get_balance_allowance()
    """

    def __init__(self):
        if not LIVE_TRADING_ENABLED:
            raise RuntimeError(
                "Live trading is disabled. Set LIVE_TRADING_ENABLED=True only when ready."
            )

        private_key = os.getenv(POLYMARKET_PRIVATE_KEY_ENV)
        funder = os.getenv(POLYMARKET_FUNDER_ENV)

        if not private_key:
            raise RuntimeError(f"Missing env var: {POLYMARKET_PRIVATE_KEY_ENV}")

        if not funder:
            raise RuntimeError(f"Missing env var: {POLYMARKET_FUNDER_ENV}")

        self.private_key = private_key
        self.funder = funder

        # V1 client: read-only/account endpoints that we already tested:
        # balance, open orders, trades.
        self.read_client = ClobClientV1(
            POLYMARKET_HOST,
            key=private_key,
            chain_id=POLYMARKET_CHAIN_ID,
            signature_type=POLYMARKET_SIGNATURE_TYPE,
            funder=funder,
        )

        read_creds = self.read_client.create_or_derive_api_creds()
        self.read_client.set_api_creds(read_creds)

        # V2 client: order creation/cancellation.
        self.l1_client = ClobClientV2(
            host=POLYMARKET_HOST,
            chain_id=POLYMARKET_CHAIN_ID,
            key=private_key,
            signature_type=POLYMARKET_SIGNATURE_TYPE,
            funder=funder,
        )

        v2_creds = self._with_retries(
            "create_or_derive_api_key",
            lambda: self.l1_client.create_or_derive_api_key(),
        )

        self.client = ClobClientV2(
            host=POLYMARKET_HOST,
            chain_id=POLYMARKET_CHAIN_ID,
            key=private_key,
            signature_type=POLYMARKET_SIGNATURE_TYPE,
            funder=funder,
            creds=v2_creds,
        )

        self.open_orders = []
        self.fills = []
        self.seen_trade_ids = set()

        adopted = self.adopt_remote_open_orders()

        if adopted:
            print(f"Adopted {len(adopted)} existing live open orders.")

    # =========================
    # Generic helpers
    # =========================

    def _with_retries(self, label, fn):
        last_error = None

        for attempt in range(1, LIVE_API_MAX_RETRIES + 1):
            try:
                return fn()
            except Exception as e:
                last_error = e
                print(
                    f"Live API call failed [{label}] attempt "
                    f"{attempt}/{LIVE_API_MAX_RETRIES}: {e}"
                )
                time.sleep(LIVE_API_RETRY_SLEEP_SECONDS)

        raise RuntimeError(f"Live API call failed after retries [{label}]: {last_error}")

    def _remote_get(self, obj, *keys, default=None):
        if isinstance(obj, dict):
            for key in keys:
                if key in obj:
                    return obj[key]
            return default

        for key in keys:
            value = getattr(obj, key, None)
            if value is not None:
                return value

        return default

    def _safe_float(self, value, default=0.0):
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    def _extract_order_id(self, response):
        if isinstance(response, dict):
            return (
                response.get("orderID")
                or response.get("order_id")
                or response.get("id")
            )

        return (
            getattr(response, "orderID", None)
            or getattr(response, "order_id", None)
            or getattr(response, "id", None)
        )

    def _side(self, side):
        if side == "BUY":
            return Side.BUY

        if side == "SELL":
            return Side.SELL

        raise RuntimeError(f"Unknown side: {side}")

    def _order_type(self):
        if LIVE_ORDER_TYPE != "GTC":
            raise RuntimeError("Only GTC live orders are allowed right now.")

        return OrderType.GTC

    def _cancel_payload(self, order_id):
        return OrderPayload(orderID=order_id)

    # =========================
    # Balance / allowance
    # =========================

    def get_balance_allowance(self):
        """
        V2 is used for order placement, but the old params object is still compatible
        with the balance endpoint in our tested setup.
        """

        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)

        return self._with_retries(
            "get_balance_allowance",
            lambda: self.read_client.get_balance_allowance(params=params),
        )

    # =========================
    # Open orders
    # =========================

    def _extract_remote_orders(self, response):
        if response is None:
            return []

        if isinstance(response, list):
            return response

        if isinstance(response, dict):
            if "data" in response and isinstance(response["data"], list):
                return response["data"]

            if "orders" in response and isinstance(response["orders"], list):
                return response["orders"]

        return []

    def fetch_remote_open_orders(self):
        response = self._with_retries(
            "get_orders",
            lambda: self.read_client.get_orders(),
        )

        return self._extract_remote_orders(response)

    def adopt_remote_open_orders(self):
        remote_orders = self.fetch_remote_open_orders()

        if not remote_orders:
            return []

        if LIVE_REFUSE_START_WITH_OPEN_ORDERS and not LIVE_ADOPT_OPEN_ORDERS:
            raise RuntimeError(
                f"Live startup blocked: found {len(remote_orders)} existing open orders. "
                "Cancel them manually or set LIVE_ADOPT_OPEN_ORDERS=True."
            )

        if not LIVE_ADOPT_OPEN_ORDERS:
            return []

        adopted = []

        for remote in remote_orders:
            order_id = self._remote_get(remote, "id", "orderID", "order_id")
            token_id = self._remote_get(remote, "asset_id", "assetId", "token_id", "tokenID")
            side = str(self._remote_get(remote, "side", default="")).upper()
            price = self._safe_float(self._remote_get(remote, "price", default=0))
            size = self._safe_float(self._remote_get(remote, "original_size", "size", default=0))
            matched = self._safe_float(
                self._remote_get(
                    remote,
                    "size_matched",
                    "sizeMatched",
                    "matched_size",
                    default=0,
                )
            )

            if not order_id or not token_id:
                continue

            local_order = {
                "order_id": order_id,
                "time": datetime.now(timezone.utc),
                "token_id": str(token_id),
                "question": "ADOPTED_LIVE_ORDER",
                "side": side,
                "price": price,
                "size": size,
                "remaining_size": max(0, size - matched),
                "filled_size": matched,
                "status": "OPEN",
                "reason": "ADOPTED_LIVE",
                "response": remote,
            }

            adopted.append(local_order)

        self.open_orders.extend(adopted)
        return adopted

    def get_open_orders(self):
        return [order for order in self.open_orders if order["status"] == "OPEN"]

    # =========================
    # Order placement / cancel
    # =========================

    def place_order(self, token_id, question, side, price, size, reason="LIVE"):
        requested_size = float(size)
        price = float(price)

        # In live mode, force strategy orders down to the configured live test size.
        size = min(requested_size, float(LIVE_ORDER_SIZE))

        if size > MAX_LIVE_ORDER_SIZE:
            raise RuntimeError(
                f"Blocked: live size {size} exceeds "
                f"MAX_LIVE_ORDER_SIZE={MAX_LIVE_ORDER_SIZE}."
            )

        order_value = size * price

        if order_value > MAX_LIVE_ORDER_VALUE:
            raise RuntimeError(
                f"Blocked: live order value {order_value:.4f} exceeds "
                f"MAX_LIVE_ORDER_VALUE={MAX_LIVE_ORDER_VALUE:.4f}."
            )

        print(
            f"Submitting LIVE order | side={side} price={price} "
            f"size={size} value={order_value:.4f}"
        )

        response = self._with_retries(
            "create_and_post_order",
            lambda: self.client.create_and_post_order(
                order_args=OrderArgs(
                    token_id=str(token_id),
                    price=price,
                    side=self._side(side),
                    size=size,
                ),
                options=PartialCreateOrderOptions(tick_size=str(LIVE_TICK_SIZE)),
                order_type=self._order_type(),
            ),
        )

        success = False
        if isinstance(response, dict):
            success = bool(response.get("success", False))

        order_id = self._extract_order_id(response)

        if not success:
            raise RuntimeError(f"Live order failed: {response}")

        if not order_id:
            raise RuntimeError(f"Live order response missing order id: {response}")

        local_order = {
            "order_id": order_id,
            "time": datetime.now(timezone.utc),
            "token_id": str(token_id),
            "question": question,
            "side": side,
            "price": price,
            "size": size,
            "remaining_size": size,
            "filled_size": 0.0,
            "status": "OPEN",
            "reason": reason,
            "response": response,
        }

        self.open_orders.append(local_order)
        return local_order

    def cancel_order(self, order):
        if order["status"] != "OPEN":
            return {
                "canceled": [],
                "not_canceled": {order.get("order_id"): "not open"},
            }

        order_id = order.get("order_id")

        if not order_id:
            order["status"] = "CANCELLED"
            return {
                "canceled": [],
                "not_canceled": {"missing_order_id": "local order missing order_id"},
            }

        payload = self._cancel_payload(order_id)

        response = self._with_retries(
            "cancel_order",
            lambda: self.client.cancel_order(payload),
        )

        canceled = []
        not_canceled = {}

        if isinstance(response, dict):
            canceled = response.get("canceled", []) or []
            not_canceled = response.get("not_canceled", {}) or {}

        if order_id in canceled:
            order["status"] = "CANCELLED"

        elif order_id in not_canceled:
            reason = str(not_canceled[order_id])

            if "already canceled" in reason or "can't be found" in reason:
                order["status"] = "CANCELLED"
            elif "matched" in reason:
                order["status"] = "FILLED"

        return response

    def cancel_all_for_token(self, token_id):
        results = []

        for order in list(self.open_orders):
            if order["status"] != "OPEN":
                continue

            if str(order["token_id"]) != str(token_id):
                continue

            results.append(self.cancel_order(order))

        return results

    def cancel_all_orders(self):
        remote_orders = self.fetch_remote_open_orders()
        results = []

        for remote in remote_orders:
            order_id = self._remote_get(remote, "id", "orderID", "order_id")

            if not order_id:
                continue

            payload = self._cancel_payload(order_id)

            try:
                response = self._with_retries(
                    "cancel_order",
                    lambda: self.client.cancel_order(payload),
                )

                results.append({
                    "order_id": order_id,
                    "status": "CANCEL_REQUESTED",
                    "response": response,
                })

            except Exception as e:
                results.append({
                    "order_id": order_id,
                    "status": "CANCEL_FAILED",
                    "error": str(e),
                })

        for order in self.open_orders:
            if order["status"] == "OPEN":
                order["status"] = "CANCELLED"

        return results

    # =========================
    # Trades / fills
    # =========================

    def _extract_remote_trades(self, response):
        if response is None:
            return []

        if isinstance(response, list):
            return response

        if isinstance(response, dict):
            if "data" in response and isinstance(response["data"], list):
                return response["data"]

            if "trades" in response and isinstance(response["trades"], list):
                return response["trades"]

        return []

    def fetch_remote_trades(self):
        response = self._with_retries(
            "get_trades",
            lambda: self.read_client.get_trades(),
        )

        return self._extract_remote_trades(response)

    def _trade_unique_id(self, trade):
        trade_id = self._remote_get(
            trade,
            "id",
            "trade_id",
            "tradeID",
            "transaction_hash",
            "transactionHash",
        )

        if trade_id:
            return str(trade_id)

        return "|".join([
            str(self._remote_get(trade, "asset_id", "assetId", "token_id", "tokenID", default="")),
            str(self._remote_get(trade, "side", default="")),
            str(self._remote_get(trade, "price", default="")),
            str(self._remote_get(trade, "size", "amount", "matched_size", "sizeMatched", default="")),
            str(self._remote_get(trade, "match_time", "created_at", "createdAt", "timestamp", "time", default="")),
        ])

    def _trade_time_value(self, trade):
        raw = self._remote_get(
            trade,
            "match_time",
            "created_at",
            "createdAt",
            "timestamp",
            "time",
            default=None,
        )

        if raw is None:
            return None

        try:
            return float(raw)
        except Exception:
            return str(raw)

    def _trade_matches_order(self, trade, order):
        """
        Match live fills by exact order id only.

        Do NOT fall back to token_id + top-level side. Polymarket maker fills can
        have a top-level trade side that is opposite from our maker_order side.
        Loose fallback matching can incorrectly count a SELL fill as a BUY fill.
        """
        order_id = str(order.get("order_id", ""))

        if not order_id:
            return False

        possible_order_ids = [
            self._remote_get(trade, "order_id"),
            self._remote_get(trade, "orderID"),
            self._remote_get(trade, "maker_order_id"),
            self._remote_get(trade, "makerOrderId"),
            self._remote_get(trade, "taker_order_id"),
            self._remote_get(trade, "takerOrderId"),
        ]

        maker_orders = self._remote_get(trade, "maker_orders", "makerOrders", default=[])

        if isinstance(maker_orders, list):
            for maker in maker_orders:
                possible_order_ids.append(
                    self._remote_get(maker, "order_id", "orderID", "id")
                )

        possible_order_ids = [str(x) for x in possible_order_ids if x]

        return order_id in possible_order_ids
    
    def _matching_maker_order(self, trade, order):
        order_id = str(order.get("order_id", ""))

        maker_orders = self._remote_get(trade, "maker_orders", "makerOrders", default=[])

        if not isinstance(maker_orders, list):
            return None

        for maker in maker_orders:
            maker_order_id = self._remote_get(
                maker,
                "order_id",
                "orderID",
                "id",
                default="",
            )

            if order_id and str(maker_order_id) == order_id:
                return maker

        return None

    def _fill_price_and_size(self, trade, order):
        maker = self._matching_maker_order(trade, order)

        if maker:
            price = self._safe_float(
                self._remote_get(maker, "price", "matched_price", "matchedPrice"),
                default=float(order["price"]),
            )

            size = self._safe_float(
                self._remote_get(
                    maker,
                    "matched_amount",
                    "matchedAmount",
                    "size",
                    "amount",
                ),
                default=0,
            )

            return price, size

        price = self._safe_float(
            self._remote_get(trade, "price", "trade_price", "tradePrice"),
            default=float(order["price"]),
        )

        size = self._safe_float(
            self._remote_get(
                trade,
                "size",
                "amount",
                "matched_size",
                "sizeMatched",
            ),
            default=0,
        )

        return price, size
    
    def reconcile_missing_fills_from_known_orders(self, known_orders_by_id, max_trades=100):
        """
        Recover remote fills for orders that are no longer present in local open_orders.

        This fixes the case where Polymarket confirms a maker fill, but the local
        bot state missed it because the order had already been cancelled/adopted/
        removed from local memory.

        Matching is by exact order_id found inside trade["maker_orders"].
        """
        if not known_orders_by_id:
            return []

        try:
            remote_trades = self.fetch_remote_trades()
        except Exception as e:
            print(f"Remote fill reconciliation skipped: could not fetch trades: {e}")
            return []

        def trade_sort_key(trade):
            raw_time = self._trade_time_value(trade)

            try:
                return float(raw_time)
            except Exception:
                return 0.0

        remote_trades = sorted(remote_trades, key=trade_sort_key)

        if max_trades:
            remote_trades = remote_trades[-max_trades:]

        recovered_fills = []

        for trade in remote_trades:
            trade_id = self._trade_unique_id(trade)

            if trade_id in self.seen_trade_ids:
                continue

            maker_orders = self._remote_get(
                trade,
                "maker_orders",
                "makerOrders",
                default=[],
            )

            if not isinstance(maker_orders, list):
                continue

            for maker in maker_orders:
                maker_order_id = self._remote_get(
                    maker,
                    "order_id",
                    "orderID",
                    "id",
                    default="",
                )

                if not maker_order_id:
                    continue

                maker_order_id = str(maker_order_id)

                if maker_order_id not in known_orders_by_id:
                    continue

                known_order = known_orders_by_id[maker_order_id]

                price = self._safe_float(
                    self._remote_get(maker, "price", "matched_price", "matchedPrice"),
                    default=self._safe_float(known_order.get("price"), default=0),
                )

                size = self._safe_float(
                    self._remote_get(
                        maker,
                        "matched_amount",
                        "matchedAmount",
                        "size",
                        "amount",
                    ),
                    default=0,
                )

                token_id = str(
                    self._remote_get(
                        maker,
                        "asset_id",
                        "assetId",
                        "token_id",
                        "tokenID",
                        default=known_order.get("token_id", ""),
                    )
                )

                side = str(
                    self._remote_get(
                        maker,
                        "side",
                        default=known_order.get("side", ""),
                    )
                ).upper()

                if not token_id or side not in {"BUY", "SELL"}:
                    continue

                if price <= 0 or size <= 0:
                    continue

                fill = {
                    "order_id": maker_order_id,
                    "time": datetime.now(timezone.utc),
                    "token_id": token_id,
                    "question": known_order.get("question") or "RECONCILED_LIVE_ORDER",
                    "side": side,
                    "price": price,
                    "size": size,
                    "remaining_size": 0.0,
                    "filled_size": size,
                    "status": "FILLED",
                    "reason": known_order.get("reason") or "RECONCILED_LIVE_FILL",
                    "response": known_order.get("response", {}),
                    "trade": trade,
                    "reconciled_from_remote": True,
                }

                recovered_fills.append(fill)
                self.seen_trade_ids.add(trade_id)

                for local_order in self.open_orders:
                    if str(local_order.get("order_id", "")) == maker_order_id:
                        local_order["status"] = "FILLED"
                        local_order["filled_size"] = size
                        local_order["remaining_size"] = 0.0

                print(
                    f"RECONCILED REMOTE FILL | side={side} price={price} "
                    f"size={size} token={token_id[:8]} order={maker_order_id[:10]}"
                )

                break

        self.fills.extend(recovered_fills)
        return recovered_fills

    
    def reconstruct_positions_from_trades(self, max_trades=500):
        trades = self.fetch_remote_trades()

        if not trades:
            return {}, {}, 0.0

        def trade_time_key(trade):
            raw = self._remote_get(
                trade,
                "match_time",
                "created_at",
                "createdAt",
                "timestamp",
                "time",
                default="",
            )
            return str(raw)

        trades = sorted(trades, key=trade_time_key)

        if max_trades:
            trades = trades[-max_trades:]

        positions = {}
        avg_prices = {}
        realized_pnl = 0.0

        for trade in trades:
            token_id = str(
                self._remote_get(
                    trade,
                    "asset_id",
                    "assetId",
                    "token_id",
                    "tokenID",
                    default="",
                )
            )

            if not token_id:
                continue

            side = str(self._remote_get(trade, "side", default="")).upper()

            price = self._safe_float(
                self._remote_get(trade, "price", "trade_price", "tradePrice"),
                default=0,
            )

            size = self._safe_float(
                self._remote_get(
                    trade,
                    "size",
                    "amount",
                    "matched_size",
                    "sizeMatched",
                ),
                default=0,
            )

            if price <= 0 or size <= 0:
                continue

            old_pos = float(positions.get(token_id, 0))
            old_avg = float(avg_prices.get(token_id, 0))

            if side == "BUY":
                new_pos = old_pos + size
                new_avg = ((old_pos * old_avg) + (price * size)) / new_pos

                positions[token_id] = new_pos
                avg_prices[token_id] = new_avg

            elif side == "SELL":
                sell_size = min(size, old_pos)

                if sell_size <= 0:
                    continue

                realized_pnl += (price - old_avg) * sell_size

                new_pos = old_pos - sell_size

                if new_pos <= 0:
                    positions.pop(token_id, None)
                    avg_prices.pop(token_id, None)
                else:
                    positions[token_id] = new_pos
                    avg_prices[token_id] = old_avg

        return positions, avg_prices, realized_pnl

    def check_fills(self, market_rows):
        new_fills = []

        try:
            remote_trades = self.fetch_remote_trades()
        except Exception:
            remote_trades = []

        for trade in remote_trades:
            trade_id = self._trade_unique_id(trade)

            if trade_id in self.seen_trade_ids:
                continue

            for order in self.open_orders:
                if not self._trade_matches_order(trade, order):
                    continue

                price, size = self._fill_price_and_size(trade, order)

                if size <= 0:
                    continue

                fill = order.copy()
                fill["price"] = price
                fill["size"] = size
                fill["status"] = "FILLED"
                fill["trade"] = trade

                new_fills.append(fill)
                self.seen_trade_ids.add(trade_id)

                order["filled_size"] = round(
                    float(order.get("filled_size", 0)) + size,
                    6,
                )
                order["remaining_size"] = max(
                    0,
                    float(order["size"]) - float(order["filled_size"]),
                )

                if order["remaining_size"] <= 0:
                    order["status"] = "FILLED"

                break

        self.fills.extend(new_fills)
        return new_fills