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
            email='admin@test.com', password='pass', role='admin')
        self.vendor_user = User.objects.create_user(
            email='vendor@test.com', password='pass', role='vendor')
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


# ── Module 08a — Negotiation Ledger Tests ─────────────────────────────────────

class NegotiationLedgerTests(TestCase):
    """Tests for NegotiationLog model, serializer, and endpoint behaviour."""

    def setUp(self):
        from apps.tender.utils import generate_tender_number
        self.admin = User.objects.create_superuser(
            email='admin_ledger@test.com', password='pass', role='admin')
        self.vendor_user = User.objects.create_user(
            email='vendor_ledger@test.com', password='pass', role='vendor')
        self.vendor = VendorProfile.objects.create(
            user=self.vendor_user, company_name='Ledger Vendor',
            gst_number='GST_LEDGER', contact_name='Test',
            status='approved')
        cat = Category.objects.create(name='Ledger Cat', slug='ledger-cat')
        self.product = Product.objects.create(
            name='Ledger Product', slug='ledger-product',
            category=cat, sku='SKU_LEDGER', mrp=100,
            is_published=True, created_by=self.admin)
        self.client = APIClient()

        # Create an open tender with one item
        self.tender = Tender.objects.create(
            tender_number=generate_tender_number(),
            title='Ledger Tender', status='open',
            created_by=self.admin)
        self.item = TenderItem.objects.create(
            tender=self.tender, product=self.product,
            required_quantity=50, target_price=80)

    def _bid_payload(self, price='75.00'):
        return {
            'overall_notes': 'Initial bid note',
            'items': [{
                'tender_item': str(self.item.id),
                'supply_quantity': 50,
                'price_per_unit': price,
                'dispatch_date': str(
                    (timezone.now() + timedelta(days=30)).date()),
                'monthly_breakdown': [{'month': '2025-06', 'quantity': 50}],
                'notes': ''
            }]
        }

    # ── T1: NegotiationLog model basics ───────────────────────────────────────

    def test_negotiation_log_created_on_submit_with_notes(self):
        """Submitting a bid with overall_notes creates one vendor log entry."""
        self.client.force_authenticate(self.vendor_user)
        self.client.post(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=self._bid_payload(), format='json')

        bid = self.tender.bids.get(vendor=self.vendor)
        self.assertEqual(bid.negotiation_logs.count(), 1)
        log = bid.negotiation_logs.first()
        self.assertEqual(log.actor_role, 'vendor')
        self.assertEqual(log.message, 'Initial bid note')
        self.assertEqual(log.actor, self.vendor_user)

    def test_no_log_created_when_submit_has_no_notes(self):
        """Submitting without overall_notes does not create a log entry."""
        self.client.force_authenticate(self.vendor_user)
        payload = self._bid_payload()
        payload['overall_notes'] = ''
        self.client.post(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=payload, format='json')

        bid = self.tender.bids.get(vendor=self.vendor)
        self.assertEqual(bid.negotiation_logs.count(), 0)

    # ── T2: Admin negotiate endpoint ──────────────────────────────────────────

    def test_negotiate_creates_admin_log(self):
        """PATCH negotiate creates an admin-role log entry."""
        # Vendor submits bid
        self.client.force_authenticate(self.vendor_user)
        self.client.post(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=self._bid_payload(), format='json')
        bid = self.tender.bids.get(vendor=self.vendor)

        # Admin negotiates
        self.client.force_authenticate(self.admin)
        res = self.client.patch(
            f'/api/v1/tender/{self.tender.id}/bids/{bid.id}/negotiate/',
            data={'negotiation_notes': 'Can you lower the price?'},
            format='json')

        self.assertEqual(res.status_code, 200)
        self.assertEqual(bid.negotiation_logs.filter(actor_role='admin').count(), 1)
        log = bid.negotiation_logs.filter(actor_role='admin').first()
        self.assertEqual(log.message, 'Can you lower the price?')
        self.assertEqual(log.actor, self.admin)

    def test_negotiate_sets_bid_status_under_negotiation(self):
        """negotiate endpoint moves bid to under_negotiation."""
        self.client.force_authenticate(self.vendor_user)
        self.client.post(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=self._bid_payload(), format='json')
        bid = self.tender.bids.get(vendor=self.vendor)

        self.client.force_authenticate(self.admin)
        self.client.patch(
            f'/api/v1/tender/{self.tender.id}/bids/{bid.id}/negotiate/',
            data={'negotiation_notes': 'Reduce by 5%'}, format='json')

        bid.refresh_from_db()
        self.assertEqual(bid.status, 'under_negotiation')

    def test_negotiate_requires_notes(self):
        """negotiate returns 400 when negotiation_notes is empty."""
        self.client.force_authenticate(self.vendor_user)
        self.client.post(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=self._bid_payload(), format='json')
        bid = self.tender.bids.get(vendor=self.vendor)

        self.client.force_authenticate(self.admin)
        res = self.client.patch(
            f'/api/v1/tender/{self.tender.id}/bids/{bid.id}/negotiate/',
            data={'negotiation_notes': ''}, format='json')
        self.assertEqual(res.status_code, 400)

    # ── T3: Vendor revision log ───────────────────────────────────────────────

    def test_update_bid_creates_vendor_log(self):
        """PATCH /bid/ with overall_notes appends a vendor log entry."""
        # Submit initial bid
        self.client.force_authenticate(self.vendor_user)
        self.client.post(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=self._bid_payload(), format='json')
        bid = self.tender.bids.get(vendor=self.vendor)

        # Admin puts under negotiation
        self.client.force_authenticate(self.admin)
        self.client.patch(
            f'/api/v1/tender/{self.tender.id}/bids/{bid.id}/negotiate/',
            data={'negotiation_notes': 'Please revise'}, format='json')

        # Vendor revises
        self.client.force_authenticate(self.vendor_user)
        revised = self._bid_payload(price='70.00')
        revised['overall_notes'] = 'Revised down to 70'
        res = self.client.patch(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=revised, format='json')

        self.assertEqual(res.status_code, 200)
        vendor_logs = bid.negotiation_logs.filter(actor_role='vendor')
        # original submit + revision = 2 vendor logs
        self.assertEqual(vendor_logs.count(), 2)
        self.assertEqual(vendor_logs.last().message, 'Revised down to 70')

    def test_update_bid_no_log_when_no_notes(self):
        """PATCH /bid/ without overall_notes does not create a log entry."""
        self.client.force_authenticate(self.vendor_user)
        self.client.post(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=self._bid_payload(), format='json')
        bid = self.tender.bids.get(vendor=self.vendor)

        # Admin puts under negotiation
        self.client.force_authenticate(self.admin)
        self.client.patch(
            f'/api/v1/tender/{self.tender.id}/bids/{bid.id}/negotiate/',
            data={'negotiation_notes': 'Revise please'}, format='json')

        log_count_before = bid.negotiation_logs.count()

        # Vendor revises without notes
        self.client.force_authenticate(self.vendor_user)
        revised = self._bid_payload(price='70.00')
        revised['overall_notes'] = ''
        self.client.patch(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=revised, format='json')

        self.assertEqual(bid.negotiation_logs.count(), log_count_before)

    # ── T4: Log ordering and thread integrity ─────────────────────────────────

    def test_logs_are_ordered_chronologically(self):
        """negotiation_logs appear in created_at ascending order."""
        self.client.force_authenticate(self.vendor_user)
        self.client.post(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=self._bid_payload(), format='json')
        bid = self.tender.bids.get(vendor=self.vendor)

        self.client.force_authenticate(self.admin)
        self.client.patch(
            f'/api/v1/tender/{self.tender.id}/bids/{bid.id}/negotiate/',
            data={'negotiation_notes': 'Admin message'}, format='json')

        logs = list(bid.negotiation_logs.all())
        self.assertEqual(logs[0].actor_role, 'vendor')   # submit first
        self.assertEqual(logs[1].actor_role, 'admin')    # negotiate second

    def test_negotiation_logs_in_bid_serializer_response(self):
        """GET /tender/{id}/ includes negotiation_logs in each bid."""
        self.client.force_authenticate(self.vendor_user)
        self.client.post(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=self._bid_payload(), format='json')
        bid = self.tender.bids.get(vendor=self.vendor)

        self.client.force_authenticate(self.admin)
        self.client.patch(
            f'/api/v1/tender/{self.tender.id}/bids/{bid.id}/negotiate/',
            data={'negotiation_notes': 'Check notes in response'}, format='json')

        res = self.client.get(f'/api/v1/tender/{self.tender.id}/')
        self.assertEqual(res.status_code, 200)
        bids = res.data.get('bids', [])
        self.assertTrue(len(bids) > 0)
        logs = bids[0]['negotiation_logs']
        self.assertGreaterEqual(len(logs), 1)
        self.assertIn('actor_role', logs[0])
        self.assertIn('actor_name', logs[0])
        self.assertIn('message', logs[0])
        self.assertIn('created_at', logs[0])

    # ── T5: actor_name resolution ─────────────────────────────────────────────

    def test_actor_name_for_admin_log(self):
        """actor_name returns admin's name or email for admin-role log."""
        from apps.tender.models import NegotiationLog
        self.client.force_authenticate(self.vendor_user)
        self.client.post(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=self._bid_payload(), format='json')
        bid = self.tender.bids.get(vendor=self.vendor)

        self.client.force_authenticate(self.admin)
        self.client.patch(
            f'/api/v1/tender/{self.tender.id}/bids/{bid.id}/negotiate/',
            data={'negotiation_notes': 'Hello vendor'}, format='json')

        log = bid.negotiation_logs.filter(actor_role='admin').first()
        self.assertIsNotNone(log)
        # actor_name should not be empty
        from apps.tender.serializers import NegotiationLogSerializer
        data = NegotiationLogSerializer(log).data
        self.assertNotEqual(data['actor_name'], '')
        self.assertNotEqual(data['actor_name'], 'Unknown')

    def test_actor_name_for_vendor_log(self):
        """actor_name returns company_name for vendor-role log."""
        from apps.tender.serializers import NegotiationLogSerializer
        from apps.tender.models import NegotiationLog
        self.client.force_authenticate(self.vendor_user)
        self.client.post(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=self._bid_payload(), format='json')
        bid = self.tender.bids.get(vendor=self.vendor)

        log = bid.negotiation_logs.filter(actor_role='vendor').first()
        data = NegotiationLogSerializer(log).data
        self.assertEqual(data['actor_name'], 'Ledger Vendor')

    def test_actor_name_unknown_when_actor_deleted(self):
        """actor_name returns 'Unknown' when actor FK is NULL."""
        from apps.tender.models import NegotiationLog
        from apps.tender.serializers import NegotiationLogSerializer
        self.client.force_authenticate(self.vendor_user)
        self.client.post(
            f'/api/v1/tender/vendor/{self.tender.id}/bid/',
            data=self._bid_payload(), format='json')
        bid = self.tender.bids.get(vendor=self.vendor)
        log = bid.negotiation_logs.first()
        log.actor = None
        log.save()

        data = NegotiationLogSerializer(log).data
        self.assertEqual(data['actor_name'], 'Unknown')
