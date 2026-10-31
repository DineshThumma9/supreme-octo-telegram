from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AuditEntry(BaseModel):
    event_triggered: str
    amount: str
    recovery_status: str
    customer: Dict[str, Any]
    next_contact: Optional[datetime] = None
    message: Optional[str] = None
    channel: Optional[str] = None
    direction: Optional[str] = None  # outbound | inbound | system
    meta_compliance: Optional[str] = None
    hsm_template: Optional[str] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.now)
    model_config = {"extra": "allow"}


class CustomerDetails(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    contact: Optional[str] = None
    payer_id: Optional[str] = None
    model_config = {"extra": "allow"}


class PayPalWebhookEvent(BaseModel):
    """A PayPal webhook delivery.

    PayPal's resource shape varies by event type, so the resource is kept as a
    validated dict. Event-specific mapping lives in paypal/events.py.
    """

    id: str
    event_type: str
    resource_type: Optional[str] = None
    resource: Dict[str, Any] = Field(default_factory=dict)
    summary: Optional[str] = None
    event_version: Optional[str] = None
    create_time: Optional[datetime] = None
    links: list[dict] = Field(default_factory=list)
    model_config = {"extra": "allow"}


class EmailReminderArgs(BaseModel):
    urgency: str = Field(description="MUST be one of: 'gentle', 'urgent', 'final'")


class PromiseToPayArgs(BaseModel):
    sentiment: str = Field(
        default="neutral",
        description="Sentiment of the reply the user sent (e.g. 'gentle', 'neutral', 'angry', 'hostile').",
    )
    reason: str = Field(
        default="Customer commitment regarding payment",
        description="The reason or context the user gave for the delay.",
    )
    date_str: Optional[str] = Field(
        default=None,
        description=(
            "The ISO format date (YYYY-MM-DD) the user promised to pay by, or None "
            "if no specific valid date could be extracted."
        ),
    )


class CompleteCaseArgs(BaseModel):
    summary: str = Field(default="Case completed.", description="Summary of actions taken to resolve the case.")


class PaymentLinkArgs(BaseModel):
    discount_pct: float = Field(
        default=0.0,
        description=(
            "Optional concession/discount percentage to apply (must be bounded between "
            "MIN_DISCOUNT and MAX_DISCOUNT, e.g. 5% to 30%)."
        ),
    )


class EscalateArgs(BaseModel):
    reason: str = Field(description="Detailed reason for why this case is being escalated.")


class SalaryDateArgs(BaseModel):
    pass


class DiscountOfferArgs(BaseModel):
    pass


class SimulationEvent(BaseModel):
    event_type: str
    decline_reason: str = "Payment declined"
    email: str = "test@example.com"
    phone: str = "+14155550123"
    name: str = "Test Customer"
    amount: float = 50.0
    currency: str = "USD"
    language: str = "english"
    account_id: Optional[str] = "paypal_default"


class CustomerAction(BaseModel):
    actions: str
    case_id: str
    messages: Optional[str] = ""
    customer: Optional[CustomerDetails] = None
