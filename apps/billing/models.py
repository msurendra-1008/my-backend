import uuid
from django.conf import settings
from django.db import models


class DiscountCode(models.Model):
    TYPE_CHOICES = [
        ('percent', 'Percentage'),
        ('flat',    'Flat amount'),
    ]

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code       = models.CharField(max_length=50, unique=True)
    type       = models.CharField(max_length=10, choices=TYPE_CHOICES, default='percent')
    value      = models.DecimalField(max_digits=10, decimal_places=2, help_text='% or flat amount')
    max_uses   = models.PositiveIntegerField(default=0, help_text='0 = unlimited')
    used_count = models.PositiveIntegerField(default=0)
    valid_from = models.DateField(null=True, blank=True)
    valid_till = models.DateField(null=True, blank=True)
    is_active  = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.code} ({self.type} {self.value})'

    def is_valid(self):
        from django.utils import timezone
        today = timezone.now().date()
        if not self.is_active:
            return False, 'Code is inactive'
        if self.max_uses > 0 and self.used_count >= self.max_uses:
            return False, 'Code usage limit reached'
        if self.valid_from and today < self.valid_from:
            return False, 'Code not yet valid'
        if self.valid_till and today > self.valid_till:
            return False, 'Code has expired'
        return True, 'Valid'


class OfflineBill(models.Model):
    PAYMENT_CHOICES = [
        ('cash', 'Cash'),
        ('upi',  'UPI'),
        ('card', 'Card'),
    ]
    CUSTOMER_TYPE_CHOICES = [
        ('walkin',  'Walk-in'),
        ('upa',     'UPA Member'),
        ('regular', 'Regular User'),
    ]

    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bill_number    = models.CharField(max_length=30, unique=True)
    order          = models.OneToOneField(
        'orders.Order',
        on_delete=models.PROTECT,
        related_name='offline_bill',
    )
    customer_type  = models.CharField(max_length=10, choices=CUSTOMER_TYPE_CHOICES)
    walkin_name    = models.CharField(max_length=255, blank=True)
    walkin_mobile  = models.CharField(max_length=20, blank=True)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_CHOICES)
    cash_received  = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    change_given   = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    discount_code  = models.ForeignKey(
        DiscountCode, null=True, blank=True, on_delete=models.SET_NULL,
    )
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    billed_by       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='bills_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.bill_number


class OfflineReturn(models.Model):
    STATUS_CHOICES = [
        ('pending',  'Pending Admin Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bill         = models.ForeignKey(OfflineBill, on_delete=models.PROTECT, related_name='returns')
    status       = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    items        = models.JSONField(default=list, help_text='[{order_item_id, qty}]')
    total_refund = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    bill_photo   = models.ImageField(upload_to='offline_returns/', null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='offline_returns',
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_offline_returns',
    )
    review_notes = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Return for {self.bill.bill_number}'


class BillingSettings(models.Model):
    """Singleton — one record only."""

    return_window_enabled = models.BooleanField(
        default=False,
        help_text='If OFF uses default 2 days',
    )
    return_window_days = models.PositiveIntegerField(
        default=2,
        help_text='Custom return window in days',
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        verbose_name = 'Billing Settings'

    def save(self, *args, **kwargs):
        self.__class__.objects.exclude(pk=self.pk).delete()
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(defaults={
            'return_window_enabled': False,
            'return_window_days':    2,
        })
        return obj

    @classmethod
    def get_return_days(cls):
        s = cls.get()
        return s.return_window_days if s.return_window_enabled else 2

    def __str__(self):
        if self.return_window_enabled:
            return f'Return window: {self.return_window_days} days'
        return 'Return window: 2 days (default)'
