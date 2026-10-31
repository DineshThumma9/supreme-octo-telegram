"""PayPal Disputes v1 helpers."""

from __future__ import annotations

from typing import Any

from paypal.client import paypal_client


def dispute_amount(dispute: dict[str, Any]) -> tuple[float, str]:
    amount = dispute.get("dispute_amount") or dispute.get("amount") or {}
    try:
        return float(amount.get("value", 0.0)), amount.get("currency_code", "USD")
    except (TypeError, ValueError):
        return 0.0, "USD"


def dispute_customer(dispute: dict[str, Any]) -> dict[str, Any]:
    buyer = dispute.get("buyer") or dispute.get("seller") or {}
    name = buyer.get("name") or {}
    full_name = " ".join(filter(None, [name.get("given_name"), name.get("surname")])).strip()
    return {
        "name": full_name or buyer.get("email_address") or "Customer",
        "email": buyer.get("email_address") or "",
        "contact": "",
    }


def dispute_order_id(dispute: dict[str, Any]) -> str | None:
    links = dispute.get("links") or []
    for link in links:
        href = link.get("href", "")
        if "/checkout/orders/" in href:
            return href.rstrip("/").split("/")[-1]
    return (dispute.get("disputed_transactions") or [{}])[0].get("seller_transaction_id")


async def get_dispute(dispute_id: str) -> dict[str, Any]:
    return await paypal_client.get_dispute(dispute_id)


async def list_disputes(page_size: int = 20) -> dict[str, Any]:
    return await paypal_client.list_disputes(page_size)
