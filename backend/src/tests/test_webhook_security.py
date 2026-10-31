"""
Suite 6: PayPal Webhook Signature Verification & Idempotency.
Validates:
- Demo-mode bypass when no webhook ID/headers are configured (simulator events)
- Fail-closed behavior in production when verification is not configured
- SUCCESS/FAILURE responses from PayPal's verify-webhook-signature API
- Duplicate event IDs are acknowledged without reprocessing
- Malformed events are rejected before persistence
"""

import asyncio
import json
from pathlib import Path
import sys
import uuid

SRC_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = SRC_DIR.parent
for p in [str(SRC_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from httpx import ASGITransport, AsyncClient

from config.config import settings
from main import app
from paypal.client import paypal_client
from paypal.webhooks import verify_webhook
from tests.common import GREEN, RESET, print_banner


def _event(event_id: str) -> dict:
    return {
        "id": event_id,
        "event_type": "PAYMENT.CAPTURE.DENIED",
        "resource_type": "capture",
        "resource": {
            "id": "CAP-TEST-123",
            "status": "DECLINED",
            "amount": {"value": "480.00", "currency_code": "USD"},
            "status_details": {"reason": "insufficient_funds", "description": "Insufficient funds"},
        },
    }


async def test_paypal_webhook_signature_verification():
    print_banner("6. PayPal Webhook Signature Verification & Idempotency")

    orig_demo = settings.demo_mode
    orig_id = settings.paypal_webhook_id
    orig_ids = settings.paypal_webhook_ids
    orig_verify = paypal_client.verify_webhook_signature

    try:
        # 1. Demo mode with no webhook ID accepts simulator-style deliveries.
        settings.demo_mode = True
        settings.paypal_webhook_id = ""
        settings.paypal_webhook_ids = ""
        accepted, detail = await verify_webhook({}, _event("WH-DEMO-1"))
        assert accepted is True and "demo_bypass" in detail, (accepted, detail)
        print("  Demo mode without webhook ID: accepted (bypass logged)")

        # 2. Production without a webhook ID fails closed.
        settings.demo_mode = False
        accepted, detail = await verify_webhook({}, _event("WH-PROD-1"))
        assert accepted is False and detail == "no_webhook_id", (accepted, detail)
        print("  Production without webhook ID: rejected")

        # 3. Demo mode tolerates missing transmission headers.
        settings.demo_mode = True
        settings.paypal_webhook_id = "WH-TEST-ID"
        accepted, detail = await verify_webhook({}, _event("WH-DEMO-2"))
        assert accepted is True and "missing_headers" in detail, (accepted, detail)
        print("  Demo mode with missing transmission headers: accepted (bypass logged)")

        # 4. Production + configured ID calls PayPal; SUCCESS accepts, FAILURE rejects.
        settings.demo_mode = False
        headers = {
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-url": "https://api-m.sandbox.paypal.com/cert.pem",
            "paypal-transmission-id": "tx-1",
            "paypal-transmission-sig": "sig",
            "paypal-transmission-time": "2026-10-31T00:00:00Z",
        }

        async def fake_success(headers, event):
            return "SUCCESS", "WH-TEST-ID"

        async def fake_failure(headers, event):
            return "FAILURE", None

        paypal_client.verify_webhook_signature = fake_success
        accepted, detail = await verify_webhook(headers, _event("WH-PROD-2"))
        assert accepted is True and detail.startswith("verified:"), (accepted, detail)
        print("  Verified signature: accepted")

        paypal_client.verify_webhook_signature = fake_failure
        accepted, detail = await verify_webhook(headers, _event("WH-PROD-3"))
        assert accepted is False and detail == "verification_failure", (accepted, detail)
        print("  Failed signature: rejected")

        # 5. Router behavior: malformed JSON / missing id are rejected.
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r_bad_json = await client.post(
                "/webhooks/paypal", content=b"{not-json", headers={"Content-Type": "application/json"}
            )
            assert r_bad_json.status_code == 400, r_bad_json.status_code
            print("  Malformed JSON: rejected (HTTP 400)")

            r_missing = await client.post(
                "/webhooks/paypal",
                json={"event_type": "PAYMENT.CAPTURE.DENIED"},
                headers={"Content-Type": "application/json"},
            )
            assert r_missing.status_code == 400, r_missing.status_code
            print("  Missing event id: rejected (HTTP 400)")

            # 6. Demo delivery is accepted once, then acknowledged as duplicate.
            settings.demo_mode = True
            settings.paypal_webhook_id = ""
            settings.paypal_webhook_ids = ""
            body = _event(f"WH-DUP-{uuid.uuid4().hex[:8]}")
            r_first = await client.post("/webhooks/paypal", json=body)
            assert r_first.status_code == 200, r_first.text
            r_second = await client.post("/webhooks/paypal", json=body)
            assert r_second.status_code == 200, r_second.text
            assert r_second.json().get("status") == "duplicate", r_second.text
            print("  Duplicate delivery: acknowledged without reprocessing")

        print(f"{GREEN}✓ PayPal webhook verification and idempotency passed!{RESET}")
    finally:
        settings.demo_mode = orig_demo
        settings.paypal_webhook_id = orig_id
        settings.paypal_webhook_ids = orig_ids
        paypal_client.verify_webhook_signature = orig_verify


if __name__ == "__main__":
    asyncio.run(test_paypal_webhook_signature_verification())
