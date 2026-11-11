"""Deterministic compliance and messaging guardrails.

Global rules only:
1. Outreach window (merchant-local 09:00–21:00) to avoid quiet hours.
2. Meta WhatsApp 24-hour customer-care window and utility-template handling.
3. Margin-safe, idempotently locked concession policy.
"""

from __future__ import annotations

import calendar
import random
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Optional

from config.config import settings
from config.logger import get_logger
from models.models import RecoveryState
from service.money import format_money

logger = get_logger(__name__)

CONTACT_WINDOW_START = time(settings.contact_window_start_hour, 0)
CONTACT_WINDOW_END = time(settings.contact_window_end_hour, 0)


def is_within_contact_window(dt: Optional[datetime] = None) -> bool:
    check_dt = dt or datetime.now()
    return CONTACT_WINDOW_START <= check_dt.time() < CONTACT_WINDOW_END


def adjust_for_contact_window(dt: datetime) -> datetime:
    """Snap a target timestamp into the permitted outreach window."""
    target_time = dt.time()
    if target_time < CONTACT_WINDOW_START:
        return dt.replace(
            hour=settings.contact_window_start_hour, minute=5, second=0, microsecond=0
        )
    if target_time >= CONTACT_WINDOW_END:
        next_day = dt + timedelta(days=1)
        return next_day.replace(
            hour=settings.contact_window_start_hour, minute=5, second=0, microsecond=0
        )
    return dt


def is_subscription_case(state: RecoveryState) -> bool:
    meta = state.case_metadata or {}
    return (
        state.case_type
        in {"failed_subscription", "subscription_cancelled", "subscription_suspended"}
        or bool(meta.get("subscription_id"))
        or str(state.source_id or "").startswith("I-")
        or bool(state.subscription_id)
    )


class WhatsAppHSMTemplate:
    """Pre-approved Meta WhatsApp utility template names."""

    PAYMENT_REMINDER = "renvue_payment_reminder_utility"
    SUBSCRIPTION_UPDATE = "renvue_subscription_update"
    INVOICE_OVERDUE = "renvue_invoice_overdue_notice"
    CHECKOUT_RECOVERY_GENTLE = "renvue_checkout_recovery_gentle"
    CHECKOUT_RECOVERY_URGENT = "renvue_checkout_recovery_urgent"
    CHECKOUT_RECOVERY_FINAL = "renvue_checkout_recovery_final"


def has_active_whatsapp_session(state: RecoveryState, max_window_hours: int = 24) -> bool:
    if not state.audit_log:
        return False
    threshold = datetime.now() - timedelta(hours=max_window_hours)

    def is_recent_inbound(entry: dict) -> bool:
        if entry.get("channel") != "whatsapp" or entry.get("direction") != "inbound":
            return False
        raw = entry.get("created_at")
        if not raw:
            return False
        try:
            dt = datetime.fromisoformat(raw) if isinstance(raw, str) else raw
            return dt >= threshold
        except Exception:
            return False

    return any(is_recent_inbound(entry) for entry in reversed(state.audit_log))


def build_whatsapp_payload(
    state: RecoveryState,
    raw_message: str,
    payment_link: Optional[str] = None,
    is_inbound_reply: bool = False,
) -> Dict[str, Any]:
    name = state.customer.get("name", "Customer")
    amount_str = format_money(state.amount, state.currency or "USD")
    ref_code = state.case_id[-4:].upper() if len(state.case_id) >= 4 else state.case_id
    meta = state.case_metadata or {}
    effective_link = payment_link or meta.get("payment_link", "")
    fallback_link = effective_link or settings.frontend_url or "the secure PayPal link"

    if effective_link and "{payment_link}" in raw_message:
        raw_message = raw_message.replace("{payment_link}", effective_link)

    is_in_window = is_inbound_reply or has_active_whatsapp_session(state)
    if is_in_window:
        logger.info(
            "[WHATSAPP COMPLIANCE] Active 24h session verified for case %s. Free-form text permitted.",
            state.case_id,
        )
        return {
            "mode": "freeform_session",
            "body": raw_message,
            "template_name": None,
            "category": "CUSTOMER_SERVICE",
            "is_hsm": False,
            "meta_compliance": "ACTIVE_24H_WINDOW",
        }

    logger.info(
        "[WHATSAPP COMPLIANCE] Cold outbound for case %s. Enforcing utility template.",
        state.case_id,
    )

    if state.case_type == "overdue_invoice":
        template_name = WhatsAppHSMTemplate.INVOICE_OVERDUE
        inv_num = meta.get("invoice_number", f"INV-{ref_code}")
        params = [name, inv_num, amount_str, fallback_link, ref_code]
        rendered_body = (
            f"Dear Accounts Payable ({name}), a courtesy reminder that Invoice {inv_num} "
            f"({amount_str}) is overdue. Pay securely: {fallback_link}. (Ref: #RNV-{ref_code})"
        )
    elif state.case_type == "abandoned_checkout":
        attempt = min(3, (state.attempt_count or 0) + 1)
        template_name = (
            WhatsAppHSMTemplate.CHECKOUT_RECOVERY_GENTLE
            if attempt <= 1
            else WhatsAppHSMTemplate.CHECKOUT_RECOVERY_URGENT
            if attempt == 2
            else WhatsAppHSMTemplate.CHECKOUT_RECOVERY_FINAL
        )
        disc = meta.get("discount_pct") or meta.get("eligible_discount")
        if disc is not None:
            logger.info(
                "[WHATSAPP COMPLIANCE] Checkout case %s carrying %.0f%% concession.",
                state.case_id,
                float(disc),
            )
        eff_amt = meta.get("effective_amount")
        eff_text = (
            format_money(eff_amt, state.currency or "USD")
            if eff_amt is not None
            else amount_str
        )
        params = [name, amount_str, eff_text, fallback_link, ref_code]
        # The agent already writes attempt-specific copy (gentle / urgent / final).
        # Keep it instead of collapsing every attempt into one fixed template body.
        rendered_body = raw_message
    elif is_subscription_case(state):
        template_name = WhatsAppHSMTemplate.SUBSCRIPTION_UPDATE
        sub_id = state.subscription_id or state.source_id or state.case_id[-8:]
        params = [name, amount_str, sub_id, fallback_link, ref_code]
        rendered_body = (
            f"Hi {name}, your subscription payment of {amount_str} needs attention. "
            f"Update your payment method or retry here: {fallback_link}. (Ref: #RNV-{ref_code})"
        )
    else:
        template_name = WhatsAppHSMTemplate.PAYMENT_REMINDER
        params = [name, amount_str, fallback_link, ref_code]
        rendered_body = raw_message

    return {
        "mode": "hsm_utility",
        "body": rendered_body,
        "template_name": template_name,
        "category": "UTILITY",
        "parameters": params,
        "is_hsm": True,
        "meta_compliance": "UTILITY_HSM_COMPLIANT",
    }


def calculate_payday_milestones(ref_date: Optional[date] = None) -> list[date]:
    """Upcoming payday-style milestones: 1st, 15th, and last Friday."""
    ref = ref_date or date.today()
    year, month = ref.year, ref.month
    milestones: list[date] = []

    for day in (1, 15):
        try:
            candidate = date(year, month, day)
            if candidate > ref:
                milestones.append(candidate)
        except ValueError:
            pass

    last_day = calendar.monthrange(year, month)[1]
    last_date = date(year, month, last_day)
    offset = (last_date.weekday() - 4) % 7
    last_friday = last_date - timedelta(days=offset)
    if last_friday > ref:
        milestones.append(last_friday)

    milestones = sorted(set(milestones))
    if not milestones:
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        milestones = [date(next_year, next_month, 1)]
    return milestones


def get_bell_curve_discount(state: RecoveryState) -> float:
    """Idempotently lock a right-skewed, margin-safe checkout concession."""
    meta = state.case_metadata or {}
    if "eligible_discount" in meta:
        return float(meta["eligible_discount"])

    if state.case_type not in {"abandoned_checkout"}:
        return 0.0

    min_d = float(settings.min_discount)
    max_d = float(settings.max_discount)
    bucket = random.choices(["min", "low", "mid", "high"], weights=[65, 22, 10, 3])[0]

    if bucket == "min":
        discount = min_d
    elif bucket == "low":
        discount = round(random.uniform(min_d, min_d + (max_d - min_d) * 0.25), 0)
    elif bucket == "mid":
        discount = round(
            random.uniform(min_d + (max_d - min_d) * 0.25, min_d + (max_d - min_d) * 0.60),
            0,
        )
    else:
        discount = round(random.uniform(min_d + (max_d - min_d) * 0.60, max_d), 0)

    discount = max(min_d, min(discount, max_d))
    if state.case_metadata is None:
        state.case_metadata = {}
    state.case_metadata["eligible_discount"] = discount
    return discount
