"""Append-only decision, action and outcome logging."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.db import AsyncSessionLocal
from config.logger import get_logger
from models.models import (
    ActionLog,
    DecisionLog,
    LearningSample,
    OutcomeLog,
    RecoveryState,
)
from policy.baseline import RulesPolicy
from policy.interfaces import Action, Observation, Outcome, Play
from service.states import save_state

logger = get_logger(__name__)
_policy = RulesPolicy()

_LEARNABLE_OUTCOMES = {"recovered", "unresponsive_timeout"}
_LEARNABLE_PLAYS = {
    "email_link",
    "sms_link",
    "paypal_invoice_reminder",
    "retry_now",
    "retry_payday",
    "update_method_link",
    "discount_link",
}


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

    if outcome_type in {"recovered", "unresponsive_timeout"}:
        try:
            await record_learning_sample(
                state=state,
                outcome_id=outcome_id,
                outcome_type=outcome_type,
                decision_id=decision_id,
                action_id=action_id,
                recovered_amount=(
                    state.recovered_amount
                    if recovered_amount is None
                    else recovered_amount
                ),
                censored=censored,
            )
        except Exception as exc:
            logger.warning("[LEARNING] sample capture failed for %s: %s", outcome_id, exc)

    return outcome_id


async def record_learning_sample(
    *,
    state: RecoveryState,
    outcome_id: str,
    outcome_type: str,
    decision_id: str | None,
    action_id: str | None,
    recovered_amount: float | None,
    censored: bool,
) -> str | None:
    """Append one live learning label. Never raise into the caller."""
    if outcome_type not in _LEARNABLE_OUTCOMES or not decision_id:
        return None

    sample_kind = "recovered" if outcome_type == "recovered" else "timeout"

    async with AsyncSessionLocal() as db:
        decision = await db.get(DecisionLog, decision_id)
        if decision is None:
            logger.warning("[LEARNING] decision %s missing; sample skipped", decision_id)
            return None

        play = decision.approved_action or decision.proposed_action
        if not play or play not in _LEARNABLE_PLAYS:
            return None

        existing = await db.scalar(
            select(LearningSample.sample_id).where(
                LearningSample.decision_id == decision_id,
                LearningSample.sample_kind == sample_kind,
            )
        )
        if existing:
            return existing

        snapshot = decision.state_snapshot_json or {}
        sample = LearningSample(
            sample_id=f"ls_{uuid.uuid4().hex}",
            case_id=state.case_id,
            decision_id=decision_id,
            action_id=action_id,
            outcome_id=outcome_id,
            play=play,
            segment=str(snapshot.get("segment") or "unknown"),
            provenance=(
                "sandbox"
                if (state.case_metadata or {}).get("simulated")
                else "live"
            ),
            source="outcome",
            sample_kind=sample_kind,
            success=outcome_type == "recovered",
            censored=censored,
            recovered_amount=float(recovered_amount or 0.0),
            currency=state.currency or "USD",
            policy_version=decision.policy_version,
            model_version=decision.model_version,
        )
        db.add(sample)
        await db.commit()
        return sample.sample_id


async def log_unresponsive_timeout(
    db: AsyncSession,
    state: RecoveryState,
    *,
    now: datetime | None = None,
) -> str | None:
    """Log a censored no-response outcome for the previous delivered attempt."""
    if (state.attempt_count or 0) <= 0:
        return None
    if state.recovery_status in {"recovered", "closed", "escalated"}:
        return None
    if state.dispute_id or (state.case_metadata or {}).get("opt_out"):
        # A dispute or opt-out is not customer silence.
        return None

    meta = state.case_metadata or {}
    touch = meta.get("last_touch") or {}
    if touch.get("outcome_logged"):
        return None
    if touch.get("attempt") != state.attempt_count:
        return None
    if touch.get("status") not in {"sent", "captured"}:
        # Delivery failed or was never verified. This is not customer silence.
        return None
    if touch.get("play") not in _LEARNABLE_PLAYS:
        return None

    decision_id, action_id = await _resolve_linkage(db, state.case_id, None, None)
    if not decision_id:
        return None

    existing = await db.scalar(
        select(OutcomeLog.outcome_id).where(
            OutcomeLog.decision_id == decision_id,
            OutcomeLog.outcome_type.in_(
                ["recovered", "unresponsive_timeout"]
            ),
        )
    )
    if existing:
        return None

    outcome_id = await log_outcome(
        db,
        state,
        "unresponsive_timeout",
        decision_id=decision_id,
        action_id=action_id,
        censored=True,
    )

    touch["outcome_logged"] = True
    touch["outcome_id"] = outcome_id
    meta["last_touch"] = touch
    state.case_metadata = meta

    # Recommended: make the label visible in the case timeline. This is a
    # system note, not an outreach action. It must not change last_action_taken
    # or recovery_status.
    if state.audit_log is None:
        state.audit_log = []
    state.audit_log.append(
        {
            "event_triggered": "unresponsive_timeout",
            "amount": f"{float(state.amount or 0):,.2f} {state.currency or 'USD'}",
            "recovery_status": state.recovery_status,
            "customer": state.customer,
            "next_contact": None,
            "message": (
                "No payment within the follow-up window. Recorded as a "
                "censored non-response learning sample."
            ),
            "channel": "system",
            "direction": "system",
            "created_at": datetime.now().isoformat(),
        }
    )
    await save_state(state, db)
    return outcome_id
