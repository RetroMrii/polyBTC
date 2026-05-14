import csv
import json
import os
import time
import requests
from py_clob_client.client import ClobClient
from datetime import datetime, timezone
from btc_5m_hybrid_strategy import BTC5MHybridStrategy
from py_clob_client.clob_types import ApiCreds, OrderArgs
from py_clob_client.constants import POLYGON
from py_clob_client.order_builder.constants import BUY, SELL

from dotenv import load_dotenv
load_dotenv()


STATE_FILE = "btc_5m_state.json"
DECISIONS_FILE = "btc_5m_decisions.csv"
TRADES_FILE = "btc_5m_trades.csv"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "mode": "paper",
            "open_positions": {},
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "last_market_id": None,
            "last_updated": None,
        }

    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state):
    state["last_updated"] = utc_now()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def settle_expired_positions(state):
    import requests

    open_positions = state.setdefault("open_positions", {})

    if not open_positions:
        return

    now_ts = int(time.time())
    settled_market_ids = []

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

        # Each BTC market is 5 minutes. Give Binance a short delay to finalize the candle.
        market_start_ts = entry_ts - (entry_ts % 300)
        market_end_ts = market_start_ts + 300

        if now_ts < market_end_ts + 10:
            continue

        kline_url = "https://api.binance.com/api/v3/klines"
        kline_params = {
            "symbol": "BTCUSDT",
            "interval": "5m",
            "startTime": market_start_ts * 1000,
            "endTime": market_end_ts * 1000,
            "limit": 1,
        }

        try:
            resp = requests.get(kline_url, params=kline_params, timeout=10)
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
                print(f"[BTC5M] live position reached expiry; not paper-settling {market_id}")
                position["resolved"] = True
                position["settled_at"] = utc_now()
                position["note"] = "Live expiry settlement not simulated by bot"
                settled_market_ids.append(market_id)
                continue

            winning_outcome = "YES" if final_price > strike else "NO"
            won = outcome == winning_outcome

            if won:
                pnl = (1.0 - entry_price) * size
            else:
                pnl = -entry_price * size

            state["daily_pnl"] = float(state.get("daily_pnl", 0.0)) + pnl
            state["total_pnl"] = float(state.get("total_pnl", 0.0)) + pnl

            position["resolved"] = True
            position["final_price"] = final_price
            position["winning_outcome"] = winning_outcome
            position["pnl"] = pnl
            position["settled_at"] = utc_now()

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
                f"[BTC5M] SETTLED market={market_id} "
                f"entry={outcome}@{entry_price} final={final_price} "
                f"strike={strike} winner={winning_outcome} pnl={pnl:.4f}"
            )

            settled_market_ids.append(market_id)

        except Exception as e:
            print(f"[BTC5M] settlement error for {market_id}: {e}")

    for market_id in settled_market_ids:
        open_positions.pop(market_id, None)
        
def maybe_cashout_profitable_position(state, snapshot):
    enable_cashout = os.getenv("BTC_5M_ENABLE_CASHOUT", "true").lower() == "true"
    if not enable_cashout:
        return False

    open_positions = state.setdefault("open_positions", {})
    closed_markets = state.setdefault("closed_markets", {})

    market_id = snapshot["market_id"]

    if market_id not in open_positions:
        return False

    position = open_positions[market_id]

    outcome = position["outcome"]
    entry_price = float(position["entry_price"])
    size = float(position["size"])

    if outcome == "YES":
        exit_price = snapshot.get("yes_bid")
    elif outcome == "NO":
        exit_price = snapshot.get("no_bid")
    else:
        return False

    if exit_price is None:
        print(f"[BTC5M] cannot cashout {market_id}, missing bid for {outcome}")
        return False

    min_net_profit = float(os.getenv("BTC_5M_MIN_NET_PROFIT", "0.02"))
    extra_fee_buffer = float(os.getenv("BTC_5M_EXTRA_FEE_BUFFER", "0.01"))

    gross_pnl = (float(exit_price) - entry_price) * size
    fee_buffer_cost = extra_fee_buffer * size
    net_pnl = gross_pnl - fee_buffer_cost

    enable_stoploss = os.getenv("BTC_5M_ENABLE_STOPLOSS", "true").lower() == "true"
    max_net_loss = float(os.getenv("BTC_5M_MAX_NET_LOSS", "0.12")) * size

    btc_price = float(snapshot["btc_price"])
    strike = float(position["strike"])

    if outcome == "YES":
        thesis_invalidated = btc_price <= strike
    elif outcome == "NO":
        thesis_invalidated = btc_price >= strike
    else:
        thesis_invalidated = False

    should_take_profit = net_pnl >= min_net_profit * size

    # Stop-loss only when the market price is down AND the BTC-side thesis has broken.
    # This avoids exiting a winning-side position just because the order book temporarily gaps.
    should_stop_loss = (
        enable_stoploss
        and net_pnl <= -max_net_loss
        and thesis_invalidated
    )

    if not should_take_profit and not should_stop_loss:
        return False

    close_reason = "cashout_profit" if should_take_profit else "stop_loss"
    trade_action = "CASHOUT" if should_take_profit else "STOPLOSS"

    mode = os.getenv("BTC_5M_MODE", "paper").lower()
    simulated = mode != "live"

    live_response = None

    if mode == "live":
        try:
            live_result = place_live_limit_sell(position, exit_price)
            live_response = live_result["response"]
            simulated = False
        except Exception as e:
            print(f"[BTC5M] LIVE EXIT FAILED/BLOCKED: {e}")
            return False

    state["daily_pnl"] = float(state.get("daily_pnl", 0.0)) + net_pnl
    state["total_pnl"] = float(state.get("total_pnl", 0.0)) + net_pnl

    reason_text = (
        f"entry={entry_price} exit={exit_price} "
        f"gross={gross_pnl:.4f} fee_buffer={fee_buffer_cost:.4f}"
    )

    if live_response is not None:
        reason_text += f" live_response={live_response}"

    log_trade([
        utc_now(),
        mode,
        market_id,
        trade_action,
        outcome,
        exit_price,
        size,
        simulated,
        reason_text,
        net_pnl,
    ])

    print(
        f"[BTC5M] {trade_action} {outcome} entry={entry_price} "
        f"exit={exit_price} gross={gross_pnl:.4f} "
        f"net_after_buffer={net_pnl:.4f}"
    )

    closed_markets[market_id] = {
        "timestamp": utc_now(),
        "reason": close_reason,
        "outcome": outcome,
        "entry_price": entry_price,
        "exit_price": float(exit_price),
        "size": size,
        "net_pnl": net_pnl,
        "question": snapshot.get("question"),
    }

    open_positions.pop(market_id, None)
    return True

def log_decision(row):
    with open(DECISIONS_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(row)


def log_trade(row):
    with open(TRADES_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(row)

def live_mode_is_armed():
    mode = os.getenv("BTC_5M_MODE", "paper").lower()
    live_armed = os.getenv("BTC_5M_LIVE_ARMED", "false").lower() == "true"
    allow_orders = os.getenv("BTC_5M_ALLOW_REAL_ORDERS", "false").lower() == "true"

    return mode == "live" and live_armed and allow_orders


def get_live_client():
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    private_key = os.getenv("PK")
    chain_id = int(os.getenv("CHAIN_ID", str(POLYGON)))
    signature_type = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "1"))
    funder = os.getenv("POLYMARKET_FUNDER") or None

    if not private_key:
        raise RuntimeError("Missing PK in .env")

    creds = ApiCreds(
        api_key=os.getenv("CLOB_API_KEY"),
        api_secret=os.getenv("CLOB_SECRET"),
        api_passphrase=os.getenv("CLOB_PASS_PHRASE"),
    )

    missing_creds = [
        name for name, value in {
            "CLOB_API_KEY": creds.api_key,
            "CLOB_SECRET": creds.api_secret,
            "CLOB_PASS_PHRASE": creds.api_passphrase,
        }.items()
        if not value
    ]

    if missing_creds:
        raise RuntimeError(f"Missing CLOB credentials in .env: {', '.join(missing_creds)}")

    return ClobClient(
        host,
        key=private_key,
        chain_id=chain_id,
        creds=creds,
        signature_type=signature_type,
        funder=funder,
    )


def token_id_for_decision(snapshot, decision):
    if decision.outcome == "YES":
        return snapshot["yes_token_id"]
    if decision.outcome == "NO":
        return snapshot["no_token_id"]
    raise ValueError(f"Unsupported outcome for live order: {decision.outcome}")


def place_live_limit_buy(snapshot, decision):
    if not live_mode_is_armed():
        raise RuntimeError(
            "Live order blocked. Require BTC_5M_MODE=live, "
            "BTC_5M_LIVE_ARMED=true, and BTC_5M_ALLOW_REAL_ORDERS=true."
        )

    price = float(decision.price)
    size = float(os.getenv("BTC_5M_LIVE_ORDER_SIZE", str(decision.size)))
    max_order_value = float(os.getenv("BTC_5M_MAX_LIVE_ORDER_VALUE", "1.00"))
    order_value = price * size

    if order_value > max_order_value:
        raise RuntimeError(
            f"Live order blocked by max value: order_value={order_value:.4f}, "
            f"limit={max_order_value:.4f}"
        )

    if price <= 0 or price >= 1:
        raise RuntimeError(f"Invalid live order price: {price}")

    if size <= 0:
        raise RuntimeError(f"Invalid live order size: {size}")

    token_id = token_id_for_decision(snapshot, decision)
    client = get_live_client()

    order_args = OrderArgs(
        price=price,
        size=size,
        side=BUY,
        token_id=token_id,
    )

    signed_order = client.create_order(order_args)
    response = client.post_order(signed_order)

    return {
        "response": response,
        "token_id": token_id,
        "price": price,
        "size": size,
        "order_value": order_value,
    }

def place_live_limit_sell(position, exit_price):
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

    client = get_live_client()

    order_args = OrderArgs(
        price=price,
        size=size,
        side=SELL,
        token_id=token_id,
    )

    signed_order = client.create_order(order_args)
    response = client.post_order(signed_order)

    return {
        "response": response,
        "token_id": token_id,
        "price": price,
        "size": size,
    }

def get_btc_5m_market_snapshot():
    def parse_json_field(value, fallback):
        if value is None:
            return fallback
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return fallback
        return value

    def best_bid_ask(book):
        if isinstance(book, dict):
            bids = book.get("bids", [])
            asks = book.get("asks", [])
        else:
            bids = getattr(book, "bids", []) or []
            asks = getattr(book, "asks", []) or []

        def price(level):
            if isinstance(level, dict):
                return float(level["price"])
            return float(getattr(level, "price"))

        best_bid = max([price(b) for b in bids], default=None)
        best_ask = min([price(a) for a in asks], default=None)

        return best_bid, best_ask

    now = int(time.time())
    interval_start = now - (now % 300)
    interval_end = interval_start + 300
    seconds_to_expiry = interval_end - now

    slug = f"btc-updown-5m-{interval_start}"
    event_url = f"https://gamma-api.polymarket.com/events/slug/{slug}"

    event_resp = requests.get(event_url, timeout=10)
    if event_resp.status_code != 200:
        print(f"[BTC5M] Gamma lookup failed: {event_resp.status_code} slug={slug}")
        return None

    event = event_resp.json()
    markets = event.get("markets", [])
    if not markets:
        print(f"[BTC5M] event found but no markets: {slug}")
        return None

    market = markets[0]

    token_ids = parse_json_field(market.get("clobTokenIds"), [])
    ##outcomes = parse_json_field(market.get("outcomes"), [])

    if len(token_ids) < 2:
        print("[BTC5M] missing clobTokenIds")
        return None

    up_token = token_ids[0]
    down_token = token_ids[1]

    # Binance current 5m candle.
    # Open price = strike/reference for Up/Down logic.
    kline_url = "https://api.binance.com/api/v3/klines"
    kline_params = {
        "symbol": "BTCUSDT",
        "interval": "5m",
        "limit": 1,
    }

    kline_resp = requests.get(kline_url, params=kline_params, timeout=10)
    if kline_resp.status_code != 200:
        print(f"[BTC5M] Binance kline failed: {kline_resp.status_code}")
        return None

    kline = kline_resp.json()[0]
    strike = float(kline[1])
    btc_price = float(kline[4])

    # Simple 60s momentum from Binance recent trades proxy using current vs candle open.
    momentum_60s = (btc_price - strike) / strike if strike > 0 else 0.0
    volatility_60s = abs(momentum_60s)

    client = ClobClient("https://clob.polymarket.com")

    up_book = client.get_order_book(up_token)
    down_book = client.get_order_book(down_token)

    up_bid, up_ask = best_bid_ask(up_book)
    down_bid, down_ask = best_bid_ask(down_book)

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


def main():
    mode = os.getenv("BTC_5M_MODE", "paper").lower()
    loop_seconds = int(os.getenv("BTC_5M_LOOP_SECONDS", "10"))

    strategy = BTC5MHybridStrategy(
    min_edge=float(os.getenv("BTC_5M_MIN_EDGE", "0.05")),
    max_spread=float(os.getenv("BTC_5M_MAX_SPREAD", "0.08")),
    order_size=float(os.getenv("BTC_5M_ORDER_SIZE", "1")),
    no_trade_last_seconds=int(os.getenv("BTC_5M_NO_TRADE_LAST_SECONDS", "75")),
    min_seconds_to_expiry=int(os.getenv("BTC_5M_MIN_SECONDS_TO_EXPIRY", "75")),
    max_seconds_to_expiry=int(os.getenv("BTC_5M_MAX_SECONDS_TO_EXPIRY", "240")),
    min_distance_from_strike=float(os.getenv("BTC_5M_MIN_DISTANCE_FROM_STRIKE", "0.00008")),
    require_momentum_confirmation=os.getenv("BTC_5M_REQUIRE_MOMENTUM_CONFIRMATION", "true").lower() == "true",
    )

    state = load_state()
    state["mode"] = mode
    save_state(state)

    print(f"[BTC5M] bot started in {mode} mode")
    if mode == "live":
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
            
            cashout_done = maybe_cashout_profitable_position(state, snapshot)
            if cashout_done:
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
                print(
                    f"[BTC5M] {decision.action} "
                    f"reason={decision.reason} "
                    f"edge={decision.edge}"
                )

            if decision.action == "BUY":
                market_id = snapshot["market_id"]

                open_positions = state.setdefault("open_positions", {})
                closed_markets = state.setdefault("closed_markets", {})

                if (
                    os.getenv("BTC_5M_PREVENT_REENTRY_AFTER_CASHOUT", "true").lower() == "true"
                    and market_id in closed_markets
                ):
                    print(f"[BTC5M] market {market_id} already closed by cashout, skipping re-entry")
                    save_state(state)
                    time.sleep(loop_seconds)
                    continue

                if market_id in open_positions:
                    pass
                elif mode == "paper":
                    open_positions[market_id] = {
                        "timestamp": utc_now(),
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
                            "outcome": decision.outcome,
                            "side": decision.side,
                            "entry_price": live_result["price"],
                            "size": live_result["size"],
                            "question": snapshot["question"],
                            "btc_price_at_entry": snapshot["btc_price"],
                            "strike": snapshot["strike"],
                            "seconds_to_expiry_at_entry": snapshot["seconds_to_expiry"],
                            "reason": decision.reason,
                            "token_id": live_result["token_id"],
                            "order_value": live_result["order_value"],
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
                            f"live_order response={live_result['response']}",
                            0.0,
                        ])

                        print(
                            f"[BTC5M] LIVE BUY {decision.outcome} "
                            f"@ {live_result['price']} size={live_result['size']} "
                            f"value={live_result['order_value']:.4f}"
                        )

                    except Exception as e:
                        print(f"[BTC5M] LIVE ORDER BLOCKED/FAILED: {e}")
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
