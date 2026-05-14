import json
import os
import time
import requests
from dotenv import load_dotenv

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    ApiCreds,
    BalanceAllowanceParams,
    AssetType,
)
from py_clob_client.constants import POLYGON

load_dotenv()


def make_client():
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

    return ClobClient(
        host,
        key=private_key,
        chain_id=chain_id,
        creds=creds,
        signature_type=signature_type,
        funder=funder,
    )


def parse_json_field(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return fallback
    return value


def get_current_btc_5m_token_ids():
    now = int(time.time())
    interval_start = now - (now % 300)
    slug = f"btc-updown-5m-{interval_start}"
    url = f"https://gamma-api.polymarket.com/events/slug/{slug}"

    resp = requests.get(url, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Gamma lookup failed: {resp.status_code} slug={slug}")

    event = resp.json()
    markets = event.get("markets", [])
    if not markets:
        raise RuntimeError(f"No markets found for slug={slug}")

    token_ids = parse_json_field(markets[0].get("clobTokenIds"), [])
    if len(token_ids) < 2:
        raise RuntimeError(f"Missing token ids for slug={slug}")

    return slug, token_ids


def main():
    client = make_client()

    print("[ALLOWANCE] Updating collateral / USDC allowance...")
    client.update_balance_allowance(
        params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    )
    print("[OK] collateral allowance update requested")

    try:
        slug, token_ids = get_current_btc_5m_token_ids()
        print(f"[ALLOWANCE] Current BTC 5m market: {slug}")

        for token_id in token_ids:
            print(f"[ALLOWANCE] Updating conditional token allowance token_id={token_id}")
            client.update_balance_allowance(
                params=BalanceAllowanceParams(
                    asset_type=AssetType.CONDITIONAL,
                    token_id=str(token_id),
                )
            )
            print("[OK] conditional token allowance update requested")

    except Exception as e:
        print(f"[WARN] conditional token allowance update skipped: {e}")

    print("[DONE] allowance update script finished")


if __name__ == "__main__":
    main()
