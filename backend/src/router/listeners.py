import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from sqlalchemy.exc import IntegrityError

from config.db import AsyncSessionLocal
from config.logger import get_logger
from models.models import WebhookEvent
from paypal.webhooks import verify_webhook
from service.service import handle_inbound_email, handle_inbound_whatsapp, handle_paypal_event

logger = get_logger(__name__)
router = APIRouter()


async def bg_paypal_event(event: dict):
    """Process a verified webhook with its own DB session."""
    async with AsyncSessionLocal() as session:
        try:
            result = await handle_paypal_event(event, session)
            logger.info("[PAYPAL WEBHOOK] Processed %s: %s", event.get("id"), result)
        except Exception as exc:
            logger.exception("[PAYPAL WEBHOOK] Processing failed for %s: %s", event.get("id"), exc)
        finally:
            record = await session.get(WebhookEvent, event.get("id"))
            if record:
                record.processed_at = datetime.now()
                session.add(record)
                await session.commit()


async def bg_inbound_email(payload: dict):
    async with AsyncSessionLocal() as session:
        await handle_inbound_email(payload, session)


async def bg_inbound_whatsapp(from_number: str, body: str):
    async with AsyncSessionLocal() as session:
        await handle_inbound_whatsapp(from_number, body, session)


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request, background_tasks: BackgroundTasks):
    """Verify, de-duplicate, and enqueue a PayPal webhook delivery."""
    body_bytes = await request.body()
    try:
        event = json.loads(body_bytes) if body_bytes else {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc

    if not event.get("id") or not event.get("event_type"):
        raise HTTPException(status_code=400, detail="Missing PayPal event id or event_type")

    accepted, detail = await verify_webhook(request.headers, event)
    if not accepted:
        raise HTTPException(status_code=400, detail=f"PayPal webhook verification failed: {detail}")

    async with AsyncSessionLocal() as session:
        existing = await session.get(WebhookEvent, str(event["id"]))
        if existing:
            return {"status": "duplicate", "event_id": event["id"]}

        record = WebhookEvent(
            event_id=str(event["id"]),
            event_type=str(event["event_type"]),
            resource_id=str((event.get("resource") or {}).get("id") or ""),
        )
        session.add(record)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return {"status": "duplicate", "event_id": event["id"]}

    background_tasks.add_task(bg_paypal_event, event)
    return {"status": "accepted", "event_id": event["id"], "verification": detail}


@router.post("/listen-emails")
async def email_receiver(request: Request, background_tasks: BackgroundTasks):
    """Resend inbound email webhook."""
    payload = await request.json()
    background_tasks.add_task(bg_inbound_email, payload)
    return {"status": "accepted"}


@router.post("/listen-message")
async def whatsapp_receiver(
    background_tasks: BackgroundTasks, From: str = Form(...), Body: str = Form(...)
):
    """Twilio WhatsApp webhook."""
    background_tasks.add_task(bg_inbound_whatsapp, From, Body)
    return {"status": "accepted"}
