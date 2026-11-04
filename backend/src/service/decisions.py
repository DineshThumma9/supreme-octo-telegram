"""Append-only decision, action and outcome logging."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from models.models import ActionLog, DecisionLog, OutcomeLog, RecoveryState
from policy.baseline import RulesPolicy
from policy.interfaces import Action, Observation, Outcome, Play

_policy = RulesPolicy()


def _snapshot(obs: Observation) -> tuple[dict, str]:
    payload = asdict(obs)
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return payload, hashlib.sha256(encoded).hexdigest()


async def log_decision(
    db: AsyncSession,
    state: RecoveryState,
    obs: Observation,
    proposed: Action,
    approved: Action,
    guardrail_result: str,
    eligible: list[Play],
    trigger_event_id: str | None = None,
    alternatives: dict | None = None,
    p_pay: float | None = None,
    expected_recovered: float | None = None,
    expected_cost: float | None = None,
    expected_net: float | None = None,
    policy_version: str | None = None,
    model_version: str | None = None,
    exploration: bool = False,
) -> str:
    decision_id = f"dec_{uuid.uuid4().hex}"
    snapshot, snapshot_hash = _snapshot(obs)
    entry = DecisionLog(
        decision_id=decision_id,
        case_id=state.case_id,
        trigger_event_id=trigger_event_id,
        state_snapshot_json=snapshot,
        state_snapshot_hash=snapshot_hash,
        eligible_actions_json=[play.value for play in eligible],
        proposed_action=proposed.play.value,
        approved_action=approved.play.value,
        p_pay=p_pay,
        expected_recovered=expected_recovered,
        expected_cost=expected_cost,
        expected_net=expected_net,
        alternatives_json=alternatives or {play.value: 0.0 for play in eligible},
        exploration=exploration,
        guardrail_result=guardrail_result,
        policy_version=policy_version or _policy.policy_version,
        model_version=model_version or "none",
    )
    db.add(entry)
    await db.commit()
    return decision_id


async def log_action(
    db: AsyncSession,
    state: RecoveryState,
    decision_id: str | None,
    action: Action,
    channel: str | None,
    provider_ref: str | None = None,
    status: str = "executed",
    error: str | None = None,
) -> str:
    action_id = f"act_{uuid.uuid4().hex}"
    db.add(
        ActionLog(
            action_id=action_id,
            decision_id=decision_id,
            case_id=state.case_id,
            play=action.play.value,
            channel=channel,
            provider="paypal",
            provider_ref=provider_ref,
            template_id=action.template_id,
            discount_pct=action.discount_pct,
            scheduled_for=action.scheduled_for,
            executed_at=datetime.now() if status == "executed" else None,
            status=status,
            error=error,
        )
    )
    await db.commit()
    return action_id


async def log_outcome(
    db: AsyncSession,
    state: RecoveryState,
    outcome_type: str,
    recovered_amount: float | None = None,
    decision_id: str | None = None,
    action_id: str | None = None,
    dispute: bool = False,
    opt_out: bool = False,
    censored: bool = False,
) -> str:
    outcome_id = f"out_{uuid.uuid4().hex}"
    db.add(
        OutcomeLog(
            outcome_id=outcome_id,
            decision_id=decision_id,
            action_id=action_id,
            case_id=state.case_id,
            outcome_type=outcome_type,
            recovered_amount=float(
                state.recovered_amount if recovered_amount is None else recovered_amount
            ),
            currency=state.currency or "USD",
            opt_out=opt_out,
            dispute=dispute,
            censored=censored,
            observation_window_end=datetime.now(),
        )
    )
    await db.commit()
    return outcome_id
