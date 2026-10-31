"""
Suite 5: Abandoned Checkout Concession & Anti-Gaming Margin Protection.
Validates:
- Strict policy denial of discounts on invoices and recurring subscriptions
- Bounded bell-curve concession margin calculation (5% to 30%)
- Initial outreach with hydrated discounted checkout link
- Multi-turn inbound conversational negotiation via LLM
- Anti-gaming enforcement: customer haggle never exceeds pre-approved margin ceiling
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
from service.compliance import get_bell_curve_discount
from service.states import load_state, save_state
import agent.nodes as agent_nodes


class _FakeLLM:
    async def ainvoke(self, messages):
        return AIMessage(content="Deterministic test reply.")


from tests.common import GREEN, RESET, print_banner


async def test_abandoned_checkout_bell_curve_discount():
    print_banner("5. Abandoned Checkout Bell-Curve Concession & Anti-Gaming")
    settings.demo_mode = True
    agent_nodes.get_llm = lambda: _FakeLLM()
    _init_db()

    # 1. Non-abandoned case policy rejection verification
    inv_state = RecoveryState(case_id="dummy_inv", source_id="INV2-1", case_type="overdue_invoice", amount=4800.0)
    sub_state = RecoveryState(case_id="dummy_sub", source_id="I-1", case_type="failed_subscription", amount=49.0)
    assert get_bell_curve_discount(inv_state) == 0.0, "Discounts must be strictly disallowed for corporate invoices"
    assert get_bell_curve_discount(sub_state) == 0.0, "Discounts must be strictly disallowed for recurring subscriptions"

    # 2. Abandoned checkout deterministic recovery flow
    case_id = f"test_cart_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:4]}"
    original_amount = 5000.0

    async with AsyncSessionLocal() as db:
        cart_case = RecoveryState(
            case_id=case_id,
            source_id="ORDER-CART-42",
            case_type="abandoned_checkout",
            amount=original_amount,
            customer={"name": "Taylor Reed", "email": "ananya@example.com", "contact": "+14155550123"},
            failure_reason="Checkout abandoned on shipping details step",
            error_details={},
            recovery_status="pending",
            attempt_count=0,
            audit_log=[],
        )
        await save_state(cart_case, db)

    agent = get_compiled_agent()
    config = {"configurable": {"thread_id": case_id}}

    # Turn 1: Deterministic outreach with bell-curve calculated concession
    await agent.ainvoke({"messages": [], "recovery_state": cart_case, "event_source": "automated.webhook"}, config=config)  # type: ignore[arg-type]

    async with AsyncSessionLocal() as db:
        t1 = await load_state(case_id, db)
    assert t1 is not None, "Case state must be persisted"

    meta_t1 = t1.case_metadata or {}
    eligible = meta_t1.get("eligible_discount")
    applied = meta_t1.get("discount_pct")
    eff_amt = meta_t1.get("effective_amount")
    link = meta_t1.get("payment_link")

    print(f"  Attempt 1 Outreach: eligible_discount={eligible}%, applied_discount={applied}%, effective_amount=${eff_amt}, link={link}")
    assert eligible is not None and 5.0 <= eligible <= 30.0, f"Eligible discount must be between 5-30% (got {eligible})"
    assert applied == eligible, f"Applied discount ({applied}%) must match locked eligible discount ({eligible}%)"
    assert applied is not None and eff_amt is not None
    expected_eff = original_amount * (1 - applied / 100.0)
    assert abs(eff_amt - expected_eff) < 0.01, f"Effective amount mismatch: {eff_amt} vs {expected_eff}"
    assert link is not None, "Discounted payment link must be generated"

    # Turn 2: Customer haggles for absurd discount (e.g. "Give me 50% discount and I will pay now")
    # Anti-gaming rule: Agent must use calculate_discount_offer and NEVER exceed the pre-approved ceiling
    await agent.ainvoke({
        "messages": [HumanMessage(content="This is too expensive. Can you give me a 50% discount right now? I will complete payment immediately.")],
        "recovery_state": t1,
        "event_source": "inbound.whatsapp",
    }, config=config)  # type: ignore[arg-type]

    async with AsyncSessionLocal() as db:
        t2 = await load_state(case_id, db)
    assert t2 is not None, "Case state must be persisted"

    meta_t2 = t2.case_metadata or {}
    post_haggle_discount = meta_t2.get("discount_pct")
    print(f"  Customer Haggle Response: eligible={eligible}%, applied={post_haggle_discount}%")
    assert post_haggle_discount is not None and post_haggle_discount <= eligible, f"Applied discount must not exceed locked ceiling ({eligible}%)"
    assert "eligible_discount" not in (t2.error_details or {}), "error_details must not contain eligible_discount"
    assert "discount_pct" not in (t2.error_details or {}), "error_details must not contain discount_pct"
    assert t2.attempt_count == 1, "Inbound negotiation reply must not increment attempt_count"

    print(f"{GREEN}✓ Abandoned Checkout Bell-Curve Concession & Anti-Gaming test passed!{RESET}")


if __name__ == "__main__":
    asyncio.run(test_abandoned_checkout_bell_curve_discount())
