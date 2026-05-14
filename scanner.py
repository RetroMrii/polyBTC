# file: scanner.py

import json
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from py_clob_client.client import ClobClient
from config import (
    MIN_VOLUME_24H,
    MIN_LIQUIDITY,
    MAX_SPREAD,
    MIN_PRICE,
    MAX_PRICE,
    MIN_YES_ASK_DOLLARS,
    MARKET_BLACKLIST_KEYWORDS,
    MARKET_BLACKLIST_CONDITION_IDS,
    USE_MARKET_WHITELIST,
    MARKET_WHITELIST_KEYWORDS,
    MARKET_WHITELIST_CONDITION_IDS,
)

HOST = "https://clob.polymarket.com"
GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"

client = ClobClient(HOST)


def parse_token_ids(raw):
    if not raw:
        return []

    if isinstance(raw, list):
        return raw

    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []

    return []


def get_top_markets(limit=100):
    params = {
        "active": "true",
        "closed": "false",
        "limit": limit,
        "order": "volume24hr",
        "ascending": "false",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36",
        "Accept": "application/json",
    }

    response = requests.get(
        GAMMA_MARKETS_URL,
        params=params,
        headers=headers,
        timeout=20,
    )

    if response.status_code == 403:
        raise RuntimeError(
            "Gamma API returned 403 Forbidden. "
            "Wait a minute and rerun, or reduce scan frequency."
        )

    response.raise_for_status()
    return response.json()


def get_best_bid_ask(token_id):
    book = client.get_order_book(token_id)

    bids = getattr(book, "bids", [])
    asks = getattr(book, "asks", [])

    if not bids or not asks:
        return None

    best_bid_order = max(bids, key=lambda bid: float(bid.price))
    best_ask_order = min(asks, key=lambda ask: float(ask.price))

    best_bid = float(best_bid_order.price)
    best_ask = float(best_ask_order.price)

    bid_size = float(best_bid_order.size)
    ask_size = float(best_ask_order.size)

    spread = best_ask - best_bid

    return best_bid, best_ask, spread, bid_size, ask_size

def classify_market(question):
    q = str(question).lower()

    sports_keywords = [
        " vs. ",
        "spread:",
        "o/u",
        "win on",
        "fifa world cup",
        "nba",
        "nfl",
        "mlb",
        "nhl",
    ]

    politics_keywords = [
        "trump",
        "biden",
        "president",
        "election",
        "senate",
        "congress",
        "iran",
        "ukraine",
        "gaza",
        "israel",
    ]

    crypto_keywords = [
        "bitcoin",
        "btc",
        "ethereum",
        "eth",
        "solana",
        "sol",
        "crypto",
    ]

    for keyword in sports_keywords:
        if keyword in q:
            return "sports"

    for keyword in politics_keywords:
        if keyword in q:
            return "politics_geo"

    for keyword in crypto_keywords:
        if keyword in q:
            return "crypto"

    return "other"

def scan_markets(limit=100):
    rows = []

    for market in get_top_markets(limit=limit):
        token_ids = parse_token_ids(market.get("clobTokenIds"))

        if len(token_ids) < 2:
            continue

        try:
            yes_bid, yes_ask, yes_spread, yes_bid_size, yes_ask_size = get_best_bid_ask(token_ids[0])
            no_bid, no_ask, no_spread, no_bid_size, no_ask_size = get_best_bid_ask(token_ids[1])

            rows.append({
                "question": market.get("question"),
                "category": classify_market(market.get("question")),
                "condition_id": market.get("conditionId"),
                "yes_token_id": token_ids[0],
                "no_token_id": token_ids[1],
                "volume24hr": float(market.get("volume24hr") or 0),
                "liquidity": float(market.get("liquidity") or 0),
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "yes_mid": round((yes_bid + yes_ask) / 2, 4),
                "yes_spread": round(yes_spread, 4),
                "yes_bid_size": round(yes_bid_size, 2),
                "yes_ask_size": round(yes_ask_size, 2),
                "imbalance": (
                    yes_bid_size / yes_ask_size
                    if yes_ask_size > 0 else 0),
                "yes_ask_dollars": round(yes_ask * yes_ask_size, 2),
                "no_bid": no_bid,
                "no_ask": no_ask,
                "no_mid": round((no_bid + no_ask) / 2, 4),
                "no_spread": round(no_spread, 4),
                "no_bid_size": round(no_bid_size, 2),
                "no_ask_size": round(no_ask_size, 2),
                "no_ask_dollars": round(no_ask * no_ask_size, 2),
                "end_date": market.get("endDate"),
            })

        except Exception:
            continue

    return pd.DataFrame(rows)

def is_blacklisted(row):
    question = str(row.get("question", "")).lower()
    condition_id = str(row.get("condition_id", ""))

    for keyword in MARKET_BLACKLIST_KEYWORDS:
        if keyword.lower() in question:
            return True

    if condition_id in MARKET_BLACKLIST_CONDITION_IDS:
        return True

    return False

def is_whitelisted(row):
    if not USE_MARKET_WHITELIST:
        return True

    question = str(row.get("question", "")).lower()
    condition_id = str(row.get("condition_id", ""))

    for keyword in MARKET_WHITELIST_KEYWORDS:
        if keyword.lower() in question:
            return True

    if condition_id in MARKET_WHITELIST_CONDITION_IDS:
        return True

    return False

def filter_tradable(df):
    if df.empty:
        return df

    df = df.copy()
    df["end_date_dt"] = pd.to_datetime(df["end_date"], utc=True, errors="coerce")
    min_end_time = datetime.now(timezone.utc) + timedelta(hours=2)
    df["is_blacklisted"] = df.apply(is_blacklisted, axis=1)
    df["is_whitelisted"] = df.apply(is_whitelisted, axis=1)

    return df[
        (df["volume24hr"] >= MIN_VOLUME_24H)
        & (df["liquidity"] >= MIN_LIQUIDITY)
        & (df["yes_spread"] <= MAX_SPREAD)
        & (df["yes_mid"] >= MIN_PRICE)
        & (df["yes_mid"] <= MAX_PRICE)
        & (df["yes_ask_dollars"] >= MIN_YES_ASK_DOLLARS)
        & (df["end_date_dt"] > min_end_time)
        & (~df["is_blacklisted"])
        & (df["is_whitelisted"])
    ].copy()

if __name__ == "__main__":
    df = scan_markets(limit=100)
    tradable = filter_tradable(df)

    if tradable.empty:
        print("No markets passed filters.")
    else:
        tradable = tradable.sort_values(
            ["yes_spread", "yes_ask_dollars", "volume24hr"],
            ascending=[True, False, False],
        )

        pd.set_option("display.float_format", "{:,.2f}".format)

        print(
            tradable[
                [
                    "question",
                    "volume24hr",
                    "liquidity",
                    "yes_bid",
                    "yes_ask",
                    "yes_mid",
                    "yes_spread",
                    "yes_ask_size",
                    "yes_ask_dollars",
                    "imbalance",
                    "end_date",
                    "category",
                ]
            ].head(20).to_string(index=False)
        )