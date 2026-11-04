"""Regression tests for the synthetic simulator, learned policy, and API."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from config.config import settings
from ml.evaluation import FIXED_NOW, _state_from_obs
from ml.models import (
    EVPolicy,
    feature_frame,
    load_bundle,
    observation_from_row,
    train_policy,
)
from ml.runtime import decide, model_info
from ml.sim import ALL_PLAYS, SimConfig, generate_dataset
from policy.baseline import RulesPolicy, eligible_plays
from policy.features import FEATURE_ALLOW_LIST, build_features
from policy.guardrails import apply_guardrails
from policy.interfaces import Action, Play
from router.policy import PolicyScoreRequest, score_case
from tests.common import print_banner

LEAKY_COLUMNS = {
    "persona",
    "mechanism",
    "world",
    "paid",
    "p_pay_true",
    "paid_day",
    "recovered_amount",
    "net",
    "dispute",
    "attribution",
}

# ``mechanism`` and ``world`` are evaluation metadata on the simulator frame;
# they are dropped by ``observation_from_row`` and never reach the model.
LEAKY_OBSERVATION_COLUMNS = LEAKY_COLUMNS - {"mechanism", "world"}

SMALL = SimConfig(
    train_per_world=900,
    val_per_world=300,
    test_per_world=120,
    rct_per_world=80,
)


def _small_data() -> dict:
    return generate_dataset(SMALL)


def test_simulator_is_deterministic_and_leak_free():
    print_banner("ML simulator determinism & latent leakage")

    first = _small_data()
    second = _small_data()
    assert first["meta"]["dataset_hash"] == second["meta"]["dataset_hash"], (
        "Simulator output changed for the same seed"
    )
    assert first["train"].equals(second["train"]), "Training log is not deterministic"

    assert set(FEATURE_ALLOW_LIST) <= set(first["test_obs"].columns)
    for column in LEAKY_OBSERVATION_COLUMNS:
        assert column not in first["test_obs"].columns, (
            f"Latent/target column {column!r} leaked into observations"
        )

    row = first["test_obs"].iloc[0].to_dict()
    obs = observation_from_row(row)
    for play in ALL_PLAYS:
        features = build_features(obs, play)
        assert not (LEAKY_COLUMNS & set(features)), "Leaky feature name constructed"
        assert f"play_{play.value}" in features
        assert all(
            key in FEATURE_ALLOW_LIST
            or any(key.startswith(f"{allowed}_") for allowed in FEATURE_ALLOW_LIST)
            or key.startswith("play_")
            for key in features
        ), f"Unexpected feature outside the locked contract: {features.keys()}"

    print("  simulator deterministic; feature boundary holds")


def test_ev_policy_respects_contract():
    print_banner("ML expected-value policy contract")

    data = _small_data()
    bundle, _ = train_policy(data, seed=7)
    policy = EVPolicy(bundle, exploration=0.0)

    for row in data["test_obs"].head(25).to_dict("records"):
        obs = observation_from_row(row)
        eligible = eligible_plays(obs)
        decision = policy.act(obs, eligible)
        allowed = set(eligible) | {Play.NO_CONTACT}
        assert decision.action.play in allowed, (
            f"Policy chose ineligible Play {decision.action.play}"
        )
        assert set(decision.alternatives) == {play.value for play in allowed}
        for scores in decision.alternatives.values():
            assert abs(
                scores["expected_net"]
                - (scores["expected_recovered"] - scores["expected_cost"])
            ) < 0.02, "Expected net is not recovered minus cost"
        assert decision.policy_version.startswith("policy-")
        assert decision.model_version != "none"

    frame = feature_frame(data["train"].head(4)).reindex(
        columns=bundle.feature_columns, fill_value=0.0
    )
    assert list(frame.columns) == bundle.feature_columns
    print("  eligible actions, scores, and feature order are consistent")


def test_guardrails_keep_final_authority():
    print_banner("Guardrails veto/downgrade learned proposals")

    data = _small_data()
    base_row = data["test_obs"].iloc[0].to_dict()
    obs = observation_from_row(base_row)
    state = _state_from_obs(obs)
    proposed = Action(Play.RETRY_NOW, None, 0.0, "retry_now_v1")

    blocked = apply_guardrails(
        state, replace(obs, opt_out=True), proposed, now=FIXED_NOW
    )
    assert blocked.action.play == Play.NO_CONTACT
    assert blocked.result == "block" and blocked.rule == "opt_out"

    frozen = apply_guardrails(
        state, replace(obs, dispute_open=True), proposed, now=FIXED_NOW
    )
    assert frozen.action.play == Play.HUMAN_ESCALATION
    assert frozen.rule == "dispute_freeze"

    discount = Action(Play.DISCOUNT_LINK, None, 5.0, "discount_link_v1")
    scoped = apply_guardrails(
        state, replace(obs, segment="card"), discount, now=FIXED_NOW
    )
    assert scoped.result == "downgrade" and scoped.rule == "discount_scope"
    assert scoped.action.discount_pct == 0.0

    terminal = state.model_copy(update={"recovery_status": "recovered"})
    stopped = apply_guardrails(terminal, obs, proposed, now=FIXED_NOW)
    assert stopped.action.play == Play.NO_CONTACT and stopped.rule == "terminal_case"
    print("  opt-out, dispute, discount scope, and terminal cases are enforced")


def test_bundle_artifact_loads_and_serves_ml():
    print_banner("Trained artifact load & runtime selection")

    bundle = load_bundle()
    assert bundle is not None, "Run scripts/train_policy.py to create the artifact"
    assert bundle.feature_columns and bundle.metrics["auroc"] > 0.5
    assert bundle.version and bundle.model_version != "none"

    info = model_info()
    assert info["loaded"] is True
    assert info["model_version"] == bundle.model_version

    data = _small_data()
    obs = observation_from_row(data["test_obs"].iloc[0].to_dict())
    decision = decide(None, obs)
    assert decision.policy_version.startswith("policy-")
    assert decision.model_version != "none"
    assert decision.alternatives

    original = settings.policy_engine
    try:
        settings.policy_engine = "rules"
        from ml import runtime

        runtime.reset_cache()
        fallback = decide(None, obs)
        assert fallback.policy_version == RulesPolicy.policy_version
        assert fallback.model_version == "none"
    finally:
        settings.policy_engine = original
        from ml import runtime

        runtime.reset_cache()
    print("  artifact loads, ML serves, and rules fallback still works")


async def test_policy_score_api():
    print_banner("Agent Lab policy score endpoint")

    response = await score_case(
        PolicyScoreRequest(
            amount_due=125.0,
            failure_class="soft",
            segment="card",
            prior_recoveries=2,
            payday_signal=False,
        ),
        db=None,
    )
    assert response["case_id"] == "api_score"
    assert response["proposed_action"] in {play.value for play in ALL_PLAYS}
    assert response["approved_action"] in {
        play.value for play in ALL_PLAYS
    }
    assert response["policy_version"]
    assert response["alternatives"]
    for scores in response["alternatives"].values():
        assert "expected_net" in scores and "p_pay" in scores
    print(
        f"  scored {response['observation']['segment']} case -> "
        f"{response['proposed_action']} (${response['expected_net']})"
    )


async def run_all() -> None:
    test_simulator_is_deterministic_and_leak_free()
    test_ev_policy_respects_contract()
    test_guardrails_keep_final_authority()
    test_bundle_artifact_loads_and_serves_ml()
    await test_policy_score_api()


if __name__ == "__main__":
    asyncio.run(run_all())
