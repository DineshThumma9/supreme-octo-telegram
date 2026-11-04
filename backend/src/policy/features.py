"""Feature contract for the policy.

Only fields present in ``Observation`` may be used. ``FEATURE_ALLOW_LIST`` is
the single source of truth for that boundary and is asserted by tests.
"""

from __future__ import annotations

from dataclasses import asdict

from policy.interfaces import Observation, Play

FEATURE_ALLOW_LIST = (
    "currency",
    "amount_due",
    "days_past_due",
    "failure_code",
    "failure_class",
    "payment_method_type",
    "method_age_days",
    "attempt_count",
    "contact_count_7d",
    "last_contact_hours",
    "prior_successful_payments",
    "prior_failed_payments",
    "prior_recoveries",
    "tenure_days",
    "segment",
    "dispute_open",
    "opt_out",
    "hour_local",
    "weekday",
    "days_to_month_end",
    "payday_signal",
    "invoice_age_days",
)


def _token(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _amount_bucket(amount: float) -> str:
    if amount < 100:
        return "lt_100"
    if amount < 500:
        return "100_500"
    if amount < 1500:
        return "500_1500"
    return "gte_1500"


def build_features(obs: Observation, play: Play) -> dict[str, float]:
    """The only place a feature is constructed (training and serving share it)."""
    raw = asdict(obs)
    values: dict[str, float] = {}

    for key in FEATURE_ALLOW_LIST:
        value = raw.get(key)
        if isinstance(value, bool):
            values[key] = 1.0 if value else 0.0
        elif isinstance(value, (int, float)) and value is not None:
            values[key] = float(value)
        elif isinstance(value, str) and value:
            # One-hot categorical values. Unknown values at serving time become
            # all-zero rows, which is the documented cold-start behaviour.
            values[f"{key}_{_token(value)}"] = 1.0

    values["currency_usd"] = 1.0 if obs.currency.upper() == "USD" else 0.0
    values[f"play_{play.value}"] = 1.0
    # Explicit action interactions let one shared response model learn that the
    # same Play behaves differently by segment, failure class, and amount band.
    values[f"play_{play.value}__segment_{_token(obs.segment)}"] = 1.0
    values[f"play_{play.value}__failure_{_token(obs.failure_class)}"] = 1.0
    values[f"play_{play.value}__amount_{_amount_bucket(obs.amount_due)}"] = 1.0
    values[f"play_{play.value}__payday_{int(obs.payday_signal)}"] = 1.0
    values[f"play_{play.value}__failed_{min(obs.prior_failed_payments, 3)}"] = 1.0
    values[f"play_{play.value}__recoveries_{min(obs.prior_recoveries, 2)}"] = 1.0
    tenure_bucket = "lt_180" if obs.tenure_days < 180 else ("180_365" if obs.tenure_days < 365 else "gte_365")
    values[f"play_{play.value}__tenure_{tenure_bucket}"] = 1.0
    values[f"play_{play.value}__attempt_{min(obs.attempt_count, 2)}"] = 1.0
    values[f"play_{play.value}__method_{_token(obs.payment_method_type or 'none')}"] = 1.0
    return values
