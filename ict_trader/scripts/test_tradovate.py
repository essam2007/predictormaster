#!/usr/bin/env python
"""Connectivity smoke test for your Tradovate account.

Authenticates against the Tradovate API (DEMO endpoint unless ICT_TRADER_MODE=live) using
the TRADOVATE_* values in your .env, and prints whether the connection + account lookup
succeed. This is the first real "is my account connected?" check.

    python scripts/test_tradovate.py
"""

from __future__ import annotations

import asyncio

import httpx

from ict_trader.config import get_settings, get_tradovate_settings
from ict_trader.execution.tradovate_rest import TradovateCredentials, TradovateREST


async def _run() -> int:
    s = get_settings()
    ts = get_tradovate_settings()
    print(f"mode={s.mode.value}  endpoint={s.tradovate_base_url}")
    if not ts.configured:
        print("✗ Tradovate credentials not set. Fill TRADOVATE_NAME/PASSWORD/CID/SECRET "
              "(and APP_ID) in .env.")
        return 2
    creds = TradovateCredentials(
        name=ts.name, password=ts.password, app_id=ts.app_id, app_version=ts.app_version,
        cid=ts.cid, sec=ts.secret, device_id=ts.device_id)
    client = httpx.AsyncClient(timeout=10.0)
    rest = TradovateREST(s.tradovate_base_url, creds, client=client)
    try:
        result = await rest.verify()
    finally:
        await client.aclose()
    if result.get("connected"):
        print(f"✓ Connected. account_id={result['account_id']}")
        return 0
    print(f"✗ Connection failed: {result.get('error')}")
    return 1


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
