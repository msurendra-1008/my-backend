import uuid

from django.conf import settings
from django.db import models

from apps.procurement.models import PurchaseOrder


SHIPMENT_STATUS_CHOICES = [
    ('awaiting_inspection', 'Awaiting Inspection'),
    ('completed',           'Completed'),
    ('cancelled',           'Cancelled'),
]


class InspectionSettings(models.Model):
    """Singleton settings object for inspection behaviour."""
    auto_stock_update = models.BooleanField(default=False)
    updated_by        = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='inspection_settings_updates',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Inspection Settings'
        verbose_name_plural = 'Inspection Settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={'auto_stock_update': False})
        return obj

    def __str__(self):
        return f'InspectionSettings(auto_stock_update={self.auto_stock_update})'


class IncomingShipment(models.Model):
    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order    = models.OneToOneField(
        PurchaseOrder, on_delete=models.PROTECT, related_name='shipment',
    )
    expected_quantity = models.PositiveIntegerField()
    status            = models.CharField(
        max_length=25, choices=SHIPMENT_STATUS_CHOICES, default='awaiting_inspection',
    )
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Shipment({self.purchase_order.po_number}, {self.status})'


class InspectionReport(models.Model):
    id                      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shipment                = models.OneToOneField(
        IncomingShipment, on_delete=models.PROTECT, related_name='report',
    )
    received_quantity       = models.PositiveIntegerField()
    accepted_quantity       = models.PositiveIntegerField()
    rejected_quantity       = models.PositiveIntegerField()
    missing_quantity        = models.PositiveIntegerField()
    rejection_breakdown     = models.JSONField(default=dict)
    rejection_other_notes   = models.TextField(blank=True)
    general_notes           = models.TextField(blank=True)
    inspected_by            = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='inspection_reports',
    )
    inspected_at            = models.DateTimeField(auto_now_add=True)
    stock_updated           = models.BooleanField(default=False)
    stock_updated_at        = models.DateTimeField(null=True, blank=True)
    stock_updated_by        = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stock_updates',
    )
    debit_note              = models.FileField(upload_to='debit_notes/', null=True, blank=True)
    debit_note_generated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'Report({self.shipment.purchase_order.po_number})'
