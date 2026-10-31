"""
Suite 2: Promise-To-Pay (PTP) Validation, Grace Period Limits & Scheduling.
Validates:
- Valid future date within policy window (<= 7 days)
- Past dates rejection
- Out-of-bounds dates rejection (> 7 days)
- Anti-exploitation: Cumulative grace period tracking from initial failure incident
- Tool execution with natural language date parsing
- Vague reply fallback (`date_str=None`) with +3 days scheduling
"""

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import uuid

SRC_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = SRC_DIR.parent
for p in [str(SRC_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.tools import log_promise_to_pay
from agent.utils import sanity_date
from config.config import settings
from config.db import AsyncSessionLocal
from models.models import RecoveryState
from service.states import load_state, save_state
from tests.common import GREEN, RESET, print_banner


async def test_promise_to_pay_case():
    print_banner("2. Promise-To-Pay (PTP) Validation & Scheduling")
    settings.demo_mode = True
    now = datetime.now()

    # 1. Valid future date (within 7 days max grace)
    valid_dt = now + timedelta(days=3)
    is_valid, msg = sanity_date(valid_dt)
    print(f"  Testing date +3 days ({valid_dt.strftime('%Y-%m-%d')}): valid={is_valid}, msg={msg}")
    assert is_valid is True, f"Expected valid date, got {msg}"

    # 2. Past date (must be rejected)
    past_dt = now - timedelta(days=1)
    is_valid_past, msg_past = sanity_date(past_dt)
    print(f"  Testing past date ({past_dt.strftime('%Y-%m-%d')}): valid={is_valid_past}, msg={msg_past}")
    assert is_valid_past is False, "Past date should be rejected"

    # 3. Excessive grace period (> 7 days, must be rejected)
    far_dt = now + timedelta(days=20)
    is_valid_far, msg_far = sanity_date(far_dt)
    print(f"  Testing far future date ({far_dt.strftime('%Y-%m-%d')}): valid={is_valid_far}, msg={msg_far}")
    assert is_valid_far is False, "Date beyond policy grace period should be rejected"

    # 4. Anti-Exploitation: Cumulative Grace Period Tracking
    # Incident five days ago; first promise today (5 days used), then the customer
    # tries to re-promise six days from now (11 cumulative days > 7 limit).
    incident_date = now.date() - timedelta(days=5)
    ptp_1 = datetime.combine(incident_date + timedelta(days=5), datetime.min.time()).replace(hour=10)
    valid_ptp_1, msg_ptp_1 = sanity_date(ptp_1, anchor_date=incident_date)
    print(f"  Testing Turn 1 promise today (incident 5 days ago): valid={valid_ptp_1}, msg={msg_ptp_1}")
    assert valid_ptp_1 is True, "First promise within 7 cumulative days should be valid"

    ptp_2_exploit = datetime.combine(incident_date + timedelta(days=11), datetime.min.time()).replace(hour=10)
    valid_ptp_2, msg_ptp_2 = sanity_date(ptp_2_exploit, anchor_date=incident_date)
    print(f"  Testing Turn 2 chained promise six days out (incident 5 days ago): valid={valid_ptp_2}, msg={msg_ptp_2}")
    assert valid_ptp_2 is False, "Chained promise exceeding cumulative 7-day limit from incident must be rejected"

    # 5. Tool execution test: Date extracted from typo ("5th of spet" -> valid tomorrow date)
    case_id_ptp = f"test_ptp_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:4]}"
    async with AsyncSessionLocal() as db:
        ptp_case = RecoveryState(
            case_id=case_id_ptp,
            source_id=f"ORDER-{uuid.uuid4().hex[:6]}",
            case_type="failed_payment",
            amount=480.0,
            customer={"name": "Alex Test", "email": "test@example.com", "contact": "+14155550123"},
            failure_reason="insufficient_funds",
            recovery_status="pending",
            attempt_count=1,
            audit_log=[],
        )
        await save_state(ptp_case, db)

    config_ptp = {"configurable": {"thread_id": case_id_ptp}}
    valid_ptp_str = (now + timedelta(days=2)).strftime("%Y-%m-%d")
    res_ptp = await log_promise_to_pay.ainvoke(
        {"date_str": valid_ptp_str, "reason": "5th of spet payment commitment", "sentiment": "neutral"},
        config=config_ptp,  # type: ignore[arg-type]
    )
    print(f"  Tool execution (valid date): {res_ptp}")
    assert "Successfully logged promise to pay" in res_ptp

    async with AsyncSessionLocal() as db:
        after_ptp = await load_state(case_id_ptp, db)
    assert after_ptp is not None, "State after_ptp must be persisted"
    assert after_ptp.recovery_status == "pending", "Case must remain pending (not escalated) on valid date"
    assert (after_ptp.case_metadata or {}).get("cumulative_grace_days_used") is not None
    assert "cumulative_grace_days_used" not in (after_ptp.error_details or {})

    # 6. Tool execution test: No date / vague reply (`date_str=None`) -> schedules +3 days, NO escalation
    case_id_none = f"test_none_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:4]}"
    async with AsyncSessionLocal() as db:
        none_case = RecoveryState(
            case_id=case_id_none,
            source_id=f"ORDER-{uuid.uuid4().hex[:6]}",
            case_type="failed_payment",
            amount=480.0,
            customer={"name": "Alex Test", "email": "test@example.com", "contact": "+14155550123"},
            failure_reason="insufficient_funds",
            recovery_status="pending",
            attempt_count=1,
            audit_log=[],
        )
        await save_state(none_case, db)

    config_none = {"configurable": {"thread_id": case_id_none}}
    res_none = await log_promise_to_pay.ainvoke(
        {"date_str": None, "reason": "Will pay in a few days", "sentiment": "gentle"},
        config=config_none,  # type: ignore[arg-type]
    )
    print(f"  Tool execution (date_str=None): {res_none}")
    assert "No concrete commitment date specified" in res_none or "standard follow-up scheduled" in res_none

    async with AsyncSessionLocal() as db:
        after_none = await load_state(case_id_none, db)
    assert after_none is not None, "State after_none must be persisted"
    assert after_none.recovery_status == "pending", "Vague reply without concrete date must NOT escalate to human"
    assert after_none.next_retry_at is not None, "Standard +3 days follow-up must be scheduled"

    print(f"{GREEN}✓ Promise-to-Pay policy validation and execution passed!{RESET}")


if __name__ == "__main__":
    asyncio.run(test_promise_to_pay_case())
