"""Append-only decision, action and outcome logging."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import select
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


async def _resolve_linkage(
    db: AsyncSession,
    case_id: str,
    decision_id: str | None,
    action_id: str | None,
) -> tuple[str | None, str | None]:
    """Attach an outcome to the executed action (and its decision) when callers omit it."""
    if decision_id is None:
        row = (
            await db.execute(
                select(ActionLog.action_id, ActionLog.decision_id)
                .where(
                    ActionLog.case_id == case_id,
                    ActionLog.status == "executed",
                    ActionLog.decision_id.is_not(None),
                )
                .order_by(ActionLog.executed_at.desc().nullslast())
                .limit(1)
            )
        ).first()
        if row is not None:
            action_id = action_id or row[0]
            decision_id = row[1]

    if decision_id is None:
        decision_id = await db.scalar(
            select(DecisionLog.decision_id)
            .where(DecisionLog.case_id == case_id)
            .order_by(DecisionLog.created_at.desc())
            .limit(1)
        )

    if action_id is None and decision_id is not None:
        action_id = await db.scalar(
            select(ActionLog.action_id)
            .where(
                ActionLog.case_id == case_id,
                ActionLog.decision_id == decision_id,
            )
            .order_by(ActionLog.executed_at.desc().nullslast())
            .limit(1)
        )

    return decision_id, action_id


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
    # A dispute is exogenous to our outreach; linking it to the last Play would
    # misattribute the cause. Recovery and escalation outcomes do belong to a Play.
    if outcome_type != "dispute":
        decision_id, action_id = await _resolve_linkage(
            db, state.case_id, decision_id, action_id
        )
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
