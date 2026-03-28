import random
import string
from datetime import date


def generate_po_number() -> str:
    from apps.procurement.models import PurchaseOrder
    while True:
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        number = f"PO-{date.today().strftime('%Y%m%d')}-{suffix}"
        if not PurchaseOrder.objects.filter(po_number=number).exists():
            return number
