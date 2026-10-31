"""PayPal Orders v2 helpers for one-time recovery links."""

from __future__ import annotations

from typing import Any

from config.config import settings
from config.logger import get_logger
from models.models import RecoveryState
from paypal.client import PayPalAPIError, find_link, paypal_client

logger = get_logger(__name__)


def order_amount(order: dict[str, Any]) -> tuple[float, str]:
    units = order.get("purchase_units") or []
    if units:
        amount = units[0].get("amount") or {}
        try:
            return float(amount.get("value", 0.0)), amount.get("currency_code", "USD")
        except (TypeError, ValueError):
            pass
    return 0.0, "USD"


def order_customer(order: dict[str, Any]) -> dict[str, Any]:
    payer = order.get("payer") or {}
    name = payer.get("name") or {}
    full_name = " ".join(
        part for part in (name.get("given_name"), name.get("surname")) if part
    ).strip()
    phone = ((payer.get("phone") or {}).get("phone_number") or {}).get("national_number")
    return {
        "name": full_name or payer.get("email_address") or "Customer",
        "email": payer.get("email_address") or "",
        "contact": phone or "",
        "payer_id": payer.get("payer_id"),
    }


def checkout_url(order: dict[str, Any]) -> str | None:
    return (
        find_link(order, "payer-action")
        or find_link(order, "approve")
        or find_link(order, "checkout")
    )


def _mock_order(state: RecoveryState, amount: float, currency: str, reason: str) -> dict[str, Any]:
    ref = state.case_id[-8:].upper()
    logger.info("[PAYPAL DEMO] Using mock order for case %s (%s)", state.case_id, reason)
    return {
        "id": f"MOCK-ORDER-{ref}",
        "status": "CREATED",
        "approve_url": f"https://www.sandbox.paypal.com/checkoutnow?token=MOCK-{ref}",
        "amount": amount,
        "currency": currency,
        "mock": True,
    }


async def create_recovery_order(
    state: RecoveryState,
    amount: float | None = None,
    currency: str | None = None,
    discount_pct: float = 0.0,
) -> dict[str, Any]:
    """Create a CAPTURE order and return its id plus buyer approval URL."""
    amount = float(state.amount if amount is None else amount)
    currency = (currency or state.currency or "USD").upper()
    email = (state.customer or {}).get("email", "")

    if settings.demo_mode or not email or "@example.com" in email or email.startswith("test"):
        return _mock_order(state, amount, currency, "demo/test customer")

    description = {
        "abandoned_checkout": "Complete your Renvue order",
        "failed_payment": "Complete your Renvue payment",
        "failed_subscription": "Resume your Renvue subscription",
        "overdue_invoice": "Pay your Renvue invoice",
    }.get(state.case_type, "Renvue payment recovery")

    return_base = settings.backend_url or settings.frontend_url
    try:
        order = await paypal_client.create_order(
            amount,
            currency,
            reference_id=state.case_id[:127],
            description=description,
            custom_id=state.case_id[:127],
            return_url=f"{return_base}/api/paypal/return?case_id={state.case_id}" if return_base else None,
            cancel_url=f"{return_base}/api/paypal/cancel?case_id={state.case_id}" if return_base else None,
        )
    except PayPalAPIError as exc:
        logger.error("[PAYPAL] Order creation failed for case %s: %s", state.case_id, exc)
        return _mock_order(state, amount, currency, f"API error {exc.status_code}")

    approve_url = checkout_url(order)
    return {
        "id": order.get("id"),
        "status": order.get("status"),
        "approve_url": approve_url,
        "amount": amount,
        "currency": currency,
        "raw": order,
        "mock": False,
    }


async def get_order(order_id: str) -> dict[str, Any]:
    return await paypal_client.get_order(order_id)


async def capture_order(order_id: str, request_id: str | None = None) -> dict[str, Any]:
    return await paypal_client.capture_order(order_id, request_id=request_id)


def capture_from_order(order: dict[str, Any]) -> dict[str, Any] | None:
    for unit in order.get("purchase_units") or []:
        for capture in (unit.get("payments") or {}).get("captures") or []:
            return capture
    return None
