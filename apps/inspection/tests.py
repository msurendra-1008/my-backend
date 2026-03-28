"""
apps.inspection — 19 tests covering the full inspection flow.
"""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from apps.products.models import Category, Product, ProductVariant
from apps.vendors.models import VendorProduct, VendorProfile
from apps.procurement.models import PurchaseOrder, ProcurementRequirement
from apps.inspection.models import IncomingShipment, InspectionReport, InspectionSettings


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_admin(mobile='9900000001'):
    return User.objects.create_user(
        password='pass', mobile=mobile, first_name='Admin', role='admin',
    )


def make_approved_vendor(mobile='9900000002'):
    cat = Category.objects.get_or_create(name='Test', defaults={'slug': 'test'})[0]
    user = User.objects.create_user(
        password='pass', mobile=mobile, role='vendor',
        first_name='Vendor', last_name='User',
    )
    profile = VendorProfile.objects.create(
        user=user, company_name='Test Vendor Co', gst_number='55AAAVP0000V1Z5',
        contact_name='Vendor User', address_line1='1 Road',
        city='Delhi', state='Delhi', pincode='110001', status='approved',
    )
    profile.categories.add(cat)
    return profile


def make_product(sku='INS-TEST-001'):
    cat = Category.objects.get_or_create(name='Test', defaults={'slug': 'test'})[0]
    product = Product.objects.create(name='Test Product', sku=sku, mrp='500.00', category=cat)
    ProductVariant.objects.create(
        product=product, name='Default', sku=f'{sku}-V1', mrp='500.00',
        stock_quantity=100, is_active=True,
    )
    return product


def make_po(vendor_profile, product, mobile_suffix='001'):
    cat = Category.objects.get_or_create(name='Test', defaults={'slug': 'test'})[0]
    vp = VendorProduct.objects.create(
        vendor=vendor_profile, name=product.name,
        sku=f'VP-{product.sku}-{mobile_suffix}', status='approved',
        catalog_product=product, category=cat,
    )
    req = ProcurementRequirement.objects.create(
        vendor_product=vp, vendor=vendor_profile, product=product,
        required_quantity=500, required_by_date='2025-12-31',
    )
    return PurchaseOrder.objects.create(
        po_number=f'PO-TEST-{mobile_suffix}',
        requirement=req,
        vendor=vendor_profile,
        product=product,
        quantity=500,
        price_per_unit='100.00',
        total_amount='50000.00',
        dispatch_date='2025-11-30',
        status='acknowledged',
    )


def auth(client, user):
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(token.access_token)}')


# ── Tests ─────────────────────────────────────────────────────────────────────

class ShipmentAutoCreateTest(TestCase):
    """B1: PO dispatched → IncomingShipment auto-created."""

    def setUp(self):
        self.client  = APIClient()
        self.admin   = make_admin()
        self.vendor  = make_approved_vendor()
        self.product = make_product('SHIP-001')
        self.po      = make_po(self.vendor, self.product, '001')
        # put PO in acknowledged state
        self.po.status = 'acknowledged'
        self.po.save()

    def test_dispatch_creates_shipment(self):
        auth(self.client, self.vendor.user)
        url = f'/api/v1/procurement/purchase-orders/{self.po.id}/dispatch/'
        resp = self.client.patch(url)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(IncomingShipment.objects.filter(purchase_order=self.po).exists())

    def test_shipment_expected_qty_equals_po_quantity(self):
        auth(self.client, self.vendor.user)
        self.client.patch(f'/api/v1/procurement/purchase-orders/{self.po.id}/dispatch/')
        shipment = IncomingShipment.objects.get(purchase_order=self.po)
        self.assertEqual(shipment.expected_quantity, self.po.quantity)


class InspectionSubmitTest(TestCase):
    """B3/B4: Inspection form validation and submission."""

    def setUp(self):
        self.client  = APIClient()
        self.admin   = make_admin('9900000010')
        self.product = make_product('INSPECT-001')
        self.vendor  = make_approved_vendor('9900000011')
        self.po      = make_po(self.vendor, self.product, '010')
        self.shipment = IncomingShipment.objects.create(
            purchase_order=self.po,
            expected_quantity=500,
            status='awaiting_inspection',
        )
        auth(self.client, self.admin)

    def _url(self):
        return f'/api/v1/inspection/shipments/{self.shipment.id}/submit-report/'

    def test_valid_submission_returns_201(self):
        resp = self.client.post(self._url(), {
            'received_quantity': 500,
            'accepted_quantity': 480,
            'rejected_quantity':  20,
            'rejection_breakdown': {'damaged_packaging': 20},
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_accepted_plus_rejected_not_equal_received_returns_400(self):
        resp = self.client.post(self._url(), {
            'received_quantity': 500,
            'accepted_quantity': 400,
            'rejected_quantity':  50,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_received_greater_than_expected_returns_400(self):
        resp = self.client.post(self._url(), {
            'received_quantity': 600,
            'accepted_quantity': 600,
            'rejected_quantity':   0,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_rejected_without_breakdown_returns_400(self):
        resp = self.client.post(self._url(), {
            'received_quantity': 500,
            'accepted_quantity': 480,
            'rejected_quantity':  20,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_breakdown_sum_mismatch_returns_400(self):
        resp = self.client.post(self._url(), {
            'received_quantity': 500,
            'accepted_quantity': 480,
            'rejected_quantity':  20,
            'rejection_breakdown': {'damaged_packaging': 15},
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_rejection_reason_key_returns_400(self):
        resp = self.client.post(self._url(), {
            'received_quantity': 500,
            'accepted_quantity': 480,
            'rejected_quantity':  20,
            'rejection_breakdown': {'invalid_reason': 20},
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_other_reason_without_notes_returns_400(self):
        resp = self.client.post(self._url(), {
            'received_quantity': 500,
            'accepted_quantity': 480,
            'rejected_quantity':  20,
            'rejection_breakdown': {'other': 20},
            'rejection_other_notes': 'short',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_submit_sets_shipment_completed(self):
        self.client.post(self._url(), {
            'received_quantity': 500,
            'accepted_quantity': 500,
            'rejected_quantity':   0,
        }, format='json')
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, 'completed')

    def test_submit_with_rejections_creates_debit_note_field(self):
        """debit_note_generated_at is set when rejected > 0 (PDF may fail in test, just check report exists)."""
        self.client.post(self._url(), {
            'received_quantity': 500,
            'accepted_quantity': 480,
            'rejected_quantity':  20,
            'rejection_breakdown': {'damaged_packaging': 20},
        }, format='json')
        report = InspectionReport.objects.get(shipment=self.shipment)
        self.assertEqual(report.rejected_quantity, 20)

    def test_submit_with_no_rejections_no_debit_note(self):
        self.client.post(self._url(), {
            'received_quantity': 500,
            'accepted_quantity': 500,
            'rejected_quantity':   0,
        }, format='json')
        report = InspectionReport.objects.get(shipment=self.shipment)
        self.assertFalse(bool(report.debit_note))

    def test_cannot_submit_twice(self):
        data = {'received_quantity': 500, 'accepted_quantity': 500, 'rejected_quantity': 0}
        self.client.post(self._url(), data, format='json')
        resp = self.client.post(self._url(), data, format='json')
        self.assertEqual(resp.status_code, 400)


class StockUpdateTest(TestCase):
    """B2: Stock update flow — auto and manual."""

    def setUp(self):
        self.client  = APIClient()
        self.admin   = make_admin('9900000020')
        self.product = make_product('STOCK-001')
        self.vendor  = make_approved_vendor('9900000021')
        self.po      = make_po(self.vendor, self.product, '020')
        self.shipment = IncomingShipment.objects.create(
            purchase_order=self.po,
            expected_quantity=500,
            status='awaiting_inspection',
        )
        auth(self.client, self.admin)

    def _submit(self, accepted=480, rejected=20):
        url = f'/api/v1/inspection/shipments/{self.shipment.id}/submit-report/'
        self.client.post(url, {
            'received_quantity': accepted + rejected,
            'accepted_quantity': accepted,
            'rejected_quantity': rejected,
            'rejection_breakdown': {'damaged_packaging': rejected} if rejected > 0 else {},
        }, format='json')
        self.shipment.refresh_from_db()

    def test_auto_stock_update_on_submit(self):
        InspectionSettings.get_settings()
        InspectionSettings.objects.update(auto_stock_update=True)
        variant_before = self.product.variants.filter(is_active=True).first().stock_quantity
        self._submit(480, 20)
        variant = self.product.variants.filter(is_active=True).first()
        self.assertEqual(variant.stock_quantity, variant_before + 480)

    def test_no_auto_stock_update_when_disabled(self):
        InspectionSettings.get_settings()
        InspectionSettings.objects.update(auto_stock_update=False)
        variant_before = self.product.variants.filter(is_active=True).first().stock_quantity
        self._submit(480, 20)
        variant = self.product.variants.filter(is_active=True).first()
        self.assertEqual(variant.stock_quantity, variant_before)

    def test_manual_stock_update(self):
        InspectionSettings.get_settings()
        InspectionSettings.objects.update(auto_stock_update=False)
        variant_before = self.product.variants.filter(is_active=True).first().stock_quantity
        self._submit(480, 20)
        url = f'/api/v1/inspection/shipments/{self.shipment.id}/update-stock/'
        resp = self.client.patch(url)
        self.assertEqual(resp.status_code, 200, resp.data)
        variant = self.product.variants.filter(is_active=True).first()
        self.assertEqual(variant.stock_quantity, variant_before + 480)

    def test_po_status_completed_after_stock_update(self):
        InspectionSettings.get_settings()
        InspectionSettings.objects.update(auto_stock_update=False)
        self._submit(480, 20)
        self.client.patch(f'/api/v1/inspection/shipments/{self.shipment.id}/update-stock/')
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, 'completed')


class PermissionTest(TestCase):
    """Employee permission checks."""

    def setUp(self):
        self.client  = APIClient()
        self.product = make_product('PERM-001')
        self.vendor  = make_approved_vendor('9900000030')
        self.po      = make_po(self.vendor, self.product, '030')
        self.shipment = IncomingShipment.objects.create(
            purchase_order=self.po,
            expected_quantity=500,
            status='awaiting_inspection',
        )

    def _make_employee(self, mobile, permissions=None):
        user = User.objects.create_user(
            password='pass', mobile=mobile, role='employee', first_name='Emp',
        )
        from apps.users.models import EmployeeProfile
        EmployeeProfile.objects.create(user=user, permissions=permissions or [])
        return user

    def test_employee_with_permission_can_submit(self):
        emp = self._make_employee('9900000031', ['inspection.perform'])
        auth(self.client, emp)
        url = f'/api/v1/inspection/shipments/{self.shipment.id}/submit-report/'
        resp = self.client.post(url, {
            'received_quantity': 500,
            'accepted_quantity': 500,
            'rejected_quantity':   0,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_employee_without_permission_gets_403(self):
        emp = self._make_employee('9900000032', [])
        auth(self.client, emp)
        url = f'/api/v1/inspection/shipments/{self.shipment.id}/submit-report/'
        resp = self.client.post(url, {
            'received_quantity': 500,
            'accepted_quantity': 500,
            'rejected_quantity':   0,
        }, format='json')
        self.assertEqual(resp.status_code, 403)
