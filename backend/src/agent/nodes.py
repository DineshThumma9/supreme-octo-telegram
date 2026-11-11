import asyncio
from datetime import datetime, timedelta
import operator
import random
from typing import Annotated, Sequence, TypedDict
import uuid

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import ToolNode

import config.db
from config.config import settings
from config.logger import get_logger
from models.models import RecoveryState
from service.broadcast import broadcast_case_update
from service.compliance import (
    adjust_for_contact_window,
    get_bell_curve_discount,
    is_subscription_case,
    is_within_contact_window,
)
from service.money import format_money
from service.states import save_state
from agent.prompts import build_system_prompt, get_escalation_tone
from agent.tools import tools
from agent.utils import (
    _log_audit,
    _schedule_task,
    cant_resolve,
    execute_deterministic_recovery,
    get_llm,
    mark_case_escalated,
    sanity_date,
)

logger = get_logger(__name__)


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    recovery_state: RecoveryState
    event_source: str


async def compliance_guardrail(state: AgentState) -> dict:
    """
    Stage 2 Pre-Flight Compliance Guardrail Node.
    Runs FIRST on every incoming graph invocation before action routing:
    1. Enforces the merchant-local outreach window: automated events outside
       business hours are deferred to the next permitted slot without burning LLM tokens.
    2. Injects strict policy bounds (min/max discount, max grace period) into state metadata.
    """
    rs = state["recovery_state"]
    event_source = state.get("event_source", "automated.webhook")

    if rs.case_metadata is None:
        rs.case_metadata = {}
    if rs.error_details is None:
        rs.error_details = {}

    # 1. Pre-calculate and inject dynamic compliance bounds
    in_contact_window = is_within_contact_window()
    is_subscription = is_subscription_case(rs)

    # For abandoned checkout cases: evaluate and idempotently lock the margin-safe bell-curve discount
    if rs.case_type == "abandoned_checkout":
        locked_discount = get_bell_curve_discount(rs)
        logger.info(f"[COMPLIANCE GUARDRAIL] Case {rs.case_id} (abandoned_checkout): locked bell-curve discount = {locked_discount}%")

    rs.case_metadata["compliance_bounds"] = {
        "min_discount": float(settings.min_discount),
        "max_discount": float(settings.max_discount),
        "max_grace_period": int(settings.max_grace_period),
        "contact_window_start_hour": int(settings.contact_window_start_hour),
        "contact_window_end_hour": int(settings.contact_window_end_hour),
        "contact_window_active": in_contact_window,
        "is_subscription": is_subscription,
        "eligible_discount": (rs.case_metadata or {}).get("eligible_discount"),
    }

    # 2. Max Attempts Stopping Rule Enforcement (Hard-Stop Policy: Max 3 Attempts)
    # Evaluated FIRST before outreach or window checks so terminal cases never get delayed or retried.
    if (rs.attempt_count or 0) >= 3 and event_source != "inbound.human_approval" and rs.recovery_status not in ["recovered", "closed", "escalated"]:
        rs.attempt_count = min(3, rs.attempt_count or 0)
        context_str = (
            f"Context: Name={rs.customer.get('name', 'Unknown')}, "
            f"Amount={format_money(rs.amount, rs.currency)}, Case={rs.case_type}, "
            f"Last Action={rs.last_action_taken}"
        )
        reason = f"Max recovery outreach attempts (3) exhausted without resolution. {context_str}"
        logger.info(f"[COMPLIANCE GUARDRAIL] Case {rs.case_id} reached attempt 3 >= 3. Auto-escalating to human operations.")
        await mark_case_escalated(rs, reason)
        return {"recovery_state": rs}

    # 3. Contact-window enforcement for automated cold outreach:
    # Defers cold automated webhooks arriving outside business hours.
    # Excludes: inbound customer replies, pre-scheduled daytime follow-ups, and interactive simulation.
    is_inbound = event_source.startswith("inbound.")
    is_scheduled = event_source == "scheduled.follow_up"
    is_sim = (
        rs.case_id.startswith("pay_fail_")
        or getattr(rs, "account_id", "") in ["paypal_default", "paypal_sandbox"]
        or settings.demo_mode
    )

    if not in_contact_window and not is_inbound and not is_scheduled and not is_sim and rs.recovery_status not in ["recovered", "closed", "escalated"]:
        morning_contact = adjust_for_contact_window(datetime.now())
        rs.next_retry_at = morning_contact
        rs.case_metadata["contact_window_deferred"] = True
        logger.info(f"[COMPLIANCE GUARDRAIL] Outside the outreach window. Deferring cold case {rs.case_id} to {morning_contact.isoformat()}.")

        async with config.db.AsyncSessionLocal() as db:
            await _schedule_task(rs, morning_contact, db)
            await _log_audit(
                rs,
                "contact_window_deferred",
                morning_contact,
                db,
                message=f"Automated communication paused until the permitted outreach window ({morning_contact.strftime('%d %b %I:%M %p')}).",
                channel="system",
                direction="system",
            )
            await save_state(rs, db)
        await broadcast_case_update(rs)

    return {"recovery_state": rs}


def route_after_compliance(state: AgentState) -> str:
    """
    Conditional router following the compliance_guardrail node:
    - If deferred by the outreach window or already closed/recovered/escalated: bypass to audit -> END
    - If inbound customer reply: route to decide_reply (Mistral LLM)
    - If automated event inside operating window: route to decide_event (Deterministic Engine)
    """
    rs = state["recovery_state"]
    if (rs.case_metadata or {}).get("contact_window_deferred"):
        rs.case_metadata.pop("contact_window_deferred", None)
        return "audit"

    if rs.recovery_status in ["recovered", "closed", "escalated"]:
        return "audit"

    event = state.get("event_source", "")
    if event.startswith("inbound."):
        return "decide_reply"
    else:
        return "decide_event"


async def decide_event(state: AgentState):
    """
    Stage 1-6 Deterministic Recovery Pipeline for automated events.
    Decoupled from LLM conversational graph for high performance (<10ms) and zero compliance drift.
    """
    rs = state["recovery_state"]
    event_source = state.get("event_source", "automated.webhook")
    logger.info(f"[ROUTER] Deterministic Fast-Path triggered for case: {rs.case_id} (source: {event_source})")
    updated_rs = await execute_deterministic_recovery(rs, event_source)
    return {"recovery_state": updated_rs, "messages": []}


async def decide_reply(state: AgentState):
    """
    Phase 2: LLM routing for conversational replies (WhatsApp, Email).
    """
    rs = state["recovery_state"]
    logger.info(f"[ROUTER] LLM routing conversational reply for case: {rs.case_id}")
    
    system_prompt = build_system_prompt(rs)
    
    first_human_idx = next((i for i, m in enumerate(state["messages"]) if getattr(m, "type", "") == "human"), None)
    
    if first_human_idx is not None:
        recent_messages = state["messages"][first_human_idx:]
    else:
        recent_messages = []
        
    clean_messages = [SystemMessage(content=system_prompt)] + recent_messages
    
    llm_with_tools = get_llm()
    
    await asyncio.sleep(random.uniform(0.3, 1.0))
    
    for attempt in range(5):
        try:
            response = await llm_with_tools.ainvoke(clean_messages)
            if getattr(response, "tool_calls", None):
                for call in response.tool_calls:
                    if call["name"] == "escalate_to_human":
                        reason = call.get("args", {}).get("reason", "Escalated by conversational agent")
                        await mark_case_escalated(rs, reason)
                        break
                return {"messages": [response]}

            # A plain-text reply has no tool call to carry it. Wrap it in
            # send_whatsapp_msg so the customer actually receives it and the
            # audit log/UI records an outbound message.
            raw_content = response.content
            content = raw_content.strip() if isinstance(raw_content, str) else ""
            if content:
                return {
                    "messages": [
                        AIMessage(
                            content=content,
                            tool_calls=[{
                                "name": "send_whatsapp_msg",
                                "args": {"msg": content},
                                "id": f"call_{uuid.uuid4().hex[:8]}",
                                "type": "tool_call",
                            }],
                        )
                    ]
                }

            logger.warning(
                "[ROUTER] LLM returned no content and no tool calls (attempt %s/5)",
                attempt + 1,
            )
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "rate_limited" in err_str:
                backoff = random.uniform(2.0, 5.0) * (attempt + 1)
                logger.warning(f"[RATE LIMIT] Mistral 429 hit. Retrying in {backoff:.1f}s (Attempt {attempt+1}/5)...")
                await asyncio.sleep(backoff)
            elif "connecterror" in err_str or "name resolution" in err_str or "temporary failure" in err_str or "timeout" in err_str:
                logger.warning(f"[LLM NETWORK WARNING] Mistral unreachable ({e}). Attempt {attempt+1}/5.")
                if attempt < 2:
                    await asyncio.sleep(2.0 * (attempt + 1))
                else:
                    # Graceful deterministic fallback so Taskiq background workers never crash on DNS drops
                    logger.info(f"[LLM RESILIENCE] Network/DNS connection failed. Falling back to deterministic escalation tone.")
                    current_attempt = min(3, (rs.attempt_count or 0) + 1)
                    wa_msg, _, _ = get_escalation_tone(rs, attempt=current_attempt)
                    fallback_ai = AIMessage(
                        content="Deterministic recovery fallback applied due to upstream LLM connectivity timeout.",
                        tool_calls=[{
                            "name": "send_whatsapp_msg",
                            "args": {"msg": wa_msg},
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                            "type": "tool_call"
                        }]
                    )
                    return {"messages": [fallback_ai]}
            else:
                raise e
                
    # Final safety fallback
    current_attempt = min(3, (rs.attempt_count or 0) + 1)
    wa_msg, _, _ = get_escalation_tone(rs, attempt=current_attempt)
    fallback_ai = AIMessage(
        content="Deterministic recovery fallback applied after retries exhausted.",
        tool_calls=[{
            "name": "send_whatsapp_msg",
            "args": {"msg": wa_msg},
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "type": "tool_call"
        }]
    )
    return {"messages": [fallback_ai]}


execute = ToolNode(tools)

def escalate_gate(state: AgentState):
    """
    Dummy node that serves as a Human-in-the-Loop breakpoint.
    The graph will be configured to interrupt_before this node.
    """
    return state


async def audit(state: AgentState):
    """
    Saves the final outcome to the SQLite database.
    
    IMPORTANT: Tools each open their own DB session and write next_retry_at / last_action_taken
    directly. The in-memory `rs` in state["recovery_state"] is the ORIGINAL pre-tool-run snapshot.
    We must reload from DB before saving so we don't overwrite those tool-written fields.
    """
    rs_snapshot = state["recovery_state"]
    messages = state["messages"]
    
    last_ai_msg = next((m for m in reversed(messages) if m.type == "ai" and getattr(m, "tool_calls", None)), None)
    
    CHANNEL_TOOLS = {"send_whatsapp_msg", "send_email_reminder", "get_voice_call", "escalate_to_human"}

    async with config.db.AsyncSessionLocal() as db:
        # Reload the CURRENT DB state — tools wrote next_retry_at / last_action_taken here already
        from service.states import load_state as _load_state
        rs = await _load_state(rs_snapshot.case_id, db)
        if not rs:
            # Fallback: use snapshot if somehow not found
            rs = rs_snapshot

        if last_ai_msg and last_ai_msg.tool_calls:
            if any(call["name"] == "complete_case" for call in last_ai_msg.tool_calls):
                rs.recovery_status = "closed"
            elif any(call["name"] == "escalate_to_human" for call in last_ai_msg.tool_calls) or rs.recovery_status == "escalated":
                rs.recovery_status = "escalated"

            # Inbound customer replies and tool calls MUST NOT increment attempt_count.
            # Attempt counts are strictly reserved for outbound recovery outreach attempts (max 3).
            rs.attempt_count = min(3, rs.attempt_count or 0)
            # Only update last_action_taken if a channel tool was used and tools didn't already set it
            if not rs.last_action_taken:
                for call in reversed(last_ai_msg.tool_calls):
                    if call["name"] in CHANNEL_TOOLS or call["name"] in ["complete_case"]:
                        rs.last_action_taken = call["name"]
                        break

        logger.info(f"[AUDIT] case={rs.case_id} attempt={rs.attempt_count} "
                    f"last_action={rs.last_action_taken} next_retry_at={rs.next_retry_at} "
                    f"status={rs.recovery_status}")

        await save_state(rs, db)
    
    return {"recovery_state": rs}



def should_continue(state: AgentState):
    """
    Decides whether to execute tools or go to the audit phase.
    """
    last_message = state["messages"][-1]
    
    if getattr(last_message, "tool_calls", None):
        if any(call["name"] == "escalate_to_human" for call in last_message.tool_calls):
            return "escalate_gate"
        return "execute"
        
    return "audit"

def after_execute(state: AgentState):
    """
    Decides where to go after executing tools.
    
    Rules:
    - Terminal/message tools (complete_case, escalate_to_human, log_promise_to_pay, send_whatsapp_msg, send_email_reminder) → always audit
    - Other tools for inbound conversational events → decide_reply (LLM loop)
    - Automated (webhook, scheduled follow-up) → audit immediately
    """
    messages = state["messages"]
    
    # Check if a conclusive action has been taken in this tool batch
    for msg in reversed(messages):
        msg_type = getattr(msg, "type", "")
        msg_name = getattr(msg, "name", None)
        if msg_type == "tool":
            if msg_name == "log_promise_to_pay" and "PROMISE_REJECTED" in str(getattr(msg, "content", "")):
                # Rejected promise has already been directly escalated to human in tool
                return "audit"
            if msg_name in ("complete_case", "escalate_to_human", "log_promise_to_pay", "send_whatsapp_msg", "send_email_reminder"):
                return "audit"
        # Stop looking once we pass the current tool results batch
        if msg_type == "ai":
            break
    
    event_source = state.get("event_source", "")
    
    # Only inbound conversational events without a message sent get an LLM reply loop
    if event_source.startswith("inbound."):
        return "decide_reply"
    
    # Automated (webhook, scheduled follow-up) → one-shot, go straight to audit
    return "audit"
