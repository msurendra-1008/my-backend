import uuid
from django.conf import settings
from django.db import models

from apps.products.models import Product
from apps.vendors.models import VendorProduct, VendorProfile


REQUIREMENT_STATUS_CHOICES = [
    ('draft',             'Draft'),
    ('sent',              'Sent'),
    ('vendor_responded',  'Vendor Responded'),
    ('negotiating',       'Negotiating'),
    ('po_generated',      'PO Generated'),
    ('cancelled',         'Cancelled'),
]

PO_STATUS_CHOICES = [
    ('generated',          'Generated'),
    ('acknowledged',       'Acknowledged'),
    ('dispatched',         'Dispatched'),
    ('inspection_pending', 'Inspection Pending'),
    ('completed',          'Completed'),
    ('cancelled',          'Cancelled'),
]


class ProcurementRequirement(models.Model):
    id                  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_product      = models.ForeignKey(
        VendorProduct, on_delete=models.PROTECT, related_name='procurement_requirements',
    )
    vendor              = models.ForeignKey(
        VendorProfile, on_delete=models.PROTECT, related_name='procurement_requirements',
    )
    product             = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='procurement_requirements',
        null=True, blank=True,
    )
    required_quantity   = models.PositiveIntegerField()
    required_by_date    = models.DateField()
    target_price        = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes               = models.TextField(blank=True)
    status              = models.CharField(
        max_length=20, choices=REQUIREMENT_STATUS_CHOICES, default='draft',
    )
    negotiation_notes   = models.TextField(blank=True)
    created_by          = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_requirements',
    )
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)
    sent_at             = models.DateTimeField(null=True, blank=True)
    confirmed_at        = models.DateTimeField(null=True, blank=True)
    confirmed_by        = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='confirmed_requirements',
    )
    cancelled_at        = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Req({self.vendor_product.name}, {self.status})"


class VendorResponse(models.Model):
    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requirement       = models.OneToOneField(
        ProcurementRequirement, on_delete=models.CASCADE, related_name='vendor_response',
    )
    supply_quantity   = models.PositiveIntegerField()
    price_per_unit    = models.DecimalField(max_digits=12, decimal_places=2)
    dispatch_date     = models.DateField()
    monthly_breakdown = models.JSONField(default=list)
    notes             = models.TextField(blank=True)
    submitted_at      = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)
    update_count      = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Response({self.requirement_id})"


class PurchaseOrder(models.Model):
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    po_number        = models.CharField(max_length=30, unique=True)
    requirement      = models.OneToOneField(
        ProcurementRequirement, on_delete=models.PROTECT, related_name='purchase_order',
    )
    vendor           = models.ForeignKey(
        VendorProfile, on_delete=models.PROTECT, related_name='purchase_orders',
    )
    product          = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='purchase_orders',
    )
    quantity         = models.PositiveIntegerField()
    price_per_unit   = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount     = models.DecimalField(max_digits=14, decimal_places=2)
    monthly_breakdown = models.JSONField(default=list)
    dispatch_date    = models.DateField()
    status           = models.CharField(max_length=20, choices=PO_STATUS_CHOICES, default='generated')
    vendor_notes     = models.TextField(blank=True)
    admin_notes      = models.TextField(blank=True)
    generated_at     = models.DateTimeField(auto_now_add=True)
    acknowledged_at  = models.DateTimeField(null=True, blank=True)
    dispatched_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-generated_at']

    def __str__(self):
        return self.po_number
