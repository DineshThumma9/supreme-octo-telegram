"""Static configuration for the PayPal-first Renvue runtime."""

# PayPal does not expose ISO 8583 decline codes the way card acquirers do.
# These are the reason/issue strings PayPal puts on denied captures and failed
# subscription payments. They are mapped to a hard/soft/transient class in
# paypal/events.py instead of being shown to customers verbatim.
HARD_DECLINE_MARKERS = (
    "card_expired",
    "expired_card",
    "invalid_card",
    "card_declined",
    "payment_denied",
    "restricted",
    "fraud",
    "stolen",
    "account_closed",
    "instrument_declined",
    "buyer_cannot_pay",
)

TRANSIENT_DECLINE_MARKERS = (
    "insufficient_funds",
    "temporary",
    "try_again",
    "processor_declined",
    "issuer_declined",
    "timeout",
)


email_messages = {
    "gentle": (
        "Hi {name},<br><br>We noticed your recent payment of ${amount} didn't go through. "
        "Your order is still reserved. Please use the secure link to retry.<br><br>"
        "Thanks,<br>The Team"
    ),
    "urgent": (
        "Hi {name},<br><br>Your payment of ${amount} is still pending. To prevent service "
        "suspension within 24 hours, please update your payment method or complete checkout "
        "using the secure link below.<br><br>Thanks,<br>The Team"
    ),
    "final": (
        "Dear {name},<br><br>FINAL NOTICE: This is our last automated reminder regarding "
        "your outstanding payment of ${amount}. Your account has been transferred to support "
        "for review.<br><br>Thanks,<br>The Team"
    ),
    "b2b_gentle": (
        "Dear Accounts Payable ({name}),<br><br>This is a courtesy reminder that Invoice "
        "<strong>{invoice_number}</strong> for <strong>${amount}</strong> is past due under "
        "the agreed payment terms.<br><br>Please settle the balance using the secure PayPal "
        "invoice link below.<br><br>Invoice: {link}<br><br>Regards,<br>Finance & Receivables"
    ),
    "b2b_urgent": (
        "Attention: Accounts Payable & Finance Team ({name}),<br><br><strong>URGENT: Overdue "
        "balance for Invoice {invoice_number} (${amount})</strong>.<br><br>This invoice is "
        "overdue. Continued non-settlement may result in a vendor account hold within 48 "
        "hours.<br><br>Immediate settlement: {link}<br><br>Regards,<br>Finance Operations"
    ),
    "b2b_final": (
        "FINAL NOTICE: Overdue commercial invoice {invoice_number} (${amount})<br><br>"
        "Dear {name},<br><br>Despite multiple notifications, the outstanding balance remains "
        "unsettled. This case has been escalated to finance operations.<br><br>Please clear "
        "the balance: {link}<br><br>Accounts Receivable"
    ),
    "cart_gentle": (
        "Hi {name},<br><br>We noticed you left items in your cart (${amount}). A reserved "
        "discount has been applied to your order.<br><br>Complete your purchase securely "
        "here: {link}<br><br>Thanks,<br>The Team"
    ),
    "cart_urgent": (
        "Hi {name},<br><br>Reminder: your reserved cart discount (payable: ${amount}) is "
        "expiring soon. Complete your checkout to secure your items.<br><br>Checkout: "
        "{link}<br><br>Thanks,<br>The Team"
    ),
    "cart_final": (
        "Dear {name},<br><br>FINAL REMINDER: your reserved items and cart discount "
        "(${amount}) will expire today.<br><br>Checkout now: {link}<br><br>Thanks,<br>The Team"
    ),
}


STATUS_ORDER = {
    "escalated": 0,
    "in_progress": 1,
    "pending": 2,
    "recovered": 3,
    "closed": 4,
}

PAYPAL_HANDLED_EVENTS = [
    "PAYMENT.CAPTURE.DENIED",
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.PENDING",
    "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.CAPTURE.REVERSED",
    "CHECKOUT.ORDER.APPROVED",
    "CHECKOUT.ORDER.COMPLETED",
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
    "BILLING.SUBSCRIPTION.SUSPENDED",
    "BILLING.SUBSCRIPTION.CANCELLED",
    "BILLING.SUBSCRIPTION.ACTIVATED",
    "INVOICING.INVOICE.PAID",
    "INVOICING.INVOICE.UPDATED",
    "CUSTOMER.DISPUTE.CREATED",
    "CUSTOMER.DISPUTE.RESOLVED",
]

PAYPAL_SUCCESS_EVENTS = {
    "PAYMENT.CAPTURE.COMPLETED",
    "CHECKOUT.ORDER.COMPLETED",
    "INVOICING.INVOICE.PAID",
    "BILLING.SUBSCRIPTION.ACTIVATED",
}

PAYPAL_FAILURE_EVENTS = {
    "PAYMENT.CAPTURE.DENIED",
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
    "INVOICING.INVOICE.UPDATED",
}

PAYPAL_HOLD_EVENTS = {"PAYMENT.CAPTURE.PENDING"}

PAYPAL_DISPUTE_EVENTS = {
    "CUSTOMER.DISPUTE.CREATED",
    "CUSTOMER.DISPUTE.RESOLVED",
}
