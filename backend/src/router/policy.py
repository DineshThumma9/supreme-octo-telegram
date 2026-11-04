"""Agent Lab API: score a case, inspect the model, read the benchmark."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config.db import get_db
from ml.runtime import decide, evaluation, model_info
from policy.baseline import observation_from_state
from policy.guardrails import apply_guardrails
from policy.interfaces import Observation
from service.states import load_state

router = APIRouter(prefix="/api/policy", tags=["policy"])


class PolicyScoreRequest(BaseModel):
    case_id: str | None = None
    currency: str = "USD"
    amount_due: float = 125.0
    days_past_due: int = 0
    failure_code: str | None = "INSUFFICIENT_FUNDS"
    failure_class: Literal["soft", "hard", "transient", "unknown"] = "soft"
    payment_method_type: str | None = "card"
    method_age_days: int | None = 120
    attempt_count: int = 0
    contact_count_7d: int = 0
    last_contact_hours: float | None = None
    prior_successful_payments: int = 4
    prior_failed_payments: int = 1
    prior_recoveries: int = 1
    tenure_days: int = 180
    segment: str = "card"
    dispute_open: bool = False
    opt_out: bool = False
    hour_local: int = 12
    weekday: int = 1
    days_to_month_end: int = 10
    payday_signal: bool = False
    invoice_age_days: int | None = None
    simulated: bool = True


@router.post("/score")
async def score_case(payload: PolicyScoreRequest, db=Depends(get_db)):
    state = None
    if payload.case_id:
        state = await load_state(payload.case_id, db)
        if state is None:
            raise HTTPException(status_code=404, detail="Case not found")
        obs = observation_from_state(state)
    else:
        values = payload.model_dump(exclude={"case_id", "simulated"})
        obs = Observation(case_id="api_score", **values)

    decision = decide(state, obs)
    approved = decision.action
    guardrail = "not_evaluated"
    if state is not None:
        guard = apply_guardrails(state, obs, decision.action)
        approved = guard.action
        guardrail = f"{guard.result}:{guard.rule}"

    return {
        "case_id": obs.case_id,
        "proposed_action": decision.action.play.value,
        "approved_action": approved.play.value,
        "guardrail": guardrail,
        "p_pay": decision.p_pay,
        "expected_recovered": decision.expected_recovered,
        "expected_cost": decision.expected_cost,
        "expected_net": decision.expected_net,
        "alternatives": decision.alternatives,
        "explanation": decision.explanation,
        "policy_version": decision.policy_version,
        "model_version": decision.model_version,
        "exploration": decision.exploration,
        "observation": obs.__dict__,
    }


@router.get("/model")
async def policy_model():
    return model_info()


@router.get("/evaluation")
async def policy_evaluation():
    report = evaluation()
    if report is None:
        raise HTTPException(status_code=404, detail="No evaluation artifact; run scripts/train_policy.py")
    return report
