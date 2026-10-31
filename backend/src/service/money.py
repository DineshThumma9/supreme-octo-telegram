"""Currency formatting helpers. Every amount carries a currency."""

from __future__ import annotations

_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "CAD": "CA$",
    "AUD": "A$",
}


def format_money(amount: float | int | None, currency: str = "USD", decimals: int = 2) -> str:
    value = float(amount or 0.0)
    code = (currency or "USD").upper()
    symbol = _SYMBOLS.get(code)
    if symbol:
        return f"{symbol}{value:,.{decimals}f}"
    return f"{code} {value:,.{decimals}f}"


def format_state_amount(state, amount: float | None = None) -> str:
    return format_money(state.amount if amount is None else amount, state.currency or "USD")
