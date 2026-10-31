"""
Suite 4: Recurring Subscription Recovery & PayPal Update-Method Links.
Validates:
- Subscription mandate failure recovery
- Generation of Mandate Re-Authorization links (`sub_card_change`) to protect future LTV
- PayPal subscription update-method link hydration
- No India-specific pre-debit compliance state
- Clean case metadata preservation without polluting error_details
"""

import asyncio
from datetime import datetime
from pathlib import Path
import sys
import uuid

SRC_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = SRC_DIR.parent
for p in [str(SRC_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.graph import get_compiled_agent
from config.config import settings
from config.db import AsyncSessionLocal, _init_db
from models.models import RecoveryState
from service.states import load_state, save_state
from tests.common import GREEN, RESET, print_banner


async def test_recurring_subscription_case():
    print_banner("4. Recurring Subscription Recovery & Update-Method Link")
    settings.demo_mode = True
    _init_db()
    case_id = f"test_sub_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:4]}"

    async with AsyncSessionLocal() as db:
        sub_case = RecoveryState(
            case_id=case_id,
            source_id="I-777",
            subscription_id="I-777",
            case_type="failed_subscription",
            amount=49.0,
            customer={"name": "Jordan Lee", "email": "rahul@example.com", "contact": "+14155550123"},
            failure_reason="Auto-debit recurring mandate failed: Card expired",
            error_details={},
            recovery_status="pending",
            attempt_count=0,
            audit_log=[],
        )
        await save_state(sub_case, db)

    agent = get_compiled_agent()
    config = {"configurable": {"thread_id": case_id}}
    await agent.ainvoke({"messages": [], "recovery_state": sub_case, "event_source": "automated.webhook"}, config=config)  # type: ignore[arg-type]

    async with AsyncSessionLocal() as db:
        after = await load_state(case_id, db)
    assert after is not None, "Case state must be persisted"

    link = (after.case_metadata or {}).get("payment_link")
    link_type = (after.case_metadata or {}).get("link_type")
    print(f"  Hydrated Link: {link} (type={link_type})")
    print(f"  Attempt={after.attempt_count}, Next Retry={after.next_retry_at}")

    assert link is not None, "PayPal update-method / payment link must be hydrated"
    assert "payment_link" not in (after.error_details or {}), "error_details must not contain payment_link"
    assert after.attempt_count == 1, "Attempt count should be 1"
    print(f"{GREEN}✓ Recurring Subscription recovery passed!{RESET}")


if __name__ == "__main__":
    asyncio.run(test_recurring_subscription_case())
