"""Nightly policy retraining pipeline and safety gates."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import settings
from config.db import AsyncSessionLocal
from config.logger import get_logger
from models.models import DecisionLog, LearningSample

logger = get_logger(__name__)

STATUS_FILE = Path(__file__).resolve().parent / "artifacts" / "retrain_status.json"


def _write_status_atomically(payload: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = STATUS_FILE.with_suffix(".json.tmp")
    tmp_file.write_text(json.dumps(payload, indent=2, default=str))
    tmp_file.replace(STATUS_FILE)


async def readiness(db: AsyncSession | None = None) -> dict:
    """Count live outcome samples and compare with the gates."""
    if db is None:
        async with AsyncSessionLocal() as session:
            return await _readiness_impl(session)
    return await _readiness_impl(db)


async def _readiness_impl(session: AsyncSession) -> dict:
    row = (
        await session.execute(
            select(
                func.count(),
                func.sum(case((LearningSample.success.is_(True), 1), else_=0)),
                func.sum(case((LearningSample.sample_kind == "timeout", 1), else_=0)),
                func.count(func.distinct(LearningSample.play)),
                func.min(LearningSample.created_at),
                func.max(LearningSample.created_at),
            ).where(
                LearningSample.provenance == "live",
                LearningSample.source == "outcome",
            )
        )
    ).first()

    samples = int(row[0] or 0) if row else 0
    recovered = int(row[1] or 0) if row else 0
    timeouts = int(row[2] or 0) if row else 0
    min_created = row[4] if row else None
    max_created = row[5] if row else None

    days = 0
    if min_created and max_created:
        days = max(0, (max_created - min_created).days)

    play_counts = (
        select(LearningSample.play, func.count().label("n"))
        .where(
            LearningSample.provenance == "live",
            LearningSample.source == "outcome",
        )
        .group_by(LearningSample.play)
        .subquery()
    )
    eligible_plays = await session.scalar(
        select(func.count())
        .select_from(play_counts)
        .where(play_counts.c.n >= settings.retrain_min_per_play)
    )
    eligible_plays = int(eligible_plays or 0)

    reasons: list[str] = []
    if samples < settings.retrain_min_samples:
        reasons.append(f"samples {samples} < {settings.retrain_min_samples}")
    if recovered < settings.retrain_min_recovered:
        reasons.append(f"recovered {recovered} < {settings.retrain_min_recovered}")
    if eligible_plays < settings.retrain_min_plays:
        reasons.append(f"eligible_plays {eligible_plays} < {settings.retrain_min_plays}")
    if days < settings.retrain_min_days:
        reasons.append(f"days {days} < {settings.retrain_min_days}")

    ready = len(reasons) == 0

    return {
        "ready": ready,
        "counts": {
            "samples": samples,
            "recovered": recovered,
            "timeouts": timeouts,
            "eligible_plays": eligible_plays,
            "days": days,
        },
        "thresholds": {
            "samples": settings.retrain_min_samples,
            "recovered": settings.retrain_min_recovered,
            "min_per_play": settings.retrain_min_per_play,
            "plays": settings.retrain_min_plays,
            "days": settings.retrain_min_days,
        },
        "reasons": reasons,
    }


async def build_training_frame(db: AsyncSession) -> tuple[Any, dict]:
    """Join live samples to decision snapshots. Imports pandas inside."""
    import pandas as pd

    result = await db.execute(
        select(LearningSample, DecisionLog)
        .join(DecisionLog, LearningSample.decision_id == DecisionLog.decision_id)
        .where(
            LearningSample.provenance == "live",
            LearningSample.source == "outcome",
        )
        .order_by(LearningSample.created_at.asc())
    )
    rows_data = result.all()

    frame_rows = []
    sample_ids = []
    skipped = 0

    required_obs_fields = {
        "amount_due",
        "days_past_due",
        "failure_class",
        "segment",
        "attempt_count",
    }

    for sample, decision in rows_data:
        snapshot = decision.state_snapshot_json or {}
        if not required_obs_fields.issubset(snapshot.keys()):
            skipped += 1
            continue

        sample_ids.append(sample.sample_id)
        row = {
            **snapshot,
            "case_id": sample.case_id,
            "action": sample.play,
            "paid": bool(sample.success),
            "recovered_amount": float(sample.recovered_amount or 0.0),
            "propensity": 1.0,
        }
        frame_rows.append(row)

    frame = pd.DataFrame(frame_rows)
    sorted_ids = sorted(sample_ids)
    dataset_hash = hashlib.sha256("".join(sorted_ids).encode()).hexdigest()

    meta = {
        "dataset_hash": dataset_hash,
        "total_rows": len(frame),
        "skipped_rows": skipped,
        "generated_at": datetime.now().isoformat(),
    }
    return frame, meta


async def run_nightly_retrain(
    *,
    trigger: str = "schedule",
    dry_run: bool | None = None,
) -> dict:
    is_dry_run = settings.retrain_dry_run if dry_run is None else dry_run

    if trigger == "schedule" and not settings.retrain_enabled:
        result = {"status": "disabled"}
        return result

    if trigger == "manual" and not is_dry_run and not settings.retrain_enabled:
        return {"status": "disabled", "reason": "RETRAIN_ENABLED=false"}

    report = await readiness()
    now_iso = datetime.now().isoformat()

    if not report["ready"]:
        status_obj = {
            "last_run_at": now_iso,
            "trigger": trigger,
            "status": "insufficient_data",
            "readiness": report,
            "metrics": None,
            "candidate_path": None,
            "promoted": False,
        }
        _write_status_atomically(status_obj)
        return status_obj

    if is_dry_run:
        async with AsyncSessionLocal() as session:
            frame, meta = await build_training_frame(session)
        status_obj = {
            "last_run_at": now_iso,
            "trigger": trigger,
            "status": "dry_run_ok",
            "readiness": report,
            "metrics": None,
            "candidate_path": None,
            "promoted": False,
            "meta": meta,
        }
        _write_status_atomically(status_obj)
        return status_obj

    try:
        import joblib
        from ml.models import train_policy

        async with AsyncSessionLocal() as session:
            frame, meta = await build_training_frame(session)

        val_size = max(20, int(len(frame) * 0.2))
        train_df = frame.iloc[:-val_size]
        val_df = frame.iloc[-val_size:]

        bundle = train_policy(train_df, val_df)
        candidate_dir = Path(__file__).resolve().parent / "artifacts" / "candidates"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        today_str = date.today().isoformat()
        candidate_path = candidate_dir / f"policy-{today_str}.joblib"

        joblib.dump(bundle, candidate_path, compress=3)

        status_obj = {
            "last_run_at": now_iso,
            "trigger": trigger,
            "status": "candidate_ready",
            "readiness": report,
            "metrics": bundle.metrics,
            "candidate_path": str(candidate_path),
            "promoted": False,
        }
        _write_status_atomically(status_obj)
        return status_obj
    except Exception as exc:
        logger.error("[RETRAIN] Fit failed: %s", exc)
        status_obj = {
            "last_run_at": now_iso,
            "trigger": trigger,
            "status": "failed",
            "error": str(exc),
            "readiness": report,
            "metrics": None,
            "candidate_path": None,
            "promoted": False,
        }
        _write_status_atomically(status_obj)
        return status_obj
