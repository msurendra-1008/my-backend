from datetime import timedelta
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone


# ── Eligibility ───────────────────────────────────────────────────────────────

def is_return_eligible(order_item):
    """
    Returns (eligible: bool, reason: str).
    """
    if order_item.status != "delivered":
        return False, "Item must be delivered before raising a return or exchange request."

    if not order_item.delivered_at:
        return False, "Delivery date not recorded for this item."

    from .models import ReturnSettings, ACTIVE_REQUEST_STATUSES
    settings = ReturnSettings.get()
    deadline = order_item.delivered_at + timedelta(days=settings.return_window_days)

    if timezone.now() > deadline:
        return False, (
            f"Return window of {settings.return_window_days} days has expired."
        )

    from .models import ReturnRequest
    if ReturnRequest.objects.filter(
        order_item=order_item, status__in=ACTIVE_REQUEST_STATUSES
    ).exists():
        return False, "An active return or exchange request already exists for this item."

    return True, ""


# ── Refund calculation ────────────────────────────────────────────────────────

def calculate_refund_amount(return_request):
    """Return upa_price × return_qty (price locked at checkout time)."""
    return Decimal(return_request.order_item.upa_price) * return_request.return_qty


# ── Process approved return ───────────────────────────────────────────────────

@transaction.atomic
def process_approved_return(return_request):
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

    # Restock inventory
    if return_request.order_item.variant_id:
        from apps.products.models import ProductVariant
        ProductVariant.objects.filter(
            pk=return_request.order_item.variant_id
        ).update(stock_quantity=models.F("stock_quantity") + return_request.return_qty)

    # Finalise request
    return_request.refund_amount = refund_amount
    return_request.status        = "completed"
    return_request.completed_at  = timezone.now()
    return_request.save(update_fields=["refund_amount", "status", "completed_at"])

    # Update OrderItem
    return_request.order_item.status = "refunded"
    return_request.order_item.save(update_fields=["status"])


# ── Process approved exchange ─────────────────────────────────────────────────

@transaction.atomic
def process_approved_exchange(return_request):
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

    # Restock old variant
    old_variant_id = return_request.order_item.variant_id
    if old_variant_id:
        ProductVariant.objects.filter(pk=old_variant_id).update(
            stock_quantity=models.F("stock_quantity") + return_request.return_qty
        )

    # Deduct new variant
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
    return_request.completed_at  = timezone.now()
    return_request.save(update_fields=["refund_amount", "status", "completed_at"])
