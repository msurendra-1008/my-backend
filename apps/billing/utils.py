import logging
import random
import string
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def generate_bill_number():
    from apps.billing.models import OfflineBill
    while True:
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        number = f"BILL-{date.today().strftime('%Y%m%d')}-{suffix}"
        if not OfflineBill.objects.filter(bill_number=number).exists():
            return number


def validate_discount_code(code_str, cart_total):
    """Returns (discount_amount, code_obj, error)."""
    from apps.billing.models import DiscountCode
    try:
        code = DiscountCode.objects.get(code__iexact=code_str)
    except DiscountCode.DoesNotExist:
        return 0, None, 'Invalid discount code'

    valid, msg = code.is_valid()
    if not valid:
        return 0, None, msg

    if code.type == 'percent':
        discount = Decimal(str(cart_total)) * code.value / 100
    else:
        discount = min(code.value, Decimal(str(cart_total)))

    return round(discount, 2), code, None


@transaction.atomic
def create_offline_bill(data, billed_by):
    """
    Main function to create an offline POS bill.

    data = {
        customer_type:    'walkin' | 'upa' | 'regular'
        customer_user_id: UUID or None
        walkin_name:      str
        walkin_mobile:    str
        items:            [{ variant_id, quantity }]
        payment_method:   'cash' | 'upi' | 'card'
        cash_received:    Decimal or None
        discount_code:    str or None
    }
    """
    from apps.billing.models import OfflineBill
    from apps.products.models import ProductVariant
    from apps.orders.models import Order, OrderItem
    from apps.orders.models import _gen_order_number

    # ── Resolve customer ──────────────────────────────────────────────────────
    customer_user = None
    if data.get('customer_user_id'):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            customer_user = User.objects.get(id=data['customer_user_id'])
        except User.DoesNotExist:
            pass

    is_upa = (
        data['customer_type'] == 'upa'
        and customer_user
        and customer_user.role == 'upa_user'
    )

    # ── Calculate items ───────────────────────────────────────────────────────
    subtotal    = Decimal('0')
    gst_total   = Decimal('0')
    other_total = Decimal('0')
    order_items = []

    for item_data in data['items']:
        variant = ProductVariant.objects.select_related('product').get(
            id=item_data['variant_id']
        )
        product = variant.product
        qty     = int(item_data['quantity'])

        unit_price = (
            Decimal(str(variant.upa_price))
            if is_upa and variant.upa_price
            else Decimal(str(variant.mrp))
        )

        if product.other_charges_type == 'flat':
            other = Decimal(str(product.other_charges or 0))
        else:
            other = unit_price * Decimal(str(product.other_charges or 0)) / 100

        gst_rate = Decimal(str(product.gst_percentage or 0))
        gst_amt  = unit_price * gst_rate / 100

        subtotal    += unit_price * qty
        gst_total   += gst_amt * qty
        other_total += other * qty

        order_items.append({
            'variant':       variant,
            'product':       product,
            'unit_price':    unit_price,
            'mrp':           Decimal(str(variant.mrp)),
            'upa_price_val': Decimal(str(variant.upa_price)) if variant.upa_price else Decimal(str(variant.mrp)),
            'quantity':      qty,
            'gst_amount':    round(gst_amt * qty, 2),
            'other_charges': round(other * qty, 2),
            'line_total':    round((unit_price + other + gst_amt) * qty, 2),
            'product_name':  product.name,
            'variant_name':  variant.name,
            'sku':           variant.sku,
        })

    # ── Apply discount ────────────────────────────────────────────────────────
    discount_amount   = Decimal('0')
    discount_code_obj = None

    if data.get('discount_code'):
        disc, code_obj, err = validate_discount_code(
            data['discount_code'],
            subtotal + other_total + gst_total,
        )
        if err:
            raise ValueError(err)
        discount_amount   = disc
        discount_code_obj = code_obj

    amount_payable = subtotal + other_total + gst_total - discount_amount

    # ── Create Order ──────────────────────────────────────────────────────────
    order = Order.objects.create(
        order_number   = _gen_order_number(),
        user           = customer_user or billed_by,
        # Address fields blank for offline orders
        address_name   = (customer_user.full_name if customer_user else data.get('walkin_name', '')),
        address_phone  = (getattr(customer_user, 'mobile', '') or data.get('walkin_mobile', '')),
        address_line   = '',
        address_city   = '',
        address_state  = '',
        address_pincode= '',
        subtotal       = subtotal,
        upa_discount   = discount_amount,
        amount_payable = amount_payable,
        payment_status = 'paid',
        order_status   = 'confirmed',
        is_offline     = True,
        order_type     = 'upa' if is_upa else 'regular',
        payment_method = data['payment_method'],
    )

    # ── Create OrderItems ─────────────────────────────────────────────────────
    for item in order_items:
        OrderItem.objects.create(
            order        = order,
            variant      = item['variant'],
            product_name = item['product_name'],
            variant_name = item['variant_name'],
            sku          = item['sku'],
            mrp          = item['mrp'],
            upa_price    = item['upa_price_val'],
            quantity     = item['quantity'],
            line_total   = item['line_total'],
            gst_amount   = item['gst_amount'],
            other_charges= item['other_charges'],
            status       = 'confirmed',
        )

    # ── Deduct stock ──────────────────────────────────────────────────────────
    try:
        from apps.warehouse.utils import deduct_stock
        for item in order_items:
            deduct_stock(
                variant    = item['variant'],
                quantity   = item['quantity'],
                reference  = order.order_number,
                notes      = f'POS bill {order.order_number}',
            )
    except Exception as e:
        logger.error('Stock deduction failed for %s: %s', order.order_number, e)

    # ── Company wallet ────────────────────────────────────────────────────────
    try:
        from apps.company_wallet.utils import record_order_received
        record_order_received(order)
    except Exception as e:
        logger.error('Wallet record_order_received failed for %s: %s', order.order_number, e)

    # ── Commission (UPA only) ─────────────────────────────────────────────────
    if is_upa:
        try:
            from apps.commissions.utils import create_commission_breakup
            from apps.commissions.models import CommissionBreakup
            for oi in order.items.all():
                create_commission_breakup(oi)
            # Offline orders are delivered immediately — set return window now
            from apps.billing.models import BillingSettings
            CommissionBreakup.objects.filter(order_item__order=order).update(
                return_window_expires=timezone.now() + timedelta(days=BillingSettings.get_return_days())
            )
        except Exception as e:
            logger.error('Commission failed for %s: %s', order.order_number, e)

    # ── Create OfflineBill ────────────────────────────────────────────────────
    cash_received = data.get('cash_received')
    change_given  = None
    if cash_received and data['payment_method'] == 'cash':
        change_given = Decimal(str(cash_received)) - amount_payable

    bill = OfflineBill.objects.create(
        bill_number     = generate_bill_number(),
        order           = order,
        customer_type   = data['customer_type'],
        walkin_name     = data.get('walkin_name', ''),
        walkin_mobile   = data.get('walkin_mobile', ''),
        payment_method  = data['payment_method'],
        cash_received   = cash_received,
        change_given    = change_given,
        discount_code   = discount_code_obj,
        discount_amount = discount_amount,
        billed_by       = billed_by,
    )

    if discount_code_obj:
        discount_code_obj.used_count += 1
        discount_code_obj.save(update_fields=['used_count'])

    return bill
