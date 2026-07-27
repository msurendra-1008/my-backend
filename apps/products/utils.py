from decimal import Decimal, ROUND_HALF_UP
from typing import TypedDict

from .models import Product, ProductVariant, UPADiscountSettings


class UPAPrice(TypedDict):
    mrp:              str
    upa_price:        str
    discount_percent: str
    saving:           str


def get_upa_price(obj: Product | ProductVariant) -> UPAPrice:
    """
    Compute UPA price for a Product or ProductVariant.

    Priority:
      1. upa_price_override set  → return exactly that price
      2. upa_discount_override % → apply that % to mrp
      3. Fallback                → apply global UPADiscountSettings.global_discount_percent
    """
    mrp: Decimal = obj.mrp

    # No MRP means UPA pricing cannot be computed
    if mrp is None:
        return None

    # 1. Exact price override
    if obj.upa_price_override is not None:
        upa = obj.upa_price_override
        saving = (mrp - upa).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        pct = (saving / mrp * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if mrp else Decimal('0')
        return {
            'mrp':              str(mrp),
            'upa_price':        str(upa),
            'discount_percent': str(pct),
            'saving':           str(saving),
        }

    # 2. Per-object discount % override (Product has upa_discount_override directly;
    #    ProductVariant does not, so we fall through to the parent product next)
    discount_pct: Decimal | None = getattr(obj, 'upa_discount_override', None)

    # 2b. For variants, inherit the parent product's discount override before global
    if discount_pct is None:
        parent = getattr(obj, 'product', None)
        if parent is not None:
            # If the product has an exact price override, apply it to this variant's MRP
            if parent.upa_price_override is not None:
                upa    = parent.upa_price_override
                saving = (mrp - upa).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                pct    = (saving / mrp * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if mrp else Decimal('0')
                return {
                    'mrp':              str(mrp),
                    'upa_price':        str(upa),
                    'discount_percent': str(pct),
                    'saving':           str(saving),
                }
            discount_pct = getattr(parent, 'upa_discount_override', None)

    # 3. Global fallback
    if discount_pct is None:
        settings = UPADiscountSettings.get()
        discount_pct = settings.global_discount_percent

    discount_pct = discount_pct or Decimal('0')
    saving = (mrp * discount_pct / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    upa    = (mrp - saving).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return {
        'mrp':              str(mrp),
        'upa_price':        str(upa),
        'discount_percent': str(discount_pct),
        'saving':           str(saving),
    }
