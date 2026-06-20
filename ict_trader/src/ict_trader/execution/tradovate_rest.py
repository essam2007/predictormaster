"""Tradovate REST client: auth + token renewal + order placement.

Endpoints (demo): ``https://demo.tradovateapi.com/v1``; live: ``https://live...``.
Auth: POST ``/auth/accessTokenRequest`` -> {accessToken, mdAccessToken, expirationTime};
renew via ``/auth/renewAccessToken`` ~15 min before expiry. Bearer token on every call.

Network calls are isolated here so the rest of the system stays testable without a broker.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .order_router import BracketSpec


@dataclass
class TradovateCredentials:
    name: str
    password: str
    app_id: str
    app_version: str
    cid: str
    sec: str
    device_id: str = ""


class TradovateAuthError(RuntimeError):
    pass


class TradovateREST:
    def __init__(self, base_url: str, creds: TradovateCredentials,
                 client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.creds = creds
        self._client = client or httpx.AsyncClient(timeout=15.0)
        self._owns_client = client is None
        self.access_token: str | None = None
        self.md_access_token: str | None = None
        self.expires_at: datetime | None = None
        self._account_id: int | None = None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- auth ------------------------------------------------------------
    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=16))
    async def authenticate(self) -> None:
        await self._auth_once()

    async def _auth_once(self) -> None:
        """A single authentication attempt (no retry) — used by the engine and verify()."""
        payload = {
            "name": self.creds.name, "password": self.creds.password,
            "appId": self.creds.app_id, "appVersion": self.creds.app_version,
            "cid": self.creds.cid, "sec": self.creds.sec,
        }
        if self.creds.device_id:
            payload["deviceId"] = self.creds.device_id
        r = await self._client.post(f"{self.base_url}/auth/accessTokenRequest", json=payload)
        data = r.json()
        if r.status_code != 200 or "accessToken" not in data:
            raise TradovateAuthError(f"auth failed: {data}")
        self.access_token = data["accessToken"]
        self.md_access_token = data.get("mdAccessToken")
        self.expires_at = _parse_expiry(data.get("expirationTime"))

    async def verify(self) -> dict:
        """Single-attempt connectivity check: authenticate + fetch the account.

        Returns a structured result and never raises, so the UI / CLI can show status.
        """
        try:
            await self._auth_once()
            acct = await self.account_id()
            return {"connected": True, "account_id": acct, "base_url": self.base_url}
        except Exception as exc:  # noqa: BLE001
            return {"connected": False, "error": str(exc), "base_url": self.base_url}

    async def renew(self) -> None:
        r = await self._client.post(f"{self.base_url}/auth/renewAccessToken",
                                    headers=self._headers())
        data = r.json()
        if "accessToken" in data:
            self.access_token = data["accessToken"]
            self.expires_at = _parse_expiry(data.get("expirationTime"))

    async def ensure_token(self) -> None:
        if self.access_token is None:
            await self.authenticate()
            return
        if self.expires_at and datetime.now(UTC) >= self.expires_at - timedelta(minutes=15):
            await self.renew()

    def _headers(self) -> dict[str, str]:
        if not self.access_token:
            raise TradovateAuthError("not authenticated")
        return {"Authorization": f"Bearer {self.access_token}"}

    # -- account ---------------------------------------------------------
    async def account_id(self) -> int:
        if self._account_id is not None:
            return self._account_id
        await self.ensure_token()
        r = await self._client.get(f"{self.base_url}/account/list", headers=self._headers())
        accounts = r.json()
        if not accounts:
            raise TradovateAuthError("no Tradovate accounts on this login")
        self._account_id = int(accounts[0]["id"])
        return self._account_id

    # -- orders ----------------------------------------------------------
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, max=8))
    async def place_order(self, body: dict) -> dict:
        await self.ensure_token()
        r = await self._client.post(f"{self.base_url}/order/placeOrder",
                                    json=body, headers=self._headers())
        return r.json()

    async def place_oso(self, body: dict) -> dict:
        """Place an OSO (order-sends-order) bracket via /order/placeOSO."""
        await self.ensure_token()
        r = await self._client.post(f"{self.base_url}/order/placeOSO",
                                    json=body, headers=self._headers())
        return r.json()

    async def cancel_order(self, order_id: int) -> dict:
        await self.ensure_token()
        r = await self._client.post(f"{self.base_url}/order/cancelOrder",
                                    json={"orderId": order_id}, headers=self._headers())
        return r.json()

    async def place_bracket(self, spec: BracketSpec) -> list[dict]:
        """Submit a bracket. Demo-friendly: places the entry then the exit legs.

        A production deployment should use a single /order/placeOSO payload so the broker
        links the OCO server-side; this sequential form is the simplest correct fallback.
        """
        acct = await self.account_id()
        results = []
        for leg in spec.legs:
            body = {
                "accountId": acct,
                "symbol": spec.symbol,
                "orderQty": leg.qty,
                "orderType": _ot(leg.order_type.value),
                "action": leg.action,
                "isAutomated": True,
            }
            if leg.price is not None:
                body["price"] = leg.price
            if leg.stop_price is not None:
                body["stopPrice"] = leg.stop_price
            results.append(await self.place_order(body))
            await asyncio.sleep(0)  # cooperative; keep within rate limits upstream
        return results


def _ot(value: str) -> str:
    return {"market": "Market", "limit": "Limit", "stop": "Stop",
            "trailing_stop": "TrailingStop"}.get(value, "Market")


def _parse_expiry(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
