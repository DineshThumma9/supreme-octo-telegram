"""PayPal sandbox proof: create a $10 order, approve it, then capture it.

Usage:
    cd backend
    .venv/bin/python scripts/paypal_proof.py
    .venv/bin/python scripts/paypal_proof.py --capture <ORDER_ID>

The first command prints the buyer approval URL and writes the order details to
``backend/data/paypal_proof.json``. Open the URL in a browser, log in with a
separate PayPal sandbox *personal* buyer account, and approve the payment.
Then run the second command with the order ID. The script never prints or stores
the client secret or OAuth token.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BACKEND_DIR / "src"
for path in (str(SRC_DIR), str(BACKEND_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from config.config import settings  # noqa: E402
from paypal.auth import normalize_base_url  # noqa: E402
from paypal.client import PayPalAPIError, find_link, paypal_client  # noqa: E402

PROOF_FILE = BACKEND_DIR / "data" / "paypal_proof.json"
AMOUNT_USD = 10.00


def _load() -> dict:
    if PROOF_FILE.exists():
        try:
            return json.loads(PROOF_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save(data: dict) -> None:
    PROOF_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROOF_FILE.write_text(json.dumps(data, indent=2))


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assert_sandbox(allow_live: bool) -> None:
    base = normalize_base_url(settings.paypal_api_base)
    if "sandbox" not in base and not allow_live:
        raise SystemExit(
            f"Refusing to run against non-sandbox PayPal host ({base}). "
            "Set PAYPAL_API_BASE=https://api-m.sandbox.paypal.com or pass --allow-live."
        )


def _capture_from_order(order: dict) -> dict | None:
    for unit in order.get("purchase_units") or []:
        for capture in (unit.get("payments") or {}).get("captures") or []:
            return capture
    return None


async def create_proof_order(allow_live: bool) -> None:
    _assert_sandbox(allow_live)
    if not settings.paypal_client_id or not settings.paypal_client_secret:
        raise SystemExit("PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are not set in backend/.env")

    return_url = f"{settings.backend_url.rstrip('/')}/api/paypal/return" if settings.backend_url else "https://example.com/renvue/paypal/return"
    cancel_url = f"{settings.backend_url.rstrip('/')}/api/paypal/cancel" if settings.backend_url else "https://example.com/renvue/paypal/cancel"

    order = await paypal_client.create_order(
        AMOUNT_USD,
        "USD",
        reference_id="renvue-sandbox-proof",
        description="Renvue $10 sandbox proof",
        custom_id="renvue-sandbox-proof",
        return_url=return_url,
        cancel_url=cancel_url,
    )
    approval_url = find_link(order, "payer-action") or find_link(order, "approve")
    if not approval_url:
        raise SystemExit(f"PayPal returned no approval link for order {order.get('id')}: {order}")

    record = {
        "environment": "sandbox",
        "api_base": normalize_base_url(settings.paypal_api_base),
        "order_id": order.get("id"),
        "status": order.get("status"),
        "amount": f"{AMOUNT_USD:.2f}",
        "currency": "USD",
        "approval_url": approval_url,
        "created_at": _stamp(),
        "capture_id": None,
        "captured_at": None,
        "capture_status": None,
    }
    _save(record)

    print("PayPal sandbox order created.")
    print(f"  Order ID : {record['order_id']}")
    print(f"  Amount   : ${AMOUNT_USD:.2f} USD")
    print(f"  Status   : {record['status']}")
    print(f"  Approve  : {approval_url}")
    print(f"  Proof    : {PROOF_FILE}")
    print()
    print("Next: approve with a separate sandbox personal buyer, then run:")
    print(f"  .venv/bin/python scripts/paypal_proof.py --capture {record['order_id']}")


async def capture_proof_order(order_id: str, allow_live: bool) -> None:
    _assert_sandbox(allow_live)
    order = await paypal_client.get_order(order_id)
    status = str(order.get("status") or "").upper()

    if status == "APPROVED":
        order = await paypal_client.capture_order(order_id)
        status = str(order.get("status") or "").upper()

    capture = _capture_from_order(order)
    if status != "COMPLETED" or not capture:
        raise SystemExit(
            f"Order {order_id} is not captured yet (status={status}). "
            "Approve it in the sandbox buyer account, then retry this command."
        )

    capture_status = str(capture.get("status") or "").upper()
    if capture_status != "COMPLETED":
        raise SystemExit(
            f"Capture for order {order_id} is {capture_status}, not COMPLETED. "
            f"PayPal response: {json.dumps(capture, indent=2)}"
        )

    record = _load()
    if record.get("order_id") != order_id:
        record = {"order_id": order_id}
    record.update(
        {
            "environment": "sandbox",
            "api_base": normalize_base_url(settings.paypal_api_base),
            "status": status,
            "capture_id": capture.get("id"),
            "capture_status": capture_status,
            "captured_at": _stamp(),
            "gross_amount": (capture.get("amount") or {}).get("value"),
            "currency": (capture.get("amount") or {}).get("currency_code", "USD"),
        }
    )
    _save(record)

    print("PayPal sandbox capture completed.")
    print(f"  Order ID  : {order_id}")
    print(f"  Capture ID: {record['capture_id']}")
    print(f"  Status    : {capture_status}")
    print(f"  Amount    : ${record.get('gross_amount')} {record.get('currency')}")
    print(f"  Proof     : {PROOF_FILE}")


async def main_async(args: argparse.Namespace) -> None:
    try:
        if args.capture:
            await capture_proof_order(args.capture, args.allow_live)
        else:
            await create_proof_order(args.allow_live)
    except PayPalAPIError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        await paypal_client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and capture a $10 PayPal sandbox order")
    parser.add_argument("--capture", metavar="ORDER_ID", help="Capture an already approved order")
    parser.add_argument("--allow-live", action="store_true", help="Permit a non-sandbox API host")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
