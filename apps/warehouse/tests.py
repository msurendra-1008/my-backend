"""
apps.warehouse — 22 tests covering models, utils, and API endpoints.
"""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from apps.products.models import Category, Product, ProductVariant

from .models import Warehouse, Zone, Rack, RackStock, StockMovement, StockTransfer
from .utils import assign_stock_to_rack, deduct_stock, transfer_stock, sync_variant_stock


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_admin(mobile='9900100001'):
    return User.objects.create_user(
        password='pass', mobile=mobile, first_name='Admin', role='admin',
    )


def make_employee(mobile='9900100010'):
    return User.objects.create_user(
        password='pass', mobile=mobile, first_name='Employee', role='employee',
    )


def auth(client, user):
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')


def make_variant(sku='WH-V-001', stock=0):
    cat = Category.objects.get_or_create(name='Test', defaults={'slug': 'test'})[0]
    product = Product.objects.create(name=f'Product {sku}', sku=sku, mrp='100.00', category=cat)
    return ProductVariant.objects.create(
        product=product, name='Default', sku=f'{sku}-V1',
        mrp='100.00', stock_quantity=stock, is_active=True,
    )


def make_warehouse(name='WH-1'):
    wh = Warehouse.objects.create(name=name, location='Test location')
    zone = Zone.objects.create(warehouse=wh, name='Zone A')
    rack = Rack.objects.create(zone=zone, code='R1', capacity=0)
    return wh, zone, rack


# ── Model / Utils Tests ───────────────────────────────────────────────────────

class SyncVariantStockTest(TestCase):
    def test_sync_sums_all_rack_stocks(self):
        _, _, rack1 = make_warehouse('WH-SYNC-1')
        _, _, rack2 = make_warehouse('WH-SYNC-2')
        variant = make_variant('SYNC-V1')

        RackStock.objects.create(rack=rack1, variant=variant, quantity=30)
        RackStock.objects.create(rack=rack2, variant=variant, quantity=20)

        sync_variant_stock(variant)
        variant.refresh_from_db()
        self.assertEqual(variant.stock_quantity, 50)

    def test_sync_zero_when_no_rack_stock(self):
        variant = make_variant('SYNC-V2', stock=99)
        sync_variant_stock(variant)
        variant.refresh_from_db()
        self.assertEqual(variant.stock_quantity, 0)


class AssignStockTest(TestCase):
    def setUp(self):
        _, _, self.rack = make_warehouse('WH-ASSIGN')
        self.variant = make_variant('ASSIGN-V1')

    def test_creates_rack_stock_and_movement(self):
        assign_stock_to_rack(self.rack, self.variant, 50)
        rs = RackStock.objects.get(rack=self.rack, variant=self.variant)
        self.assertEqual(rs.quantity, 50)
        mv = StockMovement.objects.get(rack=self.rack, variant=self.variant)
        self.assertEqual(mv.movement_type, 'inbound')
        self.assertEqual(mv.quantity, 50)

    def test_syncs_variant_stock(self):
        assign_stock_to_rack(self.rack, self.variant, 40)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 40)

    def test_capacity_warning_when_exceeded(self):
        self.rack.capacity = 10
        self.rack.save()
        _, warning = assign_stock_to_rack(self.rack, self.variant, 20)
        self.assertTrue(warning)

    def test_no_capacity_warning_when_unlimited(self):
        _, warning = assign_stock_to_rack(self.rack, self.variant, 9999)
        self.assertFalse(warning)


class DeductStockTest(TestCase):
    def setUp(self):
        _, _, self.rack = make_warehouse('WH-DEDUCT')
        self.variant = make_variant('DEDUCT-V1')
        assign_stock_to_rack(self.rack, self.variant, 100)

    def test_deducts_and_creates_outbound_movement(self):
        deduct_stock(self.variant, 30)
        rs = RackStock.objects.get(rack=self.rack, variant=self.variant)
        self.assertEqual(rs.quantity, 70)
        mv = StockMovement.objects.filter(movement_type='outbound', variant=self.variant).first()
        self.assertIsNotNone(mv)
        self.assertEqual(mv.quantity, 30)

    def test_fifo_order(self):
        _, _, rack2 = make_warehouse('WH-DEDUCT-2')
        assign_stock_to_rack(rack2, self.variant, 50)
        # Deduct more than first rack has
        deduct_stock(self.variant, 120)
        rs1 = RackStock.objects.get(rack=self.rack, variant=self.variant)
        rs2 = RackStock.objects.get(rack=rack2, variant=self.variant)
        self.assertEqual(rs1.quantity, 0)
        self.assertEqual(rs2.quantity, 30)

    def test_insufficient_stock_raises(self):
        with self.assertRaises(ValueError):
            deduct_stock(self.variant, 999)

    def test_syncs_variant_stock(self):
        deduct_stock(self.variant, 40)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 60)


class TransferStockTest(TestCase):
    def setUp(self):
        _, _, self.rack1 = make_warehouse('WH-TR-1')
        _, _, self.rack2 = make_warehouse('WH-TR-2')
        self.variant = make_variant('TR-V1')
        assign_stock_to_rack(self.rack1, self.variant, 100)

    def test_transfer_moves_stock(self):
        transfer_stock(self.rack1, self.rack2, self.variant, 40)
        rs1 = RackStock.objects.get(rack=self.rack1, variant=self.variant)
        rs2 = RackStock.objects.get(rack=self.rack2, variant=self.variant)
        self.assertEqual(rs1.quantity, 60)
        self.assertEqual(rs2.quantity, 40)

    def test_transfer_creates_two_movements(self):
        transfer_stock(self.rack1, self.rack2, self.variant, 40)
        movements = StockMovement.objects.filter(variant=self.variant)
        types = set(movements.values_list('movement_type', flat=True))
        self.assertIn('transfer_out', types)
        self.assertIn('transfer_in', types)

    def test_transfer_creates_transfer_record(self):
        t, _ = transfer_stock(self.rack1, self.rack2, self.variant, 40)
        self.assertEqual(t.status, 'completed')
        self.assertEqual(t.quantity, 40)

    def test_insufficient_raises(self):
        with self.assertRaises(ValueError):
            transfer_stock(self.rack1, self.rack2, self.variant, 999)


# ── API Tests ─────────────────────────────────────────────────────────────────

class WarehouseAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin()
        self.employee = make_employee()

    def test_admin_can_create_warehouse(self):
        auth(self.client, self.admin)
        res = self.client.post('/api/v1/warehouse/warehouses/', {'name': 'Main WH', 'location': 'Delhi'})
        self.assertEqual(res.status_code, 201)

    def test_employee_cannot_create_warehouse(self):
        auth(self.client, self.employee)
        res = self.client.post('/api/v1/warehouse/warehouses/', {'name': 'X', 'location': 'Y'})
        self.assertEqual(res.status_code, 403)

    def test_employee_can_list_warehouses(self):
        auth(self.client, self.employee)
        res = self.client.get('/api/v1/warehouse/warehouses/')
        self.assertEqual(res.status_code, 200)


class StockAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin('9900100002')
        self.wh, self.zone, self.rack = make_warehouse('WH-API')
        self.variant = make_variant('API-V1')

    def test_assign_creates_stock(self):
        auth(self.client, self.admin)
        res = self.client.post('/api/v1/warehouse/stock/assign/', {
            'rack': str(self.rack.id),
            'variant': str(self.variant.id),
            'quantity': 25,
        })
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['rack_stock']['quantity'], 25)

    def test_adjust_stock(self):
        auth(self.client, self.admin)
        RackStock.objects.create(rack=self.rack, variant=self.variant, quantity=10)
        sync_variant_stock(self.variant)
        res = self.client.post('/api/v1/warehouse/stock/adjust/', {
            'rack': str(self.rack.id),
            'variant': str(self.variant.id),
            'adjustment_type': 'add',
            'quantity': 40,
            'reason': 'Opening stock correction',
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['rack_stock']['quantity'], 50)

    def test_transfer_via_api(self):
        auth(self.client, self.admin)
        _, _, rack2 = make_warehouse('WH-API-2')
        assign_stock_to_rack(self.rack, self.variant, 60)
        res = self.client.post('/api/v1/warehouse/stock/transfer/', {
            'from_rack': str(self.rack.id),
            'to_rack': str(rack2.id),
            'variant': str(self.variant.id),
            'quantity': 20,
        })
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['transfer']['quantity'], 20)

    def test_transfer_same_rack_fails(self):
        auth(self.client, self.admin)
        res = self.client.post('/api/v1/warehouse/stock/transfer/', {
            'from_rack': str(self.rack.id),
            'to_rack': str(self.rack.id),
            'variant': str(self.variant.id),
            'quantity': 5,
        })
        self.assertEqual(res.status_code, 400)

    def test_list_movements(self):
        auth(self.client, self.admin)
        assign_stock_to_rack(self.rack, self.variant, 10)
        res = self.client.get('/api/v1/warehouse/stock/movements/')
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.data), 1)
