"""Strong deterministic rules baseline used when no trained model is loaded.

The policy proposes exactly one Play. Guardrails in ``guardrails.py`` may
downgrade or block it; the agent only ever executes the approved Play.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from models.models import RecoveryState
from policy.interfaces import Action, Observation, Outcome, Play


def _failure_class(state: RecoveryState) -> str:
    if state.decline_type in {"soft", "hard", "transient"}:
        return state.decline_type
    text = f"{state.failure_reason or ''} {state.error_details or {}}".lower()
    if any(word in text for word in ("insufficient", "temporary", "try again", "timeout")):
        return "soft"
    if any(word in text for word in ("expired", "closed", "fraud", "stolen", "invalid")):
        return "hard"
    return "unknown"


def observation_from_state(state: RecoveryState) -> Observation:
    now = datetime.now()
    meta = state.case_metadata or {}
    first_seen = state.first_seen_at or now
    outbound = [
        entry
        for entry in (state.audit_log or [])
        if entry.get("direction") == "outbound"
    ]
    recent_cutoff = now - timedelta(days=7)
    recent_contacts = 0
    last_contact_hours = None
    for entry in outbound:
        raw = entry.get("created_at")
        if not raw:
            continue
        try:
            created = datetime.fromisoformat(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        if created >= recent_cutoff:
            recent_contacts += 1
        hours = (now - created).total_seconds() / 3600
        if last_contact_hours is None or hours < last_contact_hours:
            last_contact_hours = hours

    due_raw = meta.get("due_date")
    days_past_due = 0
    if due_raw:
        try:
            due = datetime.fromisoformat(str(due_raw)[:10])
            days_past_due = max(0, (now.date() - due.date()).days)
        except Exception:
            days_past_due = 0
    elif state.case_type == "overdue_invoice":
        days_past_due = max(0, (now.date() - first_seen.date()).days)

    segment = "b2b"
    if state.case_type == "abandoned_checkout":
        segment = "checkout"
    elif state.case_type in {"failed_subscription", "subscription_cancelled", "subscription_suspended"}:
        segment = "subscription"
    elif state.case_type == "failed_payment":
        segment = "card"

    return Observation(
        case_id=state.case_id,
        currency=state.currency or "USD",
        amount_due=float(state.amount or 0.0),
        days_past_due=days_past_due,
        failure_code=(state.error_details or {}).get("issue") or (state.error_details or {}).get("reason"),
        failure_class=_failure_class(state),
        payment_method_type=state.method,
        method_age_days=meta.get("method_age_days"),
        attempt_count=int(state.attempt_count or 0),
        contact_count_7d=recent_contacts,
        last_contact_hours=last_contact_hours,
        prior_successful_payments=int(meta.get("prior_successful_payments", 0)),
        prior_failed_payments=int(meta.get("prior_failed_payments", 0)),
        prior_recoveries=int(meta.get("prior_recoveries", 0)),
        tenure_days=max(0, (now.date() - first_seen.date()).days),
        segment=segment,
        dispute_open=bool(state.dispute_id) or state.case_type == "dispute",
        opt_out=bool(meta.get("opt_out")),
        hour_local=now.hour,
        weekday=now.weekday(),
        days_to_month_end=max(0, (now.replace(day=28) + timedelta(days=4)).day - now.day),
        payday_signal=now.day <= 3 or now.day >= 28,
        invoice_age_days=days_past_due if state.case_type == "overdue_invoice" else None,
    )


def eligible_plays(obs: Observation) -> list[Play]:
    if obs.opt_out or obs.dispute_open:
        return [Play.NO_CONTACT]
    if obs.attempt_count >= 3:
        return [Play.HUMAN_ESCALATION]
    if obs.segment == "b2b":
        return [Play.PAYPAL_INVOICE_REMINDER, Play.EMAIL_LINK, Play.HUMAN_ESCALATION, Play.NO_CONTACT]
    if obs.segment == "subscription":
        return [Play.UPDATE_METHOD_LINK, Play.RETRY_PAYDAY, Play.SMS_LINK, Play.NO_CONTACT]
    if obs.segment == "checkout":
        return [Play.DISCOUNT_LINK, Play.EMAIL_LINK, Play.SMS_LINK, Play.NO_CONTACT]
    if obs.failure_class in {"soft", "transient"}:
        return [Play.RETRY_PAYDAY, Play.RETRY_NOW, Play.EMAIL_LINK, Play.NO_CONTACT]
    return [Play.UPDATE_METHOD_LINK, Play.EMAIL_LINK, Play.SMS_LINK, Play.NO_CONTACT]


class RulesPolicy:
    name = "rules"
    policy_version = "rules-v0"

    def begin(self, episode) -> None:  # noqa: ANN001 - protocol shape
        self._episode = episode

    def act(self, obs: Observation) -> Action:
        plays = eligible_plays(obs)
        if obs.opt_out or obs.dispute_open:
            play = Play.NO_CONTACT
        elif obs.attempt_count >= 3:
            play = Play.HUMAN_ESCALATION
        elif obs.segment == "b2b":
            play = Play.PAYPAL_INVOICE_REMINDER
        elif obs.segment == "subscription":
            play = Play.UPDATE_METHOD_LINK
        elif obs.segment == "checkout":
            play = Play.DISCOUNT_LINK
        elif obs.failure_class in {"soft", "transient"}:
            play = Play.RETRY_PAYDAY if obs.payday_signal else Play.RETRY_NOW
        else:
            play = Play.UPDATE_METHOD_LINK

        if play not in plays:
            play = plays[0]

        discount = 5.0 if play == Play.DISCOUNT_LINK else 0.0
        return Action(
            play=play,
            scheduled_for=None,
            discount_pct=discount,
            template_id=f"{play.value}_v1",
            rule_id=f"rules:{obs.segment}:{obs.failure_class}",
        )

    def observe_outcome(self, outcome: Outcome) -> None:
        return None

    def finalize(self, episode) -> list[Outcome]:  # noqa: ANN001 - protocol shape
        return []


policy = RulesPolicy()
