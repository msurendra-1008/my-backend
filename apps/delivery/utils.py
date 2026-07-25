from django.db.models import Count, Q
from django.utils import timezone


def find_eligible_partners(order):
    """Return active DeliveryPartner objects that serve the order's pincode."""
    from .models import DeliverySettings, DeliveryPartner

    pincode  = (order.address_pincode or '').strip()
    partners = DeliveryPartner.objects.filter(is_active=True, user__is_active=True)

    settings = DeliverySettings.get()
    if settings.assignment_mode == 'zone_match' and pincode:
        eligible = []
        for partner in partners.prefetch_related('zones'):
            for zone in partner.zones.filter(is_active=True):
                if pincode in zone.pincode_list():
                    eligible.append(partner)
                    break
        return eligible

    return list(partners)


def suggest_partner_for_order(order):
    """Return the least-loaded eligible partner, or None."""
    from .models import DeliveryPartner

    eligible = find_eligible_partners(order)
    if not eligible:
        return None

    eligible_ids = [p.id for p in eligible]
    partner = (
        DeliveryPartner.objects
        .filter(id__in=eligible_ids)
        .annotate(active_count=Count('assignments', filter=Q(assignments__status='assigned')))
        .order_by('active_count')
        .first()
    )
    return partner


def assign_order_to_partner(order, partner, assigned_by=None):
    """Create or update a DeliveryAssignment for the given order."""
    from .models import DeliveryAssignment, DeliveryStatusLog

    assignment, created = DeliveryAssignment.objects.get_or_create(
        order=order,
        defaults={'partner': partner},
    )
    if not created:
        assignment.partner = partner
        assignment.status  = 'assigned'
        assignment.save(update_fields=['partner', 'status', 'updated_at'])

    DeliveryStatusLog.objects.create(
        assignment=assignment,
        status='assigned',
        notes=f'Assigned to {partner.user.full_name}',
        created_by=assigned_by,
    )

    from apps.orders.models import Order as OrderModel
    OrderModel.objects.filter(pk=order.pk).update(
        tracking_number=str(assignment.id)[:20]
    )

    return assignment


def auto_assign_if_enabled(order, assigned_by=None):
    """Auto-assign a delivery partner if auto_assign is on. Never raises."""
    try:
        from .models import DeliverySettings
        cfg = DeliverySettings.get()
        if not cfg.auto_assign:
            return None
        partner = suggest_partner_for_order(order)
        if not partner:
            return None
        return assign_order_to_partner(order, partner, assigned_by=assigned_by)
    except Exception:
        return None


def create_exchange_assignment(return_request):
    """Ensure an unassigned DeliveryAssignment exists for an exchange request."""
    from .models import DeliveryAssignment
    assignment, _ = DeliveryAssignment.objects.get_or_create(
        exchange_request=return_request,
        defaults={
            'assignment_type': 'exchange',
            'status':          'assigned',
        },
    )
    return assignment


def assign_exchange_to_partner(return_request, partner, assigned_by=None):
    """Create or update a DeliveryAssignment for an exchange request."""
    from .models import DeliveryAssignment, DeliveryStatusLog

    assignment, created = DeliveryAssignment.objects.get_or_create(
        exchange_request=return_request,
        defaults={
            'assignment_type': 'exchange',
            'partner':         partner,
            'status':          'assigned',
        },
    )
    if not created:
        assignment.partner = partner
        assignment.status  = 'assigned'
        assignment.save(update_fields=['partner', 'status', 'updated_at'])

    DeliveryStatusLog.objects.create(
        assignment=assignment,
        status='assigned',
        notes=f'Exchange delivery assigned to {partner.user.full_name}',
        created_by=assigned_by,
    )
    return assignment


def auto_assign_exchange_if_enabled(return_request, assigned_by=None):
    """Auto-assign an exchange delivery if auto_assign is enabled. Never raises."""
    try:
        from .models import DeliverySettings
        cfg = DeliverySettings.get()
        if not cfg.auto_assign:
            return None
        # Use the original order's address for zone matching
        order = return_request.order_item.order
        partner = suggest_partner_for_order(order)
        if not partner:
            return None
        return assign_exchange_to_partner(return_request, partner, assigned_by=assigned_by)
    except Exception:
        return None


def create_return_pickup_assignment(return_request):
    """Ensure an unassigned DeliveryAssignment exists for a return pickup."""
    from .models import DeliveryAssignment
    assignment, _ = DeliveryAssignment.objects.get_or_create(
        return_request=return_request,
        defaults={
            'assignment_type': 'return',
            'status':          'assigned',
        },
    )
    return assignment


def assign_return_to_partner(return_request, partner, assigned_by=None):
    """Create or update a DeliveryAssignment for a return pickup."""
    from .models import DeliveryAssignment, DeliveryStatusLog

    assignment, created = DeliveryAssignment.objects.get_or_create(
        return_request=return_request,
        defaults={
            'assignment_type': 'return',
            'partner':         partner,
            'status':          'assigned',
        },
    )
    if not created:
        assignment.partner = partner
        assignment.status  = 'assigned'
        assignment.save(update_fields=['partner', 'status', 'updated_at'])

    DeliveryStatusLog.objects.create(
        assignment=assignment,
        status='assigned',
        notes=f'Return pickup assigned to {partner.user.full_name}',
        created_by=assigned_by,
    )
    return assignment


def auto_assign_return_if_enabled(return_request, assigned_by=None):
    """Auto-assign a return pickup if auto_assign is enabled. Never raises."""
    try:
        from .models import DeliverySettings
        cfg = DeliverySettings.get()
        if not cfg.auto_assign:
            return None
        order = return_request.order_item.order
        partner = suggest_partner_for_order(order)
        if not partner:
            return None
        return assign_return_to_partner(return_request, partner, assigned_by=assigned_by)
    except Exception:
        return None


def update_delivery_status(assignment, new_status, updated_by=None,
                            notes='', proof_image=None, failure_reason='',
                            skip_order_sync=False):
    """Update assignment status, log it, and sync the parent order status."""
    from .models import DeliveryStatusLog
    from apps.orders.models import Order as OrderModel

    assignment.status = new_status
    update_fields = ['status', 'updated_at']

    if new_status == 'picked_up' and not assignment.picked_up_at:
        assignment.picked_up_at = timezone.now()
        update_fields.append('picked_up_at')
    elif new_status == 'delivered':
        if not assignment.delivered_at:
            assignment.delivered_at = timezone.now()
            update_fields.append('delivered_at')
        if proof_image:
            assignment.proof_image = proof_image
            update_fields.append('proof_image')
    elif new_status == 'failed':
        assignment.failure_reason = failure_reason
        update_fields.append('failure_reason')

    assignment.save(update_fields=update_fields)

    DeliveryStatusLog.objects.create(
        assignment=assignment,
        status=new_status,
        notes=notes,
        created_by=updated_by,
    )

    if skip_order_sync:
        return assignment

    from apps.orders.models import OrderItem, RETURN_EXCHANGE_STATUSES

    if new_status == 'picked_up':
        OrderModel.objects.filter(pk=assignment.order_id).update(order_status='shipped')
        OrderItem.objects.filter(
            order_id=assignment.order_id,
        ).exclude(status__in=RETURN_EXCHANGE_STATUSES).update(status='shipped')

    elif new_status == 'delivered':
        now = timezone.now()
        OrderModel.objects.filter(pk=assignment.order_id).update(order_status='delivered')
        items_qs = OrderItem.objects.filter(
            order_id=assignment.order_id,
        ).exclude(status__in=RETURN_EXCHANGE_STATUSES)
        items_qs.filter(delivered_at__isnull=True).update(status='delivered', delivered_at=now)
        items_qs.filter(delivered_at__isnull=False).update(status='delivered')

        # Open commission return window — mirrors AdminOrderViewSet.partial_update
        try:
            from apps.commissions.models import CommissionBreakup
            from apps.commissions.utils import process_commission_breakup
            from apps.returns.models import ReturnSettings
            from datetime import timedelta
            order_obj = OrderModel.objects.get(pk=assignment.order_id)
            window_days = ReturnSettings.get().return_window_days
            for item in order_obj.items.exclude(status__in=RETURN_EXCHANGE_STATUSES):
                try:
                    breakup = item.commission_breakup
                    if breakup.return_window_expires is None:
                        delivered_time = item.delivered_at or now
                        breakup.return_window_expires = delivered_time + timedelta(days=window_days)
                        breakup.save()
                except CommissionBreakup.DoesNotExist:
                    pass

            # If the customer already marked this order satisfied, credit
            # commissions now that delivery is confirmed.
            if order_obj.is_satisfied:
                for item in order_obj.items.exclude(status__in=RETURN_EXCHANGE_STATUSES):
                    try:
                        breakup = item.commission_breakup
                        if breakup.status == 'pending_window':
                            process_commission_breakup(breakup)
                    except Exception:
                        pass
        except Exception:
            pass

    elif new_status == 'failed':
        # Reset to packed so admin can reassign
        OrderModel.objects.filter(pk=assignment.order_id).update(order_status='packed')
        OrderItem.objects.filter(
            order_id=assignment.order_id,
        ).exclude(status__in=RETURN_EXCHANGE_STATUSES).update(status='packed')

    return assignment
