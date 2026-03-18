"""
Razorpay integration — real or mock depending on settings.MOCK_PAYMENT_MODE.

When MOCK_PAYMENT_MODE=True:
  - create_razorpay_order() returns a fake order dict  (no API call)
  - verify_razorpay_signature() always returns True

When MOCK_PAYMENT_MODE=False:
  - Requires razorpay package + real RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET
  - Real API calls are made
"""

import hashlib
import hmac
import uuid

from django.conf import settings


def create_razorpay_order(amount_paise: int, currency: str = "INR") -> dict:
    """
    Create a Razorpay order.

    :param amount_paise: Amount in smallest currency unit (paise for INR).
    :param currency: Currency code, default "INR".
    :returns: dict with razorpay_order_id, amount, currency
    """
    if settings.MOCK_PAYMENT_MODE:
        short_id = uuid.uuid4().hex[:12]
        return {
            "razorpay_order_id": f"mock_order_{short_id}",
            "amount": amount_paise,
            "currency": currency,
        }

    import razorpay  # noqa: PLC0415  (only import when needed)
    client = razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )
    order = client.order.create(
        {"amount": amount_paise, "currency": currency, "payment_capture": 1}
    )
    return {
        "razorpay_order_id": order["id"],
        "amount": order["amount"],
        "currency": order["currency"],
    }


def verify_razorpay_signature(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """
    Verify payment signature.
    In mock mode always returns True.
    """
    if settings.MOCK_PAYMENT_MODE:
        return True

    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        f"{razorpay_order_id}|{razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, razorpay_signature)
