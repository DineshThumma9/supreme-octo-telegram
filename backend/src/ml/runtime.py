"""Policy runtime: load the learned artifact, fall back to rules safely."""

from __future__ import annotations

import json
from pathlib import Path

from config.config import settings
from config.logger import get_logger
from ml.models import EVPolicy, PolicyDecision, load_bundle
from policy.baseline import RulesPolicy, eligible_plays
from policy.interfaces import Observation

logger = get_logger(__name__)

_rules = RulesPolicy()
_ev: EVPolicy | None = None
_bundle = None
_loaded = False


def _load() -> EVPolicy | None:
    global _ev, _bundle, _loaded
    if _loaded:
        return _ev
    _loaded = True
    if settings.policy_engine.lower() == "rules":
        logger.info("[POLICY] POLICY_ENGINE=rules; serving deterministic baseline.")
        return None
    _bundle = load_bundle()
    if _bundle is None:
        logger.info("[POLICY] No trained artifact found; serving deterministic baseline.")
        return None
    _ev = EVPolicy(_bundle, exploration=float(settings.policy_exploration))
    logger.info(
        "[POLICY] Loaded %s / %s (%s rows).",
        _bundle.version,
        _bundle.model_version,
        _bundle.training_rows,
    )
    return _ev


def reset_cache() -> None:
    """Test hook and explicit reload after retraining."""
    global _ev, _bundle, _loaded
    _ev = None
    _bundle = None
    _loaded = False


def decide(state, obs: Observation) -> PolicyDecision:
    policy = _load()
    if policy is not None:
        try:
            return policy.act(obs, eligible_plays(obs))
        except Exception as exc:
            logger.warning("[POLICY] ML policy failed (%s); falling back to rules.", exc)
    action = _rules.act(obs)
    return PolicyDecision(
        action=action,
        p_pay=None,
        expected_recovered=None,
        expected_cost=None,
        expected_net=None,
        alternatives={},
        explanation=[f"rules:{obs.segment}:{obs.failure_class}"],
        policy_version=_rules.policy_version,
        model_version="none",
        exploration=False,
    )


def model_info() -> dict:
    _load()
    if _bundle is None:
        return {
            "loaded": False,
            "policy_version": _rules.policy_version,
            "model_version": "none",
            "exploration": 0.0,
        }
    return {
        "loaded": True,
        "policy_version": _bundle.version,
        "model_version": _bundle.model_version,
        "trained_at": _bundle.trained_at,
        "training_rows": _bundle.training_rows,
        "dataset_hash": _bundle.dataset_hash,
        "exploration": float(settings.policy_exploration),
        "metrics": _bundle.metrics,
        "play_rates": _bundle.play_rates,
    }


def evaluation() -> dict | None:
    path = Path(__file__).resolve().parent / "artifacts" / "metrics.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())
