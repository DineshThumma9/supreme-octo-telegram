"""Play-level empirical Bayes over observed attempt outcomes."""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import settings
from config.db import AsyncSessionLocal
from config.logger import get_logger
from ml.models import load_bundle
from models.models import LearningSample

logger = get_logger(__name__)


def shrink(
    *,
    n: int,
    k: int,
    prior_p: float,
    prior_strength: float,
    min_samples: int | None = None,
) -> tuple[float, float]:
    """Return (posterior_p, weight) for a Beta-Bernoulli update."""
    n = max(0, int(n))
    k = max(0, min(int(k), n))
    prior_p = min(1.0, max(0.0, float(prior_p)))
    s = max(1e-6, float(prior_strength))
    threshold = (
        settings.learning_min_samples
        if min_samples is None
        else max(0, int(min_samples))
    )

    posterior = (k + prior_p * s) / (n + s)
    weight = n / (n + s) if n >= threshold else 0.0
    return posterior, weight


def blend(
    *,
    p_model: float,
    posterior_p: float,
    weight: float,
) -> float:
    w = min(1.0, max(0.0, float(weight)))
    return (1.0 - w) * float(p_model) + w * float(posterior_p)


async def load_play_stats(
    db: AsyncSession,
    *,
    provenance: str = "live",
    source: str = "outcome",
) -> list[dict]:
    """Return per-play counts and posteriors. Raises on DB errors."""
    rows = (
        await db.execute(
            select(
                LearningSample.play,
                func.count().label("n"),
                func.sum(
                    case((LearningSample.success.is_(True), 1), else_=0)
                ).label("k"),
                func.sum(
                    case(
                        (LearningSample.sample_kind == "timeout", 1),
                        else_=0,
                    )
                ).label("timeouts"),
                func.max(LearningSample.created_at).label("last_sample_at"),
            )
            .where(
                LearningSample.provenance == provenance,
                LearningSample.source == source,
            )
            .group_by(LearningSample.play)
        )
    ).all()

    bundle = load_bundle()
    out: list[dict] = []
    for play, n, k, timeouts, last_sample_at in rows:
        n = int(n or 0)
        k = int(k or 0)
        prior_p = float(
            (bundle.play_rates.get(play, {}) if bundle else {}).get("paid", 0.0)
        )
        posterior, weight = shrink(
            n=n,
            k=k,
            prior_p=prior_p,
            prior_strength=settings.learning_prior_strength,
        )
        out.append(
            {
                "play": play,
                "n": n,
                "k": k,
                "timeouts": int(timeouts or 0),
                "prior_p": round(prior_p, 6),
                "posterior_p": round(posterior, 6),
                "weight": round(weight, 6),
                "last_sample_at": (
                    last_sample_at.isoformat() if last_sample_at else None
                ),
            }
        )
    return sorted(out, key=lambda item: item["play"])


async def load_learned_rates(
    db: AsyncSession | None = None,
    *,
    provenance: str = "live",
    source: str = "outcome",
) -> dict[str, dict[str, float]]:
    """Return {play: {n, k, posterior_p, weight, prior_p}}.

    Learning is a best-effort enhancement. Any failure returns {} so the
    caller serves the model prior.
    """
    if provenance == "off" or not settings.learning_enabled:
        return {}

    try:
        if db is None:
            async with AsyncSessionLocal() as session:
                stats = await load_play_stats(
                    session, provenance=provenance, source=source
                )
        else:
            stats = await load_play_stats(
                db, provenance=provenance, source=source
            )
    except Exception as exc:
        logger.warning("[LEARNING] stats load failed: %s", exc)
        return {}

    return {
        item["play"]: {
            "n": float(item["n"]),
            "k": float(item["k"]),
            "prior_p": float(item["prior_p"]),
            "posterior_p": float(item["posterior_p"]),
            "weight": float(item["weight"]),
        }
        for item in stats
    }
