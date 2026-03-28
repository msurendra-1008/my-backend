import uuid

from django.conf import settings
from django.db import models

from core.models import BaseModel


# ── Warehouse ──────────────────────────────────────────────────────────────────

class Warehouse(BaseModel):
    name     = models.CharField(max_length=200)
    location = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


# ── Zone ───────────────────────────────────────────────────────────────────────

class Zone(BaseModel):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='zones')
    name      = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['warehouse', 'name']
        unique_together = [('warehouse', 'name')]

    def __str__(self):
        return f'{self.warehouse.name} / {self.name}'


# ── Rack ───────────────────────────────────────────────────────────────────────

class Rack(BaseModel):
    zone     = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='racks')
    code     = models.CharField(max_length=50)
    capacity = models.PositiveIntegerField(default=0, help_text='Max units; 0 = unlimited')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['zone', 'code']
        unique_together = [('zone', 'code')]

    def __str__(self):
        return f'{self.zone} / {self.code}'

    @property
    def current_stock(self):
        return self.stock_entries.aggregate(total=models.Sum('quantity'))['total'] or 0

    @property
    def is_over_capacity(self):
        if self.capacity == 0:
            return False
        return self.current_stock > self.capacity


# ── RackStock ──────────────────────────────────────────────────────────────────

class RackStock(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rack         = models.ForeignKey(Rack, on_delete=models.CASCADE, related_name='stock_entries')
    variant      = models.ForeignKey(
        'app_products.ProductVariant', on_delete=models.CASCADE, related_name='rack_stocks',
    )
    quantity     = models.PositiveIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('rack', 'variant')]
        ordering = ['last_updated']

    def __str__(self):
        return f'{self.rack} — {self.variant} × {self.quantity}'


# ── StockMovement ──────────────────────────────────────────────────────────────

MOVEMENT_TYPE_CHOICES = [
    ('inbound',      'Inbound'),
    ('outbound',     'Outbound'),
    ('transfer_in',  'Transfer In'),
    ('transfer_out', 'Transfer Out'),
    ('adjustment',   'Adjustment'),
    ('return_in',    'Return In'),
]


class StockMovement(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rack          = models.ForeignKey(Rack, on_delete=models.PROTECT, related_name='movements')
    variant       = models.ForeignKey(
        'app_products.ProductVariant', on_delete=models.PROTECT, related_name='movements',
    )
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPE_CHOICES)
    quantity      = models.PositiveIntegerField()
    reference     = models.CharField(max_length=200, blank=True, help_text='PO number, order ID, etc.')
    notes         = models.TextField(blank=True)
    performed_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stock_movements',
    )
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.movement_type} {self.quantity} × {self.variant} @ {self.rack}'


# ── StockTransfer ──────────────────────────────────────────────────────────────

TRANSFER_STATUS_CHOICES = [
    ('pending',   'Pending'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled'),
]


class StockTransfer(BaseModel):
    from_rack    = models.ForeignKey(Rack, on_delete=models.PROTECT, related_name='transfers_out')
    to_rack      = models.ForeignKey(Rack, on_delete=models.PROTECT, related_name='transfers_in')
    variant      = models.ForeignKey(
        'app_products.ProductVariant', on_delete=models.PROTECT, related_name='transfers',
    )
    quantity     = models.PositiveIntegerField()
    status       = models.CharField(max_length=20, choices=TRANSFER_STATUS_CHOICES, default='pending')
    notes        = models.TextField(blank=True)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='initiated_transfers',
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Transfer {self.quantity} × {self.variant} from {self.from_rack} → {self.to_rack}'
