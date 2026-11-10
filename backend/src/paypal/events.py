"""Map PayPal webhook events and resources to Renvue recovery cases."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.constants import HARD_DECLINE_MARKERS, TRANSIENT_DECLINE_MARKERS
from config.logger import get_logger
from models.models import CustomerProfile, RecoveryState
from models.schema import PayPalWebhookEvent
from service.customer import get_customer_profile, save_customer_profile

logger = get_logger(__name__)


def event_type(event: dict[str, Any]) -> str:
    return str(event.get("event_type") or event.get("event") or "").upper()


def event_resource(event: dict[str, Any]) -> dict[str, Any]:
    resource = event.get("resource")
    return resource if isinstance(resource, dict) else {}


def _value(amount: Any) -> tuple[float, str]:
    if isinstance(amount, dict):
        # Orders v2 uses {value, currency_code}; the webhook simulator and the
        # legacy Payments API use {total, currency}. Accept both shapes.
        raw = amount.get("value")
        if raw is None:
            raw = amount.get("total")
        currency = amount.get("currency_code") or amount.get("currency") or "USD"
        try:
            return float(raw or 0.0), str(currency).upper()
        except (TypeError, ValueError):
            pass
    return 0.0, "USD"


def extract_amount(resource: dict[str, Any], event: str) -> tuple[float, str]:
    # Captures, orders, refunds and invoices all use an amount object.
    if "amount" in resource:
        amount = _value(resource["amount"])
        if amount[0] > 0:
            return amount
    for unit in resource.get("purchase_units") or []:
        amount = _value(unit.get("amount"))
        if amount[0] > 0:
            return amount
    billing = resource.get("billing_info") or {}
    last_payment = billing.get("last_payment") or {}
    if last_payment:
        amount = _value(last_payment.get("amount"))
        if amount[0] > 0:
            return amount
    if resource.get("dispute_amount"):
        return _value(resource["dispute_amount"])
    return 0.0, "USD"


def _name_from(value: dict[str, Any]) -> str:
    name = value.get("name") or {}
    if isinstance(name, str):
        return name
    return " ".join(
        part for part in (name.get("given_name"), name.get("surname"), name.get("full_name")) if part
    ).strip()


def extract_customer(resource: dict[str, Any]) -> dict[str, Any]:
    payer = resource.get("payer") or resource.get("buyer") or resource.get("subscriber") or {}
    if payer:
        phone = ((payer.get("phone") or {}).get("phone_number") or {}).get("national_number") or ""
        return {
            "name": _name_from(payer) or payer.get("email_address") or "Customer",
            "email": payer.get("email_address") or "",
            "contact": phone,
            "payer_id": payer.get("payer_id"),
        }

    recipients = resource.get("primary_recipients") or []
    if recipients:
        billing = recipients[0].get("billing_info") or {}
        return {
            "name": _name_from(billing) or billing.get("email_address") or "Accounts Payable",
            "email": billing.get("email_address") or "",
            "contact": "",
        }

    return {"name": "Customer", "email": "", "contact": ""}


def extract_issue(resource: dict[str, Any], event: str) -> tuple[str, str]:
    details = resource.get("status_details") or {}
    reason = (
        details.get("reason")
        or resource.get("reason")
        or resource.get("issue")
        or resource.get("error_code")
        or ""
    )
    description = (
        resource.get("description")
        or details.get("description")
        or resource.get("message")
        or ""
    )
    if not reason:
        if event == "INVOICING.INVOICE.UPDATED":
            reason = "INVOICE_OVERDUE"
            description = "PayPal invoice is past due"
        elif event.startswith("BILLING.SUBSCRIPTION"):
            reason = "SUBSCRIPTION_PAYMENT_FAILED"
            description = "Recurring subscription payment failed"
        elif event.startswith("CUSTOMER.DISPUTE"):
            reason = "DISPUTE_OPENED"
            description = "Customer opened a PayPal dispute"
        else:
            reason = "PAYMENT_DENIED"
            description = "PayPal declined the payment"
    return str(reason), str(description or reason).replace("_", " ").title()


def classify_decline(reason: str, description: str = "") -> str:
    text = f"{reason} {description}".lower()
    if any(marker in text for marker in TRANSIENT_DECLINE_MARKERS):
        return "soft"
    if any(marker in text for marker in HARD_DECLINE_MARKERS):
        return "hard"
    return "unknown"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None


def invoice_is_overdue(resource: dict[str, Any]) -> bool:
    status = str(resource.get("status") or "").upper()
    if status in {"PAID", "MARKED_AS_PAID", "CANCELLED", "REFUNDED", "PARTIALLY_REFUNDED"}:
        return False
    detail = resource.get("detail") or {}
    term = detail.get("payment_term") or {}
    due = _parse_dt(term.get("due_date") or detail.get("due_date"))
    if due and due.date() < date.today():
        return True
    # UNPAID only means "not paid yet"; it is not overdue until the due date passes.
    return status == "OVERDUE"


def extract_ids(resource: dict[str, Any], event: str) -> dict[str, str | None]:
    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
    order_id = related.get("order_id") or resource.get("order_id")
    capture_id = None
    subscription_id = None
    invoice_id = None
    dispute_id = None

    if event.startswith("PAYMENT.CAPTURE"):
        capture_id = resource.get("id")
        invoice_id = resource.get("invoice_id")
    elif event.startswith("CHECKOUT.ORDER"):
        order_id = resource.get("id") or order_id
    elif event.startswith("BILLING.SUBSCRIPTION"):
        subscription_id = resource.get("id")
    elif event.startswith("INVOICING.INVOICE"):
        invoice_id = resource.get("id")
    elif event.startswith("CUSTOMER.DISPUTE"):
        dispute_id = resource.get("dispute_id") or resource.get("id")
        transactions = resource.get("disputed_transactions") or []
        if transactions and not order_id:
            order_id = transactions[0].get("seller_transaction_id")

    source_id = order_id or subscription_id or invoice_id or capture_id or dispute_id
    return {
        "order_id": order_id,
        "capture_id": capture_id,
        "subscription_id": subscription_id,
        "invoice_id": invoice_id,
        "dispute_id": dispute_id,
        "source_id": source_id,
    }


def custom_id(resource: dict[str, Any]) -> str | None:
    value = resource.get("custom_id")
    if value:
        return str(value)
    for unit in resource.get("purchase_units") or []:
        if unit.get("custom_id"):
            return str(unit["custom_id"])
    return None


def case_type_for_event(event: str, resource: dict[str, Any]) -> str | None:
    if event == "PAYMENT.CAPTURE.DENIED":
        return "failed_payment"
    if event == "PAYMENT.CAPTURE.PENDING":
        return "failed_payment"
    if event == "BILLING.SUBSCRIPTION.PAYMENT.FAILED":
        return "failed_subscription"
    if event == "BILLING.SUBSCRIPTION.SUSPENDED":
        return "subscription_suspended"
    if event == "BILLING.SUBSCRIPTION.CANCELLED":
        return "subscription_cancelled"
    if event == "INVOICING.INVOICE.UPDATED" and invoice_is_overdue(resource):
        return "overdue_invoice"
    if event == "CUSTOMER.DISPUTE.CREATED":
        return "dispute"
    return None


async def _customer_profile(
    customer: dict[str, Any],
    customer_ref: str,
    db: AsyncSession,
) -> tuple[CustomerProfile, str, str, dict[str, Any]]:
    cust_id = customer.get("payer_id") or customer.get("email") or customer_ref
    cust_id = str(cust_id or hashlib.sha1(customer_ref.encode()).hexdigest()[:16])
    existing = await get_customer_profile(cust_id, db)
    if existing:
        existing.name = customer.get("name") or existing.name
        existing.email = customer.get("email") or existing.email
        existing.contact = customer.get("contact") or existing.contact
        existing.updated_at = datetime.now()
        await save_customer_profile(existing, db)
        customer = {
            **customer,
            "trust_score": existing.trust_score,
            "total_spend": existing.total_spend,
        }
        return existing, existing.language, existing.contact_preference, customer

    profile = CustomerProfile(
        id=cust_id,
        name=customer.get("name"),
        email=customer.get("email"),
        contact=customer.get("contact"),
        language="english",
        contact_preference="email",
        trust_score=100,
        total_spend=0.0,
    )
    await save_customer_profile(profile, db)
    customer = {**customer, "trust_score": 100, "total_spend": 0.0}
    return profile, "english", "email", customer


async def parse_paypal_event(event: dict[str, Any], db: AsyncSession) -> RecoveryState | None:
    """Create (or describe) a recovery case from a PayPal failure event."""
    try:
        webhook = PayPalWebhookEvent.model_validate(event)
    except Exception as exc:
        logger.error("[PAYPAL EVENT] Validation failed: %s", exc)
        return None

    etype = event_type(event)
    resource = event_resource(event)
    case_type = case_type_for_event(etype, resource)
    if not case_type:
        return None

    ids = extract_ids(resource, etype)
    amount, currency = extract_amount(resource, etype)
    customer = extract_customer(resource)
    reason, description = extract_issue(resource, etype)
    decline_type = classify_decline(reason, description)

    source_ref = ids.get("source_id") or ids.get("capture_id") or webhook.id
    _, language, contact_pref, customer = await _customer_profile(customer, source_ref, db)

    payment_source = resource.get("payment_source") or {}
    card = payment_source.get("card") or {}
    method = card.get("brand") or ("card" if card else "paypal")
    through = card.get("last_digits") or card.get("brand") or "PayPal"

    invoice_detail = resource.get("detail") or {}
    meta: dict[str, Any] = {
        "source_event_type": etype,
        "paypal_order_id": ids.get("order_id"),
        "capture_id": ids.get("capture_id"),
        "subscription_id": ids.get("subscription_id"),
        "invoice_id": ids.get("invoice_id"),
        "dispute_id": ids.get("dispute_id"),
        "due_date": (invoice_detail.get("payment_term") or {}).get("due_date"),
        "invoice_number": invoice_detail.get("invoice_number"),
    }
    meta = {key: value for key, value in meta.items() if value}
    if case_type == "overdue_invoice":
        meta.setdefault("invoice_number", ids.get("invoice_id") or f"INV-{uuid.uuid4().hex[:8].upper()}")

    error_details = {
        "issue": reason,
        "reason": reason,
        "description": description,
        "order_id": ids.get("order_id"),
        "capture_id": ids.get("capture_id"),
        "subscription_id": ids.get("subscription_id"),
        "invoice_id": ids.get("invoice_id"),
        "dispute_id": ids.get("dispute_id"),
        "card_brand": card.get("brand"),
        "card_last4": card.get("last_digits"),
        "payer_id": customer.get("payer_id"),
    }
    error_details = {key: value for key, value in error_details.items() if value}

    status = "pending"
    if etype == "PAYMENT.CAPTURE.PENDING":
        meta["hold"] = True
    if case_type == "dispute":
        status = "escalated"

    case_id = custom_id(resource) or str(uuid.uuid4())
    now = datetime.now()
    return RecoveryState(
        case_id=case_id,
        source_id=str(source_ref),
        account_id=str(resource.get("account_id") or "paypal_default"),
        paypal_order_id=ids.get("order_id"),
        capture_id=ids.get("capture_id"),
        subscription_id=ids.get("subscription_id"),
        invoice_id=ids.get("invoice_id"),
        dispute_id=ids.get("dispute_id"),
        method=method,
        through=through,
        case_type=case_type,
        decline_type=decline_type,
        failure_reason=description,
        error_details=error_details,
        case_metadata=meta,
        amount=amount,
        currency=currency,
        recovered_amount=0.0,
        customer=customer,
        contact_preference=contact_pref,
        language=language,
        recovery_status=status,
        attempt_count=0,
        last_action_taken=None,
        first_seen_at=now,
        next_retry_at=None,
        audit_log=[
            {
                "event_triggered": "payment_failed" if case_type != "dispute" else "payment_dispute",
                "amount": f"{amount:,.2f} {currency}",
                "recovery_status": status,
                "customer": customer,
                "next_contact": None,
                "message": (
                    f"PayPal event {etype}: {description}"
                    if case_type != "dispute"
                    else f"PayPal dispute opened: {description}"
                ),
                "channel": "system",
                "direction": "system",
                "created_at": now.isoformat(),
            }
        ],
    )


def event_resource_id(event: dict[str, Any]) -> str:
    resource = event_resource(event)
    ids = extract_ids(resource, event_type(event))
    return str(ids.get("source_id") or ids.get("dispute_id") or resource.get("id") or event.get("id") or "")
