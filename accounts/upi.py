"""UPI payment link and QR for a sales invoice."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote

_TWOPLACES = Decimal("0.01")


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)


def upi_payment_uri(*, vpa: str, payee_name: str, amount, note: str) -> str:
    """NPCI UPI link. Amount and invoice number are filled in for the payer."""
    params = [
        ("pa", (vpa or "").strip()),
        ("pn", (payee_name or "").strip()),
        ("am", f"{_money(amount):.2f}"),
        ("cu", "INR"),
        ("tn", (note or "").strip()),
        ("tr", (note or "").strip()),
    ]
    query = "&".join(f"{key}={quote(str(value), safe='')}" for key, value in params if value)
    return f"upi://pay?{query}"


def upi_qr_data_uri(uri: str) -> str:
    if not uri:
        return ""
    import segno

    return segno.make(uri, error="m").svg_data_uri(scale=4)
