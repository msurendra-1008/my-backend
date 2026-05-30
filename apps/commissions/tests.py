"""
Tests for Module 10 — Commission Distribution System.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from apps.commissions.models import (
    CommissionSettings,
    CommissionBreakup,
    CommissionEntry,
    ProductCommissionRule,
    DEFAULT_LEVEL_PERCENTAGES,
)
from apps.commissions.utils import (
    calculate_commission_entries,
    create_commission_breakup,
    process_commission_breakup,
    credit_pending_entry,
    get_level_percentages,
)
from apps.orders.models import Order, OrderItem
from apps.products.models import Category, Product, ProductVariant
from apps.upa_tree.models import UPATree
from apps.wallet.models import Wallet


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_user(email, upa_id=None, is_active=True, mobile=None):
    user = User.objects.create_user(
        email=email,
        password='testpass',
        first_name='Test',
        last_name='User',
        is_active=is_active,
        upa_id=upa_id,
        mobile=mobile,
    )
    Wallet.objects.create(user=user)
    return user


def make_product(name='Widget', sku='SKU-001', mrp=Decimal('100.00')):
    cat, _ = Category.objects.get_or_create(name='Test Category', defaults={'slug': 'test-category'})
    return Product.objects.create(name=name, sku=sku, mrp=mrp, slug=name.lower().replace(' ', '-'))


def make_variant(product, name='Default', price=Decimal('80.00')):
    return ProductVariant.objects.create(
        product=product,
        name=name,
        sku=f'{product.sku}-V1',
        mrp=product.mrp,
        upa_price_override=price,
        stock_quantity=100,
    )


def make_order(user):
    return Order.objects.create(
        user=user,
        address_name='Test',
        address_phone='9999999999',
        address_line='123 Street',
        address_city='City',
        address_state='State',
        address_pincode='123456',
        subtotal=Decimal('80.00'),
        upa_discount=Decimal('20.00'),
        amount_payable=Decimal('80.00'),
        payment_status='paid',
        order_status='confirmed',
    )


def make_order_item(order, variant, upa_price=Decimal('80.00'), qty=1):
    return OrderItem.objects.create(
        order=order,
        variant=variant,
        product_name=variant.product.name,
        variant_name=variant.name,
        sku=variant.sku,
        mrp=variant.mrp,
        upa_price=upa_price,
        quantity=qty,
        line_total=upa_price * qty,
    )


def make_commission_rule(product, net_pct=Decimal('7.00'), team_pct=Decimal('3.00'),
                          direction='top_heavy', level_percentages=None,
                          left_pct=Decimal('40.00'), mid_pct=Decimal('30.00'),
                          right_pct=Decimal('30.00'), max_levels=7, is_active=True):
    if level_percentages is None:
        level_percentages = DEFAULT_LEVEL_PERCENTAGES
    return ProductCommissionRule.objects.create(
        product=product,
        is_active=is_active,
        network_commission_pct=net_pct,
        team_commission_pct=team_pct,
        max_upline_levels=max_levels,
        direction=direction,
        level_percentages=level_percentages,
        left_leg_pct=left_pct,
        middle_leg_pct=mid_pct,
        right_leg_pct=right_pct,
    )


def place_user_in_tree(user, parent_user=None, leg=None, depth=0):
    return UPATree.objects.create(
        user=user,
        parent_user=parent_user,
        leg=leg,
        depth_level=depth,
    )


# ── CommissionSettings ────────────────────────────────────────────────────────

class CommissionSettingsTest(TestCase):

    def test_get_creates_singleton(self):
        self.assertEqual(CommissionSettings.objects.count(), 0)
        obj = CommissionSettings.get()
        self.assertIsNotNone(obj)
        self.assertEqual(CommissionSettings.objects.count(), 1)

    def test_get_returns_existing(self):
        obj1 = CommissionSettings.get()
        obj2 = CommissionSettings.get()
        self.assertEqual(obj1.pk, obj2.pk)

    def test_defaults_set(self):
        obj = CommissionSettings.get()
        self.assertEqual(obj.network_commission_pct, Decimal('7.00'))
        self.assertEqual(obj.team_commission_pct, Decimal('3.00'))
        self.assertEqual(obj.level_percentages, DEFAULT_LEVEL_PERCENTAGES)

    def test_get_always_returns_same_object(self):
        obj1 = CommissionSettings.get()
        # Calling get() multiple times always returns the same singleton
        obj2 = CommissionSettings.get()
        obj3 = CommissionSettings.get()
        self.assertEqual(obj1.pk, obj2.pk)
        self.assertEqual(obj2.pk, obj3.pk)
        self.assertEqual(CommissionSettings.objects.count(), 1)


# ── get_level_percentages ─────────────────────────────────────────────────────

class GetLevelPercentagesTest(TestCase):

    def test_top_heavy_unchanged(self):
        rule = type('R', (), {'level_percentages': [40, 25, 15, 10, 5, 3, 2], 'direction': 'top_heavy'})()
        result = get_level_percentages(rule)
        self.assertEqual(result, [40, 25, 15, 10, 5, 3, 2])

    def test_bottom_heavy_reversed(self):
        rule = type('R', (), {'level_percentages': [40, 25, 15, 10, 5, 3, 2], 'direction': 'bottom_heavy'})()
        result = get_level_percentages(rule)
        self.assertEqual(result, [2, 3, 5, 10, 15, 25, 40])

    def test_empty_falls_back_to_defaults(self):
        rule = type('R', (), {'level_percentages': [], 'direction': 'top_heavy'})()
        result = get_level_percentages(rule)
        self.assertEqual(result, DEFAULT_LEVEL_PERCENTAGES)


# ── No rule — None returned ───────────────────────────────────────────────────

class NoRuleTest(TestCase):

    def test_no_rule_returns_none(self):
        buyer = make_user('buyer@test.com', upa_id='UPA001')
        product = make_product()
        variant = make_variant(product)
        order = make_order(buyer)
        item = make_order_item(order, variant)
        # No ProductCommissionRule created
        result = create_commission_breakup(item)
        self.assertIsNone(result)

    def test_inactive_rule_returns_none(self):
        buyer = make_user('buyer2@test.com', upa_id='UPA002')
        product = make_product(name='Widget2', sku='SKU-002')
        variant = make_variant(product)
        make_commission_rule(product, is_active=False)
        order = make_order(buyer)
        item = make_order_item(order, variant)
        result = create_commission_breakup(item)
        self.assertIsNone(result)


# ── create_commission_breakup basic ──────────────────────────────────────────

class CreateCommissionBreakupTest(TestCase):

    def setUp(self):
        self.buyer = make_user('buyer@test.com', upa_id='UPA001')
        self.parent = make_user('parent@test.com', upa_id='UPA000')
        place_user_in_tree(self.parent, parent_user=None, leg=None, depth=0)
        place_user_in_tree(self.buyer, parent_user=self.parent, leg='L', depth=1)

        self.product = make_product()
        self.variant = make_variant(self.product, price=Decimal('100.00'))
        make_commission_rule(self.product)

        self.order = make_order(self.buyer)
        self.item = make_order_item(self.order, self.variant, upa_price=Decimal('100.00'), qty=1)

    def test_breakup_created(self):
        breakup = create_commission_breakup(self.item)
        self.assertIsNotNone(breakup)
        self.assertIsInstance(breakup, CommissionBreakup)
        self.assertEqual(breakup.order_item, self.item)
        self.assertEqual(breakup.status, 'pending_window')

    def test_base_amount(self):
        breakup = create_commission_breakup(self.item)
        self.assertEqual(breakup.total_base_amount, Decimal('100.00'))

    def test_network_pool(self):
        # 7% of 100 = 7.00
        breakup = create_commission_breakup(self.item)
        self.assertEqual(breakup.network_pool, Decimal('7.00'))

    def test_team_pool(self):
        # 3% of 100 = 3.00
        breakup = create_commission_breakup(self.item)
        self.assertEqual(breakup.team_pool, Decimal('3.00'))

    def test_entries_created(self):
        breakup = create_commission_breakup(self.item)
        self.assertTrue(breakup.entries.exists())

    def test_upline_entry_at_level1(self):
        breakup = create_commission_breakup(self.item)
        upline_entries = breakup.entries.filter(entry_type='network_upline')
        self.assertEqual(upline_entries.count(), 1)
        entry = upline_entries.first()
        self.assertEqual(entry.level, 1)
        self.assertEqual(entry.recipient, self.parent)
        # L1 gets 40% of net_pool (7.00) = 2.80
        self.assertEqual(entry.amount, Decimal('7.00') * Decimal('40') / Decimal('100'))


# ── Upline levels and amounts ─────────────────────────────────────────────────

class UplineLevelsTest(TestCase):

    def setUp(self):
        # Build a chain: root -> l1 -> l2 -> buyer
        self.root = make_user('root@test.com', upa_id='ROOT')
        self.l1   = make_user('l1@test.com', upa_id='L1')
        self.l2   = make_user('l2@test.com', upa_id='L2')
        self.buyer = make_user('buyer@test.com', upa_id='BUYER')

        place_user_in_tree(self.root, parent_user=None, leg=None, depth=0)
        place_user_in_tree(self.l1,   parent_user=self.root,  leg='L', depth=1)
        place_user_in_tree(self.l2,   parent_user=self.l1,    leg='M', depth=2)
        place_user_in_tree(self.buyer, parent_user=self.l2,   leg='R', depth=3)

        self.product = make_product(sku='SKU-CHAIN')
        self.variant = make_variant(self.product, price=Decimal('100.00'))
        make_commission_rule(self.product, net_pct=Decimal('7.00'), max_levels=7)

        self.order = make_order(self.buyer)
        self.item  = make_order_item(self.order, self.variant, upa_price=Decimal('100.00'))

    def test_three_upline_entries(self):
        breakup = create_commission_breakup(self.item)
        upline_entries = breakup.entries.filter(entry_type='network_upline').order_by('level')
        self.assertEqual(upline_entries.count(), 3)

    def test_top_heavy_L1_gets_most(self):
        breakup = create_commission_breakup(self.item)
        upline_entries = breakup.entries.filter(entry_type='network_upline').order_by('level')
        amounts = [e.amount for e in upline_entries]
        # L1 should get more than L2 which should get more than L3 (root)
        self.assertGreater(amounts[0], amounts[1])
        self.assertGreater(amounts[1], amounts[2])

    def test_level_recipients(self):
        breakup = create_commission_breakup(self.item)
        entries_by_level = {e.level: e.recipient for e in breakup.entries.filter(entry_type='network_upline')}
        self.assertEqual(entries_by_level[1], self.l2)
        self.assertEqual(entries_by_level[2], self.l1)
        self.assertEqual(entries_by_level[3], self.root)


# ── bottom_heavy direction ────────────────────────────────────────────────────

class BottomHeavyDirectionTest(TestCase):

    def setUp(self):
        self.root  = make_user('root@bottom.com', upa_id='BROOT')
        self.l1    = make_user('l1@bottom.com',   upa_id='BL1')
        self.buyer = make_user('buyer@bottom.com', upa_id='BBUYER')

        place_user_in_tree(self.root,  parent_user=None,       leg=None, depth=0)
        place_user_in_tree(self.l1,    parent_user=self.root,  leg='L',  depth=1)
        place_user_in_tree(self.buyer, parent_user=self.l1,    leg='M',  depth=2)

        self.product = make_product(name='BProduct', sku='SKU-BH')
        self.variant = make_variant(self.product, price=Decimal('100.00'))
        make_commission_rule(self.product, direction='bottom_heavy',
                             level_percentages=[40, 25, 15, 10, 5, 3, 2])

        self.order = make_order(self.buyer)
        self.item  = make_order_item(self.order, self.variant)

    def test_bottom_heavy_L2_gets_more_than_L1(self):
        """In bottom_heavy mode levels are reversed so deeper = larger % for root."""
        breakup = create_commission_breakup(self.item)
        upline_entries = breakup.entries.filter(entry_type='network_upline').order_by('level')
        amounts = [e.amount for e in upline_entries]
        # Level 1 (l1, direct parent) gets 2% (last after reversal); level 2 (root) gets 3%
        self.assertGreater(amounts[1], amounts[0])


# ── Inactive upline user → status=pending ────────────────────────────────────

class InactiveUplineTest(TestCase):

    def setUp(self):
        self.inactive_parent = make_user('inactive@test.com', upa_id='INACT', is_active=False)
        self.buyer = make_user('buyer@inactive.com', upa_id='IBUYER')

        place_user_in_tree(self.inactive_parent, parent_user=None, leg=None, depth=0)
        place_user_in_tree(self.buyer, parent_user=self.inactive_parent, leg='L', depth=1)

        self.product = make_product(name='InactProd', sku='SKU-INACT')
        self.variant = make_variant(self.product)
        make_commission_rule(self.product)

        self.order = make_order(self.buyer)
        self.item  = make_order_item(self.order, self.variant)

    def test_inactive_upline_entry_status_pending(self):
        breakup = create_commission_breakup(self.item)
        upline = breakup.entries.filter(entry_type='network_upline').first()
        self.assertIsNotNone(upline)
        self.assertEqual(upline.status, 'pending')


# ── Vacant leg → status=vacant, recipient=None ───────────────────────────────

class VacantLegTest(TestCase):

    def setUp(self):
        self.buyer = make_user('buyer@vacant.com', upa_id='VBUYER')
        place_user_in_tree(self.buyer, parent_user=None, leg=None, depth=0)
        # No children added → all legs vacant

        self.product = make_product(name='VacantProd', sku='SKU-VAC')
        self.variant = make_variant(self.product)
        make_commission_rule(self.product)

        self.order = make_order(self.buyer)
        self.item  = make_order_item(self.order, self.variant)

    def test_all_legs_vacant(self):
        breakup = create_commission_breakup(self.item)
        downline = breakup.entries.filter(entry_type='team_downline')
        self.assertEqual(downline.count(), 3)
        for entry in downline:
            self.assertEqual(entry.status, 'vacant')
            self.assertIsNone(entry.recipient)

    def test_vacant_leg_no_recipient(self):
        breakup = create_commission_breakup(self.item)
        entry = breakup.entries.filter(entry_type='team_downline', leg_position='left').first()
        self.assertIsNone(entry.recipient)


# ── process_commission_breakup ────────────────────────────────────────────────

class ProcessCommissionBreakupTest(TestCase):

    def setUp(self):
        self.active_parent = make_user('parent@process.com', upa_id='PPAR')
        self.inactive_user = make_user('inactive@process.com', upa_id='PINACT', is_active=False)
        self.buyer = make_user('buyer@process.com', upa_id='PBUYER')

        place_user_in_tree(self.active_parent, parent_user=None, leg=None, depth=0)
        # Add inactive as child of active_parent in a different leg
        place_user_in_tree(self.inactive_user, parent_user=self.active_parent, leg='M', depth=1)
        place_user_in_tree(self.buyer, parent_user=self.active_parent, leg='L', depth=1)

        self.product = make_product(name='ProcProd', sku='SKU-PROC')
        self.variant = make_variant(self.product, price=Decimal('100.00'))
        # No downline commission for simplicity — only upline
        make_commission_rule(self.product, team_pct=Decimal('0.00'),
                             left_pct=Decimal('0.00'), mid_pct=Decimal('0.00'),
                             right_pct=Decimal('0.00'))

        self.order = make_order(self.buyer)
        self.item  = make_order_item(self.order, self.variant, upa_price=Decimal('100.00'))

    def test_process_credits_active_users(self):
        breakup = create_commission_breakup(self.item)
        # All upline entries for active_parent should be in 'credited' status already
        # Let's manually set one to 'pending' to simulate, then process
        entry = breakup.entries.filter(entry_type='network_upline').first()
        self.assertIsNotNone(entry)

        # Reset to pending to test process
        entry.status = 'pending'
        entry.save()

        process_commission_breakup(breakup)
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'credited')

    def test_process_wallet_balance_increases(self):
        breakup = create_commission_breakup(self.item)
        entry = breakup.entries.filter(entry_type='network_upline').first()
        wallet = self.active_parent.wallet
        initial_balance = wallet.balance

        entry.status = 'pending'
        entry.save()

        process_commission_breakup(breakup)
        wallet.refresh_from_db()
        self.assertGreater(wallet.balance, initial_balance)

    def test_process_inactive_stays_pending(self):
        breakup = create_commission_breakup(self.item)
        entry = breakup.entries.filter(entry_type='network_upline').first()

        # Switch recipient to inactive user
        entry.recipient = self.inactive_user
        entry.status = 'pending'
        entry.save()

        process_commission_breakup(breakup)
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'pending')

    def test_process_breakup_status_completed(self):
        breakup = create_commission_breakup(self.item)
        # Set all non-vacant entries to 'pending'
        breakup.entries.filter(status='credited').update(status='pending')
        process_commission_breakup(breakup)
        breakup.refresh_from_db()
        self.assertIn(breakup.status, ['completed', 'partial'])

    def test_process_breakup_status_partial_when_pending(self):
        breakup = create_commission_breakup(self.item)
        entry = breakup.entries.filter(entry_type='network_upline').first()
        entry.recipient = self.inactive_user
        entry.status = 'pending'
        entry.save()

        process_commission_breakup(breakup)
        breakup.refresh_from_db()
        self.assertEqual(breakup.status, 'partial')

    def test_process_creates_wallet_transaction(self):
        breakup = create_commission_breakup(self.item)
        entry = breakup.entries.filter(entry_type='network_upline').first()
        entry.status = 'pending'
        entry.save()

        process_commission_breakup(breakup)
        entry.refresh_from_db()
        self.assertIsNotNone(entry.wallet_transaction)
        self.assertIsNotNone(entry.credited_at)


# ── credit_pending_entry ──────────────────────────────────────────────────────

class CreditPendingEntryTest(TestCase):

    def setUp(self):
        self.parent = make_user('parent@credit.com', upa_id='CPAR')
        self.buyer  = make_user('buyer@credit.com',  upa_id='CBUYER')

        place_user_in_tree(self.parent, parent_user=None, leg=None, depth=0)
        place_user_in_tree(self.buyer,  parent_user=self.parent, leg='L', depth=1)

        self.product = make_product(name='CreditProd', sku='SKU-CRED')
        self.variant = make_variant(self.product, price=Decimal('100.00'))
        make_commission_rule(self.product, team_pct=Decimal('0.00'),
                             left_pct=Decimal('0.00'), mid_pct=Decimal('0.00'),
                             right_pct=Decimal('0.00'))

        self.order   = make_order(self.buyer)
        self.item    = make_order_item(self.order, self.variant, upa_price=Decimal('100.00'))
        self.breakup = create_commission_breakup(self.item)

    def _get_pending_entry(self):
        entry = self.breakup.entries.filter(entry_type='network_upline').first()
        entry.status = 'pending'
        entry.save()
        return entry

    def test_credit_pending_entry_increases_wallet(self):
        entry = self._get_pending_entry()
        wallet = self.parent.wallet
        initial = wallet.balance
        credit_pending_entry(entry, credited_by=None)
        wallet.refresh_from_db()
        self.assertGreater(wallet.balance, initial)

    def test_credit_pending_entry_changes_status(self):
        entry = self._get_pending_entry()
        credit_pending_entry(entry, credited_by=None)
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'credited')

    def test_credit_pending_entry_creates_transaction(self):
        entry = self._get_pending_entry()
        credit_pending_entry(entry, credited_by=None)
        entry.refresh_from_db()
        self.assertIsNotNone(entry.wallet_transaction)

    def test_credit_non_pending_raises_value_error(self):
        entry = self.breakup.entries.filter(entry_type='network_upline').first()
        # entry.status is 'credited' (active user) — not 'pending'
        entry.status = 'credited'
        entry.save()
        with self.assertRaises(ValueError):
            credit_pending_entry(entry)

    def test_credit_vacant_raises_value_error(self):
        # Vacant entry has status='vacant' which is not 'pending'
        entry = self.breakup.entries.filter(entry_type='team_downline').first()
        if entry:
            entry.status = 'vacant'
            entry.save()
            with self.assertRaises(ValueError):
                credit_pending_entry(entry)

    def test_credit_pending_inactive_recipient_raises_value_error(self):
        entry = self._get_pending_entry()
        self.parent.is_active = False
        self.parent.save()
        with self.assertRaises(ValueError):
            credit_pending_entry(entry)

    def test_credit_updates_breakup_status_to_completed(self):
        entry = self._get_pending_entry()
        self.breakup.status = 'partial'
        self.breakup.save()
        credit_pending_entry(entry, credited_by=None)
        self.breakup.refresh_from_db()
        self.assertEqual(self.breakup.status, 'completed')


# ── Multiple order items produce separate breakups ────────────────────────────

class MultipleItemsTest(TestCase):

    def test_each_item_gets_own_breakup(self):
        buyer = make_user('buyer@multi.com', upa_id='MULTI')
        parent = make_user('parent@multi.com', upa_id='MPAR')
        place_user_in_tree(parent, parent_user=None, leg=None, depth=0)
        place_user_in_tree(buyer,  parent_user=parent, leg='L', depth=1)

        product1 = make_product(name='Prod1', sku='SKU-M1')
        product2 = make_product(name='Prod2', sku='SKU-M2')
        variant1 = make_variant(product1)
        variant2 = make_variant(product2)
        make_commission_rule(product1)
        make_commission_rule(product2)

        order = make_order(buyer)
        item1 = make_order_item(order, variant1)
        item2 = make_order_item(order, variant2)

        breakup1 = create_commission_breakup(item1)
        breakup2 = create_commission_breakup(item2)

        self.assertIsNotNone(breakup1)
        self.assertIsNotNone(breakup2)
        self.assertNotEqual(breakup1.pk, breakup2.pk)
