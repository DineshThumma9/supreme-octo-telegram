"""PayPal Invoicing v2 helpers for B2B receivables."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from config.config import settings
from config.logger import get_logger
from models.models import RecoveryState
from paypal.client import PayPalAPIError, paypal_client

logger = get_logger(__name__)


def _split_name(name: str) -> dict[str, str]:
    parts = (name or "Customer").split(maxsplit=1)
    return {
        "given_name": parts[0] if parts else "Customer",
        "surname": parts[1] if len(parts) > 1 else "",
    }


def invoice_amount(invoice: dict[str, Any]) -> tuple[float, str]:
    amount = invoice.get("amount") or {}
    if amount.get("value") is not None:
        try:
            return float(amount["value"]), amount.get("currency_code", "USD")
        except (TypeError, ValueError):
            pass
    total = (invoice.get("amount") or {}).get("value")
    return float(total or 0.0), (invoice.get("amount") or {}).get("currency_code", "USD")


def invoice_customer(invoice: dict[str, Any]) -> dict[str, Any]:
    recipients = invoice.get("primary_recipients") or []
    if not recipients:
        return {"name": "Accounts Payable", "email": "", "contact": ""}
    billing = recipients[0].get("billing_info") or {}
    name = billing.get("name") or {}
    full_name = " ".join(filter(None, [name.get("given_name"), name.get("surname")])).strip()
    return {
        "name": full_name or billing.get("email_address") or "Accounts Payable",
        "email": billing.get("email_address") or "",
        "contact": "",
    }


def invoice_due_date(invoice: dict[str, Any]) -> str | None:
    detail = invoice.get("detail") or {}
    term = detail.get("payment_term") or {}
    return term.get("due_date") or detail.get("due_date")


def invoice_status(invoice: dict[str, Any]) -> str:
    return str(invoice.get("status") or "").upper()


def invoice_link(invoice_id: str) -> str:
    host = "www.sandbox.paypal.com" if "sandbox" in settings.paypal_api_base else "www.paypal.com"
    return f"https://{host}/invoice/p/#{invoice_id}"


def _mock_invoice(state: RecoveryState, amount: float, currency: str, reason: str) -> dict[str, Any]:
    ref = state.case_id[-8:].upper()
    logger.info("[PAYPAL DEMO] Using mock invoice for case %s (%s)", state.case_id, reason)
    return {
        "id": f"MOCK-INV-{ref}",
        "approve_url": f"https://www.sandbox.paypal.com/invoice/p/#MOCK-INV-{ref}",
        "amount": amount,
        "currency": currency,
        "mock": True,
    }


async def create_recovery_invoice(
    state: RecoveryState,
    amount: float | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    amount = float(state.amount if amount is None else amount)
    currency = (currency or state.currency or "USD").upper()
    meta = state.case_metadata or {}
    email = (state.customer or {}).get("email", "")

    if settings.demo_mode or not email or "@example.com" in email or email.startswith("test"):
        return _mock_invoice(state, amount, currency, "demo/test customer")

    invoice_number = str(meta.get("invoice_number") or f"INV-{state.case_id[-8:].upper()}")
    due_date = meta.get("due_date") or (datetime.now() - timedelta(days=max(1, int(meta.get("days_overdue", 1))))).date().isoformat()
    payload = {
        "detail": {
            "invoice_number": invoice_number,
            "currency_code": currency,
            "note": "Renvue receivables recovery",
            "payment_term": {"term_type": "DUE_ON_DATE_SPECIFIED", "due_date": str(due_date)[:10]},
        },
        "invoicer": {
            "email_address": settings.paypal_business_email or None,
            "name": {"given_name": "Renvue", "surname": "Finance"},
        },
        "primary_recipients": [
            {
                "billing_info": {
                    "email_address": email,
                    "name": _split_name((state.customer or {}).get("name", "Accounts Payable")),
                }
            }
        ],
        "items": [
            {
                "name": (state.failure_reason or "Outstanding invoice")[:100],
                "description": f"Payment recovery for case {state.case_id}"[:1000],
                "quantity": "1",
                "unit_amount": {"currency_code": currency, "value": f"{amount:.2f}"},
            }
        ],
    }
    if not payload["invoicer"]["email_address"]:
        payload["invoicer"].pop("email_address", None)

    try:
        created = await paypal_client.create_invoice(payload)
        href = created.get("href") or ""
        invoice_id = created.get("id") or created.get("invoice_id")
        if not invoice_id and href:
            invoice_id = href.rstrip("/").split("/")[-1]
        if invoice_id:
            try:
                await paypal_client.send_invoice(
                    invoice_id,
                    subject=f"Invoice {invoice_number} from Renvue",
                    note="Please settle the outstanding balance using the secure PayPal invoice link.",
                )
            except PayPalAPIError as exc:
                logger.warning("[PAYPAL] Invoice created but send failed: %s", exc)
    except PayPalAPIError as exc:
        if not settings.demo_mode:
            logger.error(
                "[PAYPAL] Invoice creation failed for case %s: %s", state.case_id, exc
            )
            raise
        logger.error("[PAYPAL] Invoice creation failed for case %s: %s", state.case_id, exc)
        return _mock_invoice(state, amount, currency, f"API error {exc.status_code}")

    return {
        "id": invoice_id or invoice_number,
        "approve_url": invoice_link(invoice_id) if invoice_id else href,
        "amount": amount,
        "currency": currency,
        "raw": created,
        "mock": False,
    }


async def get_invoice(invoice_id: str) -> dict[str, Any]:
    return await paypal_client.get_invoice(invoice_id)


async def remind_invoice(state: RecoveryState, invoice_id: str) -> dict[str, Any]:
    if settings.demo_mode or invoice_id.startswith("MOCK"):
        return {"mock": True, "invoice_id": invoice_id}
    return await paypal_client.remind_invoice(
        invoice_id,
        subject=f"Reminder: invoice {invoice_id}",
        note="This is a courtesy reminder that your PayPal invoice remains outstanding.",
    )
