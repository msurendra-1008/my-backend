from decimal import Decimal
from django.db import transaction
from django.utils import timezone


def get_effective_rule(product):
    """Returns ProductCommissionRule if active, else None."""
    try:
        rule = product.commission_rule
        return rule if rule.is_active else None
    except Exception:
        return None


def get_level_percentages(rule_or_settings):
    """Returns list in correct direction order."""
    from apps.commissions.models import DEFAULT_LEVEL_PERCENTAGES
    levels = list(rule_or_settings.level_percentages or DEFAULT_LEVEL_PERCENTAGES)
    if rule_or_settings.direction == 'bottom_heavy':
        levels = list(reversed(levels))
    return levels


def _get_upline_users(buyer):
    """Walk upline from buyer. Yields (level_num, user) starting at L1."""
    from apps.upa_tree.models import UPATree
    current = buyer
    level_num = 1
    while True:
        try:
            node = UPATree.objects.select_related('parent_user').get(user=current)
        except UPATree.DoesNotExist:
            break
        parent = node.parent_user
        if not parent:
            break
        yield level_num, parent
        current = parent
        level_num += 1


def calculate_commission_entries(order_item):
    """
    Returns (entries_data, net_pool, team_pool, base) or None if no rule applies.
    """
    product = order_item.variant.product
    rule = get_effective_rule(product)
    if not rule:
        return None

    buyer = order_item.order.user
    if not buyer:
        return None

    base      = Decimal(str(order_item.upa_price)) * order_item.quantity
    net_pool  = base * rule.network_commission_pct / Decimal('100')
    team_pool = base * rule.team_commission_pct    / Decimal('100')

    entries = []
    levels  = get_level_percentages(rule)
    max_lvl = None if rule.use_max_levels else rule.max_upline_levels

    # --- UPLINE ---
    for level_num, parent_user in _get_upline_users(buyer):
        if max_lvl and level_num > max_lvl:
            break
        pct = Decimal(str(levels[level_num - 1])) if level_num <= len(levels) else Decimal('0')
        if pct <= 0:
            continue
        amount = net_pool * pct / Decimal('100')
        entries.append({
            'recipient':          parent_user,
            'recipient_upa_id':   parent_user.upa_id or '',
            'recipient_name':     parent_user.full_name,
            'recipient_mobile':   parent_user.mobile or '',
            'entry_type':         'network_upline',
            'level':              level_num,
            'leg_position':       '',
            'amount':             amount,
            'percentage_applied': pct,
            'status':             'credited' if parent_user.is_active else 'pending',
        })

    # --- DOWNLINE (buyer's direct legs) ---
    from apps.upa_tree.models import UPATree
    try:
        buyer_node = UPATree.objects.get(user=buyer)
        children = buyer_node.get_children()
    except UPATree.DoesNotExist:
        children = {'L': None, 'M': None, 'R': None}

    leg_map = [
        ('left',   'L', rule.left_leg_pct),
        ('middle', 'M', rule.middle_leg_pct),
        ('right',  'R', rule.right_leg_pct),
    ]
    for leg_name, leg_key, pct_field in leg_map:
        pct = Decimal(str(pct_field))
        if pct <= 0:
            continue
        amount = team_pool * pct / Decimal('100')
        child_node = children.get(leg_key)
        if child_node:
            child_user = child_node.user
            entries.append({
                'recipient':          child_user,
                'recipient_upa_id':   child_user.upa_id or '',
                'recipient_name':     child_user.full_name,
                'recipient_mobile':   child_user.mobile or '',
                'entry_type':         'team_downline',
                'level':              None,
                'leg_position':       leg_name,
                'amount':             amount,
                'percentage_applied': pct,
                'status':             'credited' if child_user.is_active else 'pending',
            })
        else:
            entries.append({
                'recipient':          None,
                'recipient_upa_id':   '',
                'recipient_name':     f'{leg_name.capitalize()} leg (vacant)',
                'recipient_mobile':   '',
                'entry_type':         'team_downline',
                'level':              None,
                'leg_position':       leg_name,
                'amount':             amount,
                'percentage_applied': pct,
                'status':             'vacant',
            })

    return entries, net_pool, team_pool, base


def create_commission_breakup(order_item):
    """Creates CommissionBreakup + CommissionEntry records. Called on order confirm."""
    from apps.commissions.models import CommissionBreakup, CommissionEntry
    result = calculate_commission_entries(order_item)
    if not result:
        return None
    entries_data, net_pool, team_pool, base = result

    breakup = CommissionBreakup.objects.create(
        order_item        = order_item,
        total_base_amount = base,
        network_pool      = net_pool,
        team_pool         = team_pool,
        status            = 'pending_window',
    )
    for entry in entries_data:
        CommissionEntry.objects.create(breakup=breakup, **entry)
    return breakup


def process_commission_breakup(breakup, processed_by=None):
    """Credits all eligible entries. Leaves inactive as pending."""
    from apps.wallet.models import Wallet, WalletTransaction
    from apps.commissions.models import CommissionEntry

    with transaction.atomic():
        for entry in breakup.entries.filter(status__in=['credited', 'pending']):
            if not entry.recipient or not entry.recipient.is_active:
                entry.status = 'pending'
                entry.save()
                continue
            try:
                wallet = entry.recipient.wallet
            except Exception:
                wallet = Wallet.objects.create(user=entry.recipient)
            wallet.balance += entry.amount
            wallet.save()
            product_name = breakup.order_item.product_name
            order_number = breakup.order_item.order.order_number
            tx = WalletTransaction.objects.create(
                wallet       = wallet,
                type         = 'credit',
                amount       = entry.amount,
                reason       = f'Commission — {product_name} · Order {order_number}',
                triggered_by = processed_by,
            )
            entry.wallet_transaction = tx
            entry.credited_at        = timezone.now()
            entry.status             = 'credited'
            entry.save()

        has_pending = breakup.entries.filter(status='pending').exists()
        breakup.status       = 'partial' if has_pending else 'completed'
        breakup.processed_at = timezone.now()
        breakup.save()


def credit_pending_entry(entry, credited_by=None):
    """Admin manually credits one pending entry."""
    from apps.wallet.models import Wallet, WalletTransaction

    if entry.status != 'pending':
        raise ValueError("Entry is not pending.")
    if not entry.recipient or not entry.recipient.is_active:
        raise ValueError("User is still inactive or not found.")

    with transaction.atomic():
        try:
            wallet = entry.recipient.wallet
        except Exception:
            wallet = Wallet.objects.create(user=entry.recipient)
        wallet.balance += entry.amount
        wallet.save()
        product_name = entry.breakup.order_item.product_name
        order_number = entry.breakup.order_item.order.order_number
        tx = WalletTransaction.objects.create(
            wallet       = wallet,
            type         = 'credit',
            amount       = entry.amount,
            reason       = f'Commission (manual) — {product_name} · Order {order_number}',
            triggered_by = credited_by,
        )
        entry.wallet_transaction = tx
        entry.credited_at        = timezone.now()
        entry.status             = 'credited'
        entry.save()

        # Update breakup status
        breakup = entry.breakup
        if not breakup.entries.filter(status='pending').exists():
            if breakup.status in ('partial', 'pending_window'):
                breakup.status = 'completed'
                breakup.save()
