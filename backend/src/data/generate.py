"""
Renvue — PayPal Case Generator & Live Demo Simulator
====================================================
Sends PayPal-shaped events to the local simulator endpoint, which uses the
same event mapper and recovery loop as real PayPal webhooks.

Modes:
  1. Live demo (default): a seven-case sequence across failed payments,
     abandoned checkout, subscription, invoice, recovery, and dispute freeze.
  2. Batch:
     uv run python src/data/generate.py --payment 5 --checkout 3 --subscription 3 --invoice 2
     uv run python src/data/generate.py --all
     uv run python src/data/generate.py --no-webhook   # export sample_cases.json only
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent
BACKEND_SRC = DATA_DIR.parent
BACKEND_DIR = BACKEND_SRC.parent
for p in [str(BACKEND_SRC), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import requests

from config.config import settings

DATA_EXPORT_DIR = BACKEND_DIR / "data"
DATA_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

CUSTOMERS = [
    {"name": "Alex Morgan", "email": "alex.morgan@example.com", "contact": "+14155550123"},
    {"name": "Taylor Reed", "email": "taylor.reed@example.com", "contact": "+14155550124"},
    {"name": "Jordan Lee", "email": "jordan.lee@example.com", "contact": "+14155550125"},
    {"name": "Acme Corp AP", "email": "ap@acme.example.com", "contact": "+14155550126"},
    {"name": "Northwind Finance", "email": "finance@northwind.example.com", "contact": "+14155550127"},
    {"name": "Sam Rivera", "email": "sam.rivera@example.com", "contact": "+14155550128"},
]

AMOUNTS_USD = [19.0, 29.0, 49.0, 99.0, 125.0, 240.0, 480.0, 490.0, 1200.0, 4800.0]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def rand_customer() -> dict:
    return random.choice(CUSTOMERS)


def rand_amount() -> float:
    return random.choice(AMOUNTS_USD)


def _event(event_type: str, resource: dict) -> dict:
    return {
        "event_type": event_type,
        "decline_reason": "Payment declined",
        "name": resource.get("_customer", {}).get("name", "Customer"),
        "email": resource.get("_customer", {}).get("email", "test@example.com"),
        "phone": resource.get("_customer", {}).get("contact", "+14155550123"),
        "amount": resource.get("amount", 0.0),
        "currency": "USD",
        **{k: v for k, v in resource.items() if not k.startswith("_")},
    }


def build_failed_payment(
    customer: dict,
    amount: float,
    failure_reason: str = "insufficient_funds",
    case_id: Optional[str] = None,
) -> dict:
    return {
        "event_type": "order.failed",
        "decline_reason": failure_reason,
        "amount": amount,
        "currency": "USD",
        "name": customer["name"],
        "email": customer["email"],
        "phone": customer["contact"],
        "case_id": case_id,
    }


def build_abandoned_checkout(customer: dict, amount: float) -> dict:
    return {
        "event_type": "abandoned_checkout",
        "amount": amount,
        "currency": "USD",
        "name": customer["name"],
        "email": customer["email"],
        "phone": customer["contact"],
    }


def build_subscription_halted(customer: dict, amount: float = 49.0) -> dict:
    return {
        "event_type": "subscription_failed",
        "decline_reason": "card_expired",
        "amount": amount,
        "currency": "USD",
        "name": customer["name"],
        "email": customer["email"],
        "phone": customer["contact"],
    }


def build_overdue_invoice(customer: dict, amount: float = 4800.0) -> dict:
    return {
        "event_type": "invoice_failed",
        "decline_reason": "INVOICE_OVERDUE",
        "amount": amount,
        "currency": "USD",
        "name": customer["name"],
        "email": customer["email"],
        "phone": customer["contact"],
    }


def build_dispute(customer: dict, amount: float, case_id: str) -> dict:
    return {
        "event_type": "dispute_created",
        "decline_reason": "fraudulent",
        "amount": amount,
        "currency": "USD",
        "name": customer["name"],
        "email": customer["email"],
        "phone": customer["contact"],
        "case_id": case_id,
    }


def _base_url(url: Optional[str]) -> str:
    if url:
        return url.rstrip("/")
    return f"http://localhost:{settings.port}"


def trigger_event(event: dict, url: Optional[str] = None) -> Optional[str]:
    target = f"{_base_url(url)}/api/fake-event"
    try:
        response = requests.post(target, json=event, timeout=30)
        if response.status_code == 200:
            data = response.json()
            log(f"  -> {event['event_type']:<22} | case={data.get('id')}")
            return data.get("id")
        log(f"  [Warning] {event['event_type']}: HTTP {response.status_code} - {response.text[:120]}")
    except requests.RequestException as exc:
        log(f"  [Warning] Server unreachable at {target}: {exc}")
    return None


def trigger_action(case_id: str, action: str, message: str = "", url: Optional[str] = None) -> None:
    target = f"{_base_url(url)}/api/fake-action"
    try:
        response = requests.post(
            target,
            json={"actions": action, "case_id": case_id, "messages": message},
            timeout=30,
        )
        log(f"  -> action={action:<8} | HTTP {response.status_code}")
    except requests.RequestException as exc:
        log(f"  [Warning] Action failed: {exc}")


def run_demo_simulation(url: Optional[str] = None, delay: float = 1.5) -> None:
    print("\n" + "=" * 68)
    print("  Renvue — PayPal Live Dashboard Demo Simulation")
    print("=" * 68 + "\n")
    records: list[dict] = []

    # 1. Soft decline, left pending.
    log("1/7: Soft decline ($480 — insufficient funds)")
    c1 = CUSTOMERS[0]
    case1 = trigger_event(build_failed_payment(c1, 480.0, "insufficient_funds"), url)
    records.append({"type": "failed_payment", "case_id": case1, "amount": 480.0, "status": "pending"})
    time.sleep(delay)

    # 2. Hard decline, then captured.
    log("2/7: Hard decline -> recovered ($4,900 — card expired)")
    c2 = CUSTOMERS[1]
    case2 = trigger_event(build_failed_payment(c2, 4900.0, "card_expired"), url)
    time.sleep(delay)
    if case2:
        trigger_action(case2, "pay", url=url)
    records.append({"type": "failed_payment", "case_id": case2, "amount": 4900.0, "status": "recovered"})
    time.sleep(delay)

    # 3. Abandoned checkout with a bounded concession.
    log("3/7: Abandoned checkout ($125 — reserved discount)")
    c3 = CUSTOMERS[2]
    case3 = trigger_event(build_abandoned_checkout(c3, 125.0), url)
    records.append({"type": "abandoned_checkout", "case_id": case3, "amount": 125.0, "status": "pending"})
    time.sleep(delay)

    # 4. Failed subscription -> update-method link.
    log("4/7: Failed subscription ($49 — update method)")
    c4 = CUSTOMERS[3]
    case4 = trigger_event(build_subscription_halted(c4, 49.0), url)
    records.append({"type": "failed_subscription", "case_id": case4, "amount": 49.0, "status": "pending"})
    time.sleep(delay)

    # 5. Overdue commercial invoice.
    log("5/7: Overdue invoice ($4,800 — PayPal invoice reminder)")
    c5 = CUSTOMERS[4]
    case5 = trigger_event(build_overdue_invoice(c5, 4800.0), url)
    records.append({"type": "overdue_invoice", "case_id": case5, "amount": 4800.0, "status": "pending"})
    time.sleep(delay)

    # 6. Dispute freezes an active case.
    log("6/7: Buyer dispute -> freeze ($240)")
    c6 = CUSTOMERS[5]
    case6 = trigger_event(build_failed_payment(c6, 240.0, "payment_denied"), url)
    time.sleep(delay)
    if case6:
        trigger_event(build_dispute(c6, 240.0, case6), url)
    records.append({"type": "dispute", "case_id": case6, "amount": 240.0, "status": "escalated"})
    time.sleep(delay)

    # 7. Invoice paid.
    log("7/7: Invoice paid ($1,200 — reconciled)")
    c7 = CUSTOMERS[1]
    case7 = trigger_event(build_overdue_invoice(c7, 1200.0), url)
    time.sleep(delay)
    if case7:
        trigger_action(case7, "pay", url=url)
    records.append({"type": "overdue_invoice", "case_id": case7, "amount": 1200.0, "status": "recovered"})

    export_path = DATA_EXPORT_DIR / "sample_cases.json"
    export_path.write_text(json.dumps(records, indent=2))
    print("\n" + "=" * 68)
    print("  Live demo complete")
    print(f"  Cases dispatched : {len(records)}")
    print(f"  Dataset exported : {export_path}")
    print("=" * 68 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Renvue PayPal case generator")
    parser.add_argument("--demo", action="store_true", help="Run the live demo simulation")
    parser.add_argument("--payment", type=int, default=0)
    parser.add_argument("--checkout", type=int, default=0)
    parser.add_argument("--subscription", type=int, default=0)
    parser.add_argument("--invoice", type=int, default=0)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--no-webhook", action="store_true")
    parser.add_argument("--url", type=str, default=None)
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()

    no_args = not any([args.demo, args.all, args.payment, args.checkout, args.subscription, args.invoice])
    if args.demo or no_args:
        run_demo_simulation(url=args.url, delay=args.delay)
        return

    if args.all:
        args.payment, args.checkout, args.subscription, args.invoice = 5, 5, 3, 4

    print("\n" + "=" * 68)
    print("  Renvue — PayPal Batch Case Generator")
    print("=" * 68 + "\n")

    records = []
    builders = [
        (args.payment, lambda: build_failed_payment(rand_customer(), rand_amount())),
        (args.checkout, lambda: build_abandoned_checkout(rand_customer(), rand_amount())),
        (args.subscription, lambda: build_subscription_halted(rand_customer(), 49.0)),
        (args.invoice, lambda: build_overdue_invoice(rand_customer(), rand_amount())),
    ]
    for count, builder in builders:
        for _ in range(count):
            event = builder()
            records.append(event)
            if not args.no_webhook:
                trigger_event(event, args.url)
                time.sleep(args.delay)

    export_path = DATA_EXPORT_DIR / "sample_cases.json"
    export_path.write_text(json.dumps(records, indent=2))
    print("\n" + "=" * 68)
    print(f"  Generated {len(records)} events")
    print(f"  Dataset exported : {export_path}")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    main()
