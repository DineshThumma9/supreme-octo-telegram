"""
Renvue Master Demo & Feature Regression Test Runner.
Orchestrates the 6 domain-specific test suites from `tests/`:
1. Lifecycle & Stopping Rules (tests/test_lifecycle.py)
2. Promise-To-Pay & Grace Period Validation (tests/test_promise_to_pay.py)
3. B2B Commercial Overdue Invoices (tests/test_b2b_invoices.py)
4. Recurring Subscriptions & PayPal Update-Method Links (tests/test_subscriptions.py)
5. Abandoned Checkout Concessions & Anti-Gaming (tests/test_checkout_concessions.py)
6. PayPal Webhook Signature Verification & Idempotency (tests/test_webhook_security.py)

Run directly via:
    uv run python src/tests/runner.py
"""

import asyncio
from datetime import datetime
from pathlib import Path
import sys
import traceback

SRC_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = SRC_DIR.parent
for p in [str(SRC_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from tests.common import BOLD, GREEN, RED, RESET
from tests.test_lifecycle import test_fast_forward_3_times_and_escalate
from tests.test_promise_to_pay import test_promise_to_pay_case
from tests.test_b2b_invoices import test_overdue_invoice_case
from tests.test_subscriptions import test_recurring_subscription_case
from tests.test_checkout_concessions import test_abandoned_checkout_bell_curve_discount
from tests.test_webhook_security import test_paypal_webhook_signature_verification


async def main():
    print(f"\n{BOLD}Starting Renvue Demo & Core Feature Regression Test Suite...{RESET}")
    start = datetime.now()
    try:
        await test_fast_forward_3_times_and_escalate()
        await test_promise_to_pay_case()
        await test_overdue_invoice_case()
        await test_recurring_subscription_case()
        await test_abandoned_checkout_bell_curve_discount()
        await test_paypal_webhook_signature_verification()
        elapsed = (datetime.now() - start).total_seconds()
        print(f"\n{GREEN}{BOLD}{'='*70}{RESET}")
        print(f"{GREEN}{BOLD} ALL 6 REGRESSION SUITES PASSED CLEANLY in {elapsed:.2f}s!{RESET}")
        print(f"{GREEN}{BOLD}{'='*70}{RESET}\n")
    except AssertionError as e:
        print(f"\n{RED}{BOLD}❌ REGRESSION ASSERTION FAILED:{RESET} {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}{BOLD}❌ UNEXPECTED TEST ERROR:{RESET} {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
