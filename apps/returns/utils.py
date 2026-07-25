from datetime import timedelta
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone


# ── Settings helper ───────────────────────────────────────────────────────────

def get_or_create_return_settings():
    """Return the singleton ReturnSettings, creating with defaults if needed."""
    from .models import ReturnSettings
    return ReturnSettings.get()


# ── Eligibility ───────────────────────────────────────────────────────────────

def is_return_eligible(order_item):
    """
    Returns (eligible: bool, reason: str).
    Uses max_attempts from ReturnSettings.
    """
    from .models import ACTIVE_REQUEST_STATUSES, ReturnRequest

    if order_item.return_window_blocked:
        return False, "Return not available — order was marked as satisfied."

    settings = get_or_create_return_settings()

    if order_item.return_rejection_count >= settings.max_attempts:
        return False, "Maximum return attempts reached for this item."

    if order_item.status not in ("delivered", "exchanged"):
        return False, "Item must be delivered before raising a return or exchange request."

    if not order_item.delivered_at:
        return False, "Delivery date not recorded for this item."

    deadline = order_item.delivered_at + timedelta(days=settings.return_window_days)

    if timezone.now() > deadline:
        return False, (
            f"Return window of {settings.return_window_days} days has expired."
        )

    if ReturnRequest.objects.filter(
        order_item=order_item, status__in=ACTIVE_REQUEST_STATUSES
    ).exists():
        return False, "An active return or exchange request already exists for this item."

    return True, ""


# ── Refund calculation ────────────────────────────────────────────────────────

def calculate_refund_amount(return_request):
    """Return upa_price × return_qty (price locked at checkout time)."""
    return Decimal(return_request.order_item.upa_price) * return_request.return_qty


# ── Log creation helper ───────────────────────────────────────────────────────

def create_log(return_request, action, actor=None, notes=""):
    """Create a ReturnRequestLog entry for an action."""
    from .models import ReturnRequestLog

    actor_role = ""
    if actor:
        actor_role = getattr(actor, "role", "") or ""

    return ReturnRequestLog.objects.create(
        return_request=return_request,
        action=action,
        actor=actor,
        actor_role=actor_role,
        notes=notes,
    )


# ── Process approved return ───────────────────────────────────────────────────

@transaction.atomic
def process_approved_return(return_request, admin_user=None, admin_notes=""):
    """
    Called when admin approves a return request.
    Creates a return pickup assignment and moves status to pickup_dispatched.
    Refund, restock, and commission cancel happen in complete_return_pickup()
    after admin confirms the item has been physically received from the partner.
    """
    from apps.delivery.utils import create_return_pickup_assignment, auto_assign_return_if_enabled

    refund_amount = calculate_refund_amount(return_request)
    return_request.refund_amount = refund_amount
    return_request.status        = "pickup_dispatched"
    return_request.waiting_for   = ""
    return_request.save(update_fields=["refund_amount", "status", "waiting_for"])

    create_return_pickup_assignment(return_request)
    auto_assign_return_if_enabled(return_request, assigned_by=admin_user)


# ── Complete return pickup (called by admin after item received) ───────────────

@transaction.atomic
def complete_return_pickup(assignment, confirmed_by=None):
    """
    Called when admin confirms the returned item has been physically received.

    Side effects (in order):
    1. Credit customer wallet with refund amount
    2. Restock the returned variant
    3. Cancel commission breakup
    4. Update OrderItem: status → 'refunded'
    5. Close ReturnRequest: status → 'completed'
    """
    from apps.wallet.models import Wallet, WalletTransaction

    rr         = assignment.return_request
    order_item = rr.order_item
    qty        = rr.return_qty
    now        = timezone.now()

    refund_amount = rr.refund_amount or calculate_refund_amount(rr)

    # 1. Credit wallet
    wallet, _ = Wallet.objects.get_or_create(user=rr.raised_by)
    wallet.balance += refund_amount
    wallet.save(update_fields=["balance"])

    WalletTransaction.objects.create(
        wallet=wallet,
        type="credit",
        amount=refund_amount,
        reason=f"Refund — {order_item.product_name} × {qty}",
        reference=str(rr.id),
        triggered_by=confirmed_by,
    )

    try:
        from apps.company_wallet.utils import record_refund_paid
        record_refund_paid(order_item, refund_amount)
    except Exception as _cw_err:
        import logging
        logging.getLogger(__name__).error('CompanyWallet record_refund_paid failed: %s', _cw_err)

    # 2. Restock inventory
    variant_id = order_item.variant_id
    if variant_id:
        from apps.products.models import ProductVariant
        restocked = False
        try:
            from apps.warehouse.models import StockMovement
            from apps.warehouse.utils import assign_stock_to_rack
            last_inbound = (
                StockMovement.objects.filter(variant_id=variant_id, movement_type='inbound')
                .order_by('-created_at').first()
            )
            if last_inbound:
                variant_obj = ProductVariant.objects.get(pk=variant_id)
                assign_stock_to_rack(
                    rack=last_inbound.rack, variant=variant_obj, quantity=qty,
                    reference=str(rr.id), notes='Return restock — item confirmed received',
                )
                restocked = True
        except Exception:
            pass
        if not restocked:
            ProductVariant.objects.filter(pk=variant_id).update(
                stock_quantity=models.F("stock_quantity") + qty
            )

    # 3. Cancel commissions
    try:
        from apps.commissions.models import CommissionBreakup
        breakup = order_item.commission_breakup
        if breakup.status in ('pending_window', 'exchange_hold'):
            breakup.entries.filter(
                status__in=('pending_window', 'pending')
            ).update(status='cancelled')
            breakup.status = 'cancelled'
            breakup.save(update_fields=['status'])
    except Exception:
        pass

    # 4. Update OrderItem
    order_item.status = "refunded"
    order_item.save(update_fields=["status"])

    # 5. Close ReturnRequest
    rr.status       = "completed"
    rr.waiting_for  = ""
    rr.completed_at = now
    rr.save(update_fields=["status", "waiting_for", "completed_at"])

    create_log(rr, "completed", actor=confirmed_by,
               notes=f"Item received — refund ₹{refund_amount} credited, stock restocked")


# ── Process approved exchange ─────────────────────────────────────────────────

@transaction.atomic
def process_approved_exchange(return_request, admin_user=None, admin_notes=""):
    """
    Called when admin approves an exchange request.
    - Verifies stock is available for the replacement item
    - Creates an exchange delivery assignment (reuses delivery partner flow)
    - Auto-assigns a partner based on delivery settings
    - Stock deduction, commission change, and order item update happen later
      when the delivery partner confirms delivery with OTP
    """
    from apps.products.models import ProductVariant

    # Exchange is same-variant replacement (send the same item fresh)
    variant_id = (
        return_request.exchange_variant_id
        or return_request.order_item.variant_id
    )
    if not variant_id:
        raise ValueError("Cannot determine the variant for this exchange.")

    # Lock and verify sufficient stock exists for the replacement
    new_v = ProductVariant.objects.select_for_update().get(pk=variant_id)
    if new_v.stock_quantity < return_request.return_qty:
        raise ValueError(
            f"'{new_v.name}' is out of stock "
            f"({new_v.stock_quantity} available, {return_request.return_qty} needed). "
            "You can convert this to a return to refund the customer instead."
        )

    # Ensure exchange_variant is always set to the resolved variant
    if not return_request.exchange_variant_id:
        return_request.exchange_variant_id = variant_id
        return_request.save(update_fields=['exchange_variant'])

    # Always create an exchange delivery assignment (unassigned).
    # Then try to auto-assign a partner if the setting allows.
    from apps.delivery.utils import create_exchange_assignment, auto_assign_exchange_if_enabled
    create_exchange_assignment(return_request)
    auto_assign_exchange_if_enabled(return_request, assigned_by=admin_user)

    # Move request to exchange_dispatched — delivery partner will complete it
    return_request.status     = "exchange_dispatched"
    return_request.waiting_for = ""
    return_request.save(update_fields=["status", "waiting_for"])


# ── Complete exchange delivery (called by delivery partner OTP confirmation) ──

@transaction.atomic
def complete_exchange_delivery(assignment, completed_by=None):
    """
    Called when the delivery partner confirms the exchange with customer OTP.
    One-trip model: partner delivers new item and picks up defective item.

    Side effects (in order):
    1. Restock the defective variant coming back from customer
    2. Deduct the fresh replacement variant from warehouse
    3. Update OrderItem: status → 'exchanged', delivered_at → now
    4. Reset commission window: exchange_hold with return_window_expires = now + window_days
    5. Close ReturnRequest: status → 'completed'
    """
    from apps.products.models import ProductVariant
    from apps.commissions.models import CommissionBreakup

    rr         = assignment.exchange_request
    order_item = rr.order_item
    qty        = rr.return_qty
    now        = timezone.now()

    variant_id = rr.exchange_variant_id or order_item.variant_id
    if not variant_id:
        raise ValueError("Exchange variant not resolved on return request.")

    # 1. Restock the defective item coming back to warehouse
    restocked = False
    try:
        from apps.warehouse.models import StockMovement
        from apps.warehouse.utils import assign_stock_to_rack
        last_in = (
            StockMovement.objects
            .filter(variant_id=variant_id, movement_type='inbound')
            .order_by('-created_at')
            .first()
        )
        if last_in:
            old_v = ProductVariant.objects.get(pk=variant_id)
            assign_stock_to_rack(
                rack=last_in.rack, variant=old_v, quantity=qty,
                reference=str(rr.id), notes='Exchange restock — defective item returned',
            )
            restocked = True
    except Exception:
        pass
    if not restocked:
        ProductVariant.objects.filter(pk=variant_id).update(
            stock_quantity=models.F('stock_quantity') + qty
        )

    # 2. Deduct the fresh replacement variant from warehouse
    try:
        from apps.warehouse.utils import deduct_stock as fifo_deduct
        fresh_v = ProductVariant.objects.select_for_update().get(pk=variant_id)
        fifo_deduct(fresh_v, qty, reference=str(rr.id))
    except Exception:
        ProductVariant.objects.filter(pk=variant_id).update(
            stock_quantity=models.F('stock_quantity') - qty
        )

    # 3. Update OrderItem
    order_item.status       = 'exchanged'
    order_item.delivered_at = now
    order_item.save(update_fields=['status', 'delivered_at'])

    # 4. Reset commission window — exchange_hold starts from new delivery date
    try:
        from .models import ReturnSettings
        from datetime import timedelta
        window_days = ReturnSettings.get().return_window_days
        breakup = order_item.commission_breakup
        if breakup.status in ('pending_window', 'exchange_hold'):
            breakup.status = 'exchange_hold'
            breakup.return_window_expires = now + timedelta(days=window_days)
            breakup.save(update_fields=['status', 'return_window_expires'])
    except CommissionBreakup.DoesNotExist:
        pass
    except Exception:
        pass

    # 5. Close ReturnRequest
    rr.status       = 'completed'
    rr.waiting_for  = ''
    rr.completed_at = now
    rr.save(update_fields=['status', 'waiting_for', 'completed_at'])

    create_log(rr, 'completed', actor=completed_by,
               notes='Exchange completed — new item delivered, defective item collected')
