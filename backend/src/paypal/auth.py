"""Async PayPal OAuth2 client-credentials token cache."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

from config.config import settings
from config.logger import get_logger

logger = get_logger(__name__)


class PayPalAuthError(RuntimeError):
    pass


@dataclass
class Token:
    access_token: str
    expires_at: float


def normalize_base_url(url: str | None) -> str:
    base = (url or settings.paypal_api_base or "https://api-m.sandbox.paypal.com").rstrip("/")
    # PayPal's old sandbox hostname still resolves, but api-m is the documented
    # REST host and is required for some Invoicing/Subscriptions endpoints.
    base = base.replace("https://api.sandbox.paypal.com", "https://api-m.sandbox.paypal.com")
    base = base.replace("https://api.paypal.com", "https://api-m.paypal.com")
    return base


class PayPalAuth:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.client_id = client_id or settings.paypal_client_id
        self.client_secret = client_secret or settings.paypal_client_secret
        self.base_url = normalize_base_url(base_url)
        self._token: Token | None = None
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def invalidate(self) -> None:
        self._token = None

    async def _mint(self, client: httpx.AsyncClient | None = None) -> Token:
        if not self.configured:
            raise PayPalAuthError(
                "PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are not configured"
            )

        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=30)
        try:
            response = await client.post(
                f"{self.base_url}/v1/oauth2/token",
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={
                    "Accept": "application/json",
                    "Accept-Language": "en_US",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if response.status_code >= 400:
                body = response.text[:500]
                raise PayPalAuthError(
                    f"PayPal OAuth failed ({response.status_code}): {body}"
                )
            payload = response.json()
            expires_in = max(60, int(payload.get("expires_in", 3600)) - 60)
            return Token(
                access_token=payload["access_token"],
                expires_at=time.time() + expires_in,
            )
        finally:
            if owns_client:
                await client.aclose()

    async def token(self, client: httpx.AsyncClient | None = None) -> str:
        if self._token and time.time() < self._token.expires_at:
            return self._token.access_token
        async with self._lock:
            if self._token and time.time() < self._token.expires_at:
                return self._token.access_token
            self._token = await self._mint(client)
            logger.info("[PAYPAL] OAuth token minted (cache expires in %ss)", int(self._token.expires_at - time.time()))
            return self._token.access_token

    async def auth_header(self, client: httpx.AsyncClient | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self.token(client)}"}


paypal_auth = PayPalAuth()
