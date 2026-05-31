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

    if order_item.status != "delivered":
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
    from apps.wallet.models import Wallet, WalletTransaction

    refund_amount = calculate_refund_amount(return_request)

    # Credit wallet
    wallet, _ = Wallet.objects.get_or_create(user=return_request.raised_by)
    wallet.balance += refund_amount
    wallet.save(update_fields=["balance"])

    WalletTransaction.objects.create(
        wallet=wallet,
        type="credit",
        amount=refund_amount,
        reason=(
            f"Refund — {return_request.order_item.product_name}"
            f" × {return_request.return_qty}"
        ),
        reference=str(return_request.id),
        triggered_by=return_request.reviewed_by,
    )

    # Restock inventory — return to original rack if known, else direct update
    if return_request.order_item.variant_id:
        from apps.products.models import ProductVariant
        variant_id = return_request.order_item.variant_id
        qty = return_request.return_qty
        restocked = False
        try:
            from apps.warehouse.models import StockMovement
            from apps.warehouse.utils import assign_stock_to_rack
            last_inbound = (
                StockMovement.objects.filter(variant_id=variant_id, movement_type='inbound')
                .order_by('-created_at')
                .first()
            )
            if last_inbound:
                variant_obj = ProductVariant.objects.get(pk=variant_id)
                assign_stock_to_rack(
                    rack=last_inbound.rack,
                    variant=variant_obj,
                    quantity=qty,
                    reference=str(return_request.id),
                    notes='Return restock',
                )
                restocked = True
        except Exception:
            pass
        if not restocked:
            ProductVariant.objects.filter(pk=variant_id).update(
                stock_quantity=models.F("stock_quantity") + qty
            )

    # Finalise request
    return_request.refund_amount = refund_amount
    return_request.status        = "completed"
    return_request.waiting_for   = ""
    return_request.completed_at  = timezone.now()
    return_request.save(update_fields=["refund_amount", "status", "waiting_for", "completed_at"])

    # Update OrderItem
    return_request.order_item.status = "refunded"
    return_request.order_item.save(update_fields=["status"])

    # Log
    create_log(return_request, "completed", actor=admin_user,
               notes=admin_notes or f"Approved — refund ₹{refund_amount}")


# ── Process approved exchange ─────────────────────────────────────────────────

@transaction.atomic
def process_approved_exchange(return_request, admin_user=None, admin_notes=""):
    from apps.products.models import ProductVariant
    from apps.products.utils import get_upa_price
    from apps.wallet.models import Wallet, WalletTransaction

    new_variant = return_request.exchange_variant
    if not new_variant:
        raise ValueError("Exchange variant not specified.")

    # Lock new variant and verify stock
    new_v = ProductVariant.objects.select_for_update().get(pk=new_variant.pk)
    if new_v.stock_quantity < return_request.return_qty:
        raise ValueError("Requested exchange variant is out of stock.")

    # Restock old variant — return to original rack if known
    old_variant_id = return_request.order_item.variant_id
    if old_variant_id:
        qty = return_request.return_qty
        restocked = False
        try:
            from apps.warehouse.models import StockMovement
            from apps.warehouse.utils import assign_stock_to_rack
            last_inbound = (
                StockMovement.objects.filter(variant_id=old_variant_id, movement_type='inbound')
                .order_by('-created_at')
                .first()
            )
            if last_inbound:
                old_v_obj = ProductVariant.objects.get(pk=old_variant_id)
                assign_stock_to_rack(
                    rack=last_inbound.rack,
                    variant=old_v_obj,
                    quantity=qty,
                    reference=str(return_request.id),
                    notes='Exchange restock (old variant)',
                )
                restocked = True
        except Exception:
            pass
        if not restocked:
            ProductVariant.objects.filter(pk=old_variant_id).update(
                stock_quantity=models.F("stock_quantity") + qty
            )

    # Deduct new variant (FIFO from racks)
    try:
        from apps.warehouse.utils import deduct_stock as fifo_deduct
        fifo_deduct(new_v, return_request.return_qty, reference=str(return_request.id))
    except (ValueError, Exception):
        ProductVariant.objects.filter(pk=new_v.pk).update(
            stock_quantity=models.F("stock_quantity") - return_request.return_qty
        )

    # Credit price difference if new variant is cheaper
    old_upa   = Decimal(return_request.order_item.upa_price)
    new_price = get_upa_price(new_v)
    new_upa   = Decimal(new_price["upa_price"])
    price_diff = (old_upa - new_upa) * return_request.return_qty

    refund_amount = None
    if price_diff > Decimal("0"):
        wallet, _ = Wallet.objects.get_or_create(user=return_request.raised_by)
        wallet.balance += price_diff
        wallet.save(update_fields=["balance"])

        WalletTransaction.objects.create(
            wallet=wallet,
            type="credit",
            amount=price_diff,
            reason=(
                f"Exchange credit — {return_request.order_item.product_name}"
            ),
            reference=str(return_request.id),
            triggered_by=return_request.reviewed_by,
        )
        refund_amount = price_diff

    # Update OrderItem
    return_request.order_item.status = "exchanged"
    return_request.order_item.save(update_fields=["status"])

    # Finalise request
    return_request.refund_amount = refund_amount
    return_request.status        = "completed"
    return_request.waiting_for   = ""
    return_request.completed_at  = timezone.now()
    return_request.save(update_fields=["refund_amount", "status", "waiting_for", "completed_at"])

    # Log
    create_log(return_request, "completed", actor=admin_user,
               notes=admin_notes or "Exchange approved")
