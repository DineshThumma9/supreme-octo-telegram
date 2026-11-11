import re
from typing import Optional

import httpx
import resend
from config.config import settings
from config.constants import email_messages
from config.logger import get_logger
from elevenlabs.client import AsyncBaseElevenLabs
from paypal.client import paypal_client
from paypal.invoicing import create_recovery_invoice
from paypal.orders import create_recovery_order
from paypal.subscriptions import create_update_method_link
from redis.asyncio import Redis
from twilio.http.async_http_client import AsyncTwilioHttpClient
from twilio.rest import Client

logger = get_logger(__name__)

resend.api_key = settings.resend_api_key
elevenlabs_client = AsyncBaseElevenLabs(api_key=settings.eleven_api_key)
twilo_http_client = None
twilo_client = None
http_client = None
redis_client = None


async def init_clients():
    """Eagerly initialize pooled network clients during FastAPI startup."""
    global twilo_http_client, twilo_client, http_client, redis_client
    if http_client is None:
        http_client = httpx.AsyncClient()

    if redis_client is None:
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)

    if twilo_client is None:
        twilo_http_client = AsyncTwilioHttpClient()
        twilo_client = Client(
            settings.twilo_account_sid,
            settings.twilo_auth_token,
            http_client=twilo_http_client,
        )
    logger.info("Shared clients initialized (HTTP, Redis, Twilio, PayPal).")


def get_twilio_client():
    global twilo_http_client, twilo_client
    if twilo_client is None:
        twilo_http_client = AsyncTwilioHttpClient()
        twilo_client = Client(
            settings.twilo_account_sid,
            settings.twilo_auth_token,
            http_client=twilo_http_client,
        )
    return twilo_client


def get_http_client():
    global http_client
    if http_client is None:
        http_client = httpx.AsyncClient()
    return http_client


def get_redis_client():
    global redis_client
    if redis_client is None:
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    return redis_client


async def send_resend_email_result(
    urgency: str,
    customer_name: str,
    customer_email: str,
    amount: float,
    extra_context: Optional[dict] = None,
    currency: str = "USD",
) -> tuple[bool, str]:
    """Return (ok, delivery_status) where status is sent | captured | failed."""
    extra = extra_context or {}
    template = email_messages.get(urgency, email_messages["gentle"])
    try:
        html_content = template.format(
            name=customer_name,
            amount=f"{amount:,.2f}",
            invoice_number=extra.get("invoice_number", "INV-2026-001"),
            link=extra.get("link", settings.frontend_url or "https://www.paypal.com"),
        )
    except Exception:
        html_content = template.format(name=customer_name, amount=f"{amount:,.2f}")

    if settings.demo_mode:
        logger.info(
            "[DEMO SANDBOX] Email to %s (%s): amount %s %.2f (credits preserved)",
            customer_email,
            urgency,
            currency,
            amount,
        )
        return True, "captured"

    if not settings.resend_api_key:
        logger.warning(
            "[EMAIL FAILED] RESEND_API_KEY is not set; email to %s was not delivered.",
            customer_email,
        )
        return False, "failed"

    try:
        response = await resend.Emails.send_async(
            {
                "from": "Acme <onboarding@resend.dev>",
                "to": [customer_email],
                "subject": f"Action Required: Payment Recovery ({urgency.capitalize()})",
                "html": html_content,
            }
        )
        logger.info("Email sent successfully: %s", response)
        return True, "sent"
    except Exception as exc:
        logger.warning("[EMAIL FAILED] Resend delivery to %s failed: %s", customer_email, exc)
        return False, "failed"


async def send_resend_email(
    urgency: str,
    customer_name: str,
    customer_email: str,
    amount: float,
    extra_context: Optional[dict] = None,
    currency: str = "USD",
) -> bool:
    ok, _ = await send_resend_email_result(
        urgency,
        customer_name,
        customer_email,
        amount,
        extra_context=extra_context,
        currency=currency,
    )
    return ok


async def create_paypal_payment_link(
    state,
    amount: float | None = None,
    currency: str | None = None,
    discount_pct: float = 0.0,
) -> str:
    order = await create_recovery_order(state, amount=amount, currency=currency, discount_pct=discount_pct)
    return order.get("approve_url") or f"https://www.sandbox.paypal.com/checkoutnow?token={order.get('id')}"


async def create_paypal_mandate_update_link(state) -> str:
    return await create_update_method_link(state)


async def create_paypal_invoice_link(state, amount: float | None = None, currency: str | None = None) -> str:
    invoice = await create_recovery_invoice(state, amount=amount, currency=currency)
    return invoice.get("approve_url") or ""


def _normalize_e164(contact_number: str) -> str:
    if contact_number.startswith("+"):
        return contact_number
    digits = re.sub(r"\D", "", contact_number or "")
    if len(digits) == 10:
        return f"+1{digits}"
    return f"+{digits}" if digits else contact_number


async def send_twilio_whatsapp(
    contact_number: str, msg: str, media_url: Optional[str] = None
) -> str:
    contact_number = _normalize_e164(contact_number)

    if (
        not contact_number
        or "555555" in contact_number
        or "9876543210" in contact_number
        or "1234567890" in contact_number
        or re.search(r"\+1\d{3}55501\d{2}", contact_number)
        or settings.demo_mode
    ):
        logger.info(
            "[DEMO SANDBOX] WhatsApp to %s: '%s...' (Safe dispatch, credits preserved)",
            contact_number,
            msg[:75],
        )
        return "SMdemo" + "0" * 26

    if not settings.twilo_account_sid or not settings.twilo_auth_token:
        logger.warning(
            "[SIMULATED] Twilio credentials missing; WhatsApp to %s was not delivered: '%s...'",
            contact_number,
            msg[:75],
        )
        return "SMsim" + "0" * 26

    kwargs = {
        "from_": f"whatsapp:{settings.twilo_whatsapp_number}",
        "body": msg,
        "to": f"whatsapp:{contact_number}",
    }
    if media_url:
        kwargs["media_url"] = [media_url]

    client = get_twilio_client()
    try:
        res = await client.messages.create_async(**kwargs)
        message = res[0] if isinstance(res, tuple) else res
        sid = getattr(message, "sid", str(message))
        logger.info("Twilio WhatsApp message dispatched! SID: %s", sid)
        return sid
    except Exception as exc:
        logger.error("Twilio WhatsApp Error: %s", exc)
        return f"ERROR: {exc}"


def twilio_delivery_status(sid: object) -> str:
    """Map a Twilio SID/result to sent | captured | failed."""
    text = str(sid or "")
    if text.startswith("ERROR"):
        return "failed"
    if text.startswith(("SMdemo", "SMsim")):
        return "captured"
    return "sent"


async def cleanup_clients():
    global twilo_http_client, twilo_client, http_client, redis_client
    if twilo_http_client and hasattr(twilo_http_client, "session") and twilo_http_client.session:
        try:
            await twilo_http_client.session.close()
        except Exception as exc:
            logger.warning("Error closing Twilio session: %s", exc)
        twilo_http_client = None
        twilo_client = None
    if http_client:
        try:
            await http_client.aclose()
        except Exception as exc:
            logger.warning("Error closing HTTP client: %s", exc)
        http_client = None
    if redis_client:
        try:
            await redis_client.aclose()
        except Exception as exc:
            logger.warning("Error closing Redis client: %s", exc)
        redis_client = None
    try:
        await paypal_client.close()
    except Exception as exc:
        logger.warning("Error closing PayPal client: %s", exc)
    logger.info("Shared clients cleaned up.")


async def generate_and_send_voice_note(contact_number: str, msg: str) -> str:
    logger.info("Generating ElevenLabs Voice...")
    media_url = None
    try:
        if settings.demo_mode:
            logger.info("Dispatching Twilio WhatsApp Message (Demo Sandbox)...")
            return "Message sent successfully"

        audio_generator = elevenlabs_client.text_to_speech.convert(
            text=msg,
            voice_id="JBFqnCBsd6RMkjVDRZzb",
            model_id="eleven_v3",
        )

        chunks = []
        if hasattr(audio_generator, "__aiter__"):
            async for chunk in audio_generator:
                chunks.append(chunk)
        else:
            for chunk in audio_generator:
                chunks.append(chunk)
        audio_bytes = b"".join(chunks)

        logger.info("Uploading voice note to catbox.moe...")
        client = get_http_client()
        response = await client.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": ("voice.mp3", audio_bytes, "audio/mpeg")},
            timeout=10,
        )
        media_url = response.text.strip()
    except Exception as exc:
        logger.warning("Voice note generation skipped/fallback (%s)", exc)
        media_url = "https://files.catbox.moe/voice_sample_recovery.mp3"

    logger.info("Dispatching Twilio WhatsApp Voice Message (URL: %s)...", media_url)
    body = "🎙️ (Voice Note attached) " + msg
    sid = await send_twilio_whatsapp(contact_number, body, media_url)
    return sid
