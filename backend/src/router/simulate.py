"""Demo simulator endpoints.

The simulator emits PayPal-shaped events so the same mapper and router used by
real webhooks also drive the UI. No signature is generated here because these
events are injected locally, not delivered over HTTP.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from agent.graph import build_agent
from config.db import get_db
from config.logger import get_logger
from models.models import RecoveryState
from models.schema import CustomerAction, SimulationEvent
from paypal.events import custom_id, extract_amount, extract_customer
from service.service import handle_inbound_whatsapp, handle_paypal_event
from service.money import format_money
from service.states import load_state, save_state

logger = get_logger(__name__)

router = APIRouter(prefix="/api")


def _case_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time())}_{random.randint(100, 999)}"


def _amount(amount: float) -> dict:
    return {"currency_code": "USD", "value": f"{float(amount):.2f}"}


def _reason(value: str, fallback: str = "payment_denied") -> str:
    text = (value or "").lower()
    if "expired" in text:
        return "card_expired"
    if "fraud" in text or "stolen" in text:
        return "fraud"
    if "insufficient" in text or "funds" in text:
        return "insufficient_funds"
    if "closed" in text:
        return "account_closed"
    return fallback


def _customer(state: SimulationEvent, payer_id: str) -> dict:
    return {
        "payer_id": payer_id,
        "email_address": state.email,
        "name": {"given_name": (state.name or "Test").split(" ")[0], "surname": "Customer"},
        "phone": {"phone_number": {"national_number": state.phone}},
    }


def fpayload_to_payload(fstate: SimulationEvent):
    """Build a PayPal webhook event and return (event, case_hint)."""
    currency = (fstate.currency or "USD").upper()
    account_id = fstate.account_id or "paypal_default"
    event_type = fstate.event_type
    now = datetime.now(timezone.utc).isoformat()

    if event_type in {"order.failed", "failed_payment", "payment.failed", "PAYMENT.CAPTURE.DENIED"}:
        case_id = _case_id("failed")
        order_id = f"ORDER-{int(time.time())}-{random.randint(1000, 9999)}"
        capture_id = f"CAP-{int(time.time())}-{random.randint(1000, 9999)}"
        reason = _reason(fstate.decline_reason)
        resource = {
            "id": capture_id,
            "status": "DECLINED",
            "amount": _amount(fstate.amount),
            "custom_id": case_id,
            "invoice_id": f"INV-{int(time.time())}",
            "supplementary_data": {"related_ids": {"order_id": order_id}},
            "payment_source": {
                "card": {"brand": "VISA", "last_digits": "4242", "expiry": "2028-05"}
            },
            "status_details": {"reason": reason, "description": fstate.decline_reason},
            "payer": _customer(fstate, f"PAYER-{random.randint(1000, 9999)}"),
        }
        return {
            "id": f"WH-{int(time.time())}-{random.randint(100000, 999999)}",
            "event_type": "PAYMENT.CAPTURE.DENIED",
            "resource_type": "capture",
            "resource": resource,
            "create_time": now,
        }, case_id

    if event_type in {"subscription_failed", "subscription.halted", "BILLING.SUBSCRIPTION.PAYMENT.FAILED"}:
        case_id = _case_id("sub")
        subscription_id = f"I-{random.randint(100000, 999999)}"
        reason = _reason(fstate.decline_reason, fallback="SUBSCRIPTION_PAYMENT_FAILED")
        resource = {
            "id": subscription_id,
            "status": "SUSPENDED",
            "custom_id": case_id,
            "plan_id": f"P-{random.randint(100000, 999999)}",
            "subscriber": _customer(fstate, f"PAYER-{random.randint(1000, 9999)}"),
            "billing_info": {
                "last_payment": {
                    "amount": _amount(fstate.amount),
                    "time": now,
                },
                "next_billing_time": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
                "failed_payments_count": 1,
            },
            "status_details": {"reason": reason, "description": fstate.decline_reason},
        }
        return {
            "id": f"WH-{int(time.time())}-{random.randint(100000, 999999)}",
            "event_type": "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
            "resource_type": "subscription",
            "resource": resource,
            "create_time": now,
        }, case_id

    if event_type in {"invoice_failed", "invoice.expired", "INVOICING.INVOICE.UPDATED"}:
        case_id = _case_id("invoice")
        invoice_id = f"INV2-{random.randint(100000, 999999)}"
        days_overdue = random.randint(10, 30)
        resource = {
            "id": invoice_id,
            "status": "UNPAID",
            "custom_id": case_id,
            "detail": {
                "invoice_number": f"INV-2026-{random.randint(100, 999)}",
                "currency_code": currency,
                "payment_term": {
                    "term_type": "DUE_ON_DATE_SPECIFIED",
                    "due_date": (datetime.now().date() - timedelta(days=days_overdue)).isoformat(),
                },
                "metadata": {"days_overdue": days_overdue},
            },
            "amount": _amount(fstate.amount),
            "primary_recipients": [
                {
                    "billing_info": {
                        "email_address": fstate.email,
                        "name": {
                            "given_name": (fstate.name or "Accounts").split(" ")[0],
                            "surname": "Payable",
                        },
                    }
                }
            ],
        }
        return {
            "id": f"WH-{int(time.time())}-{random.randint(100000, 999999)}",
            "event_type": "INVOICING.INVOICE.UPDATED",
            "resource_type": "invoice",
            "resource": resource,
            "create_time": now,
        }, case_id

    if event_type in {"abandoned_checkout", "CHECKOUT.ORDER.CREATED"}:
        case_id = _case_id("cart")
        order_id = f"ORDER-{int(time.time())}-{random.randint(1000, 9999)}"
        resource = {
            "id": order_id,
            "status": "CREATED",
            "intent": "CAPTURE",
            "custom_id": case_id,
            "purchase_units": [
                {
                    "reference_id": "default",
                    "custom_id": case_id,
                    "amount": _amount(fstate.amount),
                }
            ],
            "payer": _customer(fstate, f"PAYER-{random.randint(1000, 9999)}"),
            "links": [
                {
                    "rel": "payer-action",
                    "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
                }
            ],
        }
        return {
            "id": f"WH-{int(time.time())}-{random.randint(100000, 999999)}",
            "event_type": "CHECKOUT.ORDER.CREATED",
            "resource_type": "checkout-order",
            "resource": resource,
            "create_time": now,
        }, case_id

    return None, None


@router.post("/fake-event")
async def fake_event(fstate: SimulationEvent, db=Depends(get_db)):
    payload, case_id = fpayload_to_payload(fstate)
    if not payload:
        return {"status": "ignored", "id": None}

    # Checkout abandonment is a timer, not a failure webhook. Create the case
    # immediately in the simulator so the UI can exercise the discount Play.
    if fstate.event_type in {"abandoned_checkout", "CHECKOUT.ORDER.CREATED"}:
        resource = payload["resource"]
        amount, currency = extract_amount(resource, "CHECKOUT.ORDER.CREATED")
        customer = extract_customer(resource)
        case_ref = custom_id(resource) or case_id
        state = RecoveryState(
            case_id=case_ref,
            source_id=resource["id"],
            paypal_order_id=resource["id"],
            account_id=fstate.account_id or "paypal_default",
            case_type="abandoned_checkout",
            failure_reason="PayPal checkout abandoned",
            case_metadata={
                "source_event_type": "CHECKOUT.ORDER.CREATED",
                "paypal_order_id": resource["id"],
                "payment_link": (resource.get("links") or [{}])[0].get("href"),
                "simulated": True,
            },
            amount=amount,
            currency=currency,
            customer=customer,
            contact_preference="email" if customer.get("email") else "whatsapp",
            recovery_status="pending",
            audit_log=[
                {
                    "event_triggered": "checkout_abandoned",
                    "amount": format_money(amount, currency),
                    "recovery_status": "pending",
                    "customer": customer,
                    "message": "PayPal checkout abandoned. Starting discount recovery.",
                    "channel": "system",
                    "direction": "system",
                    "created_at": datetime.now().isoformat(),
                }
            ],
        )
        await save_state(state, db)
        agent = build_agent(state)
        await agent.ainvoke(
            {"messages": [], "recovery_state": state, "event_source": "automated.abandoned_cart"},
            config={"configurable": {"thread_id": state.case_id}},
        )
        return {"id": state.case_id, "event_type": "CHECKOUT.ORDER.CREATED", "result": "case created"}

    result = await handle_paypal_event(payload, db, simulated=True)
    logger.info("[SIM] %s -> %s", fstate.event_type, result)
    return {"id": case_id, "event_type": payload["event_type"], "result": result}


async def generate_success_payload(case_id: str, db):
    state: RecoveryState | None = await load_state(case_id, db)
    if not state:
        return None

    order_id = state.paypal_order_id or state.source_id
    capture_id = f"CAP-{int(time.time())}-{random.randint(1000, 9999)}"
    return {
        "id": f"WH-{int(time.time())}-{random.randint(100000, 999999)}",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource_type": "capture",
        "resource": {
            "id": capture_id,
            "status": "COMPLETED",
            "amount": _amount(state.amount),
            "custom_id": state.case_id,
            "supplementary_data": {"related_ids": {"order_id": order_id}},
            "payer": {
                "payer_id": state.customer.get("payer_id"),
                "email_address": state.customer.get("email", ""),
            },
        },
        "create_time": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/fake-action")
async def fake_action(action: CustomerAction, db=Depends(get_db)):
    if action.actions == "pay":
        payload = await generate_success_payload(action.case_id, db)
        if payload:
            await handle_paypal_event(payload, db)
        return {"status": "ok", "case_id": action.case_id, "result": "payment captured"}

    if action.actions == "ignore":
        state = await load_state(action.case_id, db)
        if not state:
            return {"status": "not_found"}
        if state.recovery_status in {"recovered", "closed", "escalated"}:
            return {"status": f"Case is already {state.recovery_status}"}
        if state.active_task_id:
            from background.worker import revoke_active_task

            await revoke_active_task(state.active_task_id)
            state.active_task_id = None
            await save_state(state, db)
        from background.worker import invoke_agent_task

        await invoke_agent_task(action.case_id)
        return {"status": "ok", "case_id": action.case_id, "result": "follow-up triggered"}

    if action.actions == "reply":
        state = await load_state(action.case_id, db)
        if state:
            phone = state.customer.get("contact", "+14155550123")
            await handle_inbound_whatsapp(phone, action.messages or "", db, case_id=action.case_id)
            return {"status": "ok", "case_id": action.case_id, "result": "reply routed"}

    return {"status": "ignored"}
