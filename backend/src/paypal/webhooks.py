"""PayPal webhook signature verification.

PayPal signs deliveries with certificate-based transmission headers. The
verification API must receive the event exactly as PayPal sent it; the router
therefore reads the raw body once and parses it without mutating it.
"""

from __future__ import annotations

from typing import Any, Mapping

from config.config import settings
from config.logger import get_logger
from paypal.client import paypal_client

logger = get_logger(__name__)

PAYPAL_HEADERS = (
    "paypal-auth-algo",
    "paypal-cert-url",
    "paypal-transmission-id",
    "paypal-transmission-sig",
    "paypal-transmission-time",
)


def transmission_headers(headers: Mapping[str, str]) -> dict[str, str]:
    lowered = {key.lower(): value for key, value in headers.items()}
    return {key: lowered.get(key, "") for key in PAYPAL_HEADERS}


async def verify_webhook(headers: Mapping[str, str], event: dict[str, Any]) -> tuple[bool, str]:
    """Return (accepted, detail).

    In explicit demo mode a missing signature is allowed but logged as a bypass.
    Simulator-generated events cannot be certificate-verified by PayPal, so this
    bypass is only for local/demo routing tests.
    """
    normalized = transmission_headers(headers)
    missing = [key for key, value in normalized.items() if not value]

    if not settings.webhook_ids:
        if settings.demo_mode:
            logger.warning(
                "[PAYPAL WEBHOOK] No PAYPAL_WEBHOOK_ID configured; DEMO_MODE bypass for event %s",
                event.get("id"),
            )
            return True, "demo_bypass_no_webhook_id"
        logger.error("[PAYPAL WEBHOOK] No PayPal webhook ID configured; rejecting delivery")
        return False, "no_webhook_id"

    if missing:
        if settings.demo_mode:
            logger.warning(
                "[PAYPAL WEBHOOK] Missing transmission headers %s; DEMO_MODE bypass for event %s",
                missing,
                event.get("id"),
            )
            return True, "demo_bypass_missing_headers"
        logger.error(
            "[PAYPAL WEBHOOK] Missing transmission headers %s; rejecting delivery", missing
        )
        return False, "missing_headers"

    status, matched_id = await paypal_client.verify_webhook_signature(normalized, event)
    if status == "SUCCESS":
        logger.info(
            "[PAYPAL WEBHOOK] Verified event %s against webhook %s",
            event.get("id"),
            matched_id,
        )
        return True, f"verified:{matched_id}"
    logger.error(
        "[PAYPAL WEBHOOK] Signature verification failed for transmission %s (status=%s)",
        normalized.get("paypal-transmission-id"),
        status,
    )
    return False, f"verification_{status.lower()}"
