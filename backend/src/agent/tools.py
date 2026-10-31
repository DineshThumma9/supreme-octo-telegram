import asyncio
import calendar
from datetime import date, datetime, timedelta

from config.clients import (
    generate_and_send_voice_note,
    send_resend_email,
    send_twilio_whatsapp,
)
import config.db as app_db
from config.config import settings
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from models.schema import (
    CompleteCaseArgs,
    DiscountOfferArgs,
    EmailReminderArgs,
    EscalateArgs,
    PaymentLinkArgs,
    PromiseToPayArgs,
    SalaryDateArgs,
)
from service.states import load_state, save_state
from service.compliance import (
    adjust_for_contact_window,
    calculate_payday_milestones,
    build_whatsapp_payload,
    get_bell_curve_discount,
)
from service.money import format_money
from typing import Optional
from config.logger import get_logger

from agent.utils import (
    get_next_follow_up_time,
    _schedule_task,
    _log_audit,
    ensure_payment_link,
    sanity_date,
    mark_case_escalated,
)

logger = get_logger(__name__)


@tool(args_schema=EmailReminderArgs)
async def send_email_reminder(urgency: str, config: RunnableConfig) -> str:
    """
    Send a recovery email to the customer.
    Use 'gentle' for first contact, 'urgent' for 2nd attempt, 'final' before escalation.
    """
    case_id = config.get("configurable", {}).get("thread_id")
    async with app_db.AsyncSessionLocal() as db:
        state = await load_state(case_id, db)
        customer_name = state.customer.get("name", "Customer")
        customer_email = state.customer.get("email", "")
        amount = state.amount

        logger.info(f"\n  [TOOL] send_email_reminder")
        logger.info(f"    → To      : {customer_name} <{customer_email}>")
        logger.info(f"    → Amount  : {format_money(amount, state.currency)}")
        logger.info(f"    → Urgency : {urgency}")

        ref_code = state.case_id[-4:].upper() if len(state.case_id) >= 4 else state.case_id
        payment_link, _, _ = await ensure_payment_link(state, db)
        meta = state.case_metadata or {}
        amount = meta.get("effective_amount", state.amount)

        extra_ctx = {
            "invoice_number": meta.get("invoice_number", f"INV-2026-{ref_code}"),
            "link": payment_link
        }

        await send_resend_email(
            urgency, customer_name, customer_email, amount, extra_context=extra_ctx, currency=state.currency
        )

        next_contact = get_next_follow_up_time(state)
        if next_contact:
            await _schedule_task(state, next_contact, db)
        else:
            state.next_retry_at = None
            await save_state(state, db)

        if "b2b" in urgency:
            email_msg = (
                f"Corporate dunning ({urgency}): invoice {extra_ctx['invoice_number']} for "
                f"{format_money(amount, state.currency)} sent to Accounts Payable <{customer_email}>."
            )
        else:
            email_msg = (
                f"Reminder ({urgency}): payment of {format_money(amount, state.currency)} for your order "
                f"is due. Please complete payment to avoid service interruption."
            )
        await _log_audit(
            state,
            "send_email_reminder",
            next_contact,
            db,
            message=email_msg,
            channel="email",
            direction="outbound",
        )

    return f"Email ({urgency}) queued for {customer_email}"


@tool(args_schema=DiscountOfferArgs)
async def calculate_discount_offer(config: RunnableConfig = None) -> str:
    """
    Evaluates customer profile and margin policy to compute the maximum approved discount percentage.
    Call this tool dynamically when an abandoned checkout customer hesitates or asks for a discount/concession.
    Returns the approved discount percentage and discounted payable amount.
    """
    case_id = config.get("configurable", {}).get("thread_id") if config else None
    async with app_db.AsyncSessionLocal() as db:
        state = await load_state(case_id, db)
        if not state:
            return "Case state not found."

        if state.case_type != "abandoned_checkout":
            return "Policy rejection: concessions are only authorized for abandoned checkouts, not invoices or subscriptions."

        discount_pct = get_bell_curve_discount(state)
        original_amt = state.amount
        discounted_amt = round(original_amt * (1.0 - (discount_pct / 100.0)), 2)
        await save_state(state, db)

        await _log_audit(
            state,
            "calculate_discount_offer",
            None,
            db,
            message=(
                f"Deterministic margin approval: {discount_pct:.0f}% concession approved "
                f"(payable: {format_money(discounted_amt, state.currency)})."
            ),
            channel="system",
            direction="system",
        )

        return (
            f"Approved Concession: {discount_pct:.0f}% discount authorized under margin policy. "
            f"Original amount: {format_money(original_amt, state.currency)}, "
            f"discounted payable amount: {format_money(discounted_amt, state.currency)}. "
            f"Call create_payment_link(discount_pct={discount_pct:.0f}) to generate the checkout link."
        )


@tool(args_schema=PaymentLinkArgs)
async def create_payment_link(discount_pct: float = 0.0, config: RunnableConfig = None) -> str:
    """
    Create a PayPal payment, invoice, or subscription update-method link for the customer.
    Optionally accepts a discount_pct bounded by policy (e.g., between 5% and 30%).
    """
    case_id = config.get("configurable", {}).get("thread_id") if config else None
    async with app_db.AsyncSessionLocal() as db:
        state = await load_state(case_id, db)
        if not state:
            return "Error: Case state not found."
        short_url, link_type, is_subscription = await ensure_payment_link(state, db, discount_pct)
        meta = state.case_metadata or {}
        amount = meta.get("effective_amount", state.amount)
        applied_disc = meta.get("discount_pct", 0.0)

        next_contact = get_next_follow_up_time(state)
        if next_contact:
            try:
                await _schedule_task(state, next_contact, db)
            except Exception as e:
                logger.info(f"    [WARN] Failed to schedule follow-up task (non-fatal): {e}")

        disc_str = (
            f" ({applied_disc:.0f}% discount applied, payable {format_money(amount, state.currency)})"
            if applied_disc > 0
            else ""
        )
        if is_subscription:
            link_msg = (
                f"PayPal subscription update-method link generated: {short_url}"
            )
        else:
            link_msg = f"Secure PayPal payment link generated{disc_str}: {short_url}"

        await _log_audit(
            state,
            "create_payment_link",
            next_contact,
            db,
            message=link_msg,
            channel="link",
            direction="outbound",
        )

    if is_subscription:
        return f"PayPal subscription update-method link generated: {short_url}"
    return f"PayPal payment link generated: {short_url}{disc_str}"


@tool(args_schema=EscalateArgs)
async def escalate_to_human(reason: str, config: RunnableConfig) -> str:
    """
    Escalate the case to human operations when automated recovery fails.
    Requires a detailed reason and customer context.
    """
    case_id = config.get("configurable", {}).get("thread_id")
    async with app_db.AsyncSessionLocal() as db:
        state = await load_state(case_id, db)
        customer_name = state.customer.get("name", "Customer")

        logger.info(f"\n  [TOOL] escalate_to_human")
        logger.info(f"    → Customer : {customer_name}")
        logger.info(f"    → Reason   : {reason}")

        await mark_case_escalated(state, reason, db=db)

    return f"Case for {customer_name} escalated to human. Reason: {reason}"


@tool(args_schema=SalaryDateArgs)
async def get_next_payday_date(config: RunnableConfig) -> str:
    """
    Returns upcoming payday milestone dates (1st, 15th, last Friday of month).
    Use this to choose the best retry date for soft declines (insufficient funds).
    """
    case_id = config.get("configurable", {}).get("thread_id")

    async with app_db.AsyncSessionLocal() as db:
        state = await load_state(case_id, db)
        ref = state.next_retry_at.date() if (state and state.next_retry_at) else date.today()
        milestones = calculate_payday_milestones(ref)

        result = ", ".join(str(d) for d in milestones)
        closest = milestones[0]
        target_time = datetime.combine(closest, datetime.min.time()) + timedelta(
            hours=10
        )  # 10 AM

        try:
            await _schedule_task(state, target_time, db)
        except Exception as e:
            logger.info(f"    [WARN] Failed to schedule follow-up task (non-fatal): {e}")

        payday_msg = f"Upcoming payday dates: {result}. Auto-scheduled next follow-up for {target_time.strftime('%b %d, %Y')}."
        await _log_audit(
            state,
            "get_next_payday_date",
            target_time,
            db,
            message=payday_msg,
            channel="system",
            direction="system",
        )

    logger.info(f"\n  [TOOL] get_next_payday_date")
    logger.info(f"    → Upcoming milestones: {result}. Scheduled retry for {target_time}.")

    return result


@tool(args_schema=CompleteCaseArgs)
async def complete_case(summary: str, config: RunnableConfig) -> str:
    """
    Call this tool when you have finished taking all necessary actions for this case.
    This tells the system to stop the workflow and move to the audit phase.
    """
    case_id = config.get("configurable", {}).get("thread_id")
    if case_id:
        async with app_db.AsyncSessionLocal() as db:
            state = await load_state(case_id, db)
            if state:
                state.recovery_status = "closed"
                await _log_audit(
                    state,
                    "complete_case",
                    None,
                    db,
                    message=f"Case closed: {summary}",
                    channel="system",
                    direction="system",
                )
    logger.info(f"[TOOL] complete_case: {summary}")
    return "Case workflow completed."


@tool
async def send_whatsapp_msg(msg: str, config: RunnableConfig):
    """
    Sends a WhatsApp message to the customer using Twilio.
    msg is the content of the message. Automatically hydrates payment links if referenced.
    """
    case_id = config.get("configurable", {}).get("thread_id")
    async with app_db.AsyncSessionLocal() as db:
        state = await load_state(case_id, db)
        if not state:
            return "Failed: Case state not found."
        contact_number = state.customer.get("contact", "")

        if not contact_number:
            return "Failed: Customer has no contact number."

        # Link Hydration (Issue #4): Ensure real payment link is injected instead of ghost link
        payment_link = (state.case_metadata or {}).get("payment_link")
        needs_link = "{payment_link}" in msg or any(
            k in msg.lower() for k in ["link", "tap", "click", "pay", "settle", "checkout", "portal", "retry"]
        )

        if not payment_link and needs_link:
            # Brief yield in case create_payment_link is running concurrently in the same tool batch
            await asyncio.sleep(0.3)
            reloaded = await load_state(case_id, db)
            if reloaded:
                state = reloaded
            payment_link, _, _ = await ensure_payment_link(state, db)

        # Hydrate message text with the payment link
        if payment_link:
            if "{payment_link}" in msg:
                msg = msg.replace("{payment_link}", payment_link)
            elif payment_link not in msg and "http://" not in msg and "https://" not in msg:
                is_recovery_msg = any(
                    k in msg.lower()
                    for k in ["link", "tap", "click", "pay", "settle", "checkout", "portal", "retry", "order", "invoice", "balance", "subscription"]
                )
                if is_recovery_msg:
                    if "(Ref:" in msg:
                        prefix, ref_part = msg.rsplit("(Ref:", 1)
                        msg = f"{prefix.strip()}\n\n🔗 Pay securely: {payment_link}\n\n(Ref:{ref_part}"
                    else:
                        msg = f"{msg.strip()}\n\n🔗 Pay securely: {payment_link}"
        
        # Meta WhatsApp HSM Utility Compliance (Issue #15)
        whatsapp_payload = build_whatsapp_payload(state, msg, payment_link=payment_link)
        outbound_text = whatsapp_payload["body"]
        
        sid = await send_twilio_whatsapp(contact_number, outbound_text)
        logger.info(f"Message dispatched successfully! SID: {sid} (Compliance: {whatsapp_payload.get('meta_compliance')})")

        next_contact = get_next_follow_up_time(state)
        if next_contact:
            try:
                await _schedule_task(state, next_contact, db)
            except Exception as e:
                logger.warning(f"[WARN] Failed to schedule follow-up task (non-fatal): {e}")
        else:
            state.next_retry_at = None
            await save_state(state, db)

        await _log_audit(
            state,
            "send_whatsapp_msg",
            next_contact,
            db,
            message=outbound_text,
            channel="whatsapp",
            direction="outbound",
            meta_compliance=whatsapp_payload.get("meta_compliance"),
            hsm_template=whatsapp_payload.get("template_name"),
        )

    return f"WhatsApp sent to {contact_number}. SID: {sid}"


@tool
async def get_voice_call(msg: str, config: RunnableConfig):
    """
    Initiates an AI voice call using ElevenLabs to the customer, and sends it as a WhatsApp voice note.
    msg is the text to speak.
    """
    case_id = config.get("configurable", {}).get("thread_id")
    async with app_db.AsyncSessionLocal() as db:
        state = await load_state(case_id, db)
        contact_number = state.customer.get("contact", "")

        if not contact_number:
            return "Failed: Customer has no contact number."

        sid = await generate_and_send_voice_note(contact_number, msg)

        next_contact = get_next_follow_up_time(state)
        if next_contact:
            try:
                await _schedule_task(state, next_contact, db)
            except Exception as e:
                logger.warning(f"[WARN] Failed to schedule follow-up task (non-fatal): {e}")
        else:
            state.next_retry_at = None
            await save_state(state, db)

        await _log_audit(
            state,
            "get_voice_call",
            next_contact,
            db,
            message=f"Voice note dispatched: {msg}",
            channel="voice",
            direction="outbound",
        )

    return f"Voice note dispatched successfully to {contact_number}! SID: {sid}"


@tool(args_schema=PromiseToPayArgs)
async def log_promise_to_pay(
    reason: str = "Customer commitment regarding payment",
    sentiment: str = "neutral",
    date_str: Optional[str] = None,
    config: RunnableConfig = None
):
    """
    Call this tool when a customer replies via email or WhatsApp regarding payment.
    - If customer committed to a specific date: validates date (not in past, not exceeding cumulative grace period),
      schedules business-hours reminder, or escalates if invalid/hostile/grace-exceeded.
    - If customer did not provide a concrete date (or date_str is None/unresolvable): schedules standard follow-up
      cadence (+3 days from now) WITHOUT escalating to human operations.
    """
    case_id = config.get("configurable", {}).get("thread_id")
    async with app_db.AsyncSessionLocal() as db:
        state = await load_state(case_id, db)
        if not state:
            return "Error: Case state not found."

        # Stopping rule: If already reached 3 attempts, reject automated promise and escalate
        if getattr(state, "attempt_count", 0) >= 3:
            rej_reason = f"Max attempts ({state.attempt_count}) reached. Cannot accept automated promise without human approval."
            logger.warning(f"[PTP REJECTED] {rej_reason} for case {state.case_id}")
            await mark_case_escalated(state, rej_reason, db=db)
            return f"PROMISE_REJECTED: {rej_reason}. Case has been escalated to human operations."

        now = datetime.now()
        today = now.date()

        # Check hostility immediately
        is_hostile = sentiment.lower() in ["explicit", "threat", "danger", "angry", "hostile", "abusive"]
        if is_hostile:
            rej_reason = f"Customer sentiment is hostile ('{sentiment}')"
            logger.warning(f"[PTP REJECTED] {rej_reason} for case {state.case_id}")
            await mark_case_escalated(state, rej_reason, db=db)
            return f"PROMISE_REJECTED: {rej_reason}. Case has been escalated to human operations."

        if state.case_metadata is None:
            state.case_metadata = {}

        # Establish anchor date from initial failure/incident
        if "initial_failure_date" not in state.case_metadata:
            state.case_metadata["initial_failure_date"] = (
                state.first_seen_at.date().isoformat() if state.first_seen_at else today.isoformat()
            )
        try:
            anchor_date = datetime.fromisoformat(state.case_metadata["initial_failure_date"]).date()
        except Exception:
            anchor_date = state.first_seen_at.date() if state.first_seen_at else today

        # Case 1: No concrete date provided (or set to None / empty) -> standard follow-up (+3 days), NO escalation
        if not date_str or str(date_str).strip().lower() in ("none", "null", ""):
            from datetime import time as dt_time
            follow_up_time = datetime.combine((now + timedelta(days=3)).date(), dt_time(10, 0))
            await _schedule_task(state, follow_up_time, db)
            
            note_msg = f"Customer reply noted without specific commitment date: '{reason}'. Standard follow-up scheduled for {follow_up_time.strftime('%b %d, %Y')} (+3 days)."
            await _log_audit(
                state,
                "log_customer_reply",
                follow_up_time,
                db,
                message=note_msg,
                channel="system",
                direction="system",
            )
            return (
                f"Customer reply recorded. No concrete commitment date specified; "
                f"standard follow-up scheduled for {follow_up_time.strftime('%Y-%m-%d')} (+3 days). "
                f"Automated recovery remains active."
            )

        # Case 2: Date provided -> Parse supporting ISO, common formats, or dateutil fuzzy parse
        clean_date_str = str(date_str).strip()
        target_date = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                target_date = datetime.strptime(clean_date_str[:19], fmt)
                break
            except ValueError:
                continue
        if not target_date:
            # Ambiguous or unparseable date -> do not escalate! Follow up as usual (+3 days)
            from datetime import time as dt_time
            follow_up_time = datetime.combine((now + timedelta(days=3)).date(), dt_time(10, 0))
            await _schedule_task(state, follow_up_time, db)
            note_msg = f"Customer reply noted with unparseable date '{date_str}' ('{reason}'). Standard follow-up scheduled for {follow_up_time.strftime('%b %d, %Y')} (+3 days)."
            await _log_audit(
                state,
                "log_customer_reply",
                follow_up_time,
                db,
                message=note_msg,
                channel="system",
                direction="system",
            )
            return (
                f"Could not parse commitment date '{date_str}'. "
                f"Standard follow-up scheduled for {follow_up_time.strftime('%Y-%m-%d')} (+3 days). "
                f"Automated recovery remains active."
            )

        # Case 3: Concrete date parsed -> Validate against past date and cumulative grace limit
        is_valid, reject_reason = sanity_date(target_date, anchor_date=anchor_date)

        if not is_valid:
            logger.warning(f"[PTP REJECTED] {reject_reason} for case {state.case_id}")
            await mark_case_escalated(state, reject_reason, db=db)
            return (
                f"PROMISE_REJECTED: {reject_reason}. "
                f"Case has been escalated to human operations."
            )

        # Timing adjustments: Snap to business hours (10:00 AM), avoiding midnight
        from datetime import time as dt_time
        if target_date.date() > today:
            target_date = datetime.combine(target_date.date(), dt_time(10, 0))
        elif target_date.date() == today:
            target_date = datetime.combine(today, dt_time(18, 0))
            if target_date <= now:
                target_date = now + timedelta(hours=2)

        # Track cumulative grace period used
        grace_days_from_incident = (target_date.date() - anchor_date).days
        state.case_metadata["ptp_date"] = target_date.strftime("%Y-%m-%d")
        state.case_metadata["cumulative_grace_days_used"] = grace_days_from_incident
        state.case_metadata["remaining_grace_days"] = max(0, settings.max_grace_period - grace_days_from_incident)

        ptp_history = state.case_metadata.get("ptp_history", [])
        ptp_history.append({
            "promised_date": target_date.strftime("%Y-%m-%d"),
            "recorded_at": now.isoformat(),
            "grace_days_used": grace_days_from_incident,
            "reason": reason
        })
        state.case_metadata["ptp_history"] = ptp_history

        await _schedule_task(state, target_date, db)

        confirm_msg = f"Thank you! We have noted your promise to pay on {target_date.strftime('%Y-%m-%d')}. Automated reminders are paused until then."
        contact_number = state.customer.get("contact", "")
        if contact_number:
            await send_twilio_whatsapp(contact_number, confirm_msg)

        ptp_msg = f"Promise to pay recorded for {target_date.strftime('%b %d, %Y')} ({grace_days_from_incident}/{settings.max_grace_period} cumulative grace days used). Confirmation sent to customer."
        await _log_audit(
            state,
            "log_promise_to_pay",
            target_date,
            db,
            message=ptp_msg,
            channel="system",
            direction="system",
        )

    return f"Successfully logged promise to pay on {target_date.strftime('%Y-%m-%d')} ({grace_days_from_incident}/{settings.max_grace_period} grace days used). Confirmation message sent to customer."


tools = [
    send_email_reminder,
    create_payment_link,
    calculate_discount_offer,
    escalate_to_human,
    get_next_payday_date,
    complete_case,
    get_voice_call,
    send_whatsapp_msg,
    log_promise_to_pay,
]
