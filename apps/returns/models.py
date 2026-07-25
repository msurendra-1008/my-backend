from django.conf import settings
from django.db import models

from core.models import BaseModel
from apps.orders.models import OrderItem
from apps.products.models import ProductVariant


# ── ReturnSettings (singleton) ────────────────────────────────────────────────

DEFAULT_REASONS = [
    "Damaged product",
    "Wrong item received",
    "Not as described",
    "Changed my mind",
    "Size/variant issue",
]


class ReturnSettings(BaseModel):
    return_window_days   = models.PositiveIntegerField(default=7)
    exchange_buffer_days = models.PositiveIntegerField(default=1)
    max_attempts         = models.PositiveIntegerField(default=2)
    predefined_reasons   = models.JSONField(default=list)
    updated_by         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="return_settings_updates",
    )

    class Meta:
        verbose_name        = "Return Settings"
        verbose_name_plural = "Return Settings"

    def __str__(self):
        return f"ReturnSettings (window={self.return_window_days} days)"

    def save(self, *args, **kwargs):
        # Enforce singleton — always save over the first existing row
        if not self.pk:
            existing = ReturnSettings.objects.first()
            if existing:
                self.pk = existing.pk
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create(
                return_window_days=7,
                predefined_reasons=DEFAULT_REASONS,
            )
        return obj


# ── ReturnRequest ─────────────────────────────────────────────────────────────

REQUEST_TYPE_CHOICES = [
    ("return",   "Return"),
    ("exchange", "Exchange"),
]

REQUEST_STATUS_CHOICES = [
    ("raised",               "Raised"),
    ("under_review",         "Under Review"),
    ("approved",             "Approved"),
    ("exchange_dispatched",  "Exchange Dispatched"),
    ("rejected",             "Rejected"),
    ("rejected_final",       "Rejected Final"),
    ("completed",            "Completed"),
]

# Admin can act on these (approve / reject / request-info)
ACTIVE_REQUEST_STATUSES = ["raised", "under_review", "approved"]

# These block mark_satisfied and commission credit for the whole order
BLOCKING_REQUEST_STATUSES = ["raised", "under_review", "approved", "exchange_dispatched"]

WAITING_FOR_CHOICES = [
    ("admin", "Admin"),
    ("user",  "User"),
    ("",      "Nobody"),
]

REFUND_MODE_CHOICES = [
    ("wallet",          "Wallet"),
    ("original_source", "Original Source"),
]

LOG_ACTION_CHOICES = [
    ("raised",        "Raised"),
    ("info_requested","Info Requested"),
    ("user_replied",  "User Replied"),
    ("approved",      "Approved"),
    ("rejected",      "Rejected"),
    ("rejected_final","Rejected Final"),
    ("re_raised",     "Re-raised"),
    ("completed",     "Completed"),
]


class ReturnRequest(BaseModel):
    order_item       = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name="return_requests")
    request_type     = models.CharField(max_length=10, choices=REQUEST_TYPE_CHOICES)
    return_qty       = models.PositiveIntegerField(default=1)
    exchange_variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="exchange_requests",
    )
    reason        = models.CharField(max_length=255)
    notes         = models.TextField(blank=True)
    status        = models.CharField(max_length=20, choices=REQUEST_STATUS_CHOICES, default="raised")
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    refund_mode   = models.CharField(max_length=20, choices=REFUND_MODE_CHOICES, default="wallet")
    admin_notes      = models.TextField(blank=True)
    user_reply_count = models.PositiveIntegerField(default=0)
    waiting_for      = models.CharField(max_length=10, choices=WAITING_FOR_CHOICES, default="admin", blank=True)
    attempt_count    = models.PositiveIntegerField(default=1)
    reviewed_at      = models.DateTimeField(null=True, blank=True)
    completed_at  = models.DateTimeField(null=True, blank=True)
    raised_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name="raised_return_requests",
    )
    reviewed_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="reviewed_return_requests",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.request_type.upper()} #{self.id} — {self.order_item} ({self.status})"


# ── ReturnRequestLog ──────────────────────────────────────────────────────────

class ReturnRequestLog(BaseModel):
    return_request = models.ForeignKey(
        ReturnRequest, on_delete=models.CASCADE, related_name="logs",
    )
    action     = models.CharField(max_length=20, choices=LOG_ACTION_CHOICES)
    actor      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="return_log_actions",
    )
    actor_role = models.CharField(max_length=20, blank=True)
    notes      = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.action} on {self.return_request_id} by {self.actor_id}"


# ── ReturnPhoto ───────────────────────────────────────────────────────────────

class ReturnPhoto(BaseModel):
    return_request = models.ForeignKey(
        ReturnRequest, on_delete=models.CASCADE, related_name="photos",
    )
    log   = models.ForeignKey(
        ReturnRequestLog, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="photos",
    )
    photo = models.ImageField(upload_to="returns/")

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Photo for {self.return_request_id}"
