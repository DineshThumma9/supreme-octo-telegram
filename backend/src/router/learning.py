"""Learning loop API: empirical Bayes stats, sandbox experiment, and retrain safety."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import settings
from config.db import get_db
from ml.learning import load_play_stats
from ml.retrain import STATUS_FILE, readiness, run_nightly_retrain
from models.models import LearningSample

router = APIRouter(prefix="/api/learning", tags=["learning"])

DEFAULT_RATES: dict[str, float] = {
    "email_link": 0.12,
    "sms_link": 0.40,
    "retry_now": 0.18,
    "retry_payday": 0.22,
    "update_method_link": 0.16,
    "discount_link": 0.30,
    "paypal_invoice_reminder": 0.10,
}


class SandboxGenerateRequest(BaseModel):
    experiment_id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    seed: int = 42
    samples_per_play: int = Field(60, ge=1, le=500)
    reset: bool = True
    rates: dict[str, float] | None = None


class RetrainRequest(BaseModel):
    confirm: bool = True
    dry_run: bool = True


@router.get("/stats")
async def learning_stats(
    provenance: Literal["live", "sandbox"] = "live",
    source: Literal["outcome", "experiment"] = "outcome",
    db: AsyncSession = Depends(get_db),
):
    rows = await load_play_stats(db, provenance=provenance, source=source)
    return {
        "provenance": provenance,
        "source": source,
        "prior_strength": settings.learning_prior_strength,
        "min_samples": settings.learning_min_samples,
        "plays": rows,
        "totals": {
            "n": sum(row["n"] for row in rows),
            "k": sum(row["k"] for row in rows),
            "timeouts": sum(row["timeouts"] for row in rows),
        },
    }


@router.post("/sandbox")
async def generate_sandbox_experiment(
    payload: SandboxGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    merged_rates = dict(DEFAULT_RATES)
    if payload.rates:
        for play, rate in payload.rates.items():
            if play not in DEFAULT_RATES:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown play '{play}'. Allowed plays: {list(DEFAULT_RATES.keys())}",
                )
            if not (0.0 <= float(rate) <= 1.0):
                raise HTTPException(
                    status_code=422,
                    detail=f"Rate for '{play}' must be between 0.0 and 1.0",
                )
            merged_rates[play] = float(rate)

    if payload.reset:
        await db.execute(
            delete(LearningSample).where(
                LearningSample.source == "experiment",
                LearningSample.experiment_id == payload.experiment_id,
            )
        )

    rows: list[LearningSample] = []
    play_summary: dict[str, dict[str, int]] = {}

    for play, rate in merged_rates.items():
        rng = random.Random(f"{payload.seed}:{play}")
        k_count = 0
        for i in range(payload.samples_per_play):
            success = rng.random() < rate
            if success:
                k_count += 1
                sample_kind = "recovered"
                censored = False
                recovered_amount = 100.0
            else:
                sample_kind = "timeout"
                censored = True
                recovered_amount = 0.0

            rows.append(
                LearningSample(
                    sample_id=f"sbx_{payload.experiment_id}_{play}_{i}",
                    case_id=f"experiment_{payload.experiment_id}_{play}_{i}",
                    decision_id=None,
                    action_id=None,
                    outcome_id=None,
                    play=play,
                    segment="sandbox",
                    provenance="sandbox",
                    source="experiment",
                    experiment_id=payload.experiment_id,
                    sample_kind=sample_kind,
                    success=success,
                    censored=censored,
                    recovered_amount=recovered_amount,
                    currency="USD",
                    policy_version="sandbox",
                    model_version="sandbox",
                )
            )
        play_summary[play] = {"n": payload.samples_per_play, "k": k_count}

    db.add_all(rows)
    await db.commit()

    return {
        "experiment_id": payload.experiment_id,
        "provenance": "sandbox",
        "source": "experiment",
        "total": len(rows),
        "plays": play_summary,
    }


@router.delete("/sandbox")
async def reset_sandbox(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        delete(LearningSample).where(LearningSample.source == "experiment")
    )
    await db.commit()
    return {"status": "ok", "deleted": result.rowcount or 0}


@router.get("/retrain-status")
async def get_retrain_status(db: AsyncSession = Depends(get_db)):
    report = await readiness(db)

    last_run = None
    if STATUS_FILE.exists():
        try:
            last_run = json.loads(STATUS_FILE.read_text())
        except Exception:
            last_run = None

    return {
        "enabled": settings.retrain_enabled,
        "dry_run": settings.retrain_dry_run,
        "auto_promote": False,
        "schedule_utc": f"{settings.retrain_hour_utc:02d}:{settings.retrain_minute:02d}",
        "ready": report["ready"],
        "counts": report["counts"],
        "thresholds": report["thresholds"],
        "reasons": report["reasons"],
        "last_run": last_run,
    }


@router.post("/retrain")
async def trigger_retrain(
    payload: RetrainRequest,
    db: AsyncSession = Depends(get_db),
):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true")

    if not payload.dry_run and not settings.retrain_enabled:
        raise HTTPException(
            status_code=409,
            detail="RETRAIN_ENABLED=false; non-dry-run retraining is disabled",
        )

    res = await run_nightly_retrain(
        trigger="manual",
        dry_run=payload.dry_run,
    )

    status_response = await get_retrain_status(db)
    status_response["last_run"] = res
    return status_response
