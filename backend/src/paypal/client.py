"""Thin async PayPal REST client used by the recovery engine.

No vendor SDK is required. Every method maps to a documented REST endpoint and
uses the shared client-credentials token cache in paypal/auth.py.
"""

from __future__ import annotations

from typing import Any

import httpx

from config.config import settings
from config.logger import get_logger
from paypal.auth import PayPalAuthError, normalize_base_url, paypal_auth

logger = get_logger(__name__)


class PayPalAPIError(RuntimeError):
    def __init__(self, status_code: int, body: str, path: str = "") -> None:
        self.status_code = status_code
        self.body = body
        self.path = path
        super().__init__(f"PayPal API {status_code} on {path}: {body[:500]}")


def find_link(resource: dict[str, Any], rel: str) -> str | None:
    for link in resource.get("links", []) or []:
        if link.get("rel") in (rel, f"https://api.paypal.com/rel/{rel}"):
            return link.get("href")
    return None


class PayPalClient:
    def __init__(self, base_url: str | None = None, auth=None) -> None:
        self.base_url = normalize_base_url(base_url)
        self.auth = auth or paypal_auth
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        client = self._http()
        token = await self.auth.token(client)
        request_headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
            **(headers or {}),
        }

        for attempt in range(2):
            response = await client.request(
                method,
                path,
                json=json,
                params=params,
                headers=request_headers,
            )
            if response.status_code == 401 and attempt == 0:
                logger.warning("[PAYPAL] Access token rejected; refreshing once")
                self.auth.invalidate()
                request_headers["Authorization"] = f"Bearer {await self.auth.token(client)}"
                continue
            if response.status_code >= 400:
                raise PayPalAPIError(response.status_code, response.text, path)
            if response.status_code == 204 or not response.content:
                return {}
            return response.json()

        raise PayPalAPIError(401, "Unauthorized after token refresh", path)

    # ------------------------------------------------------------------
    # Orders v2
    # ------------------------------------------------------------------
    async def create_order(
        self,
        amount: float,
        currency: str = "USD",
        *,
        reference_id: str = "recovery",
        description: str = "Renvue payment recovery",
        custom_id: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
        payer_email: str | None = None,
    ) -> dict[str, Any]:
        purchase_unit: dict[str, Any] = {
            "reference_id": reference_id,
            "description": description[:127],
            "amount": {
                "currency_code": currency.upper(),
                "value": f"{float(amount):.2f}",
            },
        }
        if custom_id:
            purchase_unit["custom_id"] = custom_id[:127]
        payload: dict[str, Any] = {
            "intent": "CAPTURE",
            "purchase_units": [purchase_unit],
            "application_context": {
                "brand_name": "Renvue",
                "landing_page": "NO_PREFERENCE",
                "shipping_preference": "NO_SHIPPING",
                "user_action": "PAY_NOW",
            },
        }
        if return_url or cancel_url:
            payload["application_context"]["return_url"] = return_url or settings.frontend_url
            payload["application_context"]["cancel_url"] = cancel_url or settings.frontend_url
        if payer_email:
            payload["payer"] = {"email_address": payer_email}
        return await self.request("POST", "/v2/checkout/orders", json=payload)

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/v2/checkout/orders/{order_id}")

    async def capture_order(self, order_id: str, request_id: str | None = None) -> dict[str, Any]:
        headers = {"PayPal-Request-Id": request_id} if request_id else None
        return await self.request(
            "POST",
            f"/v2/checkout/orders/{order_id}/capture",
            json={},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Subscriptions v1
    # ------------------------------------------------------------------
    async def get_subscription(self, subscription_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/v1/billing/subscriptions/{subscription_id}")

    async def revise_subscription(self, subscription_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request(
            "POST", f"/v1/billing/subscriptions/{subscription_id}/revise", json=payload
        )

    async def suspend_subscription(self, subscription_id: str, reason: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/v1/billing/subscriptions/{subscription_id}/suspend",
            json={"reason": reason[:128]},
        )

    async def activate_subscription(self, subscription_id: str, reason: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/v1/billing/subscriptions/{subscription_id}/activate",
            json={"reason": reason[:128]},
        )

    async def cancel_subscription(self, subscription_id: str, reason: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/v1/billing/subscriptions/{subscription_id}/cancel",
            json={"reason": reason[:128]},
        )

    # ------------------------------------------------------------------
    # Invoicing v2
    # ------------------------------------------------------------------
    async def create_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/v2/invoicing/invoices", json=payload)

    async def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/v2/invoicing/invoices/{invoice_id}")

    async def list_invoices(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/v2/invoicing/invoices",
            params={"page": page, "page_size": page_size, "total_required": "true"},
        )

    async def send_invoice(self, invoice_id: str, subject: str, note: str = "") -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/v2/invoicing/invoices/{invoice_id}/send",
            json={
                "send_to_recipient": True,
                "send_to_invoicer": True,
                "subject": subject[:255],
                "note": note[:4000],
            },
        )

    async def remind_invoice(self, invoice_id: str, subject: str, note: str = "") -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/v2/invoicing/invoices/{invoice_id}/remind",
            json={"subject": subject[:255], "note": note[:4000]},
        )

    # ------------------------------------------------------------------
    # Disputes v1
    # ------------------------------------------------------------------
    async def get_dispute(self, dispute_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/v1/customer/disputes/{dispute_id}")

    async def list_disputes(self, page_size: int = 20) -> dict[str, Any]:
        return await self.request(
            "GET", "/v1/customer/disputes", params={"page_size": page_size}
        )

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------
    async def verify_webhook_signature(
        self,
        headers: dict[str, str],
        event: dict[str, Any],
    ) -> tuple[str, str | None]:
        """Return (verification_status, matched_webhook_id).

        PayPal uses certificate-based transmission headers, not an HMAC secret.
        The raw parsed event is sent back exactly as received; callers must not
        re-serialize or mutate it first.
        """
        webhook_ids = settings.webhook_ids
        if not webhook_ids:
            return "NOT_CONFIGURED", None

        payload_base = {
            "auth_algo": headers.get("paypal-auth-algo", ""),
            "cert_url": headers.get("paypal-cert-url", ""),
            "transmission_id": headers.get("paypal-transmission-id", ""),
            "transmission_sig": headers.get("paypal-transmission-sig", ""),
            "transmission_time": headers.get("paypal-transmission-time", ""),
            "webhook_event": event,
        }
        if not all(
            payload_base[key]
            for key in (
                "auth_algo",
                "cert_url",
                "transmission_id",
                "transmission_sig",
                "transmission_time",
            )
        ):
            return "MISSING_HEADERS", None

        last_status = "FAILURE"
        for webhook_id in webhook_ids:
            payload = {**payload_base, "webhook_id": webhook_id}
            try:
                result = await self.request(
                    "POST", "/v1/notifications/verify-webhook-signature", json=payload
                )
            except PayPalAPIError as exc:
                logger.error(
                    "[PAYPAL WEBHOOK] Verification API error for transmission %s: %s",
                    payload_base["transmission_id"],
                    exc,
                )
                return "ERROR", None
            last_status = result.get("verification_status", "FAILURE")
            if last_status == "SUCCESS":
                return last_status, webhook_id
        return last_status, None


paypal_client = PayPalClient()


__all__ = [
    "PayPalAPIError",
    "PayPalAuthError",
    "PayPalClient",
    "find_link",
    "paypal_client",
]
