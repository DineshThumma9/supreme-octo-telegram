"""Held-out policy benchmark, calibration report, and model card."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from config.config import settings
from ml.models import (
    MLPolicyBundle,
    PolicyDecision,
    ece_score,
    feature_frame,
    observation_from_row,
)
from ml.sim import ALL_PLAYS, DISPUTE_PCT, OPT_OUT_COST
from policy.baseline import RulesPolicy, eligible_plays
from policy.guardrails import apply_guardrails
from policy.interfaces import Action, Observation, Play
from service.compliance import is_within_contact_window  # noqa: F401 - imported for parity

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
FIXED_NOW = datetime(2026, 11, 2, 12, 0, 0)


def _state_from_obs(obs: Observation):
    """Minimal RecoveryState for the real deterministic guardrail path."""
    from models.models import RecoveryState

    case_type = {
        "b2b": "overdue_invoice",
        "subscription": "failed_subscription",
        "checkout": "abandoned_checkout",
    }.get(obs.segment, "failed_payment")
    return RecoveryState(
        case_id=obs.case_id,
        source_id=obs.case_id,
        account_id="simulation",
        case_type=case_type,
        decline_type=obs.failure_class if obs.failure_class in {"soft", "hard", "transient"} else None,
        amount=obs.amount_due,
        currency=obs.currency,
        attempt_count=obs.attempt_count,
        customer={"email": "simulated@example.com", "contact": "+15555550100", "name": "Simulated"},
        method=obs.payment_method_type,
        subscription_id="I-SIMULATED" if obs.segment == "subscription" else None,
        invoice_id="INV-SIMULATED" if obs.segment == "b2b" else None,
        case_metadata={"simulated": True},
        first_seen_at=FIXED_NOW - timedelta(days=max(obs.tenure_days, 1)),
    )


def _guard(action: Action, obs: Observation) -> Action:
    return apply_guardrails(_state_from_obs(obs), obs, action, now=FIXED_NOW).action


def _no_contact(_: Observation) -> Action:
    return Action(Play.NO_CONTACT, None, 0.0, "no_contact_v1", rule_id="control")


def _rules(obs: Observation) -> Action:
    return RulesPolicy().act(obs)


def _rules_guarded(obs: Observation) -> Action:
    return _guard(_rules(obs), obs)


def _ml(policy) -> Callable[[Observation], Action]:
    def choose(obs: Observation) -> Action:
        return policy.act(obs, eligible_plays(obs)).action

    return choose


def _ml_guarded(policy) -> Callable[[Observation], Action]:
    def choose(obs: Observation) -> Action:
        return _guard(policy.act(obs, eligible_plays(obs)).action, obs)

    return choose


def _oracle(obs: Observation) -> Action:
    # Filled in per episode; this placeholder is never called directly.
    return Action(Play.NO_CONTACT, None, 0.0, "oracle")


def _oracle_pick(obs: Observation, outcomes: dict[str, dict]) -> Action:
    eligible = eligible_plays(obs)
    best = max(eligible, key=lambda play: outcomes[play.value]["net"])
    return Action(best, None, 5.0 if best == Play.DISCOUNT_LINK else 0.0, f"{best.value}_v1")


@dataclass
class PolicyRun:
    name: str
    net: list[float]
    recovered: list[float]
    paid: list[bool]
    cost: list[float]
    paid_days: list[float]
    opt_out: list[bool]
    dispute: list[bool]
    actions: list[str]
    changed_by_guardrail: int = 0
    mechanisms: list[str] | None = None

    def summary(self) -> dict:
        n = len(self.net)
        paid = sum(self.paid)
        net = np.asarray(self.net, dtype=float)
        paid_arr = np.asarray(self.paid, dtype=float)
        net_ci = _bootstrap_ci(net * 1000.0, 500)
        rate_ci = _bootstrap_ci(paid_arr * 100.0, 500)
        costs = float(sum(self.cost))
        pay_days = [
            float(day)
            for day, was_paid in zip(self.paid_days, self.paid)
            if was_paid and math.isfinite(float(day))
        ]
        return {
            "cases": n,
            "net_per_1000": round(float(net.mean() * 1000.0), 2),
            "net_per_1000_ci": [round(net_ci[0], 2), round(net_ci[1], 2)],
            "recovery_rate_pct": round(100.0 * paid / max(1, n), 2),
            "recovery_rate_ci": [round(rate_ci[0], 2), round(rate_ci[1], 2)],
            "total_recovered": round(float(sum(self.recovered)), 2),
            "cost_per_recovery": round(costs / max(1, paid), 2),
            "avg_time_to_pay_days": round(
                float(np.mean(pay_days)) if pay_days else 0.0, 2
            ),
            "opt_out_pct": round(100.0 * sum(self.opt_out) / max(1, n), 2),
            "dispute_pct": round(100.0 * sum(self.dispute) / max(1, n), 2),
            "guardrail_changes": self.changed_by_guardrail,
            "action_mix": {
                key: round(100.0 * self.actions.count(key) / max(1, n), 1)
                for key in sorted(set(self.actions))
            },
        }


def _bootstrap_ci(values: np.ndarray, draws: int = 500) -> tuple[float, float]:
    if len(values) == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(7)
    means = np.empty(draws)
    for i in range(draws):
        sample = rng.choice(values, size=len(values), replace=True)
        means[i] = sample.mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _run_policy(
    name: str,
    episodes: list[dict],
    outcomes: dict[str, dict[str, dict]],
    selector: Callable[[Observation, dict[str, dict]], Action],
    guard: bool = False,
) -> PolicyRun:
    run = PolicyRun(name, [], [], [], [], [], [], [], [], mechanisms=[])
    for row in episodes:
        obs = observation_from_row(row)
        potential = outcomes[obs.case_id]
        proposed = selector(obs, potential)
        approved = _guard(proposed, obs) if guard else proposed
        if approved.play != proposed.play:
            run.changed_by_guardrail += 1
        outcome = potential[approved.play.value]
        run.net.append(float(outcome["net"]))
        run.recovered.append(float(outcome["recovered_amount"]))
        run.paid.append(bool(outcome["paid"]))
        run.cost.append(
            float(outcome["action_cost"]) + float(outcome["discount_cost"]) + float(outcome["collateral"])
        )
        day = outcome["paid_day"]
        run.paid_days.append(
            float(day) if day is not None and not pd.isna(day) else 0.0
        )
        run.opt_out.append(bool(outcome["opt_out"]))
        run.dispute.append(bool(outcome["dispute"]))
        run.actions.append(approved.play.value)
        run.mechanisms.append(row["mechanism"])
    return run


def _outcome_index(test_potential: pd.DataFrame) -> dict[str, dict[str, dict]]:
    result: dict[str, dict[str, dict]] = {}
    for case_id, group in test_potential.groupby("case_id", sort=False):
        result[str(case_id)] = {
            row["action"]: row for row in group.to_dict("records")
        }
    return result


def _calibration_on_rct(bundle: MLPolicyBundle, rct: pd.DataFrame) -> dict:
    if rct.empty:
        return {}
    X = feature_frame(rct).reindex(columns=bundle.feature_columns, fill_value=0.0)
    raw = bundle.paid_model.predict_proba(X)[:, 1]
    probs = bundle.calibrate(raw)
    y = rct["paid"].astype(int).to_numpy()
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    return {
        "rows": int(len(rct)),
        "auroc": round(float(roc_auc_score(y, probs)), 4),
        "auprc": round(float(average_precision_score(y, probs)), 4),
        "brier": round(float(brier_score_loss(y, probs)), 4),
        "ece": round(float(ece_score(y, probs)), 4),
        "paid_rate": round(float(y.mean()), 4),
    }


def _sensitivity(
    policy,
    sensitivity: dict[str, pd.DataFrame],
) -> dict:
    table: dict[str, dict] = {}
    for label, frame in sensitivity.items():
        episodes = frame.drop_duplicates("case_id").to_dict("records")
        outcomes = _outcome_index(frame)
        runs = {
            "no_contact": _run_policy("no_contact", episodes, outcomes, lambda o, p: _no_contact(o)),
            "rules": _run_policy("rules", episodes, outcomes, lambda o, p: _rules(o), guard=True),
            "ml_ev": _run_policy("ml_ev", episodes, outcomes, lambda o, p: policy.act(o, eligible_plays(o)).action, guard=True),
            "oracle": _run_policy("oracle", episodes, outcomes, lambda o, p: _oracle_pick(o, p)),
        }
        table[label] = {
            name: run.summary()["net_per_1000"] for name, run in runs.items()
        }
        table[label]["ml_rank"] = sorted(
            [name for name in runs if name != "oracle"],
            key=lambda name: table[label][name],
            reverse=True,
        ).index("ml_ev") + 1
    return table


def benchmark(data: dict, bundle: MLPolicyBundle) -> dict:
    from ml.models import EVPolicy

    policy = EVPolicy(bundle, exploration=0.0, seed=11)
    episodes = data["test_obs"].to_dict("records")
    outcomes = _outcome_index(data["test_potential"])

    runs = {
        "no_contact": _run_policy("no_contact", episodes, outcomes, lambda o, p: _no_contact(o)),
        "rules": _run_policy("rules", episodes, outcomes, lambda o, p: _rules(o), guard=True),
        "ml_ev": _run_policy("ml_ev", episodes, outcomes, lambda o, p: policy.act(o, eligible_plays(o)).action, guard=True),
        "ml_no_guardrails": _run_policy("ml_no_guardrails", episodes, outcomes, lambda o, p: policy.act(o, eligible_plays(o)).action, guard=False),
        "oracle": _run_policy("oracle", episodes, outcomes, lambda o, p: _oracle_pick(o, p)),
    }

    by_mechanism: dict[str, dict] = {}
    for mechanism in ("reason", "persona"):
        idx = [i for i, row in enumerate(episodes) if row["mechanism"] == mechanism]
        by_mechanism[mechanism] = {}
        for name, run in runs.items():
            subset = PolicyRun(
                name=name,
                net=[run.net[i] for i in idx],
                recovered=[run.recovered[i] for i in idx],
                paid=[run.paid[i] for i in idx],
                cost=[run.cost[i] for i in idx],
                paid_days=[run.paid_days[i] for i in idx],
                opt_out=[run.opt_out[i] for i in idx],
                dispute=[run.dispute[i] for i in idx],
                actions=[run.actions[i] for i in idx],
                changed_by_guardrail=run.changed_by_guardrail,
            )
            by_mechanism[mechanism][name] = subset.summary()

    # 95% paired bootstrap for the ML-minus-rules difference.
    net_ml = np.asarray(runs["ml_ev"].net)
    net_rules = np.asarray(runs["rules"].net)
    diff_ci = _bootstrap_ci((net_ml - net_rules) * 1000.0, 500)

    results = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": data["meta"],
        "model": bundle.metrics,
        "calibration_rct": _calibration_on_rct(bundle, data["rct"]),
        "policies": {name: run.summary() for name, run in runs.items()},
        "by_mechanism": by_mechanism,
        "lift": {
            "ml_vs_no_contact_per_1000": round(
                (net_ml.mean() - np.asarray(runs["no_contact"].net).mean()) * 1000.0, 2
            ),
            "ml_vs_rules_per_1000": round((net_ml.mean() - net_rules.mean()) * 1000.0, 2),
            "ml_vs_rules_ci": [round(diff_ci[0], 2), round(diff_ci[1], 2)],
            "rules_vs_no_contact_per_1000": round(
                (net_rules.mean() - np.asarray(runs["no_contact"].net).mean()) * 1000.0, 2
            ),
            "oracle_gap_closed_pct": _oracle_gap(runs),
        },
        "sensitivity": _sensitivity(policy, data.get("sensitivity", {})),
        "guardrails": {
            "ml_changes": runs["ml_ev"].changed_by_guardrail,
            "ml_change_pct": round(
                100.0 * runs["ml_ev"].changed_by_guardrail / max(1, len(episodes)), 2
            ),
        },
    }
    return results


def _oracle_gap(runs: dict[str, PolicyRun]) -> float | None:
    ml = np.mean(runs["ml_ev"].net)
    rules = np.mean(runs["rules"].net)
    oracle = np.mean(runs["oracle"].net)
    if oracle <= rules:
        return None
    return round(100.0 * (ml - rules) / (oracle - rules), 2)


def save_metrics(results: dict, path: Path = ARTIFACT_DIR / "metrics.json") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, allow_nan=False))
    return path


def render_report(results: dict, path: Path = Path(__file__).resolve().parent / "evaluation_report.md") -> Path:
    policies = results["policies"]
    lift = results["lift"]
    model = results["model"]
    cal = results.get("calibration_rct", {})
    lines = [
        "# Renvue recovery policy — offline evaluation",
        "",
        f"Generated: {results['generated_at']}  ",
        f"Dataset hash: `{results['dataset']['dataset_hash']}`  ",
        f"Policy: `policy-0.1-ev`  ",
        "",
        "> **Simulated data.** This report evaluates a policy on a calibrated synthetic",
        "> simulator with potential outcomes. It is not a production lift claim.",
        "",
        "## Dataset",
        "",
        f"- Training decisions: {results['dataset']['train_rows']:,}",
        f"- Validation decisions: {results['dataset']['val_rows']:,}",
        f"- Held-out episodes: {results['dataset']['test_episodes']:,}",
        f"- Held-out potential outcomes: {results['dataset']['test_potential_rows']:,}",
        f"- Mechanisms: reason-driven and persona-driven",
        f"- Held-out personas: {results['dataset']['holdout_personas']}",
        "",
        "## Propensity model (M1)",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| AUROC | {model['auroc']:.3f} |",
        f"| AUPRC | {model['auprc']:.3f} |",
        f"| Brier | {model['brier']:.3f} |",
        f"| ECE (10 bins) | {model['ece']:.3f} |",
        f"| Validation paid rate | {model['val_paid_rate']:.1%} |",
    ]
    if cal:
        lines += [
            "",
            "Unbiased RCT check (uniform action assignment):",
            "",
            "| AUROC | AUPRC | Brier | ECE | Paid rate |",
            "|---:|---:|---:|---:|---:|",
            f"| {cal['auroc']:.3f} | {cal['auprc']:.3f} | {cal['brier']:.3f} | {cal['ece']:.3f} | {cal['paid_rate']:.1%} |",
        ]

    lines += [
        "",
        "## Policy comparison — held-out worlds",
        "",
        "| Policy | Net / 1,000 | 95% CI | Recovery | Cost / recovery | Time to pay | Opt-out | Dispute |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("no_contact", "rules", "ml_ev", "ml_no_guardrails", "oracle"):
        row = policies[name]
        lines.append(
            f"| `{name}` | ${row['net_per_1000']:,.0f} | ${row['net_per_1000_ci'][0]:,.0f}–${row['net_per_1000_ci'][1]:,.0f} "
            f"| {row['recovery_rate_pct']:.1f}% | ${row['cost_per_recovery']:,.2f} "
            f"| {row['avg_time_to_pay_days']:.1f}d | {row['opt_out_pct']:.2f}% | {row['dispute_pct']:.2f}% |"
        )

    lines += [
        "",
        "### Incremental lift",
        "",
        f"- ML vs rules: **${lift['ml_vs_rules_per_1000']:,.0f} / 1,000** "
        f"(95% CI ${lift['ml_vs_rules_ci'][0]:,.0f} to ${lift['ml_vs_rules_ci'][1]:,.0f})",
        f"- Rules vs no-contact: **${lift['rules_vs_no_contact_per_1000']:,.0f} / 1,000**",
        f"- ML vs no-contact: **${lift['ml_vs_no_contact_per_1000']:,.0f} / 1,000**",
        f"- Oracle gap closed: **{lift['oracle_gap_closed_pct']}%**",
        "",
        "## By mechanism",
        "",
        "| Mechanism | Policy | Net / 1,000 | Recovery |",
        "|---|---|---:|---:|",
    ]
    for mechanism, rows in results["by_mechanism"].items():
        for name in ("rules", "ml_ev", "oracle"):
            row = rows[name]
            lines.append(
                f"| {mechanism} | `{name}` | ${row['net_per_1000']:,.0f} | {row['recovery_rate_pct']:.1f}% |"
            )

    lines += [
        "",
        "## Sensitivity grid",
        "",
        "| Response curve | No-contact | Rules | ML | Oracle | ML rank |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, row in results.get("sensitivity", {}).items():
        lines.append(
            f"| {label} | ${row['no_contact']:,.0f} | ${row['rules']:,.0f} | ${row['ml_ev']:,.0f} "
            f"| ${row['oracle']:,.0f} | {row['ml_rank']} |"
        )

    lines += [
        "",
        "## Guardrails",
        "",
        f"- ML proposals changed by deterministic guardrails: {results['guardrails']['ml_changes']} "
        f"({results['guardrails']['ml_change_pct']}% of cases)",
        "- Guardrails can veto, downgrade, or defer; the executor only runs the approved Play.",
        "",
        "## What this proves",
        "",
        "- The policy learns heterogeneous action effects in two held-out mechanisms.",
        "- The rules baseline and ML policy share the same feature, eligibility, and guardrail contracts.",
        "- Decision logs contain the feature snapshot, alternatives, chosen Play, and outcome.",
        "",
        "## What this does not prove",
        "",
        "- It does not prove lift on real PayPal merchants.",
        "- It does not show that the simulator's response functions match reality.",
        "- It does not replace a production causal evaluation or legal/compliance review.",
        "",
    ]
    path.write_text("\n".join(lines))
    return path


def render_model_card(bundle: MLPolicyBundle, results: dict, path: Path = Path(__file__).resolve().parent / "model_card.md") -> Path:
    policies = results["policies"]
    lines = [
        "# Renvue recovery policy — model card",
        "",
        "## Model",
        "",
        f"- Name: `{bundle.version}` / `{bundle.model_version}`",
        "- Type: M1 calibrated LightGBM propensity + M2 LightGBM outcome model "
        "with Play features and per-Play base rates",
        f"- Training rows: {bundle.training_rows:,} simulated decisions",
        f"- Dataset hash: `{bundle.dataset_hash}`",
        f"- Trained: {bundle.trained_at}",
        "",
        "## Intended use",
        "",
        "Choose one of eight recovery Plays (or `no_contact`) for a failed PayPal payment,",
        "failed subscription, abandoned checkout, or overdue invoice. The Play is scored by",
        "expected net recovered dollars. Deterministic guardrails have final veto.",
        "",
        "## Action space",
        "",
        "`no_contact`, `email_link`, `sms_link`, `paypal_invoice_reminder`, `retry_now`,",
        "`retry_payday`, `update_method_link`, `discount_link`, `human_escalation`.",
        "",
        "## Features",
        "",
        "Only fields in the locked `Observation` contract are used: amount, currency, days",
        "past due, failure class/code, payment method and age, attempts, contact count and",
        "recency, prior payments/failures/recoveries, tenure, segment, dispute/opt-out flags,",
        "local hour/weekday, month-end proximity, payday signal, and invoice age.",
        "",
        "Latent simulator fields (`persona`, `p_pay_true`, counterfactual outcomes) never",
        "enter the feature frame. `FEATURE_ALLOW_LIST` is the boundary.",
        "",
        "## Training data",
        "",
        "A synthetic simulator calibrated to published ranges: involuntary churn roughly",
        "5–15%, B2C recovery roughly 25–40%, hard declines near zero without a method change,",
        "and retry success declining with attempts. Parameters are tagged `sourced` or",
        "`assumption` in the simulator; the sensitivity grid varies the assumption-heavy",
        "response curves.",
        "",
        "Two mechanisms are generated: a reason-driven world and a persona-driven world.",
        "Training uses worlds 1–3 and validation world 4. Final evaluation uses world 5 with",
        "held-out personas. The training log is deliberately confounded; a uniform RCT log is",
        "kept for estimator validation and is not used for training.",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Validation AUROC | {bundle.metrics['auroc']:.3f} |",
        f"| Validation AUPRC | {bundle.metrics['auprc']:.3f} |",
        f"| Validation Brier | {bundle.metrics['brier']:.3f} |",
        f"| Validation ECE | {bundle.metrics['ece']:.3f} |",
        f"| ML net / 1,000 (held out) | ${policies['ml_ev']['net_per_1000']:,.0f} |",
        f"| Rules net / 1,000 (held out) | ${policies['rules']['net_per_1000']:,.0f} |",
        f"| No-contact net / 1,000 | ${policies['no_contact']['net_per_1000']:,.0f} |",
        f"| Oracle net / 1,000 | ${policies['oracle']['net_per_1000']:,.0f} |",
        "",
        "## Limitations",
        "",
        "- No real merchant training data. The simulator is a test rig, not evidence of",
        "  production lift.",
        "- Response functions are assumptions. The sensitivity grid reports policy rank across",
        "  optimistic/base/pessimistic curves.",
        "- The live PayPal sandbox proves execution and logging, not statistical lift.",
        "- The current policy is a one-step decision policy replanned after every event; it is",
        "  not a full sequence model.",
        "- A production deployment needs legal/compliance review, merchant-specific calibration,",
        "  and monitoring for opt-out/dispute harm.",
        "",
        "## Ethical and consumer-protection notes",
        "",
        "- Opt-out and dispute freeze are hard stops in the guardrail layer.",
        "- Discounts are capped and scoped to abandoned checkouts.",
        "- Contact frequency and contact windows are enforced in code, not learned.",
        "- No protected attributes or demographic proxies are features.",
        "",
    ]
    path.write_text("\n".join(lines))
    return path
