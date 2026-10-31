from datetime import datetime
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from langchain_core.messages import HumanMessage
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from agent.graph import build_agent
from config.config import settings
from config.constants import STATUS_ORDER
from config.db import get_db
from config.logger import get_logger
from models.models import RecoveryState
from paypal.orders import capture_from_order, capture_order as paypal_capture_order, get_order
from service.service import handle_paypal_event
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


def _paypal_page(
    title: str,
    message: str,
    detail: str = "",
    *,
    ok: bool = True,
    status_code: int = 200,
) -> HTMLResponse:
    """Small standalone page for PayPal browser redirects (return/cancel)."""
    color = "#0a7d33" if ok else "#b42318"
    detail_html = f"<p class='detail'>{escape(detail)}</p>" if detail else ""
    dashboard = escape(settings.frontend_url) if settings.frontend_url else ""
    back_link = (
        f"<a class='back' href='{dashboard}'>Return to Renvue</a>" if dashboard else ""
    )
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · Renvue</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
            background: #0f1115; color: #e7e9ee;
            font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }}
    main {{ width: min(520px, calc(100% - 32px)); padding: 40px;
            border: 1px solid #262b36; border-radius: 16px; background: #151821;
            box-shadow: 0 24px 60px rgba(0,0,0,.35); text-align: center; }}
    .badge {{ width: 52px; height: 52px; margin: 0 auto 20px; border-radius: 50%;
              display: grid; place-items: center; background: {color}22;
              color: {color}; font-size: 26px; font-weight: 700; }}
    h1 {{ margin: 0 0 12px; font-size: 24px; }}
    p {{ margin: 0 0 12px; color: #aeb4c2; line-height: 1.5; }}
    .detail {{ font-family: ui-monospace, monospace; font-size: 13px;
               color: #7f8798; word-break: break-all; }}
    .back {{ display: inline-block; margin-top: 20px; padding: 10px 18px;
             border-radius: 999px; background: #0070ba; color: #fff;
             text-decoration: none; font-weight: 600; }}
    .back:hover {{ background: #005ea6; }}
  </style>
</head>
<body>
  <main>
    <div class="badge">{'✓' if ok else '!'}</div>
    <h1>{escape(title)}</h1>
    <p>{escape(message)}</p>
    {detail_html}
    {back_link}
  </main>
</body>
</html>"""
    return HTMLResponse(body, status_code=status_code)


@api_router.get("/paypal/return", response_class=HTMLResponse)
async def paypal_return(
    token: str = Query(default="", description="PayPal order id"),
    PayerID: Optional[str] = Query(default=None),
    case_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Capture an approved order after the buyer returns from PayPal.

    PayPal appends ``token`` and ``PayerID`` to the return URL. The same
    handler is used by recovery orders (which update their Renvue case) and by
    standalone proof orders (which have no case).
    """
    del PayerID, case_id  # accepted for PayPal compatibility; not needed for capture

    if not token:
        return _paypal_page(
            "Payment not completed",
            "PayPal did not return an order token.",
            ok=False,
            status_code=400,
        )

    try:
        order = await get_order(token)
    except Exception as exc:
        logger.warning("[PAYPAL RETURN] Could not fetch order %s: %s", token, exc)
        return _paypal_page(
            "Payment not confirmed",
            "We could not load the PayPal order. If you were charged, the webhook will reconcile it.",
            detail=str(exc),
            ok=False,
            status_code=502,
        )

    status = str(order.get("status") or "").upper()

    if status == "APPROVED":
        # Reuse the webhook path so the matching Renvue case is captured,
        # marked recovered, and audited exactly once.
        try:
            await handle_paypal_event(
                {
                    "id": f"return-{token}",
                    "event_type": "CHECKOUT.ORDER.APPROVED",
                    "resource": order,
                },
                db,
            )
        except Exception:
            logger.exception("[PAYPAL RETURN] Case update failed for order %s", token)
        try:
            order = await get_order(token)
            status = str(order.get("status") or "").upper()
        except Exception:
            logger.warning("[PAYPAL RETURN] Could not refresh order %s after approval", token)

    if status != "COMPLETED":
        # Standalone proof orders have no Renvue case, so capture them here.
        try:
            order = await paypal_capture_order(token)
            status = str(order.get("status") or "").upper()
        except Exception as exc:
            logger.warning("[PAYPAL RETURN] Capture failed for order %s: %s", token, exc)

    capture = capture_from_order(order) if isinstance(order, dict) else None
    if status == "COMPLETED" and capture:
        amount = (capture.get("amount") or {}).get("value", "")
        currency = (capture.get("amount") or {}).get("currency_code", "USD")
        return _paypal_page(
            "Payment complete",
            f"Your payment of ${amount} {currency} was captured.",
            f"Order {token} · Capture {capture.get('id', '')}",
        )

    if status == "APPROVED":
        return _paypal_page(
            "Payment approved",
            "PayPal approved the payment and the capture is still pending. Renvue will reconcile it.",
            f"Order {token}",
            status_code=202,
        )

    return _paypal_page(
        "Payment not completed",
        f"PayPal reports status {status or 'UNKNOWN'}.",
        f"Order {token}",
        ok=False,
        status_code=400,
    )


@api_router.get("/paypal/cancel", response_class=HTMLResponse)
async def paypal_cancel(
    token: str = Query(default="", description="PayPal order id"),
    case_id: Optional[str] = Query(default=None),
):
    """Buyer cancelled the PayPal checkout."""
    del case_id
    return _paypal_page(
        "Payment cancelled",
        "No payment was captured. You can return to Renvue and try again.",
        f"Order {token}" if token else "",
    )
