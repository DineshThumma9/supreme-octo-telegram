"""Conversational prompt templates and outbound recovery copy."""

from datetime import datetime

from config.config import settings
from models.models import RecoveryState
from service.compliance import get_bell_curve_discount
from service.money import format_money


def get_escalation_tone(rs: RecoveryState, attempt: int | None = None) -> tuple[str, str, str]:
    """Return (whatsapp_msg, email_urgency, voice_msg) for the current Play."""
    if attempt is None:
        attempt = rs.attempt_count or 1
    name = rs.customer.get("name", "Customer")
    currency = rs.currency or "USD"
    amount_str = format_money(rs.amount, currency)
    ref_code = rs.case_id[-4:].upper() if len(rs.case_id) >= 4 else rs.case_id

    if rs.case_type == "abandoned_checkout":
        meta = rs.case_metadata or {}
        disc = meta.get("discount_pct") or meta.get("eligible_discount")
        if disc is None:
            disc = get_bell_curve_discount(rs)
        disc_val = float(disc) if disc else float(settings.min_discount)
        eff_amt = meta.get("effective_amount")
        eff_amt_str = format_money(eff_amt, currency) if eff_amt else amount_str
        if attempt <= 1:
            wa_msg = (
                f"Hi {name}, you left items in your cart ({amount_str}). Complete checkout today "
                f"with a reserved {disc_val:.0f}% discount (payable: {eff_amt_str}): "
                f"{{payment_link}} (Ref: #RNV-{ref_code})"
            )
        elif attempt == 2:
            wa_msg = (
                f"Reminder: {name}, your reserved {disc_val:.0f}% cart concession "
                f"({amount_str} -> {eff_amt_str}) expires within 24 hours. Complete order: "
                f"{{payment_link}} (Ref: #RNV-{ref_code})"
            )
        else:
            wa_msg = (
                f"Final reminder: {name}, this is your last chance to claim your reserved "
                f"{disc_val:.0f}% discount. Checkout: {{payment_link}} (Ref: #RNV-{ref_code})"
            )
        voice_msg = (
            f"Hello {name}, this is Renvue customer concierge. We noticed you left items in "
            f"your cart. We've reserved a {disc_val:.0f}% discount and sent the secure PayPal "
            f"link to your WhatsApp. Thank you."
        )
        email_urg = "cart_gentle" if attempt <= 1 else "cart_urgent" if attempt == 2 else "cart_final"
        return wa_msg, email_urg, voice_msg

    if rs.case_type == "overdue_invoice":
        meta = rs.case_metadata or {}
        inv_num = meta.get("invoice_number", f"INV-{ref_code}")
        po_num = meta.get("po_number", f"PO-{ref_code}")
        if attempt <= 1:
            wa_msg = (
                f"Dear Accounts Payable ({name}), a courtesy reminder that invoice {inv_num} "
                f"({amount_str}, PO: {po_num}) is past due. Settle securely via PayPal: "
                f"{{payment_link}} (Ref: #RNV-{ref_code})"
            )
            email_urg = "b2b_gentle"
        elif attempt == 2:
            wa_msg = (
                f"Attention Accounts Payable ({name}): invoice {inv_num} ({amount_str}) is "
                f"overdue. Review and settle invoice: {{payment_link}} (Ref: #RNV-{ref_code})"
            )
            email_urg = "b2b_urgent"
        else:
            wa_msg = (
                f"Final notice: commercial invoice {inv_num} ({amount_str}) remains unsettled. "
                f"Settle invoice: {{payment_link}} (Ref: #RNV-{ref_code})"
            )
            email_urg = "b2b_final"
        voice_msg = (
            f"Hello {name}, this is Accounts Receivable regarding overdue invoice {inv_num} "
            f"for {amount_str}. Please review the PayPal invoice link to prevent a hold."
        )
        return wa_msg, email_urg, voice_msg

    if rs.case_type in {"subscription_cancelled", "subscription_suspended"}:
        wa_msg = (
            f"Hi {name}, your subscription payment of {amount_str} needs attention. Your "
            f"recurring payment method may have expired. Update it securely here: "
            f"{{payment_link}} (Ref: #RNV-{ref_code})"
        )
        email_urg = "gentle" if attempt <= 1 else "urgent" if attempt == 2 else "final"
        voice_msg = (
            f"Hello {name}, your subscription payment method needs an update. Please use the "
            f"secure PayPal link sent to your WhatsApp. Thank you."
        )
        return wa_msg, email_urg, voice_msg

    if rs.decline_type == "soft":
        if attempt <= 1:
            wa_msg = (
                f"Hi {name}, your payment of {amount_str} didn't go through due to a temporary "
                f"bank issue. Your order is reserved. Retry securely here: "
                f"{{payment_link}} (Ref: #RNV-{ref_code})"
            )
        elif attempt == 2:
            wa_msg = (
                f"Urgent: {name}, your payment of {amount_str} remains pending. Please complete "
                f"your order within 24 hours: {{payment_link}} (Ref: #RNV-{ref_code})"
            )
        else:
            wa_msg = (
                f"Final notice: {name}, this is our last reminder for {amount_str}. Review "
                f"and settle order: {{payment_link}} (Ref: #RNV-{ref_code})"
            )
        voice_msg = (
            f"Hello {name}, this is Renvue support. Your payment of {amount_str} was interrupted "
            f"by a temporary issue. We've sent a secure PayPal link to your WhatsApp."
        )
        email_urg = "gentle" if attempt <= 1 else "urgent" if attempt == 2 else "final"
        return wa_msg, email_urg, voice_msg

    details = rs.error_details or {}
    card_net = details.get("card_brand")
    card_last4 = details.get("card_last4")
    card_str = f" on your {card_net} (••{card_last4})" if card_net and card_last4 else ""

    if attempt <= 1:
        wa_msg = (
            f"Hi {name}, your payment of {amount_str}{card_str} was declined. Tap to update "
            f"your payment method or pay another way: {{payment_link}} (Ref: #RNV-{ref_code})"
        )
    elif attempt == 2:
        wa_msg = (
            f"Urgent: {name}, your payment of {amount_str} is overdue. Please update your "
            f"payment method today: {{payment_link}} (Ref: #RNV-{ref_code})"
        )
    else:
        wa_msg = (
            f"Final notice: {name}, outstanding payment of {amount_str} is unresolved. Settle "
            f"balance: {{payment_link}} (Ref: #RNV-{ref_code})"
        )
    voice_msg = (
        f"Hello {name}, this is Renvue support. Your payment of {amount_str} was declined. "
        f"A secure PayPal update link has been sent to your WhatsApp. Thank you."
    )
    email_urg = "gentle" if attempt <= 1 else "urgent" if attempt == 2 else "final"
    return wa_msg, email_urg, voice_msg


def should_send_channel(rs: RecoveryState, channel: str) -> bool:
    """Choose a channel from preference, contact data, and urgency."""
    pref = (getattr(rs, "contact_preference", None) or rs.customer.get("contact_preference", "")).lower()
    has_email = bool(rs.customer.get("email"))
    has_phone = bool(rs.customer.get("contact"))

    if channel == "email":
        if not has_email:
            return False
        if rs.case_type == "overdue_invoice":
            return True
        return pref == "email" or not has_phone or (rs.attempt_count or 0) >= 2

    if channel == "whatsapp":
        if not has_phone:
            return False
        if pref == "email" and has_email and (rs.attempt_count or 0) < 2:
            return False
        return True

    if channel == "voice":
        if not has_phone:
            return False
        if pref in ["email", "whatsapp"]:
            return False
        return pref == "call" or ((rs.attempt_count or 0) >= 2 and (rs.amount or 0) > 250)

    return False


def build_system_prompt(rs: RecoveryState) -> str:
    """Build the LLM system prompt for inbound customer replies."""
    meta = rs.case_metadata or {}
    eligible_discount = meta.get("eligible_discount")
    discount_guidance = (
        f"Pre-approved concession ceiling: {eligible_discount}%."
        if eligible_discount is not None
        else "Call 'calculate_discount_offer' to check margin approval."
    )

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    incident_date = meta.get("initial_failure_date") or (
        rs.first_seen_at.strftime("%Y-%m-%d") if rs.first_seen_at else today_str
    )
    cumulative_grace_used = meta.get("cumulative_grace_days_used", 0)
    remaining_grace = max(0, settings.max_grace_period - cumulative_grace_used)
    amount_str = format_money(rs.amount, rs.currency or "USD")

    return f"""You are an empathetic, intelligent revenue recovery concierge for Renvue.

=== CURRENT CASE ===
Customer              : {rs.customer.get('name', 'Unknown')}
Amount owed           : {amount_str}
Currency              : {rs.currency or 'USD'}
Case type             : {rs.case_type}
Attempt Count         : {rs.attempt_count}
Language              : {rs.language}
Today's Date          : {today_str}
Incident Date         : {incident_date}
Cumulative Grace Used : {cumulative_grace_used} days (remaining: {remaining_grace} days)
Max Grace Period      : {settings.max_grace_period} days from incident
Max Discount          : {settings.max_discount}%
Min Discount          : {settings.min_discount}%

=== CORE RECOVERY RULES ===
1. STOPPING RULE: If Attempt Count >= 3 (and not explicitly authorized by human approval), you MUST call 'escalate_to_human' and STOP.

2. PROMISE TO PAY:
   - Customers may respond in any language or informal text with typos.
   - Extract the intended commitment date and resolve it to YYYY-MM-DD.
   - If the date is in the past or beyond the cumulative grace period of {settings.max_grace_period} days from {incident_date}, explain and escalate only when the customer refuses to cooperate.
   - When a date is specified, call 'log_promise_to_pay(date_str="YYYY-MM-DD", reason=..., sentiment=...)'.
   - If no specific date was provided, call 'log_promise_to_pay(date_str=None, reason=..., sentiment=...)'. Do NOT escalate for a vague reply.

3. NEGOTIATION & DISCOUNTS: For abandoned checkouts only, call 'calculate_discount_offer' before mentioning a concession. Never invent a percentage. Then call 'create_payment_link(discount_pct=...)' with the approved discount.

4. OUTREACH: Use 'send_whatsapp_msg' for replies. Any generated PayPal link is attached automatically; you may position it with the placeholder '{{payment_link}}'.

5. ESCALATION: Call 'escalate_to_human' only for hostile/abusive customers, explicit refusal to pay, absurd dates used to evade payment, exhausted cumulative grace, or Attempt Count >= 3.

=== B2B COMMERCIAL INVOICE RULES ===
- For 'overdue_invoice', address Accounts Payable / Finance with formal decorum.
- Confirm payment runs, PO references, and remittance timing without promising legal outcomes.
- Use the PayPal invoice link; do not ask for bank details in chat.

=== PAYMENT CONCIERGE FAQ ===
- If money was debited but the order failed, reassure the customer and ask for the PayPal transaction ID so finance can reconcile.
- If they ask how to update a subscription payment method, tell them to use the secure PayPal link or PayPal > Settings > Payments > Automatic payments.
- If they question link legitimacy, explain that the link is a PayPal-hosted checkout/invoice and never ask for card numbers in chat.

=== OUTPUT FORMAT RULES ===
- Never output placeholder brackets like '[Service]' or '[Insert Link]'.
- Refer to the transaction naturally as 'your order', 'your invoice', or 'your subscription'.
- Keep replies concise, professional, and ready for delivery.
"""
