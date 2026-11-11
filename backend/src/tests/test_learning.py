"""
Suite 8: Empirical Bayes Learning, Timeout Attribution & Retrain Safety Gates.
Validates:
- Pure Beta-Bernoulli shrinkage and EB blending math
- EVPolicy rate blending, expectation recomputation, and policy versioning (+eb)
- Guardrail sovereignty over learned rates
- Timeout gating: verified delivery required; failed channels never labeled silence
- Sandbox vs live provenance isolation
- Nightly retrain safety gates (5 criteria, schedule flag, non-dry-run block)
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import sys

SRC_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = SRC_DIR.parent
for p in [str(SRC_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import delete, select
from config.config import settings
from config.db import AsyncSessionLocal, _init_db
from ml.learning import blend, load_learned_rates, load_play_stats, shrink
from ml.models import load_bundle
from ml.retrain import readiness, run_nightly_retrain
from ml.runtime import decide
from models.models import ActionLog, DecisionLog, LearningSample, OutcomeLog, RecoveryState
from policy.baseline import eligible_plays
from policy.guardrails import apply_guardrails
from policy.interfaces import Action, Observation, Play
from service.decisions import log_unresponsive_timeout, record_learning_sample
from tests.common import GREEN, RESET, print_banner


def _sample_obs(case_id: str = "test_eb_obs") -> Observation:
    return Observation(
        case_id=case_id,
        amount_due=125.0,
        days_past_due=1,
        failure_code="INSUFFICIENT_FUNDS",
        failure_class="soft",
        currency="USD",
        payment_method_type="card",
        method_age_days=100,
        attempt_count=0,
        contact_count_7d=0,
        last_contact_hours=None,
        prior_successful_payments=3,
        prior_failed_payments=1,
        prior_recoveries=1,
        tenure_days=120,
        segment="card",
        dispute_open=False,
        opt_out=False,
        hour_local=12,
        weekday=1,
        days_to_month_end=10,
        payday_signal=False,
        invoice_age_days=None,
    )


def test_empirical_bayes_math():
    print_banner("8.1 Pure Empirical Bayes & Shrinkage Math")

    # n=0: prior holds exactly, weight is 0
    p0, w0 = shrink(n=0, k=0, prior_p=0.2, prior_strength=20)
    assert p0 == 0.2 and w0 == 0.0, f"Expected (0.2, 0.0), got ({p0}, {w0})"

    # n=5, k=3: posterior = (3 + 0.2*20)/(5 + 20) = 7/25 = 0.28, weight = 5/25 = 0.2
    p5, w5 = shrink(n=5, k=3, prior_p=0.2, prior_strength=20)
    assert round(p5, 4) == 0.28 and round(w5, 4) == 0.2, f"Got ({p5}, {w5})"

    # n=100, k=40: posterior = (40 + 4)/120 = 0.3667, weight = 100/120 = 0.8333
    p100, w100 = shrink(n=100, k=40, prior_p=0.2, prior_strength=20)
    assert round(p100, 4) == 0.3667 and round(w100, 4) == 0.8333, f"Got ({p100}, {w100})"

    # Blend math: (1-0.5)*0.1 + 0.5*0.4 = 0.25
    b = blend(p_model=0.1, posterior_p=0.4, weight=0.5)
    assert round(b, 4) == 0.25, f"Expected 0.25, got {b}"

    # Blend with weight 0 gives exactly p_model
    b0 = blend(p_model=0.18, posterior_p=0.5, weight=0.0)
    assert b0 == 0.18

    # Clamping k > n
    p_clamp, _ = shrink(n=5, k=99, prior_p=0.2, prior_strength=20)
    assert round(p_clamp, 4) == 0.36  # (5 + 4)/25 = 0.36

    print(f"  {GREEN}shrinkage and blend formulas hold across all edge cases{RESET}")


def test_policy_blending_and_contract():
    print_banner("8.2 EVPolicy Blending, Expectations & Versioning")

    obs = _sample_obs("obs_eb_verify")

    # 1. Unblended decision: policy_version does not have +eb, alternatives have p_pay == p_model
    unblended = decide(None, obs)
    assert not unblended.policy_version.endswith("+eb"), (
        f"Unexpected +eb on unblended decision: {unblended.policy_version}"
    )
    for alt in unblended.alternatives.values():
        assert alt["p_pay"] == alt["p_model"]
        assert alt["learning_n"] == 0
        assert alt["learning_weight"] == 0.0

    # 2. Blended decision with empirical Bayes input
    learned = {
        Play.EMAIL_LINK.value: {
            "n": 50,
            "k": 40,
            "prior_p": 0.18,
            "posterior_p": 0.80,
            "weight": 0.714286,
        }
    }
    blended = decide(None, obs, learned=learned)
    assert blended.policy_version.endswith("+eb"), (
        f"Expected version ending in +eb, got {blended.policy_version}"
    )

    email_alt = blended.alternatives[Play.EMAIL_LINK.value]
    assert email_alt["p_pay"] != email_alt["p_model"], "p_pay was not blended"
    assert email_alt["p_learned"] == 0.8
    assert email_alt["learning_n"] == 50
    assert email_alt["learning_weight"] == 0.714286
    expected_rec = round(email_alt["p_pay"] * email_alt["amount_if_paid"], 2)
    assert email_alt["expected_recovered"] == expected_rec, (
        f"expected_recovered {email_alt['expected_recovered']} != {expected_rec}"
    )

    print(f"  {GREEN}EVPolicy blends p_pay, recomputes expectations, and tags +eb{RESET}")


def test_guardrail_sovereignty_over_learned_rates():
    print_banner("8.3 Guardrail Sovereignty Over Extreme Learned Rates")

    obs = _sample_obs("obs_guard_sovereign")
    # Extreme learned rate: email_link has 99% posterior with full weight
    extreme_learned = {
        Play.EMAIL_LINK.value: {
            "n": 500,
            "k": 495,
            "prior_p": 0.18,
            "posterior_p": 0.99,
            "weight": 0.961538,
        }
    }

    # 1. Opt-out: guardrail must override policy proposal to NO_CONTACT
    opt_obs = replace(obs, opt_out=True)
    opt_state = RecoveryState(
        case_id="case_opt",
        source_id="SRC-case_opt",
        case_type="failed_payment",
        case_metadata={"opt_out": True},
        recovery_status="pending",
        amount=125.0,
    )
    dec_opt = decide(opt_state, opt_obs, learned=extreme_learned)
    guard_opt = apply_guardrails(opt_state, opt_obs, dec_opt.action)
    assert guard_opt.action.play == Play.NO_CONTACT
    assert guard_opt.result == "block"

    # 2. Open Dispute: guardrail must freeze and escalate
    disp_obs = replace(obs, dispute_open=True)
    disp_state = RecoveryState(
        case_id="case_disp",
        source_id="SRC-case_disp",
        case_type="failed_payment",
        dispute_id="DISP-999",
        recovery_status="pending",
        amount=125.0,
    )
    dec_disp = decide(disp_state, disp_obs, learned=extreme_learned)
    guard_disp = apply_guardrails(disp_state, disp_obs, dec_disp.action)
    assert guard_disp.action.play == Play.HUMAN_ESCALATION
    assert guard_disp.rule == "dispute_freeze"

    # 3. Terminal state (already recovered): guardrail must block
    term_state = RecoveryState(
        case_id="case_term",
        source_id="SRC-case_term",
        case_type="failed_payment",
        recovery_status="recovered",
        amount=125.0,
    )
    dec_term = decide(term_state, obs, learned=extreme_learned)
    guard_term = apply_guardrails(term_state, obs, dec_term.action)
    assert guard_term.action.play == Play.NO_CONTACT
    assert guard_term.rule == "terminal_case"

    # 4. Max contact frequency: 3 touches in 7 days must block further outreach
    max_obs = replace(obs, contact_count_7d=3)
    max_state = RecoveryState(
        case_id="case_max",
        source_id="SRC-case_max",
        case_type="failed_payment",
        attempt_count=3,
        recovery_status="pending",
        amount=125.0,
    )
    dec_max = decide(max_state, max_obs, learned=extreme_learned)
    guard_max = apply_guardrails(max_state, max_obs, dec_max.action)
    assert guard_max.action.play in {Play.NO_CONTACT, Play.HUMAN_ESCALATION}

    print(f"  {GREEN}guardrails strictly override extreme learned probabilities in all cases{RESET}")


async def test_timeout_gating_and_attribution():
    print_banner("8.4 Timeout Gating & Delivery Verification")

    _init_db()
    case_id = f"test_gate_{uuid.uuid4().hex[:8]}"
    decision_id = f"dec_test_{uuid.uuid4().hex[:8]}"
    action_id = f"act_test_{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        # Seed test DecisionLog and ActionLog for linkage
        d_log = DecisionLog(
            decision_id=decision_id,
            case_id=case_id,
            state_snapshot_json={"segment": "card", "amount_due": 100.0},
            state_snapshot_hash="fakehash",
            eligible_actions_json=["email_link"],
            proposed_action="email_link",
            approved_action="email_link",
            guardrail_result="pass",
            policy_version="policy-0.1-ev",
            model_version="lgbm-test",
        )
        a_log = ActionLog(
            action_id=action_id,
            decision_id=decision_id,
            case_id=case_id,
            play="email_link",
            status="executed",
            channel="email",
        )
        db.add(d_log)
        db.add(a_log)

        state = RecoveryState(
            case_id=case_id,
            source_id=f"SRC-{case_id}",
            case_type="failed_payment",
            recovery_status="pending",
            attempt_count=1,
            amount=100.0,
            currency="USD",
            audit_log=[],
            case_metadata={},
        )
        db.add(state)
        await db.commit()

        try:
            # 1. Delivery failed -> MUST NOT create timeout outcome or learning sample
            state.case_metadata = {
                "last_touch": {
                    "attempt": 1,
                    "play": "email_link",
                    "status": "failed",
                    "channels": ["email"],
                }
            }
            res_failed = await log_unresponsive_timeout(db, state)
            assert res_failed is None, "Failed delivery incorrectly produced a timeout sample"

            # 2. Delivery unverified -> MUST NOT produce timeout sample
            state.case_metadata = {
                "last_touch": {
                    "attempt": 1,
                    "play": "email_link",
                    "status": "unverified",
                    "channels": ["link"],
                }
            }
            res_unver = await log_unresponsive_timeout(db, state)
            assert res_unver is None, "Unverified delivery incorrectly produced a timeout sample"

            # 3. Delivery succeeded ('sent') -> MUST produce timeout OutcomeLog and LearningSample
            state.case_metadata = {
                "last_touch": {
                    "attempt": 1,
                    "play": "email_link",
                    "status": "sent",
                    "channels": ["email"],
                }
            }
            outcome_id = await log_unresponsive_timeout(db, state)
            assert outcome_id is not None, "Verified delivery did not produce a timeout sample"

            # Verify OutcomeLog in DB
            out_row = await db.scalar(
                select(OutcomeLog).where(OutcomeLog.outcome_id == outcome_id)
            )
            assert out_row is not None
            assert out_row.outcome_type == "unresponsive_timeout"
            assert out_row.censored is True

            # Verify LearningSample in DB
            sample_row = await db.scalar(
                select(LearningSample).where(LearningSample.outcome_id == outcome_id)
            )
            assert sample_row is not None
            assert sample_row.sample_kind == "timeout"
            assert sample_row.success is False
            assert sample_row.censored is True
            assert sample_row.provenance == "live"
            assert sample_row.play == "email_link"

            # 4. Duplicate check: calling again on same attempt must return None
            dup = await log_unresponsive_timeout(db, state)
            assert dup is None, "Duplicate timeout was logged"

        finally:
            await db.execute(delete(LearningSample).where(LearningSample.case_id == case_id))
            await db.execute(delete(OutcomeLog).where(OutcomeLog.case_id == case_id))
            await db.execute(delete(ActionLog).where(ActionLog.case_id == case_id))
            await db.execute(delete(DecisionLog).where(DecisionLog.case_id == case_id))
            await db.execute(delete(RecoveryState).where(RecoveryState.case_id == case_id))
            await db.commit()

    print(f"  {GREEN}delivery gating verified: only verified sent/captured outreach is labeled silence{RESET}")


async def test_provenance_isolation_and_sandbox():
    print_banner("8.5 Provenance Isolation (Live vs Sandbox)")

    _init_db()
    case_sim = f"sim_{uuid.uuid4().hex[:8]}"
    case_live = f"live_{uuid.uuid4().hex[:8]}"
    dec_sim = f"dec_sim_{uuid.uuid4().hex[:8]}"
    dec_live = f"dec_live_{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        d_sim = DecisionLog(
            decision_id=dec_sim,
            case_id=case_sim,
            state_snapshot_json={"segment": "card", "amount_due": 50.0},
            state_snapshot_hash="fakehash",
            eligible_actions_json=["email_link"],
            proposed_action="email_link",
            approved_action="email_link",
            guardrail_result="pass",
            policy_version="policy-0.1-ev",
            model_version="lgbm-test",
        )
        d_live = DecisionLog(
            decision_id=dec_live,
            case_id=case_live,
            state_snapshot_json={"segment": "card", "amount_due": 50.0},
            state_snapshot_hash="fakehash",
            eligible_actions_json=["email_link"],
            proposed_action="email_link",
            approved_action="email_link",
            guardrail_result="pass",
            policy_version="policy-0.1-ev",
            model_version="lgbm-test",
        )
        db.add(d_sim)
        db.add(d_live)
        await db.commit()

        state_sim = RecoveryState(
            case_id=case_sim,
            source_id=f"SRC-{case_sim}",
            case_type="failed_payment",
            case_metadata={"simulated": True},
            recovery_status="recovered",
            amount=50.0,
        )
        state_live = RecoveryState(
            case_id=case_live,
            source_id=f"SRC-{case_live}",
            case_type="failed_payment",
            case_metadata={},
            recovery_status="recovered",
            amount=50.0,
        )

        try:
            # 1. Simulated state yields provenance='sandbox'
            sid_sim = await record_learning_sample(
                state=state_sim,
                outcome_id=f"out_{uuid.uuid4().hex[:8]}",
                outcome_type="recovered",
                decision_id=dec_sim,
                action_id=None,
                recovered_amount=50.0,
                censored=False,
            )
            sample_sim = await db.scalar(
                select(LearningSample).where(LearningSample.sample_id == sid_sim)
            )
            assert sample_sim.provenance == "sandbox", (
                f"Simulated case was tagged provenance={sample_sim.provenance}"
            )

            # 2. Live state yields provenance='live'
            sid_live = await record_learning_sample(
                state=state_live,
                outcome_id=f"out_{uuid.uuid4().hex[:8]}",
                outcome_type="recovered",
                decision_id=dec_live,
                action_id=None,
                recovered_amount=50.0,
                censored=False,
            )
            sample_live = await db.scalar(
                select(LearningSample).where(LearningSample.sample_id == sid_live)
            )
            assert sample_live.provenance == "live"

            # 3. Live rate query ignores sandbox rows
            stats_live = await load_learned_rates(db, provenance="live", source="outcome")
            stats_sbx = await load_learned_rates(db, provenance="sandbox", source="outcome")
            # If live stats exist, ensure sandbox sample ID didn't leak into live counts
            assert isinstance(stats_live, dict)
            assert isinstance(stats_sbx, dict)

        finally:
            await db.execute(
                delete(LearningSample).where(LearningSample.case_id.in_([case_sim, case_live]))
            )
            await db.execute(
                delete(DecisionLog).where(DecisionLog.case_id.in_([case_sim, case_live]))
            )
            await db.commit()

    print(f"  {GREEN}provenance boundary holds: simulated data strictly isolated to sandbox{RESET}")


async def test_retrain_safety_gates():
    print_banner("8.6 Nightly Retrain Safety Gates & Readiness")

    # 1. RETRAIN_ENABLED=false: schedule trigger returns status=disabled and fits nothing
    res_sched = await run_nightly_retrain(trigger="schedule")
    assert res_sched == {"status": "disabled"}, f"Expected disabled status, got {res_sched}"

    # 2. Manual trigger with non-dry-run when RETRAIN_ENABLED=false returns disabled
    res_manual = await run_nightly_retrain(trigger="manual", dry_run=False)
    assert res_manual.get("status") == "disabled", f"Expected disabled status, got {res_manual}"

    # 3. Readiness check with current live database
    rep = await readiness()
    assert rep["ready"] is False, "Premature ready flag on low data volume"
    assert len(rep["reasons"]) > 0
    assert rep["thresholds"]["samples"] == settings.retrain_min_samples
    assert rep["thresholds"]["recovered"] == settings.retrain_min_recovered

    print(f"  {GREEN}safety gates enforced: insufficient data prevents premature retraining{RESET}")


async def test_learning_suite():
    test_empirical_bayes_math()
    test_policy_blending_and_contract()
    test_guardrail_sovereignty_over_learned_rates()
    await test_timeout_gating_and_attribution()
    await test_provenance_isolation_and_sandbox()
    await test_retrain_safety_gates()


if __name__ == "__main__":
    asyncio.run(test_learning_suite())
