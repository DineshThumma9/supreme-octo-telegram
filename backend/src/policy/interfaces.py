"""Locked policy contracts (plan.md §14)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal, Protocol


class Play(str, Enum):
    NO_CONTACT = "no_contact"
    EMAIL_LINK = "email_link"
    SMS_LINK = "sms_link"
    PAYPAL_INVOICE_REMINDER = "paypal_invoice_reminder"
    RETRY_NOW = "retry_now"
    RETRY_PAYDAY = "retry_payday"
    UPDATE_METHOD_LINK = "update_method_link"
    DISCOUNT_LINK = "discount_link"
    HUMAN_ESCALATION = "human_escalation"


@dataclass(frozen=True)
class Observation:
    case_id: str
    currency: str
    amount_due: float
    days_past_due: int
    failure_code: str | None
    failure_class: Literal["soft", "hard", "transient", "unknown"]
    payment_method_type: str | None
    method_age_days: int | None
    attempt_count: int
    contact_count_7d: int
    last_contact_hours: float | None
    prior_successful_payments: int
    prior_failed_payments: int
    prior_recoveries: int
    tenure_days: int
    segment: str
    dispute_open: bool
    opt_out: bool
    hour_local: int
    weekday: int
    days_to_month_end: int
    payday_signal: bool
    invoice_age_days: int | None


@dataclass(frozen=True)
class Action:
    play: Play
    scheduled_for: datetime | None
    discount_pct: float
    template_id: str | None
    rule_id: str | None = None


@dataclass(frozen=True)
class Outcome:
    case_id: str
    decision_id: str | None
    paid: bool
    recovered_amount: float
    paid_at: datetime | None
    opt_out: bool
    dispute: bool
    cost: float
    censored: bool
    attribution: Literal[
        "system_recovered",
        "customer_self_recovered",
        "ambiguous",
        "not_recovered",
    ]


class Policy(Protocol):
    name: str

    def begin(self, episode) -> None: ...
    def act(self, obs: Observation) -> Action: ...
    def observe_outcome(self, outcome: Outcome) -> None: ...
    def finalize(self, episode) -> list[Outcome]: ...
