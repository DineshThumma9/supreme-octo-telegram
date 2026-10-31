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

    values["currency_usd"] = 1.0 if obs.currency.upper() == "USD" else 0.0
    values[f"play_{play.value}"] = 1.0
    return values
