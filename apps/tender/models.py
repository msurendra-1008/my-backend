import uuid
from django.conf import settings
from django.db import models


class Tender(models.Model):
    STATUS_CHOICES = [
        ('draft',     'Draft'),
        ('open',      'Open'),
        ('closed',    'Closed'),
        ('awarded',   'Awarded'),
        ('cancelled', 'Cancelled'),
    ]
    id                  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tender_number       = models.CharField(max_length=30, unique=True)
    title               = models.CharField(max_length=255)
    description         = models.TextField(blank=True)
    status              = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    bidding_deadline    = models.DateTimeField(null=True, blank=True)
    closed_at           = models.DateTimeField(null=True, blank=True)
    closed_by           = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='closed_tenders'
    )
    awarded_at          = models.DateTimeField(null=True, blank=True)
    awarded_by          = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='awarded_tenders'
    )
    cancellation_reason = models.TextField(blank=True)
    created_by          = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='created_tenders'
    )
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.tender_number} — {self.title}"


class VendorBid(models.Model):
    STATUS_CHOICES = [
        ('bid_submitted',     'Bid Submitted'),
        ('under_negotiation', 'Under Negotiation'),
        ('bid_revised',       'Bid Revised'),
        ('awarded',           'Awarded'),
        ('not_awarded',       'Not Awarded'),
    ]
    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tender            = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name='bids')
    vendor            = models.ForeignKey(
        'vendors.VendorProfile', on_delete=models.CASCADE, related_name='tender_bids'
    )
    status            = models.CharField(max_length=25, choices=STATUS_CHOICES, default='bid_submitted')
    overall_notes     = models.TextField(blank=True)
    negotiation_notes = models.TextField(blank=True)
    submitted_at      = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)
    update_count      = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('tender', 'vendor')

    def __str__(self):
        return f"{self.tender.tender_number} — {self.vendor.company_name}"


class TenderItem(models.Model):
    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tender            = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name='items')
    product           = models.ForeignKey('app_products.Product', on_delete=models.PROTECT)
    required_quantity = models.PositiveIntegerField()
    target_price      = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes             = models.TextField(blank=True)
    awarded_to        = models.ForeignKey(
        'vendors.VendorProfile', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='awarded_tender_items'
    )
    awarded_bid       = models.ForeignKey(
        'tender.VendorBid', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='awarded_items'
    )

    def __str__(self):
        return f"{self.tender.tender_number} — {self.product.name}"


class VendorBidItem(models.Model):
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bid              = models.ForeignKey(VendorBid, on_delete=models.CASCADE, related_name='items')
    tender_item      = models.ForeignKey(TenderItem, on_delete=models.CASCADE, related_name='bid_items')
    supply_quantity  = models.PositiveIntegerField()
    price_per_unit   = models.DecimalField(max_digits=10, decimal_places=2)
    dispatch_date    = models.DateField()
    monthly_breakdown = models.JSONField(default=list)
    notes            = models.TextField(blank=True)

    class Meta:
        unique_together = ('bid', 'tender_item')


class NegotiationLog(models.Model):
    ACTOR_CHOICES = [
        ('admin',  'Admin'),
        ('vendor', 'Vendor'),
    ]
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bid        = models.ForeignKey(
                   VendorBid, on_delete=models.CASCADE,
                   related_name='negotiation_logs')
    actor      = models.ForeignKey(
                   settings.AUTH_USER_MODEL,
                   on_delete=models.SET_NULL, null=True)
    actor_role = models.CharField(max_length=10, choices=ACTOR_CHOICES)
    message    = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.actor_role}: {self.message[:50]}"
