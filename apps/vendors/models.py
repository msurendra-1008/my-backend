import uuid
from django.conf import settings
from django.db import models

from apps.products.models import Category, Product


VENDOR_STATUS_CHOICES = [
    ('pending',        'Pending'),
    ('approved',       'Approved'),
    ('rejected',       'Rejected'),
    ('docs_requested', 'Docs Requested'),
]

VENDOR_PRODUCT_STATUS_CHOICES = [
    ('pending_approval', 'Pending Approval'),
    ('approved',         'Approved'),
    ('rejected',         'Rejected'),
    ('not_continued',    'Not Continued'),
]

# Mirrors ProductVariant.VARIANT_TYPES exactly
VARIANT_TYPES = [
    ('size',   'Size'),
    ('colour', 'Colour'),
    ('weight', 'Weight'),
    ('other',  'Other'),
]


class VendorProfile(models.Model):
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user            = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vendor_profile',
    )
    company_name    = models.CharField(max_length=200)
    gst_number      = models.CharField(max_length=20, unique=True)
    contact_name    = models.CharField(max_length=150)
    address_line1   = models.CharField(max_length=255)
    address_line2   = models.CharField(max_length=255, blank=True)
    city            = models.CharField(max_length=100)
    state           = models.CharField(max_length=100)
    pincode         = models.CharField(max_length=10)
    categories      = models.ManyToManyField(Category, blank=True, related_name='vendors')
    status          = models.CharField(max_length=20, choices=VENDOR_STATUS_CHOICES, default='pending')
    rejection_reason = models.TextField(blank=True)
    admin_notes     = models.TextField(blank=True)
    approved_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_vendors',
    )
    approved_at     = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.company_name} ({self.status})"


class VendorDocument(models.Model):
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor      = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='documents')
    label       = models.CharField(max_length=200)
    file        = models.FileField(upload_to='vendor_docs/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.label} — {self.vendor.company_name}"


# ── Vendor Products ───────────────────────────────────────────────────────────

class VendorProduct(models.Model):
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor           = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='products')
    name             = models.CharField(max_length=255)
    description      = models.TextField(blank=True)
    category         = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendor_products')
    sku              = models.CharField(max_length=100)
    barcode          = models.CharField(max_length=100, blank=True)
    monthly_capacity = models.PositiveIntegerField(null=True, blank=True)
    yearly_capacity  = models.PositiveIntegerField(null=True, blank=True)
    status           = models.CharField(max_length=20, choices=VENDOR_PRODUCT_STATUS_CHOICES, default='pending_approval')
    rejection_reason = models.TextField(blank=True)
    admin_notes      = models.TextField(blank=True)
    catalog_product  = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendor_products'
    )
    submitted_at     = models.DateTimeField(auto_now_add=True)
    reviewed_at      = models.DateTimeField(null=True, blank=True)
    reviewed_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviewed_vendor_products'
    )

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.name} ({self.vendor.company_name})"


class VendorProductVariant(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_product = models.ForeignKey(VendorProduct, on_delete=models.CASCADE, related_name='variants')
    name           = models.CharField(max_length=120)
    variant_type   = models.CharField(max_length=10, choices=VARIANT_TYPES, default='other')
    sku            = models.CharField(max_length=100)
    mrp            = models.DecimalField(max_digits=12, decimal_places=2)
    is_active      = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.vendor_product.name} — {self.name}"


class VendorProductImage(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_product = models.ForeignKey(VendorProduct, on_delete=models.CASCADE, related_name='images')
    image          = models.ImageField(upload_to='vendor_products/')
    alt_text       = models.CharField(max_length=255, blank=True)
    order          = models.PositiveIntegerField(default=0)
    is_primary     = models.BooleanField(default=False)
    uploaded_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'uploaded_at']

    def __str__(self):
        return f"Image({self.vendor_product.name}, order={self.order})"
