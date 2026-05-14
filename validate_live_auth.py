import os
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

    missing = [
        name for name, value in {
            "CLOB_API_KEY": creds.api_key,
            "CLOB_SECRET": creds.api_secret,
            "CLOB_PASS_PHRASE": creds.api_passphrase,
        }.items()
        if not value
    ]

    if missing:
        raise RuntimeError(f"Missing CLOB credentials: {', '.join(missing)}")

    return ClobClient(
        host,
        key=private_key,
        chain_id=chain_id,
        creds=creds,
        signature_type=signature_type,
        funder=funder,
    )


def main():
    client = make_client()

    print("[OK] authenticated client created")

    collateral = client.get_balance_allowance(
        params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    )
    print("[OK] collateral balance/allowance endpoint responded:")
    print(collateral)

    try:
        orders = client.get_orders()
    except TypeError:
        orders = client.get_orders({})

    print("[OK] get_orders endpoint responded:")
    print(orders)

    print("[DONE] live auth validation completed without placing orders")


if __name__ == "__main__":
    main()
