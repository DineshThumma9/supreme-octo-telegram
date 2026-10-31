"""Deterministic guardrails with veto power over the policy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from config.config import settings
from models.models import RecoveryState
from policy.interfaces import Action, Observation, Play
from service.compliance import adjust_for_contact_window, is_within_contact_window

OUTBOUND_PLAYS = {
    Play.EMAIL_LINK,
    Play.SMS_LINK,
    Play.PAYPAL_INVOICE_REMINDER,
    Play.RETRY_NOW,
    Play.RETRY_PAYDAY,
    Play.UPDATE_METHOD_LINK,
    Play.DISCOUNT_LINK,
}


@dataclass(frozen=True)
class GuardrailDecision:
    action: Action
    result: str  # pass | downgrade | defer | block
    rule: str


def _has_email(state: RecoveryState) -> bool:
    return bool((state.customer or {}).get("email"))


def _has_phone(state: RecoveryState) -> bool:
    return bool((state.customer or {}).get("contact"))


def _contact_window_bypass(state: RecoveryState) -> bool:
    return bool(
        settings.demo_mode
        or state.case_id.startswith("test_")
        or state.account_id in {"acc_TestMode", "paypal_default"}
        or (state.case_metadata or {}).get("simulated")
    )


def apply_guardrails(
    state: RecoveryState,
    obs: Observation,
    action: Action,
    now: datetime | None = None,
) -> GuardrailDecision:
    now = now or datetime.now()

    if state.recovery_status in {"recovered", "closed", "escalated"}:
        return GuardrailDecision(replace(action, play=Play.NO_CONTACT), "block", "terminal_case")

    if obs.opt_out:
        return GuardrailDecision(replace(action, play=Play.NO_CONTACT), "block", "opt_out")

    if obs.dispute_open:
        return GuardrailDecision(replace(action, play=Play.HUMAN_ESCALATION), "pass", "dispute_freeze")

    if action.play == Play.NO_CONTACT:
        return GuardrailDecision(action, "pass", "control_arm")

    if obs.amount_due <= 0:
        return GuardrailDecision(replace(action, play=Play.NO_CONTACT), "block", "amount_sanity")

    if len(obs.currency or "") != 3:
        return GuardrailDecision(replace(action, play=Play.NO_CONTACT), "block", "currency_sanity")

    if action.discount_pct > 0 and state.case_type != "abandoned_checkout":
        action = replace(action, discount_pct=0.0)
        result = "downgrade"
        rule = "discount_scope"
    elif action.discount_pct > settings.max_discount:
        action = replace(action, discount_pct=float(settings.max_discount))
        result = "downgrade"
        rule = "discount_cap"
    else:
        result = "pass"
        rule = "allowed"

    if result == "pass" and obs.contact_count_7d >= 3 and action.play not in {
        Play.HUMAN_ESCALATION,
        Play.NO_CONTACT,
    }:
        return GuardrailDecision(
            replace(action, play=Play.HUMAN_ESCALATION), "downgrade", "max_touches_7d"
        )

    if action.play == Play.HUMAN_ESCALATION:
        return GuardrailDecision(action, result, rule)

    if action.play in OUTBOUND_PLAYS and not _contact_window_bypass(state):
        if not is_within_contact_window(now):
            return GuardrailDecision(
                replace(action, scheduled_for=adjust_for_contact_window(now)),
                "defer",
                "contact_window",
            )

    if action.play == Play.EMAIL_LINK and not _has_email(state):
        if _has_phone(state):
            return GuardrailDecision(replace(action, play=Play.SMS_LINK), "downgrade", "email_missing")
        return GuardrailDecision(replace(action, play=Play.NO_CONTACT), "block", "no_channel")

    if action.play == Play.SMS_LINK and not _has_phone(state):
        if _has_email(state):
            return GuardrailDecision(replace(action, play=Play.EMAIL_LINK), "downgrade", "phone_missing")
        return GuardrailDecision(replace(action, play=Play.NO_CONTACT), "block", "no_channel")

    if action.play == Play.UPDATE_METHOD_LINK and not state.subscription_id:
        if _has_email(state):
            return GuardrailDecision(replace(action, play=Play.EMAIL_LINK), "downgrade", "not_subscription")
        return GuardrailDecision(replace(action, play=Play.NO_CONTACT), "block", "no_channel")

    if action.play == Play.PAYPAL_INVOICE_REMINDER and not state.invoice_id:
        if _has_email(state):
            return GuardrailDecision(replace(action, play=Play.EMAIL_LINK), "downgrade", "not_invoice")
        return GuardrailDecision(replace(action, play=Play.NO_CONTACT), "block", "no_channel")

    if action.play == Play.DISCOUNT_LINK and state.case_type != "abandoned_checkout":
        return GuardrailDecision(replace(action, play=Play.EMAIL_LINK), "downgrade", "discount_scope")

    if action.play in OUTBOUND_PLAYS and not (_has_email(state) or _has_phone(state)):
        return GuardrailDecision(replace(action, play=Play.NO_CONTACT), "block", "no_channel")

    return GuardrailDecision(action, result, rule)
