import asyncio
from datetime import date, datetime, timedelta
from typing import Optional

from langchain_core.messages import SystemMessage
from langchain_mistralai import ChatMistralAI
from sqlalchemy.ext.asyncio import AsyncSession

from agent.prompts import get_escalation_tone, should_send_channel
from config.clients import (
    create_paypal_invoice_link,
    create_paypal_mandate_update_link,
    create_paypal_payment_link,
    generate_and_send_voice_note,
    get_redis_client,
    send_resend_email,
    send_resend_email_result,
    send_twilio_whatsapp,
    twilio_delivery_status,
)
from config.config import settings
from config.db import AsyncSessionLocal
from config.logger import get_logger
from models.models import RecoveryState
from models.schema import AuditEntry
from policy.baseline import eligible_plays, observation_from_state
from policy.guardrails import apply_guardrails
from policy.interfaces import Action, Play
from ml.runtime import decide as decide_policy
from service.broadcast import broadcast_case_update
from service.compliance import (
    adjust_for_contact_window,
    build_whatsapp_payload,
    get_bell_curve_discount,
    is_subscription_case,
)
from service.decisions import (
    log_action,
    log_decision,
    log_outcome,
    log_unresponsive_timeout,
)
from service.money import format_money, format_state_amount
from service.states import save_state

import httpx
from langchain_groq import ChatGroq
from langchain_huggingface import ChatHuggingFace
from langchain_mistralai import ChatMistralAI
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openrouter import ChatOpenRouter


logger = get_logger(__name__)

_llm_instance = None
_llm_with_tools = None

def _ollama_headers() -> dict[str, str]:
    if settings.ollama_api_key:
        return {"Authorization": f"Bearer {settings.ollama_api_key}"}
    return {}



models = {
    "groq": lambda model_name: ChatGroq(
        model=model_name or settings.groq_model or "llama-3.3-70b-versatile",
        groq_api_key=settings.groq_api_key,
        timeout=settings.llm_timeout,
        max_tokens=settings.llm_max_tokens,
    ),
    "ollama": lambda model_name: ChatOllama(
        model=model_name or settings.ollama_model or "beam:cloud",
        base_url=settings.ollama_base_url,
        num_predict=settings.llm_max_tokens,
        timeout=settings.llm_timeout,
        sync_client_kwargs={
            "headers": _ollama_headers(),
            "transport": httpx.HTTPTransport(retries=3),
        },
        async_client_kwargs={
            "headers": _ollama_headers(),
            "transport": httpx.AsyncHTTPTransport(retries=3),
        },
    ),
    "mistral": lambda model_name: ChatMistralAI(
        model=model_name or settings.mistral_model or settings.model or "mistral-small-latest",
        mistral_api_key=settings.mistral_api_key,
        timeout=settings.llm_timeout,
        max_tokens=settings.llm_max_tokens,
    ),
    "gemini": lambda model_name: ChatGoogleGenerativeAI(
        model=model_name or settings.gemini_model or "gemini-1.5-flash",
        google_api_key=settings.gemini_api_key or settings.google_api_key,
    ),
    "openrouter": lambda model_name: ChatOpenRouter(
        model=model_name or settings.openrouter_model,
        api_key=settings.openrouter_api_key,
    ),
    "huggingface": lambda model_name: ChatHuggingFace(
        model_name=model_name or settings.huggingface_model,
    ),
}


def get_llm(tools=None):
    """Return the singleton tool-bound Chat instance."""
    global _llm_instance, _llm_with_tools
    if _llm_with_tools is None:
        if tools is None:
            from agent.tools import tools as agent_tools

            tools = agent_tools
        provider = (settings.llm_provider or "mistral").lower()
        factory = models.get(provider, models["mistral"])
        _llm_instance = factory(settings.model)
        _llm_with_tools = _llm_instance.bind_tools(tools)
    return _llm_with_tools


def get_next_follow_up_time(state: RecoveryState) -> Optional[datetime]:
    """Progressive follow-up milestone, snapped to the outreach window."""
    attempt = getattr(state, "attempt_count", 0)
    if attempt >= 3:
        return None

    now = datetime.now()
    base_dt = state.next_retry_at if state.next_retry_at and state.next_retry_at > now else now
    target = (base_dt + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
    return adjust_for_contact_window(target)


async def _schedule_task(state: RecoveryState, target_date: datetime, db: AsyncSession):
    from background.worker import invoke_agent_task, revoke_active_task, schedule_source

    if state.active_task_id:
        await revoke_active_task(state.active_task_id)

    now = datetime.now()
    if target_date <= now:
        target_date = now + timedelta(minutes=1)

    logger.info("  [SCHEDULE] case=%s next_retry_at=%s", state.case_id, target_date.isoformat())

    try:
        if schedule_source._connection_pool is None:
            await schedule_source.startup()

        created = await invoke_agent_task.kicker().schedule_by_time(
            schedule_source,
            target_date,
            state.case_id,
        )
        state.active_task_id = created.schedule_id
    except Exception as exc:
        # Local tests and demos may run without Redis. Persist the due time so
        # the UI and reconciliation loop still see the schedule.
        logger.warning("[SCHEDULE] Taskiq unavailable (%s); persisting next_retry_at only.", exc)
        state.active_task_id = None

    state.next_retry_at = target_date
    await save_state(state, db)
    logger.info(
        "  [SCHEDULE] saved next_retry_at=%s (task=%s)",
        state.next_retry_at,
        state.active_task_id,
    )


async def _log_audit(
    state: RecoveryState,
    tool_name: str,
    next_retry_at: datetime | None,
    db: AsyncSession,
    message: str | None = None,
    channel: str | None = None,
    direction: str | None = None,
    meta_compliance: str | None = None,
    hsm_template: str | None = None,
    delivery_status: str | None = None,
):
    entry = AuditEntry(
        event_triggered=tool_name,
        amount=format_state_amount(state),
        recovery_status=state.recovery_status,
        customer=state.customer,
        next_contact=next_retry_at,
        message=message,
        channel=channel,
        direction=direction,
        meta_compliance=meta_compliance,
        hsm_template=hsm_template,
        delivery_status=delivery_status,
        created_at=datetime.now(),
    )
    state.audit_log.append(entry.model_dump(mode="json"))
    logger.info(
        "  [LOG_AUDIT] tool=%s next_retry_at_param=%s message=%s",
        tool_name,
        next_retry_at,
        message,
    )
    if tool_name in ["escalate_to_human", "complete_case"]:
        state.next_retry_at = None
    if tool_name in [
        "send_whatsapp_msg",
        "send_email_reminder",
        "get_voice_call",
        "escalate_to_human",
    ] or tool_name.startswith("play_"):
        state.last_action_taken = tool_name
    await save_state(state, db)
    logger.info("  [LOG_AUDIT] save_state done for case=%s", state.case_id)


async def _generate_link_for_state(
    state: RecoveryState,
    customer_name: str,
    customer_email: str,
    contact_number: str,
    amount: float,
) -> tuple[str, str, bool]:
    """Return (url, link_type, is_subscription) for the case's PayPal rail."""
    if is_subscription_case(state):
        link = await create_paypal_mandate_update_link(state)
        return link, "update_method_link", True
    if state.case_type == "overdue_invoice":
        link = await create_paypal_invoice_link(state, amount=amount, currency=state.currency)
        return link, "paypal_invoice", False
    link = await create_paypal_payment_link(
        state, amount=amount, currency=state.currency
    )
    return link, "one_time_payment", False


async def ensure_payment_link(
    state: RecoveryState, db: AsyncSession, discount_pct: float = 0.0
) -> tuple[str, str, bool]:
    """Hydrate or reuse the case's PayPal payment / invoice / method link."""
    meta = state.case_metadata or {}
    payment_link = meta.get("payment_link")
    link_type = meta.get("link_type", "one_time_payment")
    is_sub = bool(meta.get("update_method")) or is_subscription_case(state)

    eligible_checkout_discount = (
        get_bell_curve_discount(state) if state.case_type == "abandoned_checkout" else 0.0
    )
    existing_discount = float(meta.get("discount_pct") or 0.0)
    needs_checkout_discount = (
        eligible_checkout_discount > 0 and existing_discount != eligible_checkout_discount
    )

    if payment_link and not needs_checkout_discount and (
        discount_pct <= 0.0 or existing_discount == discount_pct
    ):
        if state.case_metadata is None:
            state.case_metadata = {}
        state.case_metadata.setdefault("payment_link_is_mock", "MOCK" in payment_link)
        return payment_link, link_type, is_sub

    customer_name = state.customer.get("name", "Customer")
    customer_email = state.customer.get("email", "")
    customer_contact = state.customer.get("contact", "")
    base_amount = float(state.amount or 0.0)

    if state.case_type == "abandoned_checkout":
        eligible = get_bell_curve_discount(state)
        discount_pct = eligible if discount_pct <= 0.0 else min(discount_pct, eligible)
        amount = round(base_amount * (1.0 - (discount_pct / 100.0)), 2)
    else:
        discount_pct = 0.0
        amount = base_amount

    try:
        payment_link, link_type, is_sub = await _generate_link_for_state(
            state, customer_name, customer_email, customer_contact, amount
        )
        if state.case_metadata is None:
            state.case_metadata = {}
        state.case_metadata["payment_link"] = payment_link
        state.case_metadata["payment_link_is_mock"] = "MOCK" in payment_link
        state.case_metadata["link_type"] = link_type
        if is_sub:
            state.case_metadata["update_method"] = True
        if discount_pct > 0:
            state.case_metadata["discount_pct"] = discount_pct
            state.case_metadata["eligible_discount"] = discount_pct
            state.case_metadata["effective_amount"] = amount
        await save_state(state, db)
    except Exception as exc:
        if not settings.demo_mode:
            logger.error(
                "Could not generate PayPal link for case %s: %s", state.case_id, exc
            )
            raise
        ref_code = state.case_id[-4:].upper() if len(state.case_id) >= 4 else state.case_id
        logger.critical("Could not generate PayPal link, using mock fallback: %s", exc)
        payment_link = f"https://www.sandbox.paypal.com/checkoutnow?token=MOCK-{ref_code}"
        link_type = "one_time_payment"
        is_sub = False
        if state.case_metadata is None:
            state.case_metadata = {}
        state.case_metadata["payment_link"] = payment_link
        state.case_metadata["payment_link_is_mock"] = True
        state.case_metadata["link_type"] = link_type
        await save_state(state, db)

    return payment_link, link_type, is_sub


def sanity_date(d: datetime | None, anchor_date: date | datetime | None = None) -> tuple[bool, str]:
    """Validate a promise-to-pay date against the grace policy."""
    if not d:
        return False, "Promise date could not be parsed or was not provided"
    if d.tzinfo is not None:
        d = d.replace(tzinfo=None)
    now = datetime.now()
    today = now.date()
    target_date = d.date()

    if target_date < today:
        return False, (
            f"Date {target_date.strftime('%Y-%m-%d')} is in the past "
            f"(today is {today.strftime('%Y-%m-%d')})"
        )

    if anchor_date is not None:
        incident_date = anchor_date.date() if isinstance(anchor_date, datetime) else anchor_date
        max_cumulative_allowed = incident_date + timedelta(days=settings.max_grace_period)
        if target_date > max_cumulative_allowed:
            total_days = (target_date - incident_date).days
            return False, (
                f"Date {target_date.strftime('%Y-%m-%d')} is {total_days} days after the initial "
                f"failure incident ({incident_date.strftime('%Y-%m-%d')}), which exceeds the "
                f"cumulative policy grace period limit of {settings.max_grace_period} days"
            )

    max_allowed = today + timedelta(days=settings.max_grace_period)
    if target_date > max_allowed:
        days_out = (target_date - today).days
        return False, (
            f"Date {target_date.strftime('%Y-%m-%d')} is {days_out} days in the future, "
            f"exceeding the maximum policy grace period of {settings.max_grace_period} days"
        )

    return True, "Valid"


def cant_resolve(rs: RecoveryState) -> tuple[bool, str]:
    """Return True only for genuinely terminal failure reasons."""
    details = rs.error_details or {}
    text = " ".join(
        str(details.get(key) or "")
        for key in ("issue", "reason", "description", "error_description")
    ).lower()

    terminal_markers = ("fraud", "stolen", "account_closed", "buyer_cannot_pay", "restricted")
    if any(marker in text for marker in terminal_markers):
        return True, (
            "PayPal blocked this payment for a security or account reason. "
            "The customer needs to use a different payment method or contact PayPal."
        )
    return False, ""


async def mark_case_escalated(rs: RecoveryState, reason: str, db: AsyncSession | None = None):
    """Persist escalation, cancel pending work, log, and broadcast."""
    rs.recovery_status = "escalated"
    rs.last_action_taken = "escalate_to_human"
    rs.next_retry_at = None
    if rs.attempt_count and rs.attempt_count > 3:
        rs.attempt_count = 3

    async def _execute_escalation(session: AsyncSession):
        if getattr(rs, "active_task_id", None):
            try:
                from background.worker import revoke_active_task

                await revoke_active_task(rs.active_task_id)
                rs.active_task_id = None
            except Exception as exc:
                logger.warning("[HIL] Could not revoke task: %s", exc)

        await _log_audit(
            rs,
            "escalate_to_human",
            None,
            session,
            message=f"Escalated to human ops: {reason}",
            channel="system",
            direction="internal",
        )
        try:
            await log_outcome(
                session, rs, outcome_type="escalated", censored=True, dispute=bool(rs.dispute_id)
            )
        except Exception as exc:
            logger.debug("[OUTCOME] Could not append escalation outcome: %s", exc)
        await save_state(rs, session)

    if db is not None:
        await _execute_escalation(db)
    else:
        async with AsyncSessionLocal() as session:
            await _execute_escalation(session)

    try:
        await broadcast_case_update(rs)
    except Exception as exc:
        logger.warning("[HIL] Could not broadcast escalation: %s", exc)


def _set_last_touch(
    rs: RecoveryState,
    play: Play,
    attempt: int,
    channel: str,
    status: str,
) -> None:
    """Remember the last real delivery for timeout attribution."""
    meta = rs.case_metadata or {}
    touch = meta.get("last_touch") or {}

    if touch.get("attempt") != attempt:
        touch = {
            "play": play.value,
            "attempt": attempt,
            "channels": [],
            "status": "failed",
            "at": datetime.now().isoformat(),
        }

    if channel and channel not in touch["channels"]:
        touch["channels"].append(channel)

    if status in {"sent", "captured"}:
        touch["status"] = status
        touch["delivery_status"] = status
    elif touch.get("status") not in {"sent", "captured"}:
        touch["status"] = status

    meta["last_touch"] = touch
    rs.case_metadata = meta


def _play_channel(play: Play) -> str:
    return {
        Play.EMAIL_LINK: "email",
        Play.SMS_LINK: "whatsapp",
        Play.PAYPAL_INVOICE_REMINDER: "email",
        Play.RETRY_NOW: "link",
        Play.RETRY_PAYDAY: "link",
        Play.UPDATE_METHOD_LINK: "link",
        Play.DISCOUNT_LINK: "link",
        Play.HUMAN_ESCALATION: "system",
        Play.NO_CONTACT: "system",
    }.get(play, "system")


async def execute_deterministic_recovery(rs: RecoveryState, event_source: str) -> RecoveryState:
    """Policy proposes, guardrails dispose, the executor runs exactly one Play."""
    if rs.recovery_status in ["recovered", "closed", "escalated"]:
        logger.info(
            "[ROUTER] Case %s is terminal (%s). Aborting automated dunning.",
            rs.case_id,
            rs.recovery_status,
        )
        return rs

    try:
        async with AsyncSessionLocal() as timeout_db:
            await log_unresponsive_timeout(timeout_db, rs)
    except Exception as exc:
        logger.warning("[LEARNING] timeout capture failed: %s", exc)

    obs = observation_from_state(rs)

    learned = {}
    try:
        from ml.learning import load_learned_rates

        learned = await load_learned_rates(provenance="live", source="outcome")
    except Exception as exc:
        logger.warning("[LEARNING] learned rates unavailable; using model prior: %s", exc)

    decision = decide_policy(rs, obs, learned=learned)
    proposed = decision.action
    guard = apply_guardrails(rs, obs, proposed)
    approved = guard.action
    decision_id = None

    async with AsyncSessionLocal() as db:
        try:
            decision_id = await log_decision(
                db,
                rs,
                obs,
                proposed,
                approved,
                guard.result,
                eligible_plays(obs),
                alternatives=decision.alternatives,
                p_pay=decision.p_pay,
                expected_recovered=decision.expected_recovered,
                expected_cost=decision.expected_cost,
                expected_net=decision.expected_net,
                policy_version=decision.policy_version,
                model_version=decision.model_version,
                exploration=decision.exploration,
            )
        except Exception as exc:
            logger.warning("[DECISION] Could not persist decision log: %s", exc)

        if guard.result == "defer":
            target = approved.scheduled_for or adjust_for_contact_window(datetime.now() + timedelta(hours=1))
            rs.next_retry_at = target
            await _schedule_task(rs, target, db)
            await _log_audit(
                rs,
                "contact_window_deferred",
                target,
                db,
                message=(
                    f"Outreach deferred to the permitted contact window "
                    f"({target.strftime('%d %b %I:%M %p')})."
                ),
                channel="system",
                direction="system",
            )
            await log_action(
                db, rs, decision_id, approved, "system", status="scheduled"
            )
            rs.last_action_taken = "contact_window_deferred"
            await save_state(rs, db)
            await broadcast_case_update(rs)
            return rs

        if approved.play == Play.NO_CONTACT:
            await log_action(db, rs, decision_id, approved, "system", status="skipped")
            rs.last_action_taken = "no_contact"
            await save_state(rs, db)
            await broadcast_case_update(rs)
            return rs

        if approved.play == Play.HUMAN_ESCALATION:
            reason = f"Policy selected human escalation ({guard.rule})"
            await log_action(db, rs, decision_id, approved, "system", status="executed")
            await mark_case_escalated(rs, reason, db=db)
            return rs

        # Terminal hard-decline safeguard remains deterministic.
        unresolvable, decline_reason = cant_resolve(rs)
        if unresolvable:
            await log_action(db, rs, decision_id, approved, "system", status="blocked")
            await mark_case_escalated(rs, f"Unresolvable decline: {decline_reason}", db=db)
            return rs

        payment_link, link_type, is_sub = await ensure_payment_link(
            rs, db, discount_pct=approved.discount_pct
        )

        current_attempt = min(3, (rs.attempt_count or 0) + 1)
        wa_text, email_urgency, voice_text = get_escalation_tone(rs, attempt=current_attempt)
        if payment_link:
            if "{payment_link}" in wa_text:
                wa_text = wa_text.replace("{payment_link}", payment_link)
            elif payment_link not in wa_text:
                if "(Ref:" in wa_text:
                    prefix, ref_part = wa_text.rsplit("(Ref:", 1)
                    wa_text = f"{prefix.strip()} {payment_link} (Ref:{ref_part}"
                else:
                    wa_text = f"{wa_text.strip()} {payment_link}"
            voice_text = voice_text.replace("{payment_link}", payment_link)

        whatsapp_payload = build_whatsapp_payload(rs, wa_text, payment_link=payment_link)
        final_wa_body = whatsapp_payload["body"]
        dispatched_channel = None

        async def send_email() -> bool:
            nonlocal dispatched_channel
            if not rs.customer.get("email"):
                return False
            email_amount = (rs.case_metadata or {}).get("effective_amount", rs.amount)
            ok, delivery_status = await send_resend_email_result(
                email_urgency,
                rs.customer.get("name", "Customer"),
                rs.customer["email"],
                email_amount,
                extra_context={
                    "invoice_number": (rs.case_metadata or {}).get(
                        "invoice_number", f"INV-{rs.case_id[-4:].upper()}"
                    ),
                    "link": payment_link,
                },
                currency=rs.currency or "USD",
            )
            if ok:
                await _log_audit(
                    rs,
                    "send_email_reminder",
                    None,
                    db,
                    message=f"Sent {email_urgency} recovery email with PayPal link {payment_link}",
                    channel="email",
                    direction="outbound",
                    delivery_status=delivery_status,
                )
                _set_last_touch(rs, approved.play, current_attempt, "email", delivery_status)
                dispatched_channel = "send_email_reminder"
            else:
                await _log_audit(
                    rs,
                    "outreach_failed",
                    None,
                    db,
                    message=(
                        f"Email delivery failed for {rs.customer['email']} "
                        f"({email_urgency}). Trying the next available channel."
                    ),
                    channel="email",
                    direction="system",
                    delivery_status="failed",
                )
                _set_last_touch(rs, approved.play, current_attempt, "email", "failed")
            return ok

        async def send_whatsapp() -> bool:
            nonlocal dispatched_channel
            if not rs.customer.get("contact"):
                return False
            sid = await send_twilio_whatsapp(rs.customer["contact"], final_wa_body)
            delivery_status = twilio_delivery_status(sid)
            if delivery_status == "failed":
                await _log_audit(
                    rs,
                    "outreach_failed",
                    None,
                    db,
                    message=f"WhatsApp delivery failed to {rs.customer['contact']}: {sid}",
                    channel="whatsapp",
                    direction="system",
                    delivery_status="failed",
                )
                _set_last_touch(rs, approved.play, current_attempt, "whatsapp", "failed")
                return False
            await _log_audit(
                rs,
                "send_whatsapp_msg",
                None,
                db,
                message=final_wa_body,
                channel="whatsapp",
                direction="outbound",
                meta_compliance=whatsapp_payload.get("meta_compliance"),
                hsm_template=whatsapp_payload.get("template_name"),
                delivery_status=delivery_status,
            )
            _set_last_touch(rs, approved.play, current_attempt, "whatsapp", delivery_status)
            dispatched_channel = "send_whatsapp_msg"
            return True

        if approved.play == Play.EMAIL_LINK:
            if not await send_email():
                await send_whatsapp()
        elif approved.play == Play.SMS_LINK:
            if not await send_whatsapp():
                await send_email()
        elif approved.play == Play.PAYPAL_INVOICE_REMINDER:
            if not await send_email():
                await send_whatsapp()
            if rs.invoice_id:
                try:
                    from paypal.invoicing import remind_invoice

                    await remind_invoice(rs, rs.invoice_id)
                    _set_last_touch(rs, approved.play, current_attempt, "paypal", "sent")
                except Exception as exc:
                    logger.warning("[PAYPAL] Invoice reminder failed: %s", exc)
        elif approved.play in (Play.UPDATE_METHOD_LINK, Play.DISCOUNT_LINK):
            if not await send_email():
                await send_whatsapp()
        else:  # RETRY_NOW / RETRY_PAYDAY: multi-channel retry
            attempted = set()
            if should_send_channel(rs, "whatsapp") and rs.customer.get("contact"):
                attempted.add("whatsapp")
                await send_whatsapp()
            if should_send_channel(rs, "email") and rs.customer.get("email"):
                attempted.add("email")
                await send_email()
            if not dispatched_channel:
                # Preferred channel unavailable or failed; try the other real channel.
                if rs.customer.get("contact") and "whatsapp" not in attempted:
                    await send_whatsapp()
                elif rs.customer.get("email") and "email" not in attempted:
                    await send_email()
            if (
                should_send_channel(rs, "voice")
                and rs.customer.get("contact")
                and (rs.attempt_count or 0) >= 1
            ):
                await generate_and_send_voice_note(rs.customer["contact"], voice_text)
                await _log_audit(
                    rs,
                    "get_voice_call",
                    None,
                    db,
                    message=f"Voice note dispatched: {voice_text}",
                    channel="voice",
                    direction="outbound",
                )
                _set_last_touch(rs, approved.play, current_attempt, "voice", "sent")
                dispatched_channel = dispatched_channel or "get_voice_call"

        if not dispatched_channel:
            # The link is still a real recovery action even if the customer has
            # no usable channel; keep it in metadata and record the Play.
            dispatched_channel = f"play_{approved.play.value}"
            _set_last_touch(rs, approved.play, current_attempt, "link", "unverified")

        rs.attempt_count = min(3, (rs.attempt_count or 0) + 1)
        rs.last_action_taken = f"play_{approved.play.value}"

        if rs.attempt_count >= 3:
            base_dt = (
                rs.next_retry_at
                if rs.next_retry_at and rs.next_retry_at > datetime.now()
                else datetime.now()
            )
            final_grace = adjust_for_contact_window(
                (base_dt + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
            )
            await _schedule_task(rs, final_grace, db)
            rs.next_retry_at = final_grace
        else:
            next_contact = get_next_follow_up_time(rs)
            if next_contact:
                await _schedule_task(rs, next_contact, db)
            else:
                rs.next_retry_at = None

        await log_action(
            db,
            rs,
            decision_id,
            approved,
            _play_channel(approved.play),
            provider_ref=payment_link,
        )
        await save_state(rs, db)

    await broadcast_case_update(rs)
    return rs
