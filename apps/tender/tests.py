from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from accounts.models import User
from apps.products.models import Product, Category
from apps.vendors.models import VendorProfile
from apps.tender.models import Tender, TenderItem, VendorBid, VendorBidItem
from apps.tender.utils import generate_tender_number, finalize_tender_award
from rest_framework.test import APIClient


class TenderTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            mobile='9000000001', password='pass', role='admin')
        self.vendor_user = User.objects.create_user(
            mobile='9000000002', password='pass', role='vendor',
            name='Vendor One')
        self.vendor = VendorProfile.objects.create(
            user=self.vendor_user, company_name='Vendor Co',
            gst_number='GST001', contact_name='Test',
            status='approved')
        cat = Category.objects.create(name='Test Cat', slug='test-cat')
        self.product = Product.objects.create(
            name='Test Product', slug='test-product',
            category=cat, sku='SKU001', mrp=100,
            is_published=True, created_by=self.admin)
        self.client = APIClient()

    def _admin_login(self):
        self.client.force_authenticate(user=self.admin)

    def _vendor_login(self):
        self.client.force_authenticate(user=self.vendor_user)

    def _create_tender(self, status='draft'):
        tender = Tender.objects.create(
            tender_number=generate_tender_number(),
            title='Test Tender',
            status=status,
            created_by=self.admin)
        TenderItem.objects.create(
            tender=tender, product=self.product,
            required_quantity=100, target_price=90)
        return tender

    def test_create_tender(self):
        tender = self._create_tender()
        self.assertEqual(tender.status, 'draft')
        self.assertTrue(tender.tender_number.startswith('TND-'))

    def test_open_tender(self):
        self._admin_login()
        tender = self._create_tender()
        res = self.client.patch(f'/api/v1/tender/{tender.id}/open/')
        self.assertEqual(res.status_code, 200)
        tender.refresh_from_db()
        self.assertEqual(tender.status, 'open')

    def test_vendor_sees_open_tender(self):
        self._vendor_login()
        self._create_tender(status='open')
        res = self.client.get('/api/v1/tender/vendor/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)

    def test_vendor_submit_bid(self):
        self._vendor_login()
        tender = self._create_tender(status='open')
        item = tender.items.first()
        res = self.client.post(
            f'/api/v1/tender/vendor/{tender.id}/bid/',
            data={
                'overall_notes': 'Ready to supply',
                'items': [{
                    'tender_item': str(item.id),
                    'supply_quantity': 100,
                    'price_per_unit': '85.00',
                    'dispatch_date': str(
                        (timezone.now() + timedelta(days=30)).date()),
                    'monthly_breakdown': [
                        {'month': '2024-03', 'quantity': 100}],
                    'notes': ''
                }]
            }, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(tender.bids.count(), 1)

    def test_vendor_cannot_bid_twice(self):
        self._vendor_login()
        tender = self._create_tender(status='open')
        item = tender.items.first()
        data = {'items': [{
            'tender_item': str(item.id),
            'supply_quantity': 100,
            'price_per_unit': '85.00',
            'dispatch_date': str(
                (timezone.now() + timedelta(days=30)).date()),
            'monthly_breakdown': [{'month': '2024-03', 'quantity': 100}],
            'notes': ''
        }]}
        self.client.post(
            f'/api/v1/tender/vendor/{tender.id}/bid/',
            data=data, format='json')
        res = self.client.post(
            f'/api/v1/tender/vendor/{tender.id}/bid/',
            data=data, format='json')
        self.assertEqual(res.status_code, 400)

    def test_breakdown_sum_mismatch(self):
        self._vendor_login()
        tender = self._create_tender(status='open')
        item = tender.items.first()
        res = self.client.post(
            f'/api/v1/tender/vendor/{tender.id}/bid/',
            data={'items': [{
                'tender_item': str(item.id),
                'supply_quantity': 100,
                'price_per_unit': '85.00',
                'dispatch_date': str(
                    (timezone.now() + timedelta(days=30)).date()),
                'monthly_breakdown': [{'month': '2024-03', 'quantity': 50}],
                'notes': ''
            }]}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_admin_negotiate(self):
        self._vendor_login()
        tender = self._create_tender(status='open')
        item = tender.items.first()
        self.client.post(
            f'/api/v1/tender/vendor/{tender.id}/bid/',
            data={'items': [{
                'tender_item': str(item.id),
                'supply_quantity': 100,
                'price_per_unit': '85.00',
                'dispatch_date': str(
                    (timezone.now() + timedelta(days=30)).date()),
                'monthly_breakdown': [{'month': '2024-03', 'quantity': 100}],
                'notes': ''
            }]}, format='json')
        bid = tender.bids.first()
        self._admin_login()
        res = self.client.patch(
            f'/api/v1/tender/{tender.id}/bids/{bid.id}/negotiate/',
            data={'negotiation_notes': 'Please reduce price'},
            format='json')
        self.assertEqual(res.status_code, 200)
        bid.refresh_from_db()
        self.assertEqual(bid.status, 'under_negotiation')

    def test_close_and_award(self):
        tender = self._create_tender(status='open')
        item = tender.items.first()
        bid = VendorBid.objects.create(
            tender=tender, vendor=self.vendor,
            status='bid_submitted')
        VendorBidItem.objects.create(
            bid=bid, tender_item=item,
            supply_quantity=100, price_per_unit=85,
            dispatch_date=(timezone.now() + timedelta(days=30)).date(),
            monthly_breakdown=[{'month': '2024-03', 'quantity': 100}])

        self._admin_login()
        self.client.patch(f'/api/v1/tender/{tender.id}/close/')
        res = self.client.post(
            f'/api/v1/tender/{tender.id}/award/',
            data={'awarded_items': [{
                'tender_item_id': str(item.id),
                'vendor_bid_id':  str(bid.id)
            }]}, format='json')
        self.assertEqual(res.status_code, 200)
        tender.refresh_from_db()
        self.assertEqual(tender.status, 'awarded')
        self.assertEqual(len(res.data['po_numbers']), 1)

    def test_award_missing_item(self):
        tender = self._create_tender(status='closed')
        self._admin_login()
        res = self.client.post(
            f'/api/v1/tender/{tender.id}/award/',
            data={'awarded_items': []}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_auto_close_expired(self):
        tender = self._create_tender(status='open')
        tender.bidding_deadline = timezone.now() - timedelta(hours=1)
        tender.save()
        self._admin_login()
        self.client.get('/api/v1/tender/')
        tender.refresh_from_db()
        self.assertEqual(tender.status, 'closed')
