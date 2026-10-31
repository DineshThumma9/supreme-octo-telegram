"""
Suite 1: Lifecycle, Progressive Follow-Ups & Stopping Rule Enforcement.
Validates:
- Attempt increment on automated runs (Attempt 1 -> 2 -> 3)
- Inbound customer replies DO NOT increment attempt_count
- Stopping rule: strict auto-escalation to human ops when attempt >= 3
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

from langchain_core.messages import AIMessage, HumanMessage

from agent.graph import get_compiled_agent
from config.config import settings
from config.db import AsyncSessionLocal, _init_db
from models.models import RecoveryState
from service.states import load_state, save_state
import agent.nodes as agent_nodes


class _FakeLLM:
    async def ainvoke(self, messages):
        return AIMessage(content="Deterministic test reply.")


from tests.common import GREEN, RESET, print_banner


async def test_fast_forward_3_times_and_escalate():
    print_banner("1. Fast-Forward 3 Times & Auto-Escalation")
    settings.demo_mode = True
    agent_nodes.get_llm = lambda: _FakeLLM()
    _init_db()
    case_id = f"test_ff_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:4]}"

    async with AsyncSessionLocal() as db:
        initial = RecoveryState(
            case_id=case_id,
            source_id=f"ORDER-{uuid.uuid4().hex[:6]}",
            case_type="failed_payment",
            amount=480.0,
            customer={"name": "Alex Test", "email": "test@example.com", "contact": "+14155550123"},
            failure_reason="insufficient_funds",
            recovery_status="pending",
            attempt_count=0,
            audit_log=[],
        )
        await save_state(initial, db)

    agent = get_compiled_agent()
    config = {"configurable": {"thread_id": case_id}}

    # Turn 1: Attempt 1
    async with AsyncSessionLocal() as db:
        st = await load_state(case_id, db)
    await agent.ainvoke({"messages": [], "recovery_state": st, "event_source": "automated.webhook"}, config=config)  # type: ignore[arg-type]
    async with AsyncSessionLocal() as db:
        t1 = await load_state(case_id, db)
    assert t1 is not None, "State t1 must be persisted"
    print(f"  Turn 1: attempt={t1.attempt_count}, status={t1.recovery_status}, next_retry={t1.next_retry_at}")
    assert t1.attempt_count == 1, f"Expected attempt 1, got {t1.attempt_count}"
    assert t1.recovery_status == "pending", f"Expected pending, got {t1.recovery_status}"
    assert t1.next_retry_at is not None, "next_retry_at should be scheduled"

    # Turn 2: Fast-Forward to Attempt 2
    async with AsyncSessionLocal() as db:
        st = await load_state(case_id, db)
    await agent.ainvoke({"messages": [], "recovery_state": st, "event_source": "scheduled.follow_up"}, config=config)  # type: ignore[arg-type]
    async with AsyncSessionLocal() as db:
        t2 = await load_state(case_id, db)
    assert t2 is not None, "State t2 must be persisted"
    print(f"  Turn 2: attempt={t2.attempt_count}, status={t2.recovery_status}, next_retry={t2.next_retry_at}")
    assert t2.attempt_count == 2, f"Expected attempt 2, got {t2.attempt_count}"
    assert t2.recovery_status == "pending", f"Expected pending, got {t2.recovery_status}"
    assert t2.next_retry_at is not None, "next_retry_at should be scheduled"

    # Turn 3: Fast-Forward to Attempt 3
    async with AsyncSessionLocal() as db:
        st = await load_state(case_id, db)
    await agent.ainvoke({"messages": [], "recovery_state": st, "event_source": "scheduled.follow_up"}, config=config)  # type: ignore[arg-type]
    async with AsyncSessionLocal() as db:
        t3 = await load_state(case_id, db)
    assert t3 is not None, "State t3 must be persisted"
    print(f"  Turn 3: attempt={t3.attempt_count}, status={t3.recovery_status}, next_retry={t3.next_retry_at}")
    assert t3.attempt_count == 3, f"Expected attempt 3, got {t3.attempt_count}"

    # Turn 4: Attempt 3 reached ceiling -> Pre-flight Compliance Guardrail must Auto-Escalate to Human
    async with AsyncSessionLocal() as db:
        st = await load_state(case_id, db)
    await agent.ainvoke({"messages": [], "recovery_state": st, "event_source": "scheduled.follow_up"}, config=config)  # type: ignore[arg-type]
    async with AsyncSessionLocal() as db:
        t4 = await load_state(case_id, db)
    assert t4 is not None, "State t4 must be persisted"
    print(f"  Turn 4 (Post-Attempt 3): attempt={t4.attempt_count}, status={t4.recovery_status}, last_action={t4.last_action_taken}, next_retry={t4.next_retry_at}")
    assert t4.attempt_count == 3, f"Attempt count must NEVER exceed 3 (got {t4.attempt_count}/3)"
    assert t4.recovery_status == "escalated", f"Expected status 'escalated', got '{t4.recovery_status}'"
    assert t4.last_action_taken == "escalate_to_human", f"Expected last_action 'escalate_to_human', got '{t4.last_action_taken}'"
    assert t4.next_retry_at is None, f"Expected next_retry_at None after escalation, got {t4.next_retry_at}"
    # Inbound replies are a separate, non-attempt path: they must not consume
    # one of the three automated outreach attempts.
    inbound_case = f"test_inbound_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:4]}"
    async with AsyncSessionLocal() as db:
        inbound_state = RecoveryState(
            case_id=inbound_case,
            source_id=f"ORDER-{uuid.uuid4().hex[:6]}",
            case_type="failed_payment",
            amount=480.0,
            customer={"name": "Alex Test", "email": "test@example.com", "contact": "+14155550123"},
            failure_reason="insufficient_funds",
            recovery_status="pending",
            attempt_count=0,
            audit_log=[],
        )
        await save_state(inbound_state, db)
        st = await load_state(inbound_case, db)
    await agent.ainvoke({
        "messages": [HumanMessage(content="Why did my card payment decline? Can you help?")],
        "recovery_state": st,
        "event_source": "inbound.whatsapp",
    }, config={"configurable": {"thread_id": inbound_case}})  # type: ignore[arg-type]
    async with AsyncSessionLocal() as db:
        inbound_after = await load_state(inbound_case, db)
    assert inbound_after is not None, "Inbound state must be persisted"
    assert inbound_after.attempt_count == 0, (
        f"Inbound reply must NOT increment attempt_count (expected 0, got {inbound_after.attempt_count})"
    )
    print(f"  Inbound reply: attempt={inbound_after.attempt_count} (MUST remain 0)")

    print(f"{GREEN}✓ Fast-forward 3 times and auto-escalation strictly at 3/3 passed!{RESET}")
    print(f"{GREEN}✓ Inbound replies do not consume automated attempts!{RESET}")


if __name__ == "__main__":
    asyncio.run(test_fast_forward_3_times_and_escalate())
