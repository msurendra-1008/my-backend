import uuid
from django.conf import settings
from django.db import models

from apps.products.models import Category


VENDOR_STATUS_CHOICES = [
    ('pending',       'Pending'),
    ('approved',      'Approved'),
    ('rejected',      'Rejected'),
    ('docs_requested', 'Docs Requested'),
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
