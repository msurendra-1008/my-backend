"""
apps.procurement — 17 tests covering the full procurement flow.
"""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from apps.products.models import Category, Product
from apps.vendors.models import VendorProfile, VendorProduct


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_admin(mobile='8800000099'):
    return User.objects.create_user(
        password='pass', mobile=mobile, first_name='Admin', role='admin',
    )


def make_approved_vendor(mobile='8800000001', gst='55AAAVP0000V1Z5', company='Test Vendor Co'):
    cat = Category.objects.get_or_create(name='Textiles', defaults={'slug': 'textiles'})[0]
    user = User.objects.create_user(
        password='pass', mobile=mobile, role='vendor',
        first_name='Vendor', last_name='User',
    )
    profile = VendorProfile.objects.create(
        user=user, company_name=company, gst_number=gst,
        contact_name='Vendor User', address_line1='1 Road',
        city='Delhi', state='Delhi', pincode='110001', status='approved',
    )
    profile.categories.add(cat)
    return profile


def make_catalog_product(name='Fabric 500g', sku='FAB-500'):
    cat = Category.objects.get_or_create(name='Textiles', defaults={'slug': 'textiles'})[0]
    return Product.objects.create(
        name=name, sku=sku, mrp='500.00', category=cat, is_published=False,
    )


def make_approved_vendor_product(vendor_profile, catalog_product):
    vp = VendorProduct.objects.create(
        vendor=vendor_profile,
        name=catalog_product.name,
        sku=f'VP-{catalog_product.sku}',
        status='approved',
        catalog_product=catalog_product,
        category=catalog_product.category,
    )
    from apps.vendors.models import VendorProductVariant
    VendorProductVariant.objects.create(
        vendor_product=vp, name='Standard', variant_type='other',
        sku=f'VP-{catalog_product.sku}-S', mrp='500.00',
    )
    return vp


def auth(client, user):
    token = str(RefreshToken.for_user(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')


REQ_URL          = '/api/v1/procurement/requirements/'
VENDOR_REQ_URL   = '/api/v1/procurement/vendor-requirements/'
PO_URL           = '/api/v1/procurement/purchase-orders/'

RESPONSE_DATA = {
    'supply_quantity':   500,
    'price_per_unit':    '480.00',
    'dispatch_date':     '2030-06-01',
    'monthly_breakdown': [
        {'month': '2030-06', 'quantity': 500},
    ],
    'notes': 'Will dispatch on time.',
}


# ── Setup ─────────────────────────────────────────────────────────────────────

class ProcurementBaseTest(TestCase):
    def setUp(self):
        self.admin_client  = APIClient()
        self.vendor_client = APIClient()

        self.admin   = make_admin()
        self.vendor  = make_approved_vendor()
        self.catalog = make_catalog_product()
        self.vp      = make_approved_vendor_product(self.vendor, self.catalog)

        auth(self.admin_client, self.admin)
        auth(self.vendor_client, self.vendor.user)

    def _create_requirement(self, extra=None):
        data = {
            'vendor_product_id': str(self.vp.id),
            'required_quantity': 500,
            'required_by_date':  '2030-06-30',
            'notes':             'Test requirement',
        }
        if extra:
            data.update(extra)
        return self.admin_client.post(REQ_URL, data, format='json')


# ── B1: Create requirement ────────────────────────────────────────────────────

class CreateRequirementTests(ProcurementBaseTest):

    def test_admin_creates_requirement_for_approved_vp(self):
        """Admin creates requirement → status=draft"""
        res = self._create_requirement()
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['status'], 'draft')
        self.assertEqual(res.data['vendor_company'], self.vendor.company_name)

    def test_non_approved_vendor_product_returns_400(self):
        """Creating requirement for non-approved vendor product → 400"""
        vp2 = VendorProduct.objects.create(
            vendor=self.vendor, name='Pending Fabric', sku='PF-001',
            status='pending_approval', category=self.catalog.category,
        )
        res = self.admin_client.post(REQ_URL, {
            'vendor_product_id': str(vp2.id),
            'required_quantity': 100,
            'required_by_date':  '2030-06-30',
        }, format='json')
        self.assertEqual(res.status_code, 400)

    def test_duplicate_active_requirement_returns_400(self):
        """Creating second requirement for same vendor product → 400"""
        self._create_requirement()
        res = self._create_requirement()
        self.assertEqual(res.status_code, 400)


# ── B2: Send to vendor ────────────────────────────────────────────────────────

class SendRequirementTests(ProcurementBaseTest):

    def test_admin_sends_requirement_vendor_can_see(self):
        """Admin sends requirement → status=sent, vendor can list it"""
        req_id = self._create_requirement().data['id']
        res = self.admin_client.patch(f'{REQ_URL}{req_id}/send/', {}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'sent')

        # Vendor can now see it
        vres = self.vendor_client.get(VENDOR_REQ_URL)
        self.assertEqual(vres.data['count'], 1)


# ── B3: Vendor responds ───────────────────────────────────────────────────────

class VendorResponseTests(ProcurementBaseTest):

    def _sent_req_id(self):
        req_id = self._create_requirement().data['id']
        self.admin_client.patch(f'{REQ_URL}{req_id}/send/', {}, format='json')
        return req_id

    def test_vendor_responds_when_sent(self):
        """Vendor submits response → status=vendor_responded, VendorResponse created"""
        req_id = self._sent_req_id()
        res = self.vendor_client.post(
            f'{VENDOR_REQ_URL}{req_id}/respond/', RESPONSE_DATA, format='json',
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['status'], 'vendor_responded')

    def test_vendor_cannot_respond_when_not_sent(self):
        """Vendor responds when status=draft → 400"""
        req_id = self._create_requirement().data['id']  # still draft
        res = self.vendor_client.post(
            f'{VENDOR_REQ_URL}{req_id}/respond/', RESPONSE_DATA, format='json',
        )
        self.assertEqual(res.status_code, 400)

    def test_monthly_breakdown_sum_mismatch_returns_400(self):
        """Monthly breakdown total ≠ supply_quantity → 400"""
        req_id = self._sent_req_id()
        bad_data = {**RESPONSE_DATA, 'monthly_breakdown': [{'month': '2030-06', 'quantity': 200}]}
        res = self.vendor_client.post(
            f'{VENDOR_REQ_URL}{req_id}/respond/', bad_data, format='json',
        )
        self.assertEqual(res.status_code, 400)

    def test_duplicate_months_in_breakdown_returns_400(self):
        """Duplicate months in breakdown → 400"""
        req_id = self._sent_req_id()
        bad_data = {
            **RESPONSE_DATA,
            'supply_quantity': 500,
            'monthly_breakdown': [
                {'month': '2030-06', 'quantity': 250},
                {'month': '2030-06', 'quantity': 250},
            ],
        }
        res = self.vendor_client.post(
            f'{VENDOR_REQ_URL}{req_id}/respond/', bad_data, format='json',
        )
        self.assertEqual(res.status_code, 400)

    def test_vendor_updates_response_increments_count(self):
        """Vendor updates response → update_count incremented"""
        req_id = self._sent_req_id()
        self.vendor_client.post(
            f'{VENDOR_REQ_URL}{req_id}/respond/', RESPONSE_DATA, format='json',
        )
        res = self.vendor_client.patch(
            f'{VENDOR_REQ_URL}{req_id}/update-response/',
            {'notes': 'Updated notes.'},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['vendor_response']['update_count'], 1)

    def test_vendor_cannot_update_after_po_generated(self):
        """Vendor cannot update response after PO generated → 400"""
        req_id = self._sent_req_id()
        self.vendor_client.post(
            f'{VENDOR_REQ_URL}{req_id}/respond/', RESPONSE_DATA, format='json',
        )
        # Admin confirms
        self.admin_client.patch(f'{REQ_URL}{req_id}/confirm/', {}, format='json')
        # Try to update
        res = self.vendor_client.patch(
            f'{VENDOR_REQ_URL}{req_id}/update-response/',
            {'notes': 'Too late.'},
            format='json',
        )
        self.assertEqual(res.status_code, 400)


# ── B4: Negotiation ───────────────────────────────────────────────────────────

class NegotiationTests(ProcurementBaseTest):

    def _with_vendor_response(self):
        req_id = self._create_requirement().data['id']
        self.admin_client.patch(f'{REQ_URL}{req_id}/send/', {}, format='json')
        self.vendor_client.post(
            f'{VENDOR_REQ_URL}{req_id}/respond/', RESPONSE_DATA, format='json',
        )
        return req_id

    def test_admin_negotiates_sets_status_and_notes(self):
        """Admin sends back for negotiation → status=negotiating, notes saved"""
        req_id = self._with_vendor_response()
        res = self.admin_client.patch(
            f'{REQ_URL}{req_id}/negotiate/',
            {'negotiation_notes': 'Please lower the price per unit.'},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'negotiating')
        self.assertEqual(res.data['negotiation_notes'], 'Please lower the price per unit.')

    def test_vendor_updates_response_when_negotiating(self):
        """Vendor updates response when negotiating → status back to vendor_responded"""
        req_id = self._with_vendor_response()
        self.admin_client.patch(
            f'{REQ_URL}{req_id}/negotiate/',
            {'negotiation_notes': 'Please lower the price per unit.'},
            format='json',
        )
        res = self.vendor_client.patch(
            f'{VENDOR_REQ_URL}{req_id}/update-response/',
            {'price_per_unit': '450.00', 'notes': 'Revised price.'},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'vendor_responded')


# ── B5: Confirm → PO ─────────────────────────────────────────────────────────

class ConfirmAndPOTests(ProcurementBaseTest):

    def _vendor_responded_req_id(self):
        req_id = self._create_requirement().data['id']
        self.admin_client.patch(f'{REQ_URL}{req_id}/send/', {}, format='json')
        self.vendor_client.post(
            f'{VENDOR_REQ_URL}{req_id}/respond/', RESPONSE_DATA, format='json',
        )
        return req_id

    def test_admin_confirms_generates_po(self):
        """Admin confirms → PO created with correct totals, status=po_generated"""
        req_id = self._vendor_responded_req_id()
        res = self.admin_client.patch(f'{REQ_URL}{req_id}/confirm/', {}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'po_generated')
        po = res.data['po']
        self.assertIsNotNone(po)
        self.assertEqual(po['quantity'], RESPONSE_DATA['supply_quantity'])
        self.assertEqual(po['price_per_unit'], RESPONSE_DATA['price_per_unit'])
        # total = 500 × 480.00 = 240000.00
        self.assertEqual(float(po['total_amount']), 500 * 480.0)

    def test_admin_confirms_without_response_returns_400(self):
        """Admin confirms without vendor response → 400"""
        req_id = self._create_requirement().data['id']
        self.admin_client.patch(f'{REQ_URL}{req_id}/send/', {}, format='json')
        res = self.admin_client.patch(f'{REQ_URL}{req_id}/confirm/', {}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_admin_cancels_requirement(self):
        """Admin cancels → status=cancelled"""
        req_id = self._create_requirement().data['id']
        res = self.admin_client.patch(
            f'{REQ_URL}{req_id}/cancel/',
            {'cancellation_reason': 'Budget cut.'},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'cancelled')


# ── B6: PO Lifecycle ──────────────────────────────────────────────────────────

class POLifecycleTests(ProcurementBaseTest):

    def _get_po_id(self):
        req_id = self._create_requirement().data['id']
        self.admin_client.patch(f'{REQ_URL}{req_id}/send/', {}, format='json')
        self.vendor_client.post(
            f'{VENDOR_REQ_URL}{req_id}/respond/', RESPONSE_DATA, format='json',
        )
        confirm_res = self.admin_client.patch(f'{REQ_URL}{req_id}/confirm/', {}, format='json')
        return confirm_res.data['po']['id']

    def test_vendor_acknowledges_po(self):
        """Vendor acknowledges PO → status=acknowledged"""
        po_id = self._get_po_id()
        res = self.vendor_client.patch(f'{PO_URL}{po_id}/acknowledge/', {}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'acknowledged')

    def test_vendor_marks_dispatched(self):
        """Vendor marks PO as dispatched → status=dispatched"""
        po_id = self._get_po_id()
        self.vendor_client.patch(f'{PO_URL}{po_id}/acknowledge/', {}, format='json')
        res = self.vendor_client.patch(
            f'{PO_URL}{po_id}/dispatch/', {'vendor_notes': 'Sent via truck.'}, format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'dispatched')
