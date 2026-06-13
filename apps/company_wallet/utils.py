from decimal import Decimal
from django.db import transaction


def _get_wallet():
    from apps.company_wallet.models import CompanyWallet
    return CompanyWallet.get()


def _record(wallet, tx_type, amount, description, order=None, order_item=None,
            commission_entry=None, triggered_by=None):
    from apps.company_wallet.models import CompanyTransaction

    amount = Decimal(str(amount))
    wallet.balance += amount
    wallet.save()

    CompanyTransaction.objects.create(
        wallet           = wallet,
        transaction_type = tx_type,
        amount           = amount,
        balance_after    = wallet.balance,
        description      = description,
        order            = order,
        order_item       = order_item,
        commission_entry = commission_entry,
        triggered_by     = triggered_by,
    )


@transaction.atomic
def record_order_received(order):
    """
    When an order is confirmed, credit the company wallet with the full
    amount payable (razorpay + wallet used) and record GST per item.
    """
    from apps.company_wallet.models import GSTLedgerEntry

    wallet = _get_wallet()
    prefix = '[OFFLINE] ' if getattr(order, 'is_offline', False) else ''

    amount = Decimal(str(order.amount_payable or 0))
    if amount > 0:
        _record(
            wallet,
            tx_type     = 'order_received',
            amount      = amount,
            description = f'{prefix}Order {order.order_number} received',
            order       = order,
        )

    for item in order.items.all():
        gst = Decimal(str(item.gst_amount or 0))
        if gst > 0:
            GSTLedgerEntry.objects.create(
                gst_type    = 'collected',
                amount      = gst,
                order_item  = item,
                description = f'GST on {item.product_name}',
                reference   = order.order_number,
            )


@transaction.atomic
def record_commission_paid(entry):
    """Debit company wallet when a commission entry is credited to a user."""
    wallet = _get_wallet()

    amount = Decimal(str(entry.amount or 0))
    if amount <= 0:
        return

    order_number = entry.breakup.order_item.order.order_number
    _record(
        wallet,
        tx_type          = 'commission_paid',
        amount           = -amount,
        description      = f'Commission {entry.entry_type} L{entry.level or ""} — Order {order_number}',
        order_item       = entry.breakup.order_item,
        commission_entry = entry,
    )


@transaction.atomic
def record_refund_paid(order_item, refund_amount):
    """Debit company wallet when a refund is paid to a customer."""
    wallet = _get_wallet()

    amount = Decimal(str(refund_amount or 0))
    if amount <= 0:
        return

    order_number = order_item.order.order_number
    _record(
        wallet,
        tx_type     = 'refund_paid',
        amount      = -amount,
        description = f'Refund for {order_item.product_name} — Order {order_number}',
        order_item  = order_item,
        order       = order_item.order,
    )


@transaction.atomic
def record_manual_entry(tx_type, amount, description, triggered_by=None):
    """Admin-initiated manual credit or debit."""
    if tx_type not in ('manual_credit', 'manual_debit'):
        raise ValueError("tx_type must be 'manual_credit' or 'manual_debit'")

    wallet = _get_wallet()
    signed = Decimal(str(amount)) if tx_type == 'manual_credit' else -Decimal(str(amount))
    _record(
        wallet,
        tx_type      = tx_type,
        amount       = signed,
        description  = description,
        triggered_by = triggered_by,
    )
