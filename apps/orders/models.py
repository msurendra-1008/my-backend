import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

from core.models import BaseModel
from apps.products.models import ProductVariant


# ── Address ───────────────────────────────────────────────────────────────────

class Address(BaseModel):
    user         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="addresses"
    )
    name         = models.CharField(max_length=120)
    phone        = models.CharField(max_length=20)
    address_line = models.TextField()
    city         = models.CharField(max_length=100)
    state        = models.CharField(max_length=100)
    pincode      = models.CharField(max_length=10)
    is_default   = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        return f"{self.name}, {self.city} ({self.user})"

    def save(self, *args, **kwargs):
        # Enforce single default per user
        if self.is_default:
            Address.objects.filter(user=self.user, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


# ── Cart ──────────────────────────────────────────────────────────────────────

class Cart(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart"
    )

    def __str__(self):
        return f"Cart({self.user})"


class CartItem(BaseModel):
    cart     = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant  = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="cart_items")
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ("cart", "variant")
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.variant} × {self.quantity}"


# ── Order ─────────────────────────────────────────────────────────────────────

ORDER_STATUS_CHOICES = [
    ("pending",   "Pending"),
    ("confirmed", "Confirmed"),
    ("packed",    "Packed"),
    ("shipped",   "Shipped"),
    ("delivered", "Delivered"),
    ("cancelled", "Cancelled"),
]

PAYMENT_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("paid",    "Paid"),
    ("failed",  "Failed"),
    ("refunded","Refunded"),
]


def _gen_order_number():
    return "ORD-" + uuid.uuid4().hex[:8].upper()


class Order(BaseModel):
    order_number   = models.CharField(max_length=30, unique=True, default=_gen_order_number)
    user           = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="orders"
    )

    # Address snapshot (denormalised so it doesn't change if user edits address)
    address_name   = models.CharField(max_length=120)
    address_phone  = models.CharField(max_length=20)
    address_line   = models.TextField()
    address_city   = models.CharField(max_length=100)
    address_state  = models.CharField(max_length=100)
    address_pincode = models.CharField(max_length=10)

    # Financials
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    upa_discount    = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    amount_payable  = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    wallet_used     = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    razorpay_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    # Razorpay
    razorpay_order_id   = models.CharField(max_length=100, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    razorpay_signature  = models.CharField(max_length=255, blank=True)

    # Status
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default="pending")
    order_status   = models.CharField(max_length=15, choices=ORDER_STATUS_CHOICES, default="pending")

    # Shipping
    tracking_number = models.CharField(max_length=100, blank=True)

    # Offline POS billing
    is_offline   = models.BooleanField(default=False)
    order_type   = models.CharField(
        max_length=10,
        choices=[('upa', 'UPA'), ('regular', 'Regular')],
        default='regular',
        blank=True,
    )
    payment_method = models.CharField(max_length=10, blank=True, default='')

    # Satisfied
    is_satisfied = models.BooleanField(default=False)
    satisfied_at = models.DateTimeField(null=True, blank=True)
    satisfied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='satisfied_orders'
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_number


ORDER_ITEM_STATUS = [
    ("pending",            "Pending"),
    ("confirmed",          "Confirmed"),
    ("packed",             "Packed"),
    ("shipped",            "Shipped"),
    ("delivered",          "Delivered"),
    ("return_requested",   "Return Requested"),
    ("return_approved",    "Return Approved"),
    ("return_rejected",    "Return Rejected"),
    ("exchange_requested", "Exchange Requested"),
    ("exchange_approved",  "Exchange Approved"),
    ("exchange_rejected",  "Exchange Rejected"),
    ("refunded",           "Refunded"),
    ("exchanged",          "Exchanged"),
]

RETURN_EXCHANGE_STATUSES = {
    "return_requested", "return_approved", "return_rejected",
    "exchange_requested", "exchange_approved", "exchange_rejected",
    "refunded", "exchanged",
}


class OrderItem(BaseModel):
    order        = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant      = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL, null=True, blank=True
    )
    product_name = models.CharField(max_length=255)
    variant_name = models.CharField(max_length=120)
    sku          = models.CharField(max_length=100)
    mrp          = models.DecimalField(max_digits=12, decimal_places=2)
    upa_price    = models.DecimalField(max_digits=12, decimal_places=2)
    quantity     = models.PositiveIntegerField()
    line_total   = models.DecimalField(max_digits=12, decimal_places=2)
    other_charges = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gst_amount    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status       = models.CharField(
        max_length=30, choices=ORDER_ITEM_STATUS, default="pending"
    )
    delivered_at                 = models.DateTimeField(null=True, blank=True)
    return_rejection_count       = models.PositiveIntegerField(default=0)
    return_window_blocked        = models.BooleanField(default=False)
    return_window_blocked_reason = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.product_name} — {self.variant_name} × {self.quantity}"
