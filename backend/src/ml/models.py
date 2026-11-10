"""Train and serve the learned recovery policy.

M1: calibrated payment propensity.
M2: LightGBM expected recovered amount, with Play as a feature.
M4: cost-sensitive expected-value policy with optional exploration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from ml.sim import (
    ALL_PLAYS,
    DISCOUNT_PCT,
    DISPUTE_PCT,
    OPT_OUT_COST,
    PLAY_COST,
)
from policy.baseline import eligible_plays
from policy.features import build_features
from policy.interfaces import Action, Observation, Play

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
BUNDLE_PATH = ARTIFACT_DIR / "policy.joblib"


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def observation_from_row(row: dict | pd.Series) -> Observation:
    """Reconstruct the exact serving contract from a simulator row."""
    return Observation(
        case_id=str(row["case_id"]),
        currency=str(row["currency"]),
        amount_due=float(row["amount_due"]),
        days_past_due=int(row["days_past_due"]),
        failure_code=_clean(row.get("failure_code")),
        failure_class=str(row["failure_class"]),  # type: ignore[arg-type]
        payment_method_type=_clean(row.get("payment_method_type")),
        method_age_days=int(row["method_age_days"]) if _clean(row.get("method_age_days")) is not None else None,
        attempt_count=int(row["attempt_count"]),
        contact_count_7d=int(row["contact_count_7d"]),
        last_contact_hours=(
            float(row["last_contact_hours"])
            if _clean(row.get("last_contact_hours")) is not None
            else None
        ),
        prior_successful_payments=int(row["prior_successful_payments"]),
        prior_failed_payments=int(row["prior_failed_payments"]),
        prior_recoveries=int(row["prior_recoveries"]),
        tenure_days=int(row["tenure_days"]),
        segment=str(row["segment"]),
        dispute_open=bool(row["dispute_open"]),
        opt_out=bool(row["opt_out"]),
        hour_local=int(row["hour_local"]),
        weekday=int(row["weekday"]),
        days_to_month_end=int(row["days_to_month_end"]),
        payday_signal=bool(row["payday_signal"]),
        invoice_age_days=(
            int(row["invoice_age_days"])
            if _clean(row.get("invoice_age_days")) is not None
            else None
        ),
    )


def feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in df.to_dict("records"):
        obs = observation_from_row(row)
        rows.append(build_features(obs, Play(row["action"])))
    return pd.DataFrame(rows).fillna(0.0)


def ece_score(y_true: np.ndarray, probs: np.ndarray, bins: int = 10) -> float:
    order = np.argsort(probs)
    y_true, probs = np.asarray(y_true)[order], np.asarray(probs)[order]
    total = len(probs)
    ece = 0.0
    for chunk in np.array_split(np.arange(total), bins):
        if len(chunk) == 0:
            continue
        ece += (len(chunk) / total) * abs(y_true[chunk].mean() - probs[chunk].mean())
    return float(ece)


@dataclass
class MLPolicyBundle:
    amount_model: Any
    paid_model: Any
    calibrator: IsotonicRegression
    feature_columns: list[str]
    play_rates: dict[str, dict[str, float]]
    costs: dict[str, float]
    metrics: dict[str, Any] = field(default_factory=dict)
    version: str = "policy-0.1"
    model_version: str = "lgbm-unknown"
    trained_at: str = ""
    training_rows: int = 0
    dataset_hash: str = ""
    mechanisms: list[str] = field(default_factory=lambda: ["reason", "persona"])

    def calibrate(self, raw: np.ndarray) -> np.ndarray:
        return np.clip(self.calibrator.predict(raw), 0.0, 1.0)


@dataclass(frozen=True)
class PolicyDecision:
    action: Action
    p_pay: float | None
    expected_recovered: float | None
    expected_cost: float | None
    expected_net: float | None
    alternatives: dict[str, dict[str, float]]
    explanation: list[str] = field(default_factory=list)
    policy_version: str = "rules-v0"
    model_version: str = "none"
    exploration: bool = False


def _amount_model(seed: int) -> lgb.LGBMRegressor:
    return lgb.LGBMRegressor(
        n_estimators=280,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=30,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        random_state=seed,
        verbosity=-1,
        n_jobs=-1,
    )


def _paid_model(seed: int) -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(
        n_estimators=280,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=30,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        random_state=seed,
        verbosity=-1,
        n_jobs=-1,
    )


def train_policy(data: dict, seed: int = 42) -> tuple[MLPolicyBundle, dict]:
    train = data["train"].copy()
    val = data["val"].copy()
    X_train = feature_frame(train)
    X_val = feature_frame(val).reindex(columns=X_train.columns, fill_value=0.0)
    y_paid = train["paid"].astype(int).to_numpy()
    y_val_paid = val["paid"].astype(int).to_numpy()

    paid_model = _paid_model(seed)
    paid_model.fit(X_train, y_paid)
    val_raw = paid_model.predict_proba(X_val)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(val_raw, y_val_paid)
    val_probs = np.clip(calibrator.predict(val_raw), 0.0, 1.0)

    paid_rows = train[train["paid"]].copy()
    amount_model = _amount_model(seed + 1)
    if len(paid_rows) >= 200:
        weights = (1.0 / paid_rows["propensity"].clip(lower=1e-6)).clip(0.5, 8.0)
        amount_model.fit(
            feature_frame(paid_rows).reindex(columns=X_train.columns, fill_value=0.0),
            paid_rows["recovered_amount"],
            sample_weight=weights,
        )
    else:
        amount_model = None

    play_rates: dict[str, dict[str, float]] = {}
    for play in ALL_PLAYS:
        subset = train[train["action"] == play.value]
        play_rates[play.value] = {
            "paid": float(subset["paid"].mean()) if len(subset) else 0.0,
            "opt_out": float(subset["opt_out"].mean()) if len(subset) else 0.0,
            "dispute": float(subset["dispute"].mean()) if len(subset) else 0.0,
            "recovered": float(subset["recovered_amount"].mean()) if len(subset) else 0.0,
        }

    metrics = {
        "auroc": float(roc_auc_score(y_val_paid, val_probs)) if y_val_paid.min() != y_val_paid.max() else 0.0,
        "auprc": float(average_precision_score(y_val_paid, val_probs)) if y_val_paid.min() != y_val_paid.max() else 0.0,
        "brier": float(brier_score_loss(y_val_paid, val_probs)),
        "ece": ece_score(y_val_paid, val_probs),
        "val_paid_rate": float(y_val_paid.mean()),
        "train_paid_rate": float(y_paid.mean()),
        "train_rows": int(len(train)),
        "val_rows": int(len(val)),
    }

    bundle = MLPolicyBundle(
        amount_model=amount_model,
        paid_model=paid_model,
        calibrator=calibrator,
        feature_columns=list(X_train.columns),
        play_rates=play_rates,
        costs=dict(PLAY_COST),
        metrics=metrics,
        version="policy-0.1",
        model_version=f"lgbm-{date.today().isoformat()}",
        trained_at=pd.Timestamp.utcnow().isoformat(),
        training_rows=int(len(train)),
        dataset_hash=data["meta"]["dataset_hash"],
    )
    return bundle, metrics


class EVPolicy:
    """Expected-value policy over the eligible Plays. Guardrails still dispose."""

    name = "ml_ev"

    def __init__(self, bundle: MLPolicyBundle, exploration: float = 0.0, seed: int = 0):
        self.bundle = bundle
        self.exploration = exploration
        self._rng = np.random.default_rng(seed)
        self.policy_version = f"{bundle.version}-ev"

    def _frame(self, obs: Observation, plays: list[Play]) -> pd.DataFrame:
        rows = [build_features(obs, play) for play in plays]
        frame = pd.DataFrame(rows).fillna(0.0)
        return frame.reindex(columns=self.bundle.feature_columns, fill_value=0.0)

    def _expected_amount(self, play: Play, frame: pd.DataFrame) -> np.ndarray:
        if self.bundle.amount_model is None:
            rate = self.bundle.play_rates.get(play.value, {})
            return np.full(len(frame), float(rate.get("recovered", 0.0)))
        return np.clip(self.bundle.amount_model.predict(frame), 0.0, None)

    def act(self, obs: Observation, eligible: list[Play] | None = None) -> PolicyDecision:
        plays = list(eligible or eligible_plays(obs))
        if Play.NO_CONTACT not in plays:
            plays.append(Play.NO_CONTACT)
        # Keep the order stable and de-duplicated.
        plays = list(dict.fromkeys(plays))
        frame = self._frame(obs, plays)
        raw = self.bundle.paid_model.predict_proba(frame)[:, 1]
        p_pay = self.bundle.calibrate(raw)

        alternatives: dict[str, dict[str, float]] = {}
        for index, play in enumerate(plays):
            amount_if_paid = float(self._expected_amount(play, frame.iloc[[index]])[0])
            expected_recovered = float(p_pay[index]) * amount_if_paid
            rates = self.bundle.play_rates.get(play.value, {})
            discount_cost = expected_recovered * DISCOUNT_PCT if play == Play.DISCOUNT_LINK else 0.0
            expected_cost = (
                self.bundle.costs.get(play.value, 0.0)
                + discount_cost
                + float(rates.get("opt_out", 0.0)) * OPT_OUT_COST
                + float(rates.get("dispute", 0.0)) * DISPUTE_PCT * obs.amount_due
            )
            alternatives[play.value] = {
                "p_pay": round(float(p_pay[index]), 6),
                "amount_if_paid": round(amount_if_paid, 2),
                "expected_recovered": round(expected_recovered, 2),
                "expected_cost": round(expected_cost, 2),
                "expected_net": round(expected_recovered - expected_cost, 2),
            }

        ranked = sorted(
            alternatives.items(), key=lambda item: item[1]["expected_net"], reverse=True
        )
        chosen_key = ranked[0][0]
        exploration = bool(self.exploration > 0 and self._rng.random() < self.exploration)
        if exploration:
            pool = [key for key, _ in ranked[: min(3, len(ranked))]]
            chosen_key = str(self._rng.choice(pool))

        chosen = alternatives[chosen_key]
        play = Play(chosen_key)
        discount = 5.0 if play == Play.DISCOUNT_LINK else 0.0
        action = Action(
            play=play,
            scheduled_for=None,
            discount_pct=discount,
            template_id=f"{play.value}_v1",
            rule_id=None,
        )
        return PolicyDecision(
            action=action,
            p_pay=chosen["p_pay"],
            expected_recovered=chosen["expected_recovered"],
            expected_cost=chosen["expected_cost"],
            expected_net=chosen["expected_net"],
            alternatives=alternatives,
            explanation=self.explain(obs, play),
            policy_version=self.policy_version,
            model_version=self.bundle.model_version,
            exploration=exploration,
        )

    def explain(self, obs: Observation, play: Play, top: int = 5) -> list[str]:
        if self.bundle.amount_model is None:
            return []
        frame = self._frame(obs, [play])
        try:
            contrib = self.bundle.amount_model.predict(frame, pred_contrib=True)[0]
        except Exception:
            return []
        names = list(self.bundle.feature_columns)
        pairs = list(zip(names, contrib[:-1]))
        pairs.sort(key=lambda item: abs(float(item[1])), reverse=True)
        out = []
        for name, value in pairs[:top]:
            if name.startswith("play_"):
                continue
            if "_" in name and name.rsplit("_", 1)[-1] in {
                "soft", "hard", "transient", "unknown", "card", "checkout", "b2b",
                "subscription", "usd", "paypal", "invoice", "payment", "expired",
                "funds", "denied", "timeout",
            }:
                key, token = name.rsplit("_", 1)
                out.append(f"{key}={token} ({float(value):+.2f})")
            elif name in {"amount_due", "days_past_due", "attempt_count", "contact_count_7d"}:
                raw = getattr(obs, name, None)
                out.append(f"{name}={raw} ({float(value):+.2f})")
            else:
                out.append(f"{name} ({float(value):+.2f})")
        return out[:top]


def save_bundle(bundle: MLPolicyBundle, path: Path = BUNDLE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path, compress=3)
    return path


def load_bundle(path: Path = BUNDLE_PATH) -> MLPolicyBundle | None:
    if not path.exists():
        return None
    try:
        return joblib.load(path)
    except Exception:
        return None
