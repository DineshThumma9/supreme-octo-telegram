from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from langchain_core.messages import HumanMessage
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from agent.graph import build_agent
from config.constants import STATUS_ORDER
from config.db import get_db
from config.logger import get_logger
from models.models import RecoveryState
from service.states import load_state, save_state

logger = get_logger(__name__)
api_router = APIRouter(prefix="/api")

ACCOUNT_HEADER = "X-PayPal-Account-Id"


def _effective_account(account_id: str | None, header_account: str | None) -> str | None:
    return account_id or header_account


@api_router.get("/metrics")
async def get_metrics(
    account_id: Optional[str] = Query(default=None),
    x_paypal_account_id: Optional[str] = Header(default=None, alias=ACCOUNT_HEADER),
    db: AsyncSession = Depends(get_db),
):
    effective_acc = _effective_account(account_id, x_paypal_account_id)
    stmt = select(RecoveryState)
    if effective_acc:
        stmt = stmt.where(RecoveryState.account_id == effective_acc)
    cases = (await db.execute(stmt)).scalars().all()
    total_at_risk = sum(c.amount for c in cases)
    recovered = [c for c in cases if c.recovery_status == "recovered"]
    escalated = [c for c in cases if c.recovery_status == "escalated"]
    return {
        "account_id": effective_acc,
        "currency": "USD",
        "total_cases": len(cases),
        "total_at_risk": total_at_risk,
        "recovered_count": len(recovered),
        "recovered_amount": sum(c.recovered_amount for c in recovered),
        "recovery_rate_pct": round(len(recovered) / len(cases) * 100, 1) if cases else 0,
        "escalated_count": len(escalated),
        "still_active": len(cases) - len(recovered) - len(escalated),
    }


@api_router.delete("/cases/clear")
async def clear_cases(
    account_id: Optional[str] = Query(default=None),
    x_paypal_account_id: Optional[str] = Header(default=None, alias=ACCOUNT_HEADER),
    db: AsyncSession = Depends(get_db),
):
    effective_acc = _effective_account(account_id, x_paypal_account_id)
    stmt = delete(RecoveryState)
    if effective_acc:
        stmt = stmt.where(RecoveryState.account_id == effective_acc)
    await db.execute(stmt)
    await db.commit()
    return {
        "status": "ok",
        "message": f"Cases cleared{' for ' + effective_acc if effective_acc else ''}",
    }


@api_router.get("/cases")
async def list_cases(
    account_id: Optional[str] = Query(default=None),
    x_paypal_account_id: Optional[str] = Header(default=None, alias=ACCOUNT_HEADER),
    db: AsyncSession = Depends(get_db),
):
    effective_acc = _effective_account(account_id, x_paypal_account_id)
    stmt = select(RecoveryState)
    if effective_acc:
        stmt = stmt.where(RecoveryState.account_id == effective_acc)
    cases = (await db.execute(stmt)).scalars().all()
    sorted_cases = sorted(cases, key=lambda c: STATUS_ORDER.get(c.recovery_status, 99))
    return [c.model_dump(mode="json") for c in sorted_cases]


@api_router.get("/cases/{case_id}")
async def get_case(
    case_id: str,
    account_id: Optional[str] = Query(default=None),
    x_paypal_account_id: Optional[str] = Header(default=None, alias=ACCOUNT_HEADER),
    db: AsyncSession = Depends(get_db),
):
    state = await load_state(case_id, db)
    if not state:
        raise HTTPException(status_code=404, detail="Case not found")
    effective_acc = _effective_account(account_id, x_paypal_account_id)
    if effective_acc and state.account_id != effective_acc:
        raise HTTPException(status_code=404, detail="Case not found for specified merchant account")
    return state.model_dump(mode="json")


@api_router.post("/cases/{case_id}/approve")
async def approve_escalation(
    case_id: str,
    account_id: Optional[str] = Query(default=None),
    x_paypal_account_id: Optional[str] = Header(default=None, alias=ACCOUNT_HEADER),
    db: AsyncSession = Depends(get_db),
):
    state = await load_state(case_id, db)
    if not state:
        raise HTTPException(status_code=404, detail="Case not found")
    effective_acc = _effective_account(account_id, x_paypal_account_id)
    if effective_acc and state.account_id != effective_acc:
        raise HTTPException(status_code=404, detail="Case not found for specified merchant account")
    if state.recovery_status != "escalated":
        raise HTTPException(status_code=400, detail=f"Case is not escalated (current: {state.recovery_status})")
    state.recovery_status = "in_progress"
    await save_state(state, db)
    agent = build_agent(state)
    config = {"configurable": {"thread_id": case_id}}
    await agent.ainvoke(
        {
            "messages": [HumanMessage(content="Human approved. Proceed with the next recovery Play.")],
            "recovery_state": state,
            "event_source": "inbound.human_approval",
        },
        config=config,
    )
    return {"status": "approved", "case_id": case_id}


@api_router.post("/cases/{case_id}/close")
async def close_case(
    case_id: str,
    account_id: Optional[str] = Query(default=None),
    x_paypal_account_id: Optional[str] = Header(default=None, alias=ACCOUNT_HEADER),
    db: AsyncSession = Depends(get_db),
):
    state = await load_state(case_id, db)
    if not state:
        raise HTTPException(status_code=404, detail="Case not found")
    effective_acc = _effective_account(account_id, x_paypal_account_id)
    if effective_acc and state.account_id != effective_acc:
        raise HTTPException(status_code=404, detail="Case not found for specified merchant account")
    state.recovery_status = "closed"
    state.next_retry_at = None
    if state.audit_log is None:
        state.audit_log = []
    state.audit_log.append(
        {
            "event_triggered": "case_manually_closed",
            "amount": f"{state.amount:,.2f} {state.currency or 'USD'}",
            "recovery_status": "closed",
            "customer": state.customer,
            "next_contact": None,
            "message": "Case closed manually by merchant/admin.",
            "channel": "system",
            "direction": "system",
            "created_at": datetime.now().isoformat(),
        }
    )
    await save_state(state, db)
    from service.service import kill_all_tasks

    await kill_all_tasks(case_id, db)
    return {"status": "closed", "case_id": case_id}
