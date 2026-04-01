import random
import string
from datetime import date
from django.utils import timezone
from django.db import transaction


def generate_tender_number():
    from apps.tender.models import Tender
    while True:
        suffix = ''.join(random.choices(
            string.ascii_uppercase + string.digits, k=4))
        number = f"TND-{date.today().strftime('%Y%m%d')}-{suffix}"
        if not Tender.objects.filter(tender_number=number).exists():
            return number


def check_and_close_expired_tenders():
    from apps.tender.models import Tender
    Tender.objects.filter(
        status='open',
        bidding_deadline__lt=timezone.now()
    ).update(status='closed', closed_at=timezone.now())


@transaction.atomic
def award_tender_item(tender_item, vendor_bid, admin_user):
    from apps.procurement.models import PurchaseOrder
    from apps.procurement.utils import generate_po_number

    bid_item = vendor_bid.items.filter(
        tender_item=tender_item).first()
    if not bid_item:
        raise ValueError("No bid item found for this tender item")

    po = PurchaseOrder.objects.create(
        po_number      = generate_po_number(),
        requirement    = None,
        vendor         = vendor_bid.vendor,
        product        = tender_item.product,
        quantity       = bid_item.supply_quantity,
        price_per_unit = bid_item.price_per_unit,
        total_amount   = bid_item.supply_quantity * bid_item.price_per_unit,
        monthly_breakdown = bid_item.monthly_breakdown,
        dispatch_date  = bid_item.dispatch_date,
        status         = 'generated',
        admin_notes    = f'Awarded via tender {tender_item.tender.tender_number}'
    )

    tender_item.awarded_to  = vendor_bid.vendor
    tender_item.awarded_bid = vendor_bid
    tender_item.save()

    vendor_bid.status = 'awarded'
    vendor_bid.save()

    return po


@transaction.atomic
def finalize_tender_award(tender, awarded_items, admin_user):
    # awarded_items = [{ 'tender_item_id': ..., 'vendor_bid_id': ... }]
    from apps.tender.models import TenderItem, VendorBid

    awarded_bid_ids = set()
    created_pos = []

    for item in awarded_items:
        tender_item = TenderItem.objects.get(
            id=item['tender_item_id'], tender=tender)
        vendor_bid  = VendorBid.objects.get(
            id=item['vendor_bid_id'], tender=tender)
        po = award_tender_item(tender_item, vendor_bid, admin_user)
        created_pos.append(po)
        awarded_bid_ids.add(str(vendor_bid.id))

    # Mark non-awarded bids as not_awarded
    tender.bids.exclude(
        id__in=awarded_bid_ids
    ).update(status='not_awarded')

    tender.status     = 'awarded'
    tender.awarded_at = timezone.now()
    tender.awarded_by = admin_user
    tender.save()

    return created_pos
