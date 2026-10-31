"""PayPal Subscriptions v1 helpers."""

from __future__ import annotations

from typing import Any

from config.config import settings
from config.logger import get_logger
from models.models import RecoveryState
from paypal.client import PayPalAPIError, find_link, paypal_client

logger = get_logger(__name__)


def subscription_amount(subscription: dict[str, Any]) -> tuple[float, str]:
    billing = subscription.get("billing_info") or {}
    last_payment = billing.get("last_payment") or {}
    amount = last_payment.get("amount") or subscription.get("amount") or {}
    try:
        return float(amount.get("value", 0.0)), amount.get("currency_code", "USD")
    except (TypeError, ValueError):
        return 0.0, "USD"


def subscription_customer(subscription: dict[str, Any]) -> dict[str, Any]:
    subscriber = subscription.get("subscriber") or {}
    name = subscriber.get("name") or {}
    given = name.get("given_name") or ""
    surname = name.get("surname") or ""
    phone = ((subscriber.get("phone") or {}).get("phone_number") or {}).get("national_number")
    return {
        "name": " ".join(filter(None, [given, surname])) or subscriber.get("email_address") or "Customer",
        "email": subscriber.get("email_address") or "",
        "contact": phone or "",
        "payer_id": subscriber.get("payer_id"),
    }


def update_method_url(subscription_id: str) -> str:
    """Deep link where a buyer can update the funding source for a subscription."""
    host = "www.sandbox.paypal.com" if "sandbox" in settings.paypal_api_base else "www.paypal.com"
    return f"https://{host}/webapps/billing/subscriptions?ba_token={subscription_id}"


async def get_subscription(subscription_id: str) -> dict[str, Any]:
    return await paypal_client.get_subscription(subscription_id)


async def create_update_method_link(state: RecoveryState) -> str:
    subscription_id = state.subscription_id or state.source_id
    if settings.demo_mode or not subscription_id or subscription_id.startswith("MOCK"):
        ref = (state.case_id[-8:] if state.case_id else "subscription").upper()
        return f"https://www.sandbox.paypal.com/webapps/billing/subscriptions?ba_token=MOCK-{ref}"

    try:
        subscription = await get_subscription(subscription_id)
        approve = find_link(subscription, "approve") or find_link(subscription, "edit")
        if approve:
            return approve
    except PayPalAPIError as exc:
        logger.warning("[PAYPAL] Subscription lookup failed for %s: %s", subscription_id, exc)
    return update_method_url(subscription_id)
