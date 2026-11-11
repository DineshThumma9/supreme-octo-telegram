from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import JSON, DateTime, Index, UniqueConstraint
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator
from sqlmodel import Column, Field, SQLModel


class NaiveUTCDateTime(TypeDecorator):
    """Store aware or naive datetimes, return naive UTC for legacy code.

    SQLModel 0.0.48 rejects naive datetimes by default. Renvue's policy and
    scheduling code works in merchant-local naive time, so this decorator binds
    values as UTC and returns naive UTC from PostgreSQL.
    """

    impl = DateTime
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(timezone=True)

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None)


def utc_datetime_column() -> Column:
    return Column(NaiveUTCDateTime())


class CustomerProfile(SQLModel, table=True):
    __tablename__ = "customers"

    id: str = Field(primary_key=True)  # PayPal payer_id or merchant customer reference
    name: Optional[str] = None
    email: Optional[str] = None
    contact: Optional[str] = None
    language: str = "english"
    contact_preference: str = "email"
    trust_score: int = 100
    total_spend: float = 0.0
    created_at: datetime = Field(default_factory=datetime.now, sa_column=utc_datetime_column())
    updated_at: datetime = Field(default_factory=datetime.now, sa_column=utc_datetime_column())


class RecoveryState(SQLModel, table=True):
    __tablename__ = "recovery_cases"

    # Identity & multi-tenancy
    case_id: str = Field(primary_key=True)  # our internal ID (uuid)
    source_id: str  # PayPal order / subscription / invoice / capture ID
    account_id: str = Field(default="paypal_default", index=True)

    # PayPal resource identifiers (all optional; one or more is populated)
    paypal_order_id: Optional[str] = None
    capture_id: Optional[str] = None
    subscription_id: Optional[str] = None
    invoice_id: Optional[str] = None
    dispute_id: Optional[str] = None

    method: Optional[str] = None
    through: Optional[str] = None
    case_type: str  # failed_payment | abandoned_checkout | failed_subscription | overdue_invoice
    decline_type: Optional[str] = None  # hard | soft | transient | None
    failure_reason: Optional[str] = None
    error_details: dict = Field(default_factory=dict, sa_column=Column(JSON))
    case_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))

    # Money. Every amount has a currency; USD is the demo default.
    amount: float
    currency: str = "USD"
    recovered_amount: float = 0.0

    # Customer (JSON)
    customer: dict = Field(default_factory=dict, sa_column=Column(JSON))
    contact_preference: str = "email"  # email | sms | whatsapp | call
    language: str = "english"

    # Lifecycle
    recovery_status: str = "pending"  # pending | in_progress | recovered | escalated | closed
    attempt_count: int = 0
    last_action_taken: Optional[str] = None
    first_seen_at: datetime = Field(default_factory=datetime.now, sa_column=utc_datetime_column())
    next_retry_at: Optional[datetime] = Field(default=None, sa_column=utc_datetime_column())

    # History (JSON)
    audit_log: List[dict] = Field(default_factory=list, sa_column=Column(JSON))

    # Background tasks
    active_task_id: Optional[str] = Field(default=None, exclude=True)


class WebhookEvent(SQLModel, table=True):
    """Idempotency ledger for PayPal webhook deliveries."""

    __tablename__ = "webhook_events"

    event_id: str = Field(primary_key=True)
    event_type: str
    resource_id: Optional[str] = None
    received_at: datetime = Field(default_factory=datetime.now, sa_column=utc_datetime_column())
    processed_at: Optional[datetime] = Field(default=None, sa_column=utc_datetime_column())


class DecisionLog(SQLModel, table=True):
    """Append-only record of every policy decision."""

    __tablename__ = "decision_log"

    decision_id: str = Field(primary_key=True)
    case_id: str = Field(index=True)
    trigger_event_id: Optional[str] = None
    state_snapshot_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    state_snapshot_hash: Optional[str] = None
    eligible_actions_json: list = Field(default_factory=list, sa_column=Column(JSON))
    proposed_action: str
    approved_action: Optional[str] = None
    p_pay: Optional[float] = None
    expected_recovered: Optional[float] = None
    expected_cost: Optional[float] = None
    expected_net: Optional[float] = None
    alternatives_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    exploration: bool = False
    guardrail_result: str = "pass"
    policy_version: str = "rules-v0"
    model_version: str = "none"
    created_at: datetime = Field(default_factory=datetime.now, sa_column=utc_datetime_column())


class ActionLog(SQLModel, table=True):
    """Append-only record of every executed Play."""

    __tablename__ = "action_log"

    action_id: str = Field(primary_key=True)
    decision_id: Optional[str] = Field(default=None, index=True)
    case_id: str = Field(index=True)
    play: str
    channel: Optional[str] = None
    provider: str = "paypal"
    provider_ref: Optional[str] = None
    template_id: Optional[str] = None
    discount_pct: float = 0.0
    scheduled_for: Optional[datetime] = Field(default=None, sa_column=utc_datetime_column())
    executed_at: Optional[datetime] = Field(default=None, sa_column=utc_datetime_column())
    status: str = "scheduled"
    error: Optional[str] = None


class OutcomeLog(SQLModel, table=True):
    """Append-only record of observed outcomes."""

    __tablename__ = "outcome_log"

    outcome_id: str = Field(primary_key=True)
    decision_id: Optional[str] = Field(default=None, index=True)
    action_id: Optional[str] = Field(default=None, index=True)
    case_id: str = Field(index=True)
    outcome_type: str
    recovered_amount: float = 0.0
    currency: str = "USD"
    time_to_pay_hours: Optional[float] = None
    cost_usd: float = 0.0
    opt_out: bool = False
    dispute: bool = False
    censored: bool = False
    observation_window_end: Optional[datetime] = Field(default=None, sa_column=utc_datetime_column())
    observed_at: datetime = Field(default_factory=datetime.now, sa_column=utc_datetime_column())


class LearningSample(SQLModel, table=True):
    """One observed attempt-level learning label.

    Live rows are created from OutcomeLog entries. Experiment rows are created
    only by the labeled sandbox endpoint. This table is append-only; do not
    mutate labels in place.
    """

    __tablename__ = "learning_sample"
    __table_args__ = (
        UniqueConstraint(
            "decision_id",
            "sample_kind",
            name="uq_learning_decision_kind",
        ),
        UniqueConstraint("outcome_id", name="uq_learning_outcome"),
        Index("ix_learning_provenance_source_play", "provenance", "source", "play"),
    )

    sample_id: str = Field(primary_key=True)
    case_id: str = Field(index=True)
    decision_id: Optional[str] = Field(default=None, index=True)
    action_id: Optional[str] = Field(default=None, index=True)
    outcome_id: Optional[str] = Field(default=None, index=True)
    play: str = Field(index=True)
    segment: str = "unknown"

    # live = observed by the running deployment (including PayPal sandbox webhooks)
    # sandbox = injected simulator case or labeled experiment
    provenance: str = Field(default="live", index=True)
    # outcome = came from an OutcomeLog; experiment = came from /api/learning/sandbox
    source: str = Field(default="outcome", index=True)
    experiment_id: Optional[str] = Field(default=None, index=True)

    # recovered = paid within the observation window
    # timeout   = a delivered touch produced no payment before the next follow-up
    sample_kind: str = "recovered"
    success: bool = False
    censored: bool = False
    recovered_amount: float = 0.0
    currency: str = "USD"

    policy_version: Optional[str] = None
    model_version: Optional[str] = None
    created_at: datetime = Field(
        default_factory=datetime.now, sa_column=utc_datetime_column()
    )

