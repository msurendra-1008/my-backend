import uuid
import random
import string

import pytz
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.orders.models import Order
from apps.returns.models import ReturnRequest

IST = pytz.timezone('Asia/Kolkata')


def _gen_otp():
    return ''.join(random.choices(string.digits, k=6))


class DeliveryZone(models.Model):
    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name      = models.CharField(max_length=100)
    pincodes  = models.TextField(help_text='Comma-separated list of pincodes')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def pincode_list(self):
        return [p.strip() for p in self.pincodes.split(',') if p.strip()]


class DeliveryPartner(models.Model):
    VEHICLE_CHOICES = [
        ('bike',    'Bike'),
        ('scooter', 'Scooter'),
        ('car',     'Car'),
        ('van',     'Van'),
        ('other',   'Other'),
    ]

    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user           = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='delivery_partner_profile',
    )
    vehicle_type   = models.CharField(max_length=20, choices=VEHICLE_CHOICES, default='bike')
    vehicle_number = models.CharField(max_length=20, blank=True)
    zones          = models.ManyToManyField(DeliveryZone, blank=True, related_name='partners')
    is_active        = models.BooleanField(default=True)
    is_on_duty       = models.BooleanField(default=False)
    duty_started_at  = models.DateTimeField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.user.full_name


class DutyLog(models.Model):
    STATUS_CHOICES = [
        ('on_duty',  'On Duty'),
        ('off_duty', 'Off Duty'),
    ]

    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    partner   = models.ForeignKey(
        DeliveryPartner, on_delete=models.CASCADE, related_name='duty_logs'
    )
    status    = models.CharField(max_length=10, choices=STATUS_CHOICES)
    timestamp = models.DateTimeField(default=timezone.now)
    date      = models.DateField()

    class Meta:
        ordering = ['timestamp']
        indexes  = [
            models.Index(fields=['partner', 'date']),
        ]

    def save(self, *args, **kwargs):
        if self.timestamp:
            ts = self.timestamp
            ist_ts = ts.astimezone(IST) if timezone.is_aware(ts) else IST.localize(ts)
            self.date = ist_ts.date()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.partner.user.full_name} — {self.status} at {self.timestamp:%Y-%m-%d %H:%M}'


class DeliverySettings(models.Model):
    ASSIGNMENT_MODE_CHOICES = [
        ('manual',    "Manual — I'll assign every order myself"),
        ('suggested', 'Suggested — System suggests, I confirm'),
        ('automatic', 'Automatic — System assigns instantly'),
    ]

    PROOF_TYPE_CHOICES = [
        ('photo',  'Photo only'),
        ('otp',    'OTP only'),
        ('either', 'Either'),
    ]

    auto_assign              = models.BooleanField(default=True)
    assignment_mode          = models.CharField(max_length=20, choices=ASSIGNMENT_MODE_CHOICES, default='manual')
    default_proof_type       = models.CharField(max_length=10, choices=PROOF_TYPE_CHOICES, default='either')
    max_orders_per_partner   = models.PositiveIntegerField(default=8)
    full_day_hours           = models.DecimalField(
        max_digits=4, decimal_places=1, default=6.0,
        help_text='Minimum hours to count as a full day. Default: 6.0 hours',
    )
    half_day_hours           = models.DecimalField(
        max_digits=4, decimal_places=1, default=3.0,
        help_text='Minimum hours to count as a half day. Default: 3.0 hours',
    )
    count_half_days          = models.BooleanField(
        default=True,
        help_text='If OFF, only Full Day or Absent — no half day status',
    )
    updated_by               = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='delivery_settings_updates',
    )
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                'assignment_mode':        'manual',
                'default_proof_type':     'either',
                'max_orders_per_partner': 8,
                'full_day_hours':         6.0,
                'half_day_hours':         3.0,
                'count_half_days':        True,
            },
        )
        return obj

    class Meta:
        verbose_name = 'Delivery Settings'
        verbose_name_plural = 'Delivery Settings'

    def __str__(self):
        return 'Delivery Settings'


class DeliveryAssignment(models.Model):
    STATUS_CHOICES = [
        ('assigned',  'Assigned'),
        ('picked_up', 'Picked Up'),
        ('delivered', 'Delivered'),
        ('failed',    'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    ASSIGNMENT_TYPE_CHOICES = [
        ('order',    'Order Delivery'),
        ('exchange', 'Exchange Delivery'),
        ('return',   'Return Pickup'),
    ]

    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assignment_type  = models.CharField(
        max_length=20, choices=ASSIGNMENT_TYPE_CHOICES, default='order'
    )
    order            = models.OneToOneField(
        Order, on_delete=models.CASCADE, related_name='delivery_assignment',
        null=True, blank=True,
    )
    exchange_request = models.OneToOneField(
        ReturnRequest, on_delete=models.CASCADE, related_name='exchange_delivery',
        null=True, blank=True,
    )
    return_request = models.OneToOneField(
        ReturnRequest, on_delete=models.CASCADE, related_name='return_pickup',
        null=True, blank=True,
    )
    partner        = models.ForeignKey(
        DeliveryPartner, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assignments',
    )
    otp            = models.CharField(max_length=6, default=_gen_otp)
    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default='assigned')
    assigned_at    = models.DateTimeField(auto_now_add=True)
    picked_up_at   = models.DateTimeField(null=True, blank=True)
    delivered_at   = models.DateTimeField(null=True, blank=True)
    proof_image    = models.ImageField(upload_to='delivery_proofs/', null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    notes          = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        if self.assignment_type == 'exchange' and self.exchange_request:
            return f'Exchange delivery for {self.exchange_request.order_item.product_name}'
        if self.assignment_type == 'return' and self.return_request:
            return f'Return pickup for {self.return_request.order_item.product_name}'
        return f'Delivery for {self.order.order_number if self.order else "—"}'


class DeliveryStatusLog(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assignment = models.ForeignKey(
        DeliveryAssignment, on_delete=models.CASCADE, related_name='logs'
    )
    status     = models.CharField(max_length=20)
    notes      = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='delivery_status_logs',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.assignment} → {self.status}'
