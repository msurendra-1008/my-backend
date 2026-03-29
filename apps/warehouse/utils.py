"""
Warehouse utility functions.

Rules:
- NEVER update ProductVariant.stock_quantity directly — always call sync_variant_stock(variant).
- EVERY stock change must create a StockMovement record.
- deduct_stock() uses FIFO: order_by('last_updated') with select_for_update().
"""
from django.db import transaction
from django.db.models import Sum


def sync_variant_stock(variant):
    """Recompute variant.stock_quantity from sum of all RackStock entries."""
    from .models import RackStock
    total = RackStock.objects.filter(variant=variant).aggregate(total=Sum('quantity'))['total'] or 0
    variant.stock_quantity = total
    variant.save(update_fields=['stock_quantity'])


def find_suggested_rack(variant, warehouse=None):
    """
    Return the rack that already holds this variant (most stock first).
    If none found, return the first active rack with remaining capacity in the warehouse.
    Returns None if no suitable rack exists.
    """
    from .models import Rack, RackStock

    qs = RackStock.objects.filter(variant=variant, quantity__gt=0).select_related('rack__zone__warehouse')
    if warehouse:
        qs = qs.filter(rack__zone__warehouse=warehouse)
    existing = qs.order_by('-quantity').first()
    if existing:
        return existing.rack

    rack_qs = Rack.objects.filter(is_active=True).select_related('zone__warehouse')
    if warehouse:
        rack_qs = rack_qs.filter(zone__warehouse=warehouse)
    for rack in rack_qs:
        if rack.capacity == 0 or rack.current_stock < rack.capacity:
            return rack
    return None


@transaction.atomic
def assign_stock_to_rack(rack, variant, quantity, performed_by=None, reference='', notes=''):
    """
    Add quantity to rack for variant.
    Creates/updates RackStock and a StockMovement(inbound).
    Syncs variant.stock_quantity.
    Raises ValueError if adding would exceed rack.capacity.
    Returns (rack_stock, capacity_warning).
    """
    from .models import RackStock, StockMovement

    # Hard-block: check capacity before writing
    if rack.capacity > 0:
        current_total = (
            RackStock.objects.filter(rack=rack)
            .aggregate(total=Sum('quantity'))['total'] or 0
        )
        new_total = current_total + quantity
        if new_total > rack.capacity:
            available = rack.capacity - current_total
            raise ValueError(
                f'This rack has a capacity of {rack.capacity} units. '
                f'Currently has {current_total} units. '
                f'Cannot add {quantity} more units. '
                f'Available space: {available} units'
            )

    rack_stock, _ = RackStock.objects.select_for_update().get_or_create(
        rack=rack, variant=variant, defaults={'quantity': 0},
    )
    rack_stock.quantity += quantity
    rack_stock.save(update_fields=['quantity', 'last_updated'])

    StockMovement.objects.create(
        rack=rack,
        variant=variant,
        movement_type='inbound',
        quantity=quantity,
        reference=reference,
        notes=notes,
        performed_by=performed_by,
    )

    sync_variant_stock(variant)

    # Always False now — we block at entry instead of warning after the fact
    return rack_stock, False


@transaction.atomic
def deduct_stock(variant, quantity, performed_by=None, reference='', notes=''):
    """
    Deduct quantity from RackStock using FIFO (oldest last_updated first).
    Raises ValueError if insufficient stock.
    Syncs variant.stock_quantity after deduction.
    """
    from .models import RackStock, StockMovement

    rack_stocks = list(
        RackStock.objects.filter(variant=variant, quantity__gt=0)
        .order_by('last_updated')
        .select_for_update()
    )

    total_available = sum(rs.quantity for rs in rack_stocks)
    if total_available < quantity:
        raise ValueError(
            f'Insufficient stock for {variant}: need {quantity}, have {total_available}.'
        )

    remaining = quantity
    for rs in rack_stocks:
        if remaining <= 0:
            break
        deducted = min(rs.quantity, remaining)
        rs.quantity -= deducted
        rs.save(update_fields=['quantity', 'last_updated'])

        StockMovement.objects.create(
            rack=rs.rack,
            variant=variant,
            movement_type='outbound',
            quantity=deducted,
            reference=reference,
            notes=notes,
            performed_by=performed_by,
        )
        remaining -= deducted

    sync_variant_stock(variant)


@transaction.atomic
def transfer_stock(from_rack, to_rack, variant, quantity, performed_by=None, notes=''):
    """
    Transfer quantity from from_rack to to_rack for variant.
    Creates TWO StockMovement records (transfer_out + transfer_in).
    Raises ValueError if insufficient stock in from_rack OR destination
    rack capacity would be exceeded.
    Returns (transfer, capacity_warning).
    """
    from .models import RackStock, StockMovement, StockTransfer
    from django.utils import timezone

    # Lock source
    source = RackStock.objects.select_for_update().filter(rack=from_rack, variant=variant).first()
    if not source or source.quantity < quantity:
        available = source.quantity if source else 0
        raise ValueError(
            f'Insufficient stock in {from_rack}: need {quantity}, have {available}.'
        )

    # Check destination rack capacity
    if to_rack.capacity > 0:
        dest_total = (
            RackStock.objects.filter(rack=to_rack)
            .aggregate(total=Sum('quantity'))['total'] or 0
        )
        if dest_total + quantity > to_rack.capacity:
            available_space = to_rack.capacity - dest_total
            raise ValueError(
                f'This rack has a capacity of {to_rack.capacity} units. '
                f'Currently has {dest_total} units. '
                f'Cannot add {quantity} more units. '
                f'Available space: {available_space} units'
            )

    source.quantity -= quantity
    source.save(update_fields=['quantity', 'last_updated'])

    # Add to destination
    dest, _ = RackStock.objects.select_for_update().get_or_create(
        rack=to_rack, variant=variant, defaults={'quantity': 0},
    )
    dest.quantity += quantity
    dest.save(update_fields=['quantity', 'last_updated'])

    ref = f'Transfer {from_rack} → {to_rack}'

    StockMovement.objects.create(
        rack=from_rack, variant=variant, movement_type='transfer_out',
        quantity=quantity, reference=ref, notes=notes, performed_by=performed_by,
    )
    StockMovement.objects.create(
        rack=to_rack, variant=variant, movement_type='transfer_in',
        quantity=quantity, reference=ref, notes=notes, performed_by=performed_by,
    )

    transfer = StockTransfer.objects.create(
        from_rack=from_rack,
        to_rack=to_rack,
        variant=variant,
        quantity=quantity,
        status='completed',
        notes=notes,
        initiated_by=performed_by,
        completed_at=timezone.now(),
    )

    # variant stock_quantity stays the same (just moved between racks) but sync anyway
    sync_variant_stock(variant)

    # Always False — blocked at entry instead of warning after the fact
    return transfer, False
