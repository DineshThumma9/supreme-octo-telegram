"""PayPal event handling for the Renvue recovery loop."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import or_, select

from agent.graph import build_agent
from agent.utils import _schedule_task
from background.worker import abandoned_cart_timer, invoke_agent_task, revoke_active_task
from config.clients import send_twilio_whatsapp
from config.logger import get_logger
from models.models import RecoveryState
from paypal.events import (
    case_type_for_event,
    classify_decline,
    custom_id,
    event_resource,
    event_type,
    extract_amount,
    extract_customer,
    extract_ids,
    extract_issue,
    invoice_is_overdue,
    parse_paypal_event,
)
from paypal.orders import capture_from_order, capture_order as paypal_capture_order
from service.money import format_money
from service.states import load_state, save_state

logger = get_logger(__name__)

SUCCESS_EVENTS = {
    "PAYMENT.CAPTURE.COMPLETED",
    "CHECKOUT.ORDER.COMPLETED",
    "INVOICING.INVOICE.PAID",
    "BILLING.SUBSCRIPTION.ACTIVATED",
}

FAILURE_EVENTS = {
    "PAYMENT.CAPTURE.DENIED",
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
    "BILLING.SUBSCRIPTION.SUSPENDED",
    "BILLING.SUBSCRIPTION.CANCELLED",
    "INVOICING.INVOICE.UPDATED",
}

TERMINAL = {"recovered", "closed", "escalated"}


def _audit(
    state: RecoveryState,
    event_triggered: str,
    message: str,
    *,
    channel: str = "system",
    direction: str = "system",
    next_contact: datetime | None = None,
) -> None:
    if state.audit_log is None:
        state.audit_log = []
    state.audit_log.append(
        {
            "event_triggered": event_triggered,
            "amount": format_money(state.amount, state.currency),
            "recovery_status": state.recovery_status,
            "customer": state.customer,
            "next_contact": next_contact.isoformat() if next_contact else None,
            "message": message,
            "channel": channel,
            "direction": direction,
            "created_at": datetime.now().isoformat(),
        }
    )


async def kill_all_tasks(case_id: str, db: AsyncSession) -> None:
    state = await load_state(case_id, db)
    if state and state.active_task_id:
        logger.info("[TASKIQ] Revoking active task %s for case %s", state.active_task_id, case_id)
        try:
            await revoke_active_task(state.active_task_id)
        except Exception as exc:
            logger.warning("[TASKIQ] Could not revoke task: %s", exc)
        state.active_task_id = None
        await save_state(state, db)


def _case_filters(ids: dict[str, str | None], case_ref: str | None = None) -> list:
    filters = []
    if case_ref:
        filters.append(RecoveryState.case_id == case_ref)
    if ids.get("order_id"):
        filters.append(RecoveryState.paypal_order_id == ids["order_id"])
        filters.append(RecoveryState.source_id == ids["order_id"])
    if ids.get("capture_id"):
        filters.append(RecoveryState.capture_id == ids["capture_id"])
    if ids.get("subscription_id"):
        filters.append(RecoveryState.subscription_id == ids["subscription_id"])
        filters.append(RecoveryState.source_id == ids["subscription_id"])
    if ids.get("invoice_id"):
        filters.append(RecoveryState.invoice_id == ids["invoice_id"])
        filters.append(RecoveryState.source_id == ids["invoice_id"])
    if ids.get("dispute_id"):
        filters.append(RecoveryState.dispute_id == ids["dispute_id"])
    return filters


async def _find_case(
    db: AsyncSession,
    event: dict[str, Any],
    *,
    active_only: bool = False,
) -> tuple[RecoveryState | None, dict[str, Any]]:
    resource = event_resource(event)
    etype = event_type(event)
    ids = extract_ids(resource, etype)
    filters = _case_filters(ids, custom_id(resource))
    if not filters:
        return None, ids

    stmt = select(RecoveryState).where(or_(*filters))
    if active_only:
        stmt = stmt.where(RecoveryState.recovery_status.notin_(list(TERMINAL)))
    state = (await db.execute(stmt)).scalars().first()
    return state, ids


def _recovered_amount(state: RecoveryState, resource: dict[str, Any], etype: str) -> float:
    amount, _ = extract_amount(resource, etype)
    if amount > 0:
        return amount
    if etype.startswith("PAYMENT.CAPTURE") and resource.get("id"):
        # Capture resource amounts are authoritative when present.
        capture_amount, _ = extract_amount(resource, etype)
        if capture_amount > 0:
            return capture_amount
    return float(state.amount or 0.0)


async def _mark_recovered(
    db: AsyncSession,
    state: RecoveryState,
    resource: dict[str, Any],
    etype: str,
    message: str,
) -> str:
    amount = _recovered_amount(state, resource, etype)
    state.recovery_status = "recovered"
    state.recovered_amount = amount
    state.next_retry_at = None
    _audit(state, "payment_recovered", message, next_contact=None)
    await save_state(state, db)
    await kill_all_tasks(state.case_id, db)
    try:
        from service.decisions import log_outcome

        await log_outcome(db, state, outcome_type="recovered", recovered_amount=amount)
    except Exception as exc:
        logger.debug("[OUTCOME] Could not append recovery outcome: %s", exc)
    return f"Case {state.case_id} marked recovered ({format_money(amount, state.currency)})."


async def _mark_dispute(db: AsyncSession, event: dict[str, Any]) -> str:
    resource = event_resource(event)
    etype = event_type(event)
    state, ids = await _find_case(db, event, active_only=False)
    dispute_id = ids.get("dispute_id") or resource.get("dispute_id") or resource.get("id")
    reason, description = extract_issue(resource, etype)

    if state is None:
        state = await parse_paypal_event(event, db)
        if state is None:
            return "Dispute event ignored: no matching case."
        state.dispute_id = dispute_id
        state.recovery_status = "escalated"
        state.next_retry_at = None
        _audit(state, "payment_dispute", f"PayPal dispute opened: {description}")
        await save_state(state, db)
        await kill_all_tasks(state.case_id, db)
        return f"Dispute case {state.case_id} created and frozen."

    state.dispute_id = dispute_id or state.dispute_id
    state.recovery_status = "escalated"
    state.next_retry_at = None
    if state.case_metadata is None:
        state.case_metadata = {}
    state.case_metadata["dispute_status"] = str(resource.get("status") or "OPEN").upper()
    _audit(state, "payment_dispute", f"PayPal dispute opened ({reason}): {description}")
    await save_state(state, db)
    await kill_all_tasks(state.case_id, db)
    try:
        from service.decisions import log_outcome

        await log_outcome(db, state, outcome_type="dispute", dispute=True, censored=True)
    except Exception as exc:
        logger.debug("[OUTCOME] Could not append dispute outcome: %s", exc)
    return f"Case {state.case_id} frozen for dispute {dispute_id}."


async def _resolve_dispute(db: AsyncSession, event: dict[str, Any]) -> str:
    resource = event_resource(event)
    state, ids = await _find_case(db, event, active_only=False)
    if state is None:
        return "Dispute resolution ignored: no matching case."

    status = str(resource.get("status") or "").upper()
    if state.case_metadata is None:
        state.case_metadata = {}
    state.case_metadata["dispute_status"] = status or "RESOLVED"
    state.dispute_id = ids.get("dispute_id") or state.dispute_id
    state.next_retry_at = None

    if status in {"RESOLVED", "CLOSED"} and state.recovery_status != "recovered":
        state.recovery_status = "in_progress"
        state.case_metadata["dispute_resolved_at"] = datetime.now().isoformat()
        _audit(state, "payment_dispute_resolved", "PayPal dispute resolved. Automated recovery resumed.")
        await save_state(state, db)
        await _enqueue_agent(state.case_id)
        return f"Case {state.case_id} resumed after dispute resolution."

    _audit(state, "payment_dispute_resolved", f"PayPal dispute update: {status or 'RESOLVED'}.")
    await save_state(state, db)
    return f"Case {state.case_id} dispute status updated."


async def _handle_approved_order(db: AsyncSession, event: dict[str, Any]) -> str:
    state, ids = await _find_case(db, event, active_only=True)
    if state is None:
        return "Order approval ignored: no active Renvue case."

    order_id = ids.get("order_id")
    state.recovery_status = "in_progress"
    state.next_retry_at = None
    _audit(state, "checkout_order_approved", "Buyer approved the PayPal order. Capturing payment.")
    await save_state(state, db)
    await kill_all_tasks(state.case_id, db)

    if not order_id:
        return f"Case {state.case_id} marked approved."

    try:
        order = await paypal_capture_order(order_id)
    except Exception as exc:
        logger.warning("[PAYPAL] Capture after approval failed for %s: %s", order_id, exc)
        try:
            from paypal.orders import get_order

            order = await get_order(order_id)
        except Exception:
            return f"Case {state.case_id} approved; capture pending."

    capture = capture_from_order(order) if isinstance(order, dict) else None
    if capture and str(capture.get("status", "")).upper() == "COMPLETED":
        return await _mark_recovered(
            db,
            state,
            capture,
            "PAYMENT.CAPTURE.COMPLETED",
            f"Buyer approved and payment captured ({capture.get('id')}).",
        )

    if str(order.get("status", "")).upper() == "COMPLETED":
        return await _mark_recovered(
            db,
            state,
            order,
            "CHECKOUT.ORDER.COMPLETED",
            "PayPal order completed after buyer approval.",
        )

    _audit(state, "capture_pending", "Buyer approved; PayPal capture is pending.")
    await save_state(state, db)
    return f"Case {state.case_id} approved; capture pending."


async def _handle_hold(db: AsyncSession, event: dict[str, Any]) -> str:
    state, _ = await _find_case(db, event, active_only=False)
    if state is None:
        return "Capture pending ignored: no matching case."
    if state.recovery_status in TERMINAL:
        return f"Case {state.case_id} is already {state.recovery_status}."
    if state.case_metadata is None:
        state.case_metadata = {}
    state.case_metadata["hold"] = True
    state.recovery_status = "pending"
    state.next_retry_at = None
    _audit(state, "capture_pending", "PayPal placed the capture on hold. Outreach paused until resolved.")
    await save_state(state, db)
    await kill_all_tasks(state.case_id, db)
    return f"Case {state.case_id} placed on hold."


async def _handle_failure(db: AsyncSession, event: dict[str, Any]) -> str:
    etype = event_type(event)
    resource = event_resource(event)
    state, ids = await _find_case(db, event, active_only=False)

    if state is not None and state.recovery_status == "recovered":
        return f"Case {state.case_id} is already recovered; failure ignored."

    if state is None:
        state = await parse_paypal_event(event, db)
        if state is None:
            return "Failure event ignored: unsupported case type."
        await save_state(state, db)
    else:
        amount, currency = extract_amount(resource, etype)
        if amount > 0:
            state.amount = amount
            state.currency = currency or state.currency
        reason, description = extract_issue(resource, etype)
        state.failure_reason = description
        state.decline_type = classify_decline(reason, description)
        state.paypal_order_id = ids.get("order_id") or state.paypal_order_id
        state.capture_id = ids.get("capture_id") or state.capture_id
        state.subscription_id = ids.get("subscription_id") or state.subscription_id
        state.invoice_id = ids.get("invoice_id") or state.invoice_id
        if etype == "BILLING.SUBSCRIPTION.SUSPENDED":
            state.case_type = "subscription_suspended"
        elif etype == "BILLING.SUBSCRIPTION.CANCELLED":
            state.case_type = "subscription_cancelled"
        _audit(
            state,
            "payment_failed",
            f"PayPal event {etype}: {description}",
        )
        await save_state(state, db)

    logger.info("[PAYPAL EVENT] Created/updated case %s for %s", state.case_id, etype)
    await _enqueue_agent(state.case_id)
    return f"Case {state.case_id} queued for recovery."


async def _enqueue_agent(case_id: str) -> None:
    try:
        await asyncio.wait_for(invoke_agent_task.kiq(case_id), timeout=3.0)
    except Exception as exc:
        logger.warning("[TASKIQ] Failed to enqueue case %s (%s); running in-process.", case_id, exc)
        asyncio.create_task(invoke_agent_task(case_id))


async def handle_paypal_event(event: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
    """Route a verified PayPal webhook event into the recovery state machine."""
    etype = event_type(event)
    resource = event_resource(event)

    if not etype:
        return {"status": "ignored", "reason": "missing event_type"}

    logger.info("[PAYPAL EVENT] %s id=%s", etype, event.get("id"))

    if etype in SUCCESS_EVENTS:
        state, _ = await _find_case(db, event, active_only=False)
        if state is None:
            return {"status": "ignored", "reason": "no matching case"}
        if state.recovery_status == "recovered":
            return {"status": "duplicate", "case_id": state.case_id}
        capture = None
        if etype == "PAYMENT.CAPTURE.COMPLETED":
            capture = resource
        elif etype == "CHECKOUT.ORDER.COMPLETED":
            capture = capture_from_order(resource)
        message = {
            "PAYMENT.CAPTURE.COMPLETED": "PayPal capture completed.",
            "CHECKOUT.ORDER.COMPLETED": "PayPal order completed.",
            "INVOICING.INVOICE.PAID": "PayPal invoice paid.",
            "BILLING.SUBSCRIPTION.ACTIVATED": "PayPal subscription active again.",
        }[etype]
        return {
            "status": await _mark_recovered(
                db, state, capture or resource, etype, message
            )
        }

    if etype == "PAYMENT.CAPTURE.PENDING":
        return {"status": await _handle_hold(db, event)}

    if etype == "CHECKOUT.ORDER.APPROVED":
        return {"status": await _handle_approved_order(db, event)}

    if etype == "CUSTOMER.DISPUTE.CREATED":
        return {"status": await _mark_dispute(db, event)}

    if etype == "CUSTOMER.DISPUTE.RESOLVED":
        return {"status": await _resolve_dispute(db, event)}

    if etype in FAILURE_EVENTS:
        if etype == "INVOICING.INVOICE.UPDATED" and not invoice_is_overdue(resource):
            state, _ = await _find_case(db, event, active_only=False)
            if state is not None:
                due = (resource.get("detail") or {}).get("payment_term") or {}
                if state.case_metadata is None:
                    state.case_metadata = {}
                state.case_metadata["due_date"] = due.get("due_date") or state.case_metadata.get("due_date")
                _audit(state, "invoice_updated", "PayPal invoice status reconciled; no recovery action required.")
                await save_state(state, db)
            return {"status": "reconciled", "reason": "invoice not overdue"}
        return {"status": await _handle_failure(db, event)}

    # Demo-only synthetic event used by the simulator to start abandoned-checkout timers.
    if etype == "CHECKOUT.ORDER.CREATED" and resource.get("id"):
        target = datetime.now() + timedelta(minutes=15)
        from background.worker import schedule_source

        if schedule_source._connection_pool is None:
            await schedule_source.startup()
        customer = extract_customer(resource)
        await abandoned_cart_timer.kicker().schedule_by_time(
            schedule_source, target, resource["id"], customer
        )
        return {"status": "abandoned cart timer scheduled", "order_id": resource["id"]}

    return {"status": "ignored", "reason": f"unhandled event {etype}"}


async def _run_agent(state: RecoveryState, message: str, event_source: str) -> None:
    agent = build_agent(state)
    config = {"configurable": {"thread_id": state.case_id}}
    await agent.ainvoke(
        {"messages": [HumanMessage(content=message)], "recovery_state": state, "event_source": event_source},
        config=config,
    )


async def handle_inbound_email(payload: dict, db: AsyncSession) -> dict:
    recipient = payload.get("to", "")
    try:
        case_id = recipient.split("+")[1].split("@")[0]
    except IndexError:
        return {"status": "ignored", "reason": "No valid case_id in recipient"}

    state = await load_state(case_id, db)
    if not state or state.recovery_status in TERMINAL:
        return {"status": "ignored", "reason": "Case not active"}

    text = payload.get("text", "")
    _audit(state, "customer_reply", text, channel="email", direction="inbound")
    await save_state(state, db)
    await _run_agent(state, f"Customer Replied via Email: {text}", "inbound.email")
    return {"status": "Agent woken up successfully"}


async def handle_inbound_whatsapp(
    from_number: str, body: str, db: AsyncSession, case_id: str | None = None
) -> dict:
    logger.info("[INBOUND WHATSAPP] Received message from %s: %s", from_number, body)

    active_case = None
    if case_id:
        active_case = await load_state(case_id, db)

    if not active_case:
        contact_number = from_number.replace("whatsapp:", "").strip()
        logger.info("[INBOUND WHATSAPP] Looking for active case for contact: %s", contact_number)

        result = await db.execute(
            select(RecoveryState)
            .where(RecoveryState.recovery_status.notin_(list(TERMINAL)))
            .order_by(RecoveryState.first_seen_at.desc())
        )
        cases = result.scalars().all()
        match_cases = []
        for case in cases:
            case_contact = (case.customer or {}).get("contact", "")
            if case_contact and (
                case_contact == contact_number
                or contact_number.endswith(case_contact[-10:])
                or case_contact.endswith(contact_number[-10:])
            ):
                match_cases.append(case)

        if not match_cases:
            logger.info("[INBOUND WHATSAPP] Ignored: no active case found for %s", contact_number)
            return {"status": "ignored", "reason": "No active case found for this number"}

        import re

        match = re.search(
            r"(?:#?RNV-|#|ticket:?\s*|ref:?\s*)([A-Za-z0-9]{4})\b", body, re.IGNORECASE
        )
        if match:
            code = match.group(1).upper()
            for candidate in match_cases:
                if candidate.case_id[-4:].upper() == code:
                    active_case = candidate
                    break

        if not active_case and body.strip() in ["1", "2", "3"]:
            idx = int(body.strip()) - 1
            if 0 <= idx < len(match_cases):
                active_case = match_cases[idx]

        if not active_case and len(match_cases) == 1:
            active_case = match_cases[0]

        if not active_case:
            options = "\n".join(
                f"{i + 1}. {format_money(c.amount, c.currency)} for {c.failure_reason or 'Order'} (Ref: #RNV-{c.case_id[-4:].upper()})"
                for i, c in enumerate(match_cases[:3])
            )
            customer_name = (match_cases[0].customer or {}).get("name", "Customer")
            prompt = (
                f"Hi {customer_name}, we found multiple pending payments on file:\n\n"
                f"{options}\n\n"
                f"Please reply with 1 or 2 to choose which payment this message is regarding."
            )
            await send_twilio_whatsapp(contact_number, prompt)
            return {"status": "disambiguation_prompt_sent", "active_cases_count": len(match_cases)}

    if body.strip().upper() == "STOP":
        logger.info("[INBOUND WHATSAPP] Customer requested STOP. Closing case %s.", active_case.case_id)
        active_case.recovery_status = "closed"
        active_case.next_retry_at = None
        if active_case.case_metadata is None:
            active_case.case_metadata = {}
        active_case.case_metadata["opt_out"] = True
        _audit(
            active_case,
            "customer_opt_out",
            "Customer sent STOP. Opt-out processed, case closed.",
            channel="whatsapp",
            direction="inbound",
        )
        await save_state(active_case, db)
        await kill_all_tasks(active_case.case_id, db)
        return {"status": "Opted out"}

    _audit(active_case, "customer_reply", body, channel="whatsapp", direction="inbound")
    await save_state(active_case, db)
    await _run_agent(
        active_case,
        f"Customer Replied via WhatsApp: {body}",
        "inbound.whatsapp",
    )
    return {"status": "Agent woken up successfully"}
