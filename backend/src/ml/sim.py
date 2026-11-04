"""Calibrated synthetic recovery simulator with potential outcomes.

The simulator is deliberately explicit about what it is: a test rig. Every
episode has a latent persona and a latent outcome for *every* Play, generated
with common random numbers. The policy only ever sees an ``Observation``.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

import numpy as np
import pandas as pd

from policy.interfaces import Observation, Play

ALL_PLAYS: tuple[Play, ...] = (
    Play.NO_CONTACT,
    Play.EMAIL_LINK,
    Play.SMS_LINK,
    Play.PAYPAL_INVOICE_REMINDER,
    Play.RETRY_NOW,
    Play.RETRY_PAYDAY,
    Play.UPDATE_METHOD_LINK,
    Play.DISCOUNT_LINK,
    Play.HUMAN_ESCALATION,
)

# Action costs in USD. Human time dominates; notification channels are cheap.
PLAY_COST: dict[str, float] = {
    Play.NO_CONTACT.value: 0.0,
    Play.EMAIL_LINK.value: 0.002,
    Play.SMS_LINK.value: 0.02,
    Play.PAYPAL_INVOICE_REMINDER.value: 0.003,
    Play.RETRY_NOW.value: 0.0,
    Play.RETRY_PAYDAY.value: 0.0,
    Play.UPDATE_METHOD_LINK.value: 0.0,
    Play.DISCOUNT_LINK.value: 0.0,
    Play.HUMAN_ESCALATION.value: 12.0,
}

DISCOUNT_PCT = 0.05
OPT_OUT_COST = 8.0
DISPUTE_PCT = 0.15

OBSERVATION_FIELDS = (
    "case_id",
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


@dataclass(frozen=True)
class Persona:
    key: str
    label: str
    base_pay: float
    amount_sensitivity: float
    dispute_mult: float
    optout_mult: float
    speed_days: float
    tenure: int
    prior_success: int
    prior_failed: int
    prior_recoveries: int
    method_age: int


PERSONAS: dict[str, Persona] = {
    "reliable_forgetful": Persona(
        "reliable_forgetful", "Reliable but forgetful", 0.20, 0.08, 0.6, 0.7, 3.0,
        480, 14, 1, 2, 420,
    ),
    "cash_strapped": Persona(
        "cash_strapped", "Cash-strapped until payday", 0.13, 0.22, 0.8, 1.0, 5.0,
        220, 6, 3, 1, 300,
    ),
    "expired_card": Persona(
        "expired_card", "Expired or replaced payment method", 0.04, 0.05, 0.5, 0.6, 6.0,
        520, 22, 2, 0, 1_500,
    ),
    "b2b_ap": Persona(
        "b2b_ap", "B2B accounts payable", 0.18, 0.12, 0.5, 0.4, 8.0,
        760, 31, 1, 3, 900,
    ),
    "high_value": Persona(
        "high_value", "High-value account at risk", 0.16, 0.05, 0.7, 0.5, 4.0,
        930, 42, 0, 1, 600,
    ),
    "dispute_prone": Persona(
        "dispute_prone", "Dispute-prone", 0.14, 0.18, 2.5, 1.5, 4.0,
        310, 4, 6, 0, 380,
    ),
    "hard_decline": Persona(
        "hard_decline", "Hard decline / blocked method", 0.015, 0.02, 0.9, 0.5, 8.0,
        120, 1, 5, 0, 700,
    ),
    "serial_ptp": Persona(
        "serial_ptp", "Serial promise-to-pay breaker", 0.12, 0.15, 1.0, 1.1, 6.0,
        360, 8, 7, 2, 450,
    ),
}

PERSONA_KEYS = tuple(PERSONAS)

# Log-odds response offsets when the *reason* mechanism dominates.
REASON_OFFSETS: dict[str, dict[str, float]] = {
    "soft": {
        "no_contact": -0.40, "email_link": 0.50, "sms_link": 0.35,
        "paypal_invoice_reminder": -0.60, "retry_now": 0.80, "retry_payday": 1.10,
        "update_method_link": -0.20, "discount_link": 0.30, "human_escalation": 0.40,
    },
    "transient": {
        "no_contact": -0.30, "email_link": 0.40, "sms_link": 0.30,
        "paypal_invoice_reminder": -0.50, "retry_now": 1.20, "retry_payday": 0.90,
        "update_method_link": -0.10, "discount_link": 0.20, "human_escalation": 0.30,
    },
    "hard": {
        "no_contact": -0.80, "email_link": 0.10, "sms_link": 0.00,
        "paypal_invoice_reminder": -0.80, "retry_now": -0.60, "retry_payday": -0.80,
        "update_method_link": 1.30, "discount_link": -0.70, "human_escalation": 0.20,
    },
    "unknown": {
        "no_contact": -0.40, "email_link": 0.70, "sms_link": 0.60,
        "paypal_invoice_reminder": -0.30, "retry_now": 0.40, "retry_payday": 0.30,
        "update_method_link": 0.30, "discount_link": 0.10, "human_escalation": 0.50,
    },
}

# Log-odds response offsets when the *persona* mechanism dominates.
PERSONA_OFFSETS: dict[str, dict[str, float]] = {
    "reliable_forgetful": {
        "no_contact": -0.20, "email_link": 0.90, "sms_link": 0.60,
        "paypal_invoice_reminder": 0.00, "retry_now": 0.40, "retry_payday": 0.50,
        "update_method_link": 0.10, "discount_link": -0.40, "human_escalation": -0.10,
    },
    "cash_strapped": {
        "no_contact": -0.40, "email_link": 0.30, "sms_link": 0.40,
        "paypal_invoice_reminder": 0.00, "retry_now": 0.20, "retry_payday": 1.20,
        "update_method_link": -0.10, "discount_link": 0.90, "human_escalation": 0.10,
    },
    "expired_card": {
        "no_contact": -0.80, "email_link": 0.30, "sms_link": 0.20,
        "paypal_invoice_reminder": -0.20, "retry_now": -0.30, "retry_payday": -0.40,
        "update_method_link": 1.60, "discount_link": -0.50, "human_escalation": 0.20,
    },
    "b2b_ap": {
        "no_contact": -0.40, "email_link": 0.60, "sms_link": -0.40,
        "paypal_invoice_reminder": 1.30, "retry_now": 0.20, "retry_payday": 0.50,
        "update_method_link": -0.20, "discount_link": 0.10, "human_escalation": 0.40,
    },
    "high_value": {
        "no_contact": -0.30, "email_link": 0.50, "sms_link": 0.30,
        "paypal_invoice_reminder": 0.20, "retry_now": 0.30, "retry_payday": 0.40,
        "update_method_link": 0.10, "discount_link": 0.20, "human_escalation": 1.00,
    },
    "dispute_prone": {
        "no_contact": 0.40, "email_link": -0.50, "sms_link": -0.90,
        "paypal_invoice_reminder": -0.30, "retry_now": -0.30, "retry_payday": -0.20,
        "update_method_link": -0.10, "discount_link": -0.60, "human_escalation": -0.50,
    },
    "hard_decline": {
        "no_contact": -1.20, "email_link": -0.20, "sms_link": -0.40,
        "paypal_invoice_reminder": -0.50, "retry_now": -1.00, "retry_payday": -1.10,
        "update_method_link": 0.90, "discount_link": -0.80, "human_escalation": -0.20,
    },
    "serial_ptp": {
        "no_contact": -0.50, "email_link": 0.60, "sms_link": 0.50,
        "paypal_invoice_reminder": 0.00, "retry_now": 0.20, "retry_payday": 0.40,
        "update_method_link": 0.00, "discount_link": 0.40, "human_escalation": 0.50,
    },
}

OPT_OUT_RATE = {
    "no_contact": 0.003, "email_link": 0.008, "sms_link": 0.030,
    "paypal_invoice_reminder": 0.006, "retry_now": 0.004, "retry_payday": 0.005,
    "update_method_link": 0.005, "discount_link": 0.010, "human_escalation": 0.020,
}
DISPUTE_RATE = {
    "no_contact": 0.002, "email_link": 0.004, "sms_link": 0.006,
    "paypal_invoice_reminder": 0.003, "retry_now": 0.003, "retry_payday": 0.003,
    "update_method_link": 0.004, "discount_link": 0.006, "human_escalation": 0.010,
}

HOLDOUT_PERSONAS = {
    "reason": {"serial_ptp"},
    "persona": {"dispute_prone"},
}


@dataclass(frozen=True)
class World:
    index: int
    mechanism: str  # reason | persona
    seed: int
    response_scale: float = 1.0
    holdout: frozenset[str] = field(default_factory=frozenset)

    @property
    def name(self) -> str:
        return f"{self.mechanism}-w{self.index}"


@dataclass(frozen=True)
class SimConfig:
    seed: int = 42
    train_per_world: int = 9_000
    val_per_world: int = 3_000
    test_per_world: int = 5_000
    rct_per_world: int = 3_000


def _seed(*parts: object) -> int:
    """Stable across processes; Python's built-in hash is salted per run."""
    payload = "|".join(str(part) for part in parts).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _sigmoid(value: float) -> float:
    value = max(-30.0, min(30.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def _logit(value: float) -> float:
    value = max(1e-6, min(1 - 1e-6, value))
    return math.log(value / (1 - value))


def _choice(rng: random.Random, weights: dict[str, float]) -> str:
    total = sum(weights.values())
    draw = rng.random() * total
    upto = 0.0
    for key, weight in weights.items():
        upto += weight
        if draw <= upto:
            return key
    return next(reversed(weights))


def _mix_uniform(weights: dict[str, float], epsilon: float = 0.12) -> dict[str, float]:
    plays = [play.value for play in ALL_PLAYS]
    return {
        play: (1.0 - epsilon) * weights.get(play, 0.0) + epsilon / len(plays)
        for play in plays
    }


def behavior_weights(obs: Observation) -> dict[str, float]:
    """Deliberately confounded behaviour policy used for the training log."""
    if obs.segment == "b2b":
        weights = {
            "paypal_invoice_reminder": 0.55, "email_link": 0.20, "sms_link": 0.03,
            "retry_now": 0.04, "retry_payday": 0.05, "update_method_link": 0.02,
            "discount_link": 0.01, "human_escalation": 0.05, "no_contact": 0.05,
        }
    elif obs.failure_class == "hard":
        weights = {
            "update_method_link": 0.45, "email_link": 0.12, "sms_link": 0.04,
            "retry_now": 0.03, "retry_payday": 0.03, "human_escalation": 0.08,
            "paypal_invoice_reminder": 0.01, "discount_link": 0.02, "no_contact": 0.22,
        }
    elif obs.segment == "subscription":
        weights = {
            "update_method_link": 0.45, "retry_payday": 0.15, "email_link": 0.15,
            "sms_link": 0.05, "retry_now": 0.03, "human_escalation": 0.05,
            "paypal_invoice_reminder": 0.01, "discount_link": 0.02, "no_contact": 0.09,
        }
    elif obs.segment == "checkout":
        weights = {
            "discount_link": 0.40, "email_link": 0.20, "sms_link": 0.15,
            "retry_now": 0.05, "retry_payday": 0.03, "update_method_link": 0.02,
            "human_escalation": 0.05, "paypal_invoice_reminder": 0.01, "no_contact": 0.09,
        }
    elif obs.failure_class in {"soft", "transient"}:
        weights = {
            "retry_payday": 0.45, "retry_now": 0.15, "email_link": 0.15,
            "sms_link": 0.06, "discount_link": 0.05, "human_escalation": 0.03,
            "update_method_link": 0.03, "paypal_invoice_reminder": 0.01, "no_contact": 0.07,
        }
    else:
        weights = {
            "email_link": 0.30, "sms_link": 0.15, "human_escalation": 0.10,
            "retry_now": 0.10, "update_method_link": 0.10, "retry_payday": 0.05,
            "discount_link": 0.05, "paypal_invoice_reminder": 0.05, "no_contact": 0.10,
        }
    return _mix_uniform(weights)


def _persona_for(rng: random.Random, world: World, include_holdout: bool) -> Persona:
    allowed = [p for p in PERSONA_KEYS if include_holdout or p not in world.holdout]
    return PERSONAS[rng.choice(allowed)]


def _failure_class(persona: Persona) -> str:
    if persona.key in {"expired_card", "hard_decline"}:
        return "hard"
    if persona.key == "reliable_forgetful":
        return "transient"
    if persona.key in {"high_value", "b2b_ap"}:
        return "unknown"
    return "soft"


def _make_episode(world: World, index: int, include_holdout: bool) -> tuple[dict, Persona]:
    rng = random.Random(world.seed * 1_000_003 + index)
    persona = _persona_for(rng, world, include_holdout)
    failure_class = _failure_class(persona)

    if persona.key == "b2b_ap":
        case_type, segment = "overdue_invoice", "b2b"
        amount = min(15_000.0, rng.lognormvariate(math.log(1_200), 0.7))
        days_past_due = rng.randint(3, 45)
        method = "paypal"
    elif persona.key == "expired_card":
        case_type, segment = "failed_subscription", "subscription"
        amount = min(1_500.0, rng.lognormvariate(math.log(45), 0.6))
        days_past_due = rng.randint(1, 7)
        method = "card"
    elif persona.key in {"reliable_forgetful", "high_value"} and rng.random() < 0.15:
        case_type, segment = "abandoned_checkout", "checkout"
        amount = min(2_500.0, rng.lognormvariate(math.log(180), 0.8))
        days_past_due = 0
        method = "card"
    else:
        case_type, segment = "failed_payment", "card"
        amount = min(5_000.0, rng.lognormvariate(math.log(120), 0.9))
        days_past_due = rng.randint(0, 10)
        method = rng.choice(["card", "card", "paypal"])

    if persona.key == "high_value":
        amount = max(amount, 600.0)
    amount = round(max(5.0, amount), 2)

    day_of_month = rng.randint(1, 28)
    days_to_month_end = max(0, 28 - day_of_month)
    payday_signal = day_of_month <= 3 or day_of_month >= 26
    attempt_count = 0
    if rng.random() < 0.22:
        attempt_count = 1
    if persona.key == "serial_ptp" and rng.random() < 0.45:
        attempt_count = min(2, attempt_count + 1)

    failure_codes = {
        "soft": "INSUFFICIENT_FUNDS",
        "transient": "PROCESSOR_TIMEOUT",
        "hard": "CARD_EXPIRED" if persona.key == "expired_card" else "PAYMENT_DENIED",
        "unknown": "PAYMENT_DENIED",
    }
    obs = Observation(
        case_id=f"{world.name}-{index:06d}",
        currency="USD",
        amount_due=amount,
        days_past_due=days_past_due,
        failure_code=failure_codes[failure_class],
        failure_class=failure_class,  # type: ignore[arg-type]
        payment_method_type=method,
        method_age_days=max(1, persona.method_age + rng.randint(-60, 60)),
        attempt_count=attempt_count,
        contact_count_7d=rng.choices([0, 1, 2], weights=[0.80, 0.15, 0.05])[0],
        last_contact_hours=(rng.choice([None, 24.0, 48.0, 96.0])),
        prior_successful_payments=max(0, persona.prior_success + rng.randint(-2, 2)),
        prior_failed_payments=max(0, persona.prior_failed + rng.randint(-1, 1)),
        prior_recoveries=max(0, persona.prior_recoveries + rng.choice([-1, 0, 0, 1])),
        tenure_days=max(1, persona.tenure + rng.randint(-40, 40)),
        segment=segment,
        dispute_open=bool(persona.key == "dispute_prone" and rng.random() < 0.02),
        opt_out=False,
        hour_local=rng.randint(9, 20),
        weekday=rng.randint(0, 6),
        days_to_month_end=days_to_month_end,
        payday_signal=payday_signal,
        invoice_age_days=days_past_due if case_type == "overdue_invoice" else None,
    )
    row = {name: getattr(obs, name) for name in OBSERVATION_FIELDS}
    row["case_type"] = case_type
    return row, persona


def _play_offset(
    play: Play, obs: Observation, persona: Persona, world: World
) -> float:
    key = play.value
    if world.mechanism == "reason":
        reason, person = 0.75, 0.25
    else:
        reason, person = 0.30, 0.70

    offset = (
        reason * REASON_OFFSETS[obs.failure_class][key]
        + person * PERSONA_OFFSETS[persona.key][key]
    )

    if key == "paypal_invoice_reminder":
        offset += 1.0 if obs.segment == "b2b" else -0.8
        if obs.invoice_age_days:
            offset += min(0.4, 0.01 * obs.invoice_age_days)
    elif key == "update_method_link":
        offset += 0.6 if obs.segment == "subscription" else -0.4
    elif key == "discount_link":
        offset += 0.7 if obs.segment == "checkout" else -1.2
        offset += 0.2 if obs.amount_due > 500 else 0.0
    elif key == "retry_payday":
        offset += 0.9 if obs.payday_signal else -0.3
        offset -= 0.30 * obs.attempt_count
    elif key == "human_escalation":
        offset += 0.4 if obs.amount_due > 500 else -0.2
    elif key in {"retry_now", "retry_payday"}:
        offset -= 0.25 * obs.attempt_count

    offset -= 0.12 * obs.attempt_count
    offset -= 0.10 * obs.contact_count_7d
    offset -= persona.amount_sensitivity * math.log1p(obs.amount_due / 100.0)
    return offset * world.response_scale


def _common_draws(rng: random.Random) -> dict:
    return {
        "pay": rng.random(),
        "partial": rng.random(),
        "partial_size": rng.random(),
        "day": rng.random(),
        "opt_out": rng.random(),
        "dispute": rng.random(),
        "noise": [rng.gauss(0.0, 0.18) for _ in ALL_PLAYS],
    }


def _outcome(
    play: Play,
    obs: Observation,
    persona: Persona,
    world: World,
    draws: dict,
    play_index: int,
) -> dict:
    p_pay = _sigmoid(
        _logit(persona.base_pay)
        + _play_offset(play, obs, persona, world)
        + draws["noise"][play_index]
    )
    paid = draws["pay"] < p_pay

    discount_cost = 0.0
    recovered = 0.0
    paid_day = None
    if paid:
        factor = 1.0
        partial_rate = 0.20 if obs.segment == "b2b" else 0.12
        if draws["partial"] < partial_rate:
            factor = 0.25 + 0.55 * draws["partial_size"]
        if play == Play.DISCOUNT_LINK:
            discount_cost = round(obs.amount_due * DISCOUNT_PCT, 2)
        recovered = round(obs.amount_due * factor - discount_cost, 2)
        speed = persona.speed_days * (1.25 if obs.segment == "b2b" else 1.0)
        horizon = 30 if obs.segment == "b2b" else 14
        paid_day = min(horizon, 1 + int(-math.log(max(1e-6, draws["day"])) * speed))

    opt_out = draws["opt_out"] < (
        OPT_OUT_RATE[play.value]
        * persona.optout_mult
        * (1.0 + 0.15 * obs.contact_count_7d)
    )
    dispute = draws["dispute"] < (
        DISPUTE_RATE[play.value]
        * persona.dispute_mult
        * (1.0 + 0.08 * obs.attempt_count)
    )
    cost = PLAY_COST[play.value] + discount_cost
    collateral = (OPT_OUT_COST if opt_out else 0.0) + (
        DISPUTE_PCT * obs.amount_due if dispute else 0.0
    )
    net = recovered - cost - collateral
    return {
        "action": play.value,
        "p_pay_true": p_pay,
        "paid": paid,
        "recovered_amount": recovered,
        "paid_day": paid_day,
        "opt_out": opt_out,
        "dispute": dispute,
        "action_cost": PLAY_COST[play.value],
        "discount_cost": discount_cost,
        "collateral": collateral,
        "net": net,
    }


def _attribution(assigned: dict, control: dict) -> str:
    if not assigned["paid"] and not control["paid"]:
        return "not_recovered"
    if assigned["paid"] and not control["paid"]:
        return "system_recovered"
    if assigned["paid"] and control["paid"]:
        if (
            assigned["paid_day"] is not None
            and control["paid_day"] is not None
            and assigned["paid_day"] < control["paid_day"]
            and assigned["recovered_amount"] >= control["recovered_amount"] * 0.99
        ):
            return "ambiguous"
        return "customer_self_recovered"
    return "not_recovered"


def _observed_row(
    obs_row: dict,
    persona: Persona,
    world: World,
    action: Play,
    propensity: float,
) -> dict:
    obs = Observation(
        **{name: obs_row[name] for name in OBSERVATION_FIELDS}
    )
    rng = random.Random(_seed(world.seed, obs_row["case_id"], "outcomes"))
    draws = _common_draws(rng)
    outcomes = {
        play: _outcome(play, obs, persona, world, draws, i)
        for i, play in enumerate(ALL_PLAYS)
    }
    assigned = outcomes[action]
    control = outcomes[Play.NO_CONTACT]
    row = dict(obs_row)
    row.update(
        {
            "mechanism": world.mechanism,
            "world": world.index,
            "action": action.value,
            "propensity": propensity,
            **{k: v for k, v in assigned.items() if k != "action"},
            "no_contact_paid": control["paid"],
            "no_contact_recovered": control["recovered_amount"],
            "no_contact_day": control["paid_day"],
            "attribution": _attribution(assigned, control),
        }
    )
    return row


def _potential_rows(
    obs_row: dict, persona: Persona, world: World
) -> list[dict]:
    obs = Observation(**{name: obs_row[name] for name in OBSERVATION_FIELDS})
    rng = random.Random(_seed(world.seed, obs_row["case_id"], "outcomes"))
    draws = _common_draws(rng)
    rows = []
    for i, play in enumerate(ALL_PLAYS):
        outcome = _outcome(play, obs, persona, world, draws, i)
        row = dict(obs_row)
        row.update({"mechanism": world.mechanism, "world": world.index, **outcome})
        rows.append(row)
    return rows


def _world(mechanism: str, index: int, config: SimConfig, scale: float = 1.0) -> World:
    return World(
        index=index,
        mechanism=mechanism,
        seed=config.seed + (100 * index) + (17 if mechanism == "persona" else 0),
        response_scale=scale,
        holdout=frozenset(HOLDOUT_PERSONAS[mechanism]),
    )


def generate_dataset(config: SimConfig | None = None) -> dict:
    """Generate behaviour/RCT logs and held-out potential outcomes."""
    config = config or SimConfig()
    train_worlds = [
        _world(mechanism, index, config)
        for mechanism in ("reason", "persona")
        for index in (1, 2, 3)
    ]
    val_worlds = [_world(mechanism, 4, config) for mechanism in ("reason", "persona")]
    test_worlds = [_world(mechanism, 5, config) for mechanism in ("reason", "persona")]

    train: list[dict] = []
    val: list[dict] = []
    rct: list[dict] = []
    test_obs: list[dict] = []
    test_potential: list[dict] = []

    for world in train_worlds:
        for i in range(config.train_per_world):
            obs_row, persona = _make_episode(world, i, include_holdout=False)
            weights = behavior_weights(Observation(**{n: obs_row[n] for n in OBSERVATION_FIELDS}))
            action = Play(_choice(random.Random(_seed(world.seed, i, "action")), weights))
            train.append(_observed_row(obs_row, persona, world, action, weights[action.value]))
        if world.index <= 2:
            for i in range(config.rct_per_world):
                obs_row, persona = _make_episode(world, i, include_holdout=False)
                action = Play(ALL_PLAYS[random.Random(_seed(world.seed, i, "rct")).randrange(len(ALL_PLAYS))])
                rct.append(_observed_row(obs_row, persona, world, action, 1.0 / len(ALL_PLAYS)))

    for world in val_worlds:
        for i in range(config.val_per_world):
            obs_row, persona = _make_episode(world, i, include_holdout=False)
            weights = behavior_weights(Observation(**{n: obs_row[n] for n in OBSERVATION_FIELDS}))
            action = Play(_choice(random.Random(_seed(world.seed, i, "action")), weights))
            val.append(_observed_row(obs_row, persona, world, action, weights[action.value]))

    for world in test_worlds:
        for i in range(config.test_per_world):
            obs_row, persona = _make_episode(world, i, include_holdout=True)
            obs_row["mechanism"] = world.mechanism
            obs_row["world"] = world.index
            test_obs.append(obs_row)
            test_potential.extend(_potential_rows(obs_row, persona, world))

    meta = {
        "seed": config.seed,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "train_rows": len(train),
        "val_rows": len(val),
        "test_episodes": len(test_obs),
        "test_potential_rows": len(test_potential),
        "rct_rows": len(rct),
        "mechanisms": ["reason", "persona"],
        "holdout_personas": {k: sorted(v) for k, v in HOLDOUT_PERSONAS.items()},
        "train_personas": sorted(set(p for p in PERSONA_KEYS if p not in HOLDOUT_PERSONAS["reason"] | HOLDOUT_PERSONAS["persona"])),
        "action_set": [p.value for p in ALL_PLAYS],
        "contract": "Observation -> eligible Play -> guardrails -> one action",
    }
    # Hash only stable fields so the same seed yields the same dataset ID.
    stable = {key: value for key, value in meta.items() if key != "generated_at"}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:16]
    meta["dataset_hash"] = digest

    return {
        "train": pd.DataFrame(train),
        "val": pd.DataFrame(val),
        "rct": pd.DataFrame(rct),
        "test_obs": pd.DataFrame(test_obs),
        "test_potential": pd.DataFrame(test_potential),
        "meta": meta,
    }


def generate_sensitivity(config: SimConfig | None = None, n: int = 2_000) -> dict[str, pd.DataFrame]:
    """Held-out worlds with optimistic/base/pessimistic response curves."""
    config = config or SimConfig()
    result: dict[str, pd.DataFrame] = {}
    for label, scale in (("optimistic", 1.20), ("base", 1.00), ("pessimistic", 0.80)):
        rows: list[dict] = []
        for mechanism in ("reason", "persona"):
            world = _world(mechanism, 5, config, scale=scale)
            for i in range(n // 2):
                obs_row, persona = _make_episode(world, i, include_holdout=True)
                rows.extend(_potential_rows(obs_row, persona, world))
        result[label] = pd.DataFrame(rows)
    return result
