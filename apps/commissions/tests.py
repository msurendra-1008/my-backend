"""
Tests for Commission Distribution System — product rules + variant-level overrides.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from apps.commissions.models import (
    CommissionSettings,
    CommissionBreakup,
    CommissionEntry,
    ProductCommissionRule,
    VariantCommissionRule,
    DEFAULT_LEVEL_PERCENTAGES,
)
from apps.commissions.utils import (
    get_effective_rule,
    get_level_amounts,
    create_commission_breakup,
    process_commission_breakup,
    credit_pending_entry,
)
from apps.orders.models import Order, OrderItem
from apps.products.models import Category, Product, ProductVariant
from apps.upa_tree.models import UPATree
from apps.wallet.models import Wallet


# ── Test helpers ──────────────────────────────────────────────────────────────

def make_user(email, upa_id=None, is_active=True, mobile=None, role='upa_user'):
    user = User.objects.create_user(
        email=email,
        password='testpass',
        first_name='Test',
        last_name='User',
        is_active=is_active,
        upa_id=upa_id,
        mobile=mobile,
    )
    user.role = role
    user.save()
    Wallet.objects.get_or_create(user=user)
    return user


def make_product(name='Widget', sku='SKU-001', mrp=Decimal('100.00'),
                 purchase_price=None):
    cat, _ = Category.objects.get_or_create(
        name='Test Category', defaults={'slug': 'test-category'},
    )
    return Product.objects.create(
        name=name, sku=sku, mrp=mrp,
        slug=name.lower().replace(' ', '-').replace('/', '-'),
        purchase_price=purchase_price,
    )


def make_variant(product, name='Default', mrp=None, upa_price=Decimal('80.00'),
                 purchase_price=None):
    return ProductVariant.objects.create(
        product=product,
        name=name,
        sku=f'{product.sku}-{name[:4].upper()}',
        mrp=mrp or product.mrp,
        upa_price_override=upa_price,
        stock_quantity=100,
        purchase_price=purchase_price,
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


def make_product_rule(product, net_pct=Decimal('7.00'), team_pct=Decimal('3.00'),
                      direction='direct_first', level_percentages=None,
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


def make_variant_rule(variant, net_pct=Decimal('10.00'), team_pct=Decimal('5.00'),
                      direction='direct_first', level_percentages=None,
                      left_pct=Decimal('40.00'), mid_pct=Decimal('30.00'),
                      right_pct=Decimal('30.00'), max_levels=7, is_active=True):
    if level_percentages is None:
        level_percentages = DEFAULT_LEVEL_PERCENTAGES
    return VariantCommissionRule.objects.create(
        variant=variant,
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


def place_in_tree(user, parent_user=None, leg=None, depth=0):
    return UPATree.objects.create(
        user=user,
        parent_user=parent_user,
        leg=leg,
        depth_level=depth,
    )


# ── CommissionSettings singleton ──────────────────────────────────────────────

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

    def test_defaults(self):
        obj = CommissionSettings.get()
        self.assertEqual(obj.network_commission_pct, Decimal('7.00'))
        self.assertEqual(obj.team_commission_pct, Decimal('3.00'))
        self.assertEqual(obj.level_percentages, DEFAULT_LEVEL_PERCENTAGES)

    def test_singleton_enforced_on_save(self):
        CommissionSettings.get()
        CommissionSettings.get()
        self.assertEqual(CommissionSettings.objects.count(), 1)


# ── get_effective_rule ────────────────────────────────────────────────────────

class GetEffectiveRuleTest(TestCase):

    def setUp(self):
        self.product = make_product(sku='GER-001')
        self.variant = make_variant(self.product)

    def test_no_rules_returns_none(self):
        self.assertIsNone(get_effective_rule(self.product, self.variant))

    def test_product_rule_returned_when_no_variant_rule(self):
        rule = make_product_rule(self.product)
        result = get_effective_rule(self.product, self.variant)
        self.assertEqual(result, rule)
        self.assertEqual(result.rule_source, 'product')

    def test_variant_rule_takes_priority(self):
        make_product_rule(self.product)
        vr = make_variant_rule(self.variant)
        result = get_effective_rule(self.product, self.variant)
        self.assertEqual(result, vr)
        self.assertEqual(result.rule_source, 'variant')

    def test_inactive_variant_rule_falls_back_to_product(self):
        product_rule = make_product_rule(self.product)
        make_variant_rule(self.variant, is_active=False)
        result = get_effective_rule(self.product, self.variant)
        self.assertEqual(result, product_rule)
        self.assertEqual(result.rule_source, 'product')

    def test_inactive_product_rule_returns_none(self):
        make_product_rule(self.product, is_active=False)
        self.assertIsNone(get_effective_rule(self.product, self.variant))

    def test_both_inactive_returns_none(self):
        make_product_rule(self.product, is_active=False)
        make_variant_rule(self.variant, is_active=False)
        self.assertIsNone(get_effective_rule(self.product, self.variant))

    def test_without_variant_arg_skips_variant_check(self):
        product_rule = make_product_rule(self.product)
        make_variant_rule(self.variant)
        result = get_effective_rule(self.product)  # no variant arg
        self.assertEqual(result, product_rule)
        self.assertEqual(result.rule_source, 'product')


# ── get_level_amounts ─────────────────────────────────────────────────────────

class GetLevelAmountsTest(TestCase):

    def _make_rule(self, direction, percentages):
        return type('R', (), {
            'level_percentages': percentages,
            'direction': direction,
            'max_upline_levels': len(percentages),
        })()

    def test_direct_first_preserves_order(self):
        rule = self._make_rule('direct_first', [40, 25, 15, 10, 5, 3, 2])
        amounts = get_level_amounts(100, rule)
        pcts = [p for p, _ in amounts]
        self.assertEqual(pcts, [40, 25, 15, 10, 5, 3, 2])

    def test_ancestor_first_reverses_percentages(self):
        rule = self._make_rule('ancestor_first', [40, 25, 15, 10, 5, 3, 2])
        amounts = get_level_amounts(100, rule)
        pcts = [p for p, _ in amounts]
        self.assertEqual(pcts, [2, 3, 5, 10, 15, 25, 40])

    def test_amounts_computed_correctly(self):
        rule = self._make_rule('direct_first', [40, 60])
        amounts = get_level_amounts(100, rule)
        self.assertAlmostEqual(amounts[0][1], 40.0)
        self.assertAlmostEqual(amounts[1][1], 60.0)

    def test_empty_percentages_falls_back_to_defaults(self):
        rule = type('R', (), {
            'level_percentages': [],
            'direction': 'direct_first',
            'max_upline_levels': 7,
        })()
        amounts = get_level_amounts(100, rule)
        pcts = [p for p, _ in amounts]
        self.assertEqual(pcts, DEFAULT_LEVEL_PERCENTAGES)


# ── create_commission_breakup — basic ─────────────────────────────────────────

class CreateCommissionBreakupBasicTest(TestCase):

    def setUp(self):
        self.buyer  = make_user('buyer@basic.com', upa_id='B001')
        self.parent = make_user('parent@basic.com', upa_id='P001')
        place_in_tree(self.parent)
        place_in_tree(self.buyer, parent_user=self.parent, leg='L', depth=1)

        self.product = make_product(sku='BASIC-001')
        self.variant = make_variant(self.product, upa_price=Decimal('100.00'))
        make_product_rule(self.product)

        self.order = make_order(self.buyer)
        self.item  = make_order_item(self.order, self.variant, upa_price=Decimal('100.00'))

    def test_breakup_created(self):
        b = create_commission_breakup(self.item)
        self.assertIsNotNone(b)
        self.assertIsInstance(b, CommissionBreakup)
        self.assertEqual(b.status, 'pending_window')

    def test_network_pool_7pct_of_profit(self):
        # profit = upa_price (100) + other_charges (0) − purchase_price (0) = 100
        b = create_commission_breakup(self.item)
        self.assertEqual(b.network_pool, Decimal('7.00'))

    def test_team_pool_3pct_of_profit(self):
        b = create_commission_breakup(self.item)
        self.assertEqual(b.team_pool, Decimal('3.00'))

    def test_entries_created(self):
        b = create_commission_breakup(self.item)
        self.assertTrue(b.entries.exists())

    def test_upline_entry_at_L1(self):
        b = create_commission_breakup(self.item)
        entry = b.entries.filter(entry_type='network_upline', level=1).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.recipient, self.parent)
        # L1 = 40% of 7.00 = 2.80
        self.assertAlmostEqual(float(entry.amount), 7.0 * 40 / 100, places=2)

    def test_rule_snapshot_has_rule_source_product(self):
        b = create_commission_breakup(self.item)
        self.assertEqual(b.rule_snapshot.get('rule_source'), 'product')

    def test_no_rule_returns_none(self):
        product2 = make_product(name='No Rule', sku='NR-001')
        variant2 = make_variant(product2)
        order2   = make_order(self.buyer)
        item2    = make_order_item(order2, variant2)
        self.assertIsNone(create_commission_breakup(item2))

    def test_inactive_rule_returns_none(self):
        product3 = make_product(name='Inactive', sku='INACT-001')
        variant3 = make_variant(product3)
        make_product_rule(product3, is_active=False)
        order3 = make_order(self.buyer)
        item3  = make_order_item(order3, variant3)
        self.assertIsNone(create_commission_breakup(item3))

    def test_non_upa_user_returns_none(self):
        admin = make_user('admin@test.com', upa_id='ADM001', role='admin')
        order = make_order(admin)
        item  = make_order_item(order, self.variant)
        self.assertIsNone(create_commission_breakup(item))

    def test_zero_profit_returns_none(self):
        # purchase_price = upa_price → profit = 0
        product4 = make_product(name='ZeroProfit', sku='ZP-001',
                                purchase_price=Decimal('100.00'))
        variant4 = make_variant(product4, upa_price=Decimal('100.00'))
        make_product_rule(product4)
        order4 = make_order(self.buyer)
        item4  = make_order_item(order4, variant4, upa_price=Decimal('100.00'))
        result = create_commission_breakup(item4)
        self.assertIsNone(result)


# ── Variant rule takes priority over product rule ─────────────────────────────

class VariantRulePriorityTest(TestCase):

    def setUp(self):
        self.buyer  = make_user('buyer@vprio.com', upa_id='VP01')
        self.parent = make_user('parent@vprio.com', upa_id='VP00')
        place_in_tree(self.parent)
        place_in_tree(self.buyer, parent_user=self.parent, leg='L', depth=1)

        self.product        = make_product(sku='VPRIO-001')
        self.variant        = make_variant(self.product, upa_price=Decimal('100.00'))
        self.product_rule   = make_product_rule(self.product, net_pct=Decimal('7.00'))
        self.variant_rule   = make_variant_rule(self.variant, net_pct=Decimal('12.00'))

        self.order = make_order(self.buyer)
        self.item  = make_order_item(self.order, self.variant, upa_price=Decimal('100.00'))

    def test_variant_rule_used_for_commission(self):
        b = create_commission_breakup(self.item)
        self.assertIsNotNone(b)
        # 12% of 100 profit = 12.00 (not 7.00 from product rule)
        self.assertEqual(b.network_pool, Decimal('12.00'))

    def test_rule_snapshot_records_variant_source(self):
        b = create_commission_breakup(self.item)
        self.assertEqual(b.rule_snapshot.get('rule_source'), 'variant')
        self.assertEqual(b.rule_snapshot.get('variant_id'), str(self.variant.id))

    def test_rule_snapshot_records_variant_rule_id(self):
        b = create_commission_breakup(self.item)
        self.assertEqual(b.rule_snapshot.get('rule_id'), str(self.variant_rule.id))

    def test_inactive_variant_rule_falls_back_to_product_rule(self):
        self.variant_rule.is_active = False
        self.variant_rule.save()
        b = create_commission_breakup(self.item)
        self.assertIsNotNone(b)
        # Falls back to product rule: 7% of 100 = 7.00
        self.assertEqual(b.network_pool, Decimal('7.00'))
        self.assertEqual(b.rule_snapshot.get('rule_source'), 'product')

    def test_different_variants_get_different_rules(self):
        """One variant has an override, another uses the product rule."""
        variant2 = make_variant(self.product, name='Plain',
                                upa_price=Decimal('100.00'))
        # No variant rule for variant2 → uses product rule (7%)

        order2 = make_order(self.buyer)
        item2  = make_order_item(order2, variant2, upa_price=Decimal('100.00'))

        b1 = create_commission_breakup(self.item)   # variant1 → variant rule 12%
        b2 = create_commission_breakup(item2)        # variant2 → product rule 7%

        self.assertEqual(b1.network_pool, Decimal('12.00'))
        self.assertEqual(b2.network_pool, Decimal('7.00'))
        self.assertEqual(b1.rule_snapshot['rule_source'], 'variant')
        self.assertEqual(b2.rule_snapshot['rule_source'], 'product')


# ── Profit calculation with purchase price ────────────────────────────────────

class ProfitCalculationTest(TestCase):

    def setUp(self):
        self.buyer  = make_user('buyer@profit.com', upa_id='PRF01')
        self.parent = make_user('parent@profit.com', upa_id='PRF00')
        place_in_tree(self.parent)
        place_in_tree(self.buyer, parent_user=self.parent, leg='L', depth=1)

    def test_profit_uses_variant_purchase_price(self):
        product = make_product(sku='VPP-001', purchase_price=Decimal('50.00'))
        variant = make_variant(product, upa_price=Decimal('100.00'),
                               purchase_price=Decimal('60.00'))  # variant overrides
        make_product_rule(product, net_pct=Decimal('10.00'))
        order = make_order(self.buyer)
        item  = make_order_item(order, variant, upa_price=Decimal('100.00'))
        b = create_commission_breakup(item)
        # profit = 100 - 60 = 40; network = 10% of 40 = 4.00
        self.assertEqual(b.network_pool, Decimal('4.00'))
        self.assertEqual(b.rule_snapshot['profit'], 40.0)

    def test_profit_falls_back_to_product_purchase_price(self):
        product = make_product(sku='PPP-001', purchase_price=Decimal('50.00'))
        variant = make_variant(product, upa_price=Decimal('100.00'))  # no variant purchase price
        make_product_rule(product, net_pct=Decimal('10.00'))
        order = make_order(self.buyer)
        item  = make_order_item(order, variant, upa_price=Decimal('100.00'))
        b = create_commission_breakup(item)
        # profit = 100 - 50 = 50; network = 10% of 50 = 5.00
        self.assertEqual(b.network_pool, Decimal('5.00'))
        self.assertEqual(b.rule_snapshot['profit'], 50.0)

    def test_profit_snapshot_values_are_accurate(self):
        product = make_product(sku='PSN-001', purchase_price=Decimal('40.00'))
        variant = make_variant(product, upa_price=Decimal('80.00'))
        make_product_rule(product)
        order = make_order(self.buyer)
        item  = make_order_item(order, variant, upa_price=Decimal('80.00'))
        b = create_commission_breakup(item)
        snap = b.rule_snapshot
        # profit = 80 - 40 = 40
        self.assertEqual(snap['profit'], 40.0)
        self.assertEqual(snap['purchase_total'], 40.0)
        self.assertEqual(snap['upa_price'], 80.0)


# ── Upline chain distribution ─────────────────────────────────────────────────

class UplineChainTest(TestCase):

    def setUp(self):
        self.root  = make_user('root@chain.com',   upa_id='ROOT')
        self.l1    = make_user('l1@chain.com',     upa_id='L1')
        self.l2    = make_user('l2@chain.com',     upa_id='L2')
        self.buyer = make_user('buyer@chain.com',  upa_id='BUY')

        place_in_tree(self.root)
        place_in_tree(self.l1,    parent_user=self.root,  leg='L', depth=1)
        place_in_tree(self.l2,    parent_user=self.l1,    leg='M', depth=2)
        place_in_tree(self.buyer, parent_user=self.l2,    leg='R', depth=3)

        self.product = make_product(sku='CHAIN-001')
        self.variant = make_variant(self.product, upa_price=Decimal('100.00'))
        make_product_rule(self.product, net_pct=Decimal('7.00'), max_levels=7)

        self.order = make_order(self.buyer)
        self.item  = make_order_item(self.order, self.variant, upa_price=Decimal('100.00'))

    def test_three_upline_entries_created(self):
        b = create_commission_breakup(self.item)
        count = b.entries.filter(entry_type='network_upline').count()
        self.assertEqual(count, 3)

    def test_direct_first_L1_gets_most(self):
        b = create_commission_breakup(self.item)
        entries = list(b.entries.filter(entry_type='network_upline').order_by('level'))
        self.assertGreater(entries[0].amount, entries[1].amount)
        self.assertGreater(entries[1].amount, entries[2].amount)

    def test_ancestor_first_top_gets_most(self):
        p = make_product(name='AncestorFirst', sku='ANC-001')
        v = make_variant(p, upa_price=Decimal('100.00'))
        make_product_rule(p, direction='ancestor_first',
                          level_percentages=[40, 25, 15, 10, 5, 3, 2])
        order = make_order(self.buyer)
        item  = make_order_item(order, v, upa_price=Decimal('100.00'))
        b = create_commission_breakup(item)
        entries = list(b.entries.filter(entry_type='network_upline').order_by('level'))
        # ancestor_first → L3 (root) gets more than L2, L1
        self.assertGreater(entries[2].amount, entries[1].amount)
        self.assertGreater(entries[1].amount, entries[0].amount)

    def test_correct_recipients_per_level(self):
        b = create_commission_breakup(self.item)
        by_level = {e.level: e.recipient for e in b.entries.filter(entry_type='network_upline')}
        self.assertEqual(by_level[1], self.l2)   # direct parent of buyer
        self.assertEqual(by_level[2], self.l1)
        self.assertEqual(by_level[3], self.root)


# ── Vacant leg handling ───────────────────────────────────────────────────────

class VacantLegTest(TestCase):

    def setUp(self):
        self.buyer = make_user('buyer@vacant.com', upa_id='VAC01')
        place_in_tree(self.buyer)  # no children → all legs vacant

        self.product = make_product(sku='VAC-001')
        self.variant = make_variant(self.product)
        make_product_rule(self.product)
        self.order = make_order(self.buyer)
        self.item  = make_order_item(self.order, self.variant)

    def test_all_three_legs_created(self):
        b = create_commission_breakup(self.item)
        count = b.entries.filter(entry_type='team_downline').count()
        self.assertEqual(count, 3)

    def test_all_legs_status_vacant(self):
        b = create_commission_breakup(self.item)
        for entry in b.entries.filter(entry_type='team_downline'):
            self.assertEqual(entry.status, 'vacant')
            self.assertIsNone(entry.recipient)


# ── Inactive upline → status=pending ─────────────────────────────────────────

class InactiveUplineTest(TestCase):

    def test_inactive_upline_gets_pending_status(self):
        inactive = make_user('inactive@up.com', upa_id='INACT', is_active=False)
        buyer    = make_user('buyer@up.com',    upa_id='IBUYER')
        place_in_tree(inactive)
        place_in_tree(buyer, parent_user=inactive, leg='L', depth=1)

        product = make_product(sku='INACT-UP')
        variant = make_variant(product)
        make_product_rule(product)
        order = make_order(buyer)
        item  = make_order_item(order, variant)

        b = create_commission_breakup(item)
        entry = b.entries.filter(entry_type='network_upline').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, 'pending')


# ── process_commission_breakup ────────────────────────────────────────────────

class ProcessCommissionBreakupTest(TestCase):

    def setUp(self):
        self.parent = make_user('parent@proc.com', upa_id='PPAR')
        self.buyer  = make_user('buyer@proc.com',  upa_id='PBUY')
        place_in_tree(self.parent)
        place_in_tree(self.buyer, parent_user=self.parent, leg='L', depth=1)

        self.product = make_product(sku='PROC-001')
        self.variant = make_variant(self.product, upa_price=Decimal('100.00'))
        make_product_rule(self.product, team_pct=Decimal('0.00'),
                          left_pct=Decimal('0.00'), mid_pct=Decimal('0.00'),
                          right_pct=Decimal('0.00'))
        self.order   = make_order(self.buyer)
        self.item    = make_order_item(self.order, self.variant, upa_price=Decimal('100.00'))

    def test_pending_window_entry_gets_credited(self):
        b = create_commission_breakup(self.item)
        entry = b.entries.filter(entry_type='network_upline').first()
        self.assertEqual(entry.status, 'pending_window')
        process_commission_breakup(b)
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'credited')

    def test_wallet_balance_increases(self):
        b = create_commission_breakup(self.item)
        wallet = self.parent.wallet
        old_balance = wallet.balance
        process_commission_breakup(b)
        wallet.refresh_from_db()
        self.assertGreater(wallet.balance, old_balance)

    def test_breakup_status_completed(self):
        b = create_commission_breakup(self.item)
        process_commission_breakup(b)
        b.refresh_from_db()
        self.assertIn(b.status, ['completed', 'partial'])

    def test_wallet_transaction_created(self):
        b = create_commission_breakup(self.item)
        entry = b.entries.filter(entry_type='network_upline').first()
        process_commission_breakup(b)
        entry.refresh_from_db()
        self.assertIsNotNone(entry.wallet_transaction)
        self.assertIsNotNone(entry.credited_at)

    def test_inactive_user_stays_pending(self):
        b = create_commission_breakup(self.item)
        entry = b.entries.filter(entry_type='network_upline').first()
        entry.recipient = make_user('inactive2@proc.com', upa_id='PINACT2', is_active=False)
        entry.status = 'pending'
        entry.save()
        process_commission_breakup(b)
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'pending')

    def test_partial_status_when_some_entries_pending(self):
        b = create_commission_breakup(self.item)
        entry = b.entries.filter(entry_type='network_upline').first()
        entry.status = 'pending'
        entry.save()
        process_commission_breakup(b)
        b.refresh_from_db()
        self.assertEqual(b.status, 'partial')


# ── credit_pending_entry ──────────────────────────────────────────────────────

class CreditPendingEntryTest(TestCase):

    def setUp(self):
        self.parent = make_user('parent@cred.com', upa_id='CPAR')
        self.buyer  = make_user('buyer@cred.com',  upa_id='CBUY')
        place_in_tree(self.parent)
        place_in_tree(self.buyer, parent_user=self.parent, leg='L', depth=1)

        self.product = make_product(sku='CRED-001')
        self.variant = make_variant(self.product, upa_price=Decimal('100.00'))
        make_product_rule(self.product, team_pct=Decimal('0.00'),
                          left_pct=Decimal('0.00'), mid_pct=Decimal('0.00'),
                          right_pct=Decimal('0.00'))
        self.order   = make_order(self.buyer)
        self.item    = make_order_item(self.order, self.variant, upa_price=Decimal('100.00'))
        self.breakup = create_commission_breakup(self.item)

    def _pending_entry(self):
        entry = self.breakup.entries.filter(entry_type='network_upline').first()
        entry.status = 'pending'
        entry.save()
        return entry

    def test_credits_entry_and_increases_wallet(self):
        entry = self._pending_entry()
        old = self.parent.wallet.balance
        credit_pending_entry(entry)
        self.parent.wallet.refresh_from_db()
        self.assertGreater(self.parent.wallet.balance, old)

    def test_status_becomes_credited(self):
        entry = self._pending_entry()
        credit_pending_entry(entry)
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'credited')

    def test_transaction_created(self):
        entry = self._pending_entry()
        credit_pending_entry(entry)
        entry.refresh_from_db()
        self.assertIsNotNone(entry.wallet_transaction)

    def test_non_pending_raises(self):
        entry = self.breakup.entries.filter(entry_type='network_upline').first()
        entry.status = 'credited'
        entry.save()
        with self.assertRaises(ValueError):
            credit_pending_entry(entry)

    def test_inactive_recipient_raises(self):
        entry = self._pending_entry()
        self.parent.is_active = False
        self.parent.save()
        with self.assertRaises(ValueError):
            credit_pending_entry(entry)

    def test_breakup_status_updated_to_completed(self):
        entry = self._pending_entry()
        self.breakup.status = 'partial'
        self.breakup.save()
        credit_pending_entry(entry)
        self.breakup.refresh_from_db()
        self.assertEqual(self.breakup.status, 'completed')


# ── Multiple items get independent breakups ───────────────────────────────────

class MultipleItemsTest(TestCase):

    def test_each_item_gets_own_breakup(self):
        parent = make_user('par@multi.com',  upa_id='MPAR')
        buyer  = make_user('buy@multi.com',  upa_id='MBUY')
        place_in_tree(parent)
        place_in_tree(buyer, parent_user=parent, leg='L', depth=1)

        p1 = make_product(name='P1', sku='M-001')
        p2 = make_product(name='P2', sku='M-002')
        v1 = make_variant(p1, upa_price=Decimal('100.00'))
        v2 = make_variant(p2, upa_price=Decimal('100.00'))
        make_product_rule(p1)
        make_product_rule(p2)

        order = make_order(buyer)
        b1 = create_commission_breakup(make_order_item(order, v1))
        b2 = create_commission_breakup(make_order_item(order, v2))

        self.assertIsNotNone(b1)
        self.assertIsNotNone(b2)
        self.assertNotEqual(b1.pk, b2.pk)


# ── VariantCommissionRule model ───────────────────────────────────────────────

class VariantCommissionRuleModelTest(TestCase):

    def setUp(self):
        self.product = make_product(sku='VCR-001')
        self.variant = make_variant(self.product)

    def test_create_variant_rule(self):
        rule = make_variant_rule(self.variant)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.variant, self.variant)
        self.assertEqual(rule.rule_source, 'variant')

    def test_one_to_one_constraint(self):
        make_variant_rule(self.variant)
        with self.assertRaises(Exception):
            make_variant_rule(self.variant)  # duplicate → IntegrityError

    def test_rule_source_property(self):
        rule = make_variant_rule(self.variant)
        self.assertEqual(rule.rule_source, 'variant')

    def test_product_rule_source_property(self):
        rule = make_product_rule(self.product)
        self.assertEqual(rule.rule_source, 'product')

    def test_str_representation(self):
        rule = make_variant_rule(self.variant)
        self.assertIn(self.product.name, str(rule))
        self.assertIn(self.variant.name, str(rule))


# ── API — VariantCommissionRuleViewSet ────────────────────────────────────────

class VariantRuleAPITest(TestCase):

    def setUp(self):
        self.admin   = make_user('admin@api.com', role='admin')
        self.product = make_product(sku='API-001')
        self.variant = make_variant(self.product, upa_price=Decimal('80.00'))
        make_product_rule(self.product)

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_create_variant_rule(self):
        url = '/api/v1/commissions/variant-rules/'
        payload = {
            'variant':               str(self.variant.id),
            'is_active':             True,
            'network_commission_pct': '10.00',
            'team_commission_pct':    '5.00',
            'social_work_pct':        '0.00',
            'company_pct':            '0.00',
            'self_commission_enabled': False,
            'self_commission_pct':    '0.00',
            'delivery_packaging_pct': '0.00',
            'max_upline_levels':      7,
            'use_max_levels':         False,
            'direction':              'direct_first',
            'level_percentages':      DEFAULT_LEVEL_PERCENTAGES,
            'left_leg_pct':           '40.00',
            'middle_leg_pct':         '30.00',
            'right_leg_pct':          '30.00',
        }
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['variant_name'], self.variant.name)
        self.assertEqual(resp.data['network_commission_pct'], '10.00')

    def test_update_variant_rule(self):
        rule = make_variant_rule(self.variant, net_pct=Decimal('10.00'))
        url  = f'/api/v1/commissions/variant-rules/{rule.id}/'
        resp = self.client.patch(url, {'network_commission_pct': '15.00'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['network_commission_pct'], '15.00')

    def test_delete_variant_rule(self):
        rule = make_variant_rule(self.variant)
        url  = f'/api/v1/commissions/variant-rules/{rule.id}/'
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(VariantCommissionRule.objects.filter(id=rule.id).exists())

    def test_by_variant_action(self):
        rule = make_variant_rule(self.variant)
        url  = f'/api/v1/commissions/variant-rules/by-variant/?variant_id={self.variant.id}'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['id'], str(rule.id))

    def test_by_variant_not_found(self):
        url = f'/api/v1/commissions/variant-rules/by-variant/?variant_id={self.variant.id}'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_variants_status_action(self):
        product_rule = ProductCommissionRule.objects.get(product=self.product)
        make_variant_rule(self.variant)
        url = f'/api/v1/commissions/product-rules/{product_rule.id}/variants-status/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)
        self.assertEqual(len(resp.data), 1)
        row = resp.data[0]
        self.assertEqual(row['variant_id'], str(self.variant.id))
        self.assertTrue(row['has_override'])
        self.assertIsNotNone(row['rule'])

    def test_variants_status_no_override(self):
        product_rule = ProductCommissionRule.objects.get(product=self.product)
        url = f'/api/v1/commissions/product-rules/{product_rule.id}/variants-status/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        row = resp.data[0]
        self.assertFalse(row['has_override'])
        self.assertIsNone(row['rule'])

    def test_product_rule_includes_variant_rule_count(self):
        make_variant_rule(self.variant)
        product_rule = ProductCommissionRule.objects.get(product=self.product)
        url = f'/api/v1/commissions/product-rules/{product_rule.id}/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['variant_rule_count'], 1)

    def test_unauthenticated_cannot_create(self):
        self.client.logout()
        url = '/api/v1/commissions/variant-rules/'
        resp = self.client.post(url, {}, format='json')
        self.assertEqual(resp.status_code, 401)


# ── UPA Pricing Accuracy Tests ────────────────────────────────────────────────

class UPAPricingAccuracyTest(TestCase):
    """
    Verifies get_upa_price and _compute_variant_pricing produce correct numbers
    under the full hierarchy: variant override → product override → product discount → global.
    """

    def setUp(self):
        from apps.products.models import UPADiscountSettings
        self.settings = UPADiscountSettings.get()
        self.settings.global_discount_percent = Decimal('10.00')
        self.settings.save()

        self.product = make_product(
            name='Accuracy Widget',
            sku='ACC-001',
            mrp=Decimal('1200.00'),
            purchase_price=Decimal('800.00'),
        )
        self.product.other_charges = Decimal('200.00')
        self.product.other_charges_type = 'flat'
        self.product.gst_percentage = Decimal('5.00')
        self.product.pricing_configured = True
        self.product.save()

    def _make_variant(self, mrp=None, purchase_price=Decimal('800.00'),
                      upa_price_override=None):
        from apps.products.models import ProductVariant
        v = ProductVariant.objects.create(
            product=self.product,
            name='Variant',
            sku='ACC-001-VAR',
            mrp=mrp or self.product.mrp,
            purchase_price=purchase_price,
            upa_price_override=upa_price_override,
            stock_quantity=10,
        )
        return v

    # ── get_upa_price tests ────────────────────────────────────────────────────

    def test_global_discount_applied_when_no_overrides(self):
        """With global=10%, variant MRP 1200 → UPA price = 1080."""
        from apps.products.utils import get_upa_price
        v = self._make_variant()
        result = get_upa_price(v)
        self.assertIsNotNone(result)
        self.assertEqual(result['upa_price'], '1080.00')
        self.assertEqual(result['discount_percent'], '10.00')
        self.assertEqual(result['saving'], '120.00')

    def test_product_discount_override_applied_to_variant(self):
        """Product upa_discount_override=20% must take precedence over global 10%."""
        from apps.products.utils import get_upa_price
        self.product.upa_discount_override = Decimal('20.00')
        self.product.save()
        v = self._make_variant()
        result = get_upa_price(v)
        self.assertIsNotNone(result)
        self.assertEqual(result['upa_price'], '960.00')   # 1200 * 0.80
        self.assertEqual(result['discount_percent'], '20.00')

    def test_variant_price_override_wins_over_product_discount(self):
        """Variant upa_price_override must beat the product-level discount."""
        from apps.products.utils import get_upa_price
        self.product.upa_discount_override = Decimal('20.00')
        self.product.save()
        v = self._make_variant(upa_price_override=Decimal('900.00'))
        result = get_upa_price(v)
        self.assertEqual(result['upa_price'], '900.00')

    def test_product_price_override_applied_to_variant(self):
        """Product upa_price_override propagates to variant (when no variant override)."""
        from apps.products.utils import get_upa_price
        self.product.upa_price_override = Decimal('1000.00')
        self.product.save()
        v = self._make_variant()
        result = get_upa_price(v)
        self.assertEqual(result['upa_price'], '1000.00')

    def test_returns_none_when_mrp_is_none(self):
        """get_upa_price returns None when obj.mrp is None (Product level)."""
        from apps.products.utils import get_upa_price
        no_mrp_product = make_product(name='No MRP Product', sku='NOMRP-001', mrp=None)
        self.assertIsNone(get_upa_price(no_mrp_product))

    # ── _compute_variant_pricing tests ────────────────────────────────────────

    def test_compute_variant_pricing_correct_values(self):
        """Full pricing breakdown with product 10% discount must be accurate."""
        from apps.commissions.serializers import _compute_variant_pricing
        v = self._make_variant()
        p = _compute_variant_pricing(v)
        self.assertIsNotNone(p)
        # MRP 1200, 10% discount → UPA price 1080
        self.assertEqual(p['selling_price'], 1200.0)
        self.assertEqual(p['upa_price'], 1080.0)
        self.assertEqual(p['upa_discount_pct'], 10.0)
        self.assertEqual(p['upa_discount_amt'], 120.0)
        # other_charges = 200 (flat)
        self.assertEqual(p['other_charges'], 200.0)
        # regular_profit = (1200 + 200) - 800 = 600
        self.assertEqual(p['regular_profit'], 600.0)
        # upa_profit = (1080 + 200) - 800 = 480
        self.assertEqual(p['upa_profit'], 480.0)
        # GST = 5% of upa_price = 5% of 1080 = 54
        self.assertAlmostEqual(p['gst_amount'], 54.0, places=2)

    def test_compute_variant_pricing_returns_none_without_purchase_price(self):
        """No purchase price on variant or product → returns None (not configured)."""
        from apps.commissions.serializers import _compute_variant_pricing
        # Clear product-level purchase price too so the fallback chain also yields 0
        self.product.purchase_price = None
        self.product.save()
        v = self._make_variant(purchase_price=None)
        self.assertIsNone(_compute_variant_pricing(v))

    def test_compute_percent_other_charges(self):
        """Percent-based other charges are computed on UPA price, not MRP."""
        from apps.commissions.serializers import _compute_variant_pricing
        self.product.other_charges = Decimal('10.00')   # 10%
        self.product.other_charges_type = 'percent'
        self.product.save()
        v = self._make_variant()
        p = _compute_variant_pricing(v)
        # UPA price = 1080, other = 10% of 1080 = 108
        self.assertAlmostEqual(p['other_charges'], 108.0, places=2)
        self.assertAlmostEqual(p['upa_profit'], (1080 + 108) - 800, places=2)

    # ── Priority 1b: stored variant.upa_price tests ───────────────────────────

    def test_stored_upa_price_used_over_global_discount(self):
        """variant.upa_price (written by set_pricing) beats global discount."""
        from apps.products.utils import get_upa_price
        v = self._make_variant()
        # Simulate set_pricing storing 2% off 1200 = 1176
        v.upa_price = Decimal('1176.00')
        v.save()
        result = get_upa_price(v)
        # global is 10% (would give 1080), stored value is 1176 — must use 1176
        self.assertEqual(result['upa_price'], '1176.00')

    def test_stored_upa_price_used_over_product_discount_override(self):
        """variant.upa_price beats product.upa_discount_override."""
        from apps.products.utils import get_upa_price
        self.product.upa_discount_override = Decimal('20.00')  # would give 960
        self.product.save()
        v = self._make_variant()
        v.upa_price = Decimal('1176.00')
        v.save()
        result = get_upa_price(v)
        self.assertEqual(result['upa_price'], '1176.00')

    def test_upa_price_override_still_beats_stored_upa_price(self):
        """Manual upa_price_override wins over stored upa_price."""
        from apps.products.utils import get_upa_price
        v = self._make_variant(upa_price_override=Decimal('900.00'))
        v.upa_price = Decimal('1176.00')
        v.save()
        result = get_upa_price(v)
        self.assertEqual(result['upa_price'], '900.00')

    def test_compute_variant_pricing_uses_stored_upa_price(self):
        """_compute_variant_pricing produces correct positive upa_profit using stored upa_price."""
        from apps.commissions.serializers import _compute_variant_pricing
        v = self._make_variant()
        # As set_pricing would write: 2% off 1200
        v.upa_price = Decimal('1176.00')
        v.save()
        p = _compute_variant_pricing(v)
        self.assertIsNotNone(p)
        self.assertEqual(p['upa_price'], 1176.0)
        # upa_profit = (1176 + 200) - 800 = 576 — must be positive
        self.assertAlmostEqual(p['upa_profit'], 576.0, places=2)
        self.assertGreater(p['upa_profit'], 0)

    def test_none_upa_price_falls_back_to_global(self):
        """When variant.upa_price is None, global discount is still used as last resort."""
        from apps.products.utils import get_upa_price
        v = self._make_variant()  # upa_price not set → None
        result = get_upa_price(v)
        # global = 10% → 1080
        self.assertEqual(result['upa_price'], '1080.00')


# ── variants-status API Pricing Tests ─────────────────────────────────────────

class VariantsStatusPricingTest(TestCase):
    """
    Verifies that variants-status endpoint returns variant_pricing field
    with correct values, even for variants without an override rule.
    """

    def setUp(self):
        from apps.products.models import UPADiscountSettings
        settings = UPADiscountSettings.get()
        settings.global_discount_percent = Decimal('10.00')
        settings.save()

        self.admin = make_user('vstatus@test.com', role='admin')
        self.product = make_product(name='Status Product', sku='STP-001',
                                    mrp=Decimal('1000.00'),
                                    purchase_price=Decimal('600.00'))
        self.product.other_charges = Decimal('50.00')
        self.product.other_charges_type = 'flat'
        self.product.gst_percentage = Decimal('0.00')
        self.product.pricing_configured = True
        self.product.upa_discount_override = Decimal('15.00')
        self.product.save()

        from apps.products.models import ProductVariant
        self.variant = ProductVariant.objects.create(
            product=self.product, name='V1', sku='STP-001-V1',
            mrp=Decimal('1000.00'), purchase_price=Decimal('600.00'),
            stock_quantity=5,
        )
        self.product_rule = make_product_rule(self.product)

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_variants_status_includes_variant_pricing(self):
        url = f'/api/v1/commissions/product-rules/{self.product_rule.id}/variants-status/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        row = resp.data[0]
        self.assertIn('variant_pricing', row)
        self.assertIsNotNone(row['variant_pricing'])

    def test_variants_status_pricing_uses_product_discount(self):
        """UPA price must use product's 15% discount, not global 10%."""
        url = f'/api/v1/commissions/product-rules/{self.product_rule.id}/variants-status/'
        resp = self.client.get(url)
        row = resp.data[0]
        pricing = row['variant_pricing']
        # 1000 * (1 - 0.15) = 850
        self.assertEqual(pricing['upa_price'], 850.0)
        self.assertEqual(pricing['upa_discount_pct'], 15.0)

    def test_variants_status_upa_profit_is_positive(self):
        """UPA profit must be positive when UPA price > purchase price."""
        url = f'/api/v1/commissions/product-rules/{self.product_rule.id}/variants-status/'
        resp = self.client.get(url)
        pricing = resp.data[0]['variant_pricing']
        # upa_profit = (850 + 50) - 600 = 300
        self.assertEqual(pricing['upa_profit'], 300.0)
        self.assertGreater(pricing['upa_profit'], 0)

    def test_variants_status_pricing_none_without_purchase_price(self):
        """Variant with no purchase price → variant_pricing is null."""
        from apps.products.models import ProductVariant
        v2 = ProductVariant.objects.create(
            product=self.product, name='V2', sku='STP-001-V2',
            mrp=Decimal('1000.00'), purchase_price=None, stock_quantity=0,
        )
        self.product.purchase_price = None
        self.product.save()
        url = f'/api/v1/commissions/product-rules/{self.product_rule.id}/variants-status/'
        resp = self.client.get(url)
        v2_row = next(r for r in resp.data if r['variant_id'] == str(v2.id))
        self.assertIsNone(v2_row['variant_pricing'])
