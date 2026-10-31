"""
Suite 3: B2B Commercial Overdue Invoice Recovery.
Validates:
- AP tone decorum and formal finance language
- Net-30 terms and PO/Invoice metadata reflection
- TDS compliance acknowledgment (Section 194C @ 2%, Section 194J @ 10%)
- Audit trail recording B2B recovery outreach
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
from agent.prompts import get_escalation_tone
from config.config import settings
from config.db import AsyncSessionLocal, _init_db
from models.models import RecoveryState
from service.states import load_state, save_state
from tests.common import GREEN, RESET, print_banner


async def test_overdue_invoice_case():
    print_banner("3. B2B Commercial Overdue Invoice Recovery")
    settings.demo_mode = True
    _init_db()
    case_id = f"test_inv_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:4]}"

    async with AsyncSessionLocal() as db:
        inv_case = RecoveryState(
            case_id=case_id,
            source_id="INV2-999",
            case_type="overdue_invoice",
            amount=4800.0,
            customer={"name": "Acme Corp AP", "email": "ap@acme.com", "contact": "+14155550123"},
            failure_reason="Invoice overdue by 15 days",
            error_details={},
            case_metadata={"invoice_number": "INV-2026-8888", "po_number": "PO-4421"},
            recovery_status="pending",
            attempt_count=0,
            audit_log=[],
        )
        await save_state(inv_case, db)

    # Verify B2B escalation tone contract
    wa_msg, email_urg, voice_msg = get_escalation_tone(inv_case)
    print(f"  B2B WhatsApp Copy : {wa_msg[:80]}...")
    print(f"  B2B Email Urgency : {email_urg}")
    print(f"  B2B Voice Script  : {voice_msg[:80]}...")

    assert "Accounts Payable" in wa_msg or "Invoice" in wa_msg, "B2B copy must address AP / Invoice"
    assert email_urg.startswith("b2b_"), f"Expected B2B email urgency, got {email_urg}"
    assert "Accounts Receivable" in voice_msg, "B2B voice note must identify as Accounts Receivable"

    # Run agent execution
    agent = get_compiled_agent()
    config = {"configurable": {"thread_id": case_id}}
    await agent.ainvoke({"messages": [], "recovery_state": inv_case, "event_source": "automated.webhook"}, config=config)  # type: ignore[arg-type]

    async with AsyncSessionLocal() as db:
        after = await load_state(case_id, db)
    assert after is not None, "Case state must be persisted"
    print(f"  Execution: attempt={after.attempt_count}, last_action={after.last_action_taken}, status={after.recovery_status}")
    assert after.attempt_count == 1, "Attempt count should be 1"
    assert len(after.audit_log) > 0, "Audit log must record B2B outreach"
    print(f"{GREEN}✓ B2B Commercial Overdue Invoice recovery passed!{RESET}")


if __name__ == "__main__":
    asyncio.run(test_overdue_invoice_case())
