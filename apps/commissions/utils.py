from decimal import Decimal
from datetime import timedelta
from django.db import transaction
from django.utils import timezone


def get_effective_rule(product):
    """Returns ProductCommissionRule if active, else None."""
    try:
        rule = product.commission_rule
        return rule if rule.is_active else None
    except Exception:
        return None


def get_profit_for_order_item(order_item):
    """
    Calculate actual profit when a UPA user buys this item.
    Profit = (UPA price paid + other charges) - purchase cost
    """
    variant = order_item.variant
    product = variant.product if variant else None

    if not product:
        return None

    # Purchase price: prefer variant-level, fall back to product-level
    purchase_per_unit = float(
        (variant.purchase_price if variant and variant.purchase_price else None)
        or product.purchase_price
        or 0
    )

    # UPA price actually paid per unit (already discounted from MRP)
    upa_per_unit = float(order_item.upa_price)

    # Other charges per unit (shipping/packaging the company keeps)
    if product.other_charges_type == 'flat':
        other_per_unit = float(product.other_charges or 0)
    else:
        other_per_unit = upa_per_unit * float(product.other_charges or 0) / 100

    qty = order_item.quantity
    upa_total      = upa_per_unit      * qty
    purchase_total = purchase_per_unit * qty
    other_total    = other_per_unit    * qty

    profit = (upa_total + other_total) - purchase_total

    return {
        'upa_price':      round(upa_total, 2),
        'purchase_total': round(purchase_total, 2),
        'other_total':    round(other_total, 2),
        'profit':         round(profit, 2),
    }


def get_upline_chain(buyer_user, max_levels, use_max):
    """
    Walk UP from buyer through UPATree.parent_user.
    Returns list: [{'user': user, 'level': 1, ...}, ...] where L1 = direct parent.
    Stops at max_levels unless use_max is False (unlimited).
    """
    from apps.upa_tree.models import UPATree

    chain = []
    current = buyer_user
    level = 1

    while True:
        if not use_max and level > max_levels:
            break

        try:
            node = UPATree.objects.select_related('parent_user').get(user=current)
        except UPATree.DoesNotExist:
            break

        parent = node.parent_user
        if not parent:
            break

        chain.append({
            'user':      parent,
            'level':     level,
            'is_active': parent.is_active,
        })

        current = parent
        level += 1

        if level > 100:  # safety limit
            break

    return chain


def get_downline_legs(buyer_user):
    """
    Get buyer's direct 3 children by leg position.
    UPATree.leg values: 'L'=left, 'M'=middle, 'R'=right.
    Returns: {'left': user|None, 'middle': user|None, 'right': user|None}
    """
    from apps.upa_tree.models import UPATree

    legs = {'left': None, 'middle': None, 'right': None}
    leg_map = {'L': 'left', 'M': 'middle', 'R': 'right'}

    try:
        buyer_node = UPATree.objects.get(user=buyer_user)
        children   = buyer_node.get_children()  # {'L': UPATree|None, 'M': ..., 'R': ...}
        for leg_code, node in children.items():
            if node:
                legs[leg_map[leg_code]] = node.user
    except UPATree.DoesNotExist:
        pass

    return legs


def get_level_amounts(network_pool, rule):
    """
    Returns list of (pct, amount) in L1→LX order.
    direct_first:   percentages[0] → L1 (direct parent gets most)
    ancestor_first: percentages reversed → L1 gets smallest share
    """
    from apps.commissions.models import DEFAULT_LEVEL_PERCENTAGES

    percentages = list(rule.level_percentages or DEFAULT_LEVEL_PERCENTAGES)
    max_lvl = rule.max_upline_levels

    while len(percentages) < max_lvl:
        percentages.append(0)
    percentages = percentages[:max_lvl]

    if rule.direction == 'ancestor_first':
        percentages = list(reversed(percentages))

    return [
        (pct, round(float(network_pool) * pct / 100, 2))
        for pct in percentages
    ]


@transaction.atomic
def create_commission_breakup(order_item):
    """
    Creates CommissionBreakup + CommissionEntry records on order confirm.
    Uses profit (not MRP/sale price) as the commission base.
    Status = pending_window until return window expires.
    """
    from apps.commissions.models import CommissionBreakup, CommissionEntry

    # Only for UPA users
    buyer = order_item.order.user
    if not buyer or getattr(buyer, 'role', None) != 'upa_user':
        return None

    # Need a variant to reach the product
    if not order_item.variant:
        return None

    product = order_item.variant.product
    rule = get_effective_rule(product)
    if not rule:
        return None

    profit_data = get_profit_for_order_item(order_item)
    if not profit_data:
        return None

    profit = profit_data['profit']
    if profit <= 0:
        return None

    # Pool amounts — all based on profit, not sale price
    network_pool = round(profit * float(rule.network_commission_pct) / 100, 2)
    team_pool    = round(profit * float(rule.team_commission_pct)    / 100, 2)
    social_pool  = round(profit * float(rule.social_work_pct)        / 100, 2)
    company_pool = round(profit * float(rule.company_pct)            / 100, 2)

    self_pool    = round(profit * float(rule.self_commission_pct)    / 100, 2) if rule.self_commission_enabled else 0
    delivery_pool = round(profit * float(rule.delivery_packaging_pct) / 100, 2)

    # For offline orders, set return window immediately (2 days from bill date)
    order = order_item.order
    if getattr(order, 'is_offline', False):
        try:
            bill_date = order.offline_bill.created_at
        except Exception:
            bill_date = order.created_at
        _return_window = bill_date + timedelta(days=2)
    else:
        _return_window = None  # set later when order is marked delivered

    breakup = CommissionBreakup.objects.create(
        order_item            = order_item,
        total_base_amount     = profit_data['upa_price'],
        network_pool          = network_pool,
        team_pool             = team_pool,
        status                = 'pending_window',
        return_window_expires = _return_window,
        rule_snapshot         = {
            'rule_id':                  str(rule.id),
            'network_pct':              float(rule.network_commission_pct),
            'team_pct':                 float(rule.team_commission_pct),
            'social_pct':               float(rule.social_work_pct),
            'company_pct':              float(rule.company_pct),
            'self_commission_enabled':  rule.self_commission_enabled,
            'self_pct':                 float(rule.self_commission_pct),
            'delivery_pct':             float(rule.delivery_packaging_pct),
            'direction':                rule.direction,
            'max_upline_levels':        rule.max_upline_levels,
            'use_max_levels':           rule.use_max_levels,
            'level_percentages':        rule.level_percentages,
            'left_leg_pct':             float(rule.left_leg_pct),
            'middle_leg_pct':           float(rule.middle_leg_pct),
            'right_leg_pct':            float(rule.right_leg_pct),
            'profit':                   profit,
            'upa_price':                profit_data['upa_price'],
            'purchase_total':           profit_data['purchase_total'],
            'other_total':              profit_data['other_total'],
        },
    )

    entries = []

    # ── NETWORK: walk upline ──────────────────────────────────────────────────
    upline        = get_upline_chain(buyer, rule.max_upline_levels, rule.use_max_levels)
    level_amounts = get_level_amounts(network_pool, rule)

    for i, person in enumerate(upline):
        if i >= len(level_amounts):
            break
        pct, amount = level_amounts[i]
        if amount <= 0:
            continue
        entries.append(CommissionEntry(
            breakup            = breakup,
            recipient          = person['user'],
            recipient_upa_id   = person['user'].upa_id   or '',
            recipient_name     = person['user'].full_name or '',
            recipient_mobile   = person['user'].mobile   or '',
            entry_type         = 'network_upline',
            level              = person['level'],
            amount             = amount,
            percentage_applied = pct,
            status             = 'pending_window' if person['is_active'] else 'pending',
        ))

    # ── TEAM: buyer's direct legs ─────────────────────────────────────────────
    legs = get_downline_legs(buyer)

    for leg_pos, leg_pct_field in [
        ('left',   rule.left_leg_pct),
        ('middle', rule.middle_leg_pct),
        ('right',  rule.right_leg_pct),
    ]:
        pct    = float(leg_pct_field)
        amount = round(team_pool * pct / 100, 2)
        if amount <= 0:
            continue
        child = legs.get(leg_pos)

        if child:
            entries.append(CommissionEntry(
                breakup            = breakup,
                recipient          = child,
                recipient_upa_id   = child.upa_id   or '',
                recipient_name     = child.full_name or '',
                recipient_mobile   = child.mobile   or '',
                entry_type         = 'team_downline',
                leg_position       = leg_pos,
                amount             = amount,
                percentage_applied = pct,
                status             = 'pending_window' if child.is_active else 'pending',
            ))
        else:
            entries.append(CommissionEntry(
                breakup            = breakup,
                recipient          = None,
                recipient_upa_id   = '',
                recipient_name     = f'{leg_pos.capitalize()} leg (vacant)',
                recipient_mobile   = '',
                entry_type         = 'team_downline',
                leg_position       = leg_pos,
                amount             = amount,
                percentage_applied = pct,
                status             = 'vacant',
            ))

    # ── SELF COMMISSION: credits back to the buyer ────────────────────────────
    if rule.self_commission_enabled and self_pool > 0:
        entries.append(CommissionEntry(
            breakup            = breakup,
            recipient          = buyer,
            recipient_upa_id   = buyer.upa_id   or '',
            recipient_name     = buyer.full_name or '',
            recipient_mobile   = buyer.mobile   or '',
            entry_type         = 'self_commission',
            amount             = self_pool,
            percentage_applied = float(rule.self_commission_pct),
            status             = 'pending_window' if buyer.is_active else 'pending',
        ))

    # ── SOCIAL WORK ───────────────────────────────────────────────────────────
    if social_pool > 0:
        entries.append(CommissionEntry(
            breakup            = breakup,
            recipient          = None,
            recipient_upa_id   = '',
            recipient_name     = 'Social Work Fund',
            recipient_mobile   = '',
            entry_type         = 'social_work',
            amount             = social_pool,
            percentage_applied = float(rule.social_work_pct),
            status             = 'pending_window',
        ))

    # ── COMPANY ───────────────────────────────────────────────────────────────
    if company_pool > 0:
        entries.append(CommissionEntry(
            breakup            = breakup,
            recipient          = None,
            recipient_upa_id   = '',
            recipient_name     = 'Company',
            recipient_mobile   = '',
            entry_type         = 'company',
            amount             = company_pool,
            percentage_applied = float(rule.company_pct),
            status             = 'pending_window',
        ))

    CommissionEntry.objects.bulk_create(entries)
    return breakup


@transaction.atomic
def process_commission_breakup(breakup, processed_by=None):
    """
    Credits all eligible pending_window entries after return window expires.
    Social work and company entries are marked credited without a wallet transaction.
    """
    from apps.wallet.models import Wallet, WalletTransaction
    from apps.commissions.models import CommissionEntry

    product_name = breakup.order_item.product_name
    order_number = breakup.order_item.order.order_number

    for entry in breakup.entries.filter(status='pending_window'):

        # Fund entries — mark credited, no wallet needed
        if entry.entry_type in ('social_work', 'company', 'delivery_packaging'):
            entry.status      = 'credited'
            entry.credited_at = timezone.now()
            entry.save()
            continue

        # User must be present and active
        if not entry.recipient or not entry.recipient.is_active:
            entry.status = 'pending'
            entry.save()
            continue

        try:
            try:
                wallet = entry.recipient.wallet
            except Exception:
                wallet = Wallet.objects.create(user=entry.recipient)

            wallet.balance += Decimal(str(entry.amount))
            wallet.save()

            if entry.entry_type == 'self_commission':
                level_label = 'Self Commission'
            elif entry.level:
                level_label = f'L{entry.level}'
            else:
                level_label = entry.leg_position or entry.entry_type
            tx = WalletTransaction.objects.create(
                wallet       = wallet,
                type         = 'credit',
                amount       = entry.amount,
                reason       = f'Commission — {product_name} · Order {order_number} · {level_label}',
                triggered_by = processed_by,
            )
            entry.wallet_transaction = tx
            entry.status             = 'credited'
            entry.credited_at        = timezone.now()
            entry.save()

            try:
                from apps.company_wallet.utils import record_commission_paid
                record_commission_paid(entry)
            except Exception as _cw_err:
                import logging
                logging.getLogger(__name__).error('CompanyWallet commission_paid failed: %s', _cw_err)

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f'Commission credit failed for entry {entry.id}: {e}')
            entry.status = 'pending'
            entry.save()

    has_pending      = breakup.entries.filter(status='pending').exists()
    breakup.status   = 'partial' if has_pending else 'completed'
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

        wallet.balance += Decimal(str(entry.amount))
        wallet.save()

        product_name = entry.breakup.order_item.product_name
        order_number = entry.breakup.order_item.order.order_number
        level_label  = f'L{entry.level}' if entry.level else entry.leg_position

        tx = WalletTransaction.objects.create(
            wallet       = wallet,
            type         = 'credit',
            amount       = entry.amount,
            reason       = f'Commission (manual) — {product_name} · Order {order_number} · {level_label}',
            triggered_by = credited_by,
        )
        entry.wallet_transaction = tx
        entry.credited_at        = timezone.now()
        entry.status             = 'credited'
        entry.save()

        try:
            from apps.company_wallet.utils import record_commission_paid
            record_commission_paid(entry)
        except Exception as _cw_err:
            import logging
            logging.getLogger(__name__).error('CompanyWallet commission_paid failed: %s', _cw_err)

        breakup = entry.breakup
        if not breakup.entries.filter(status='pending').exists():
            if breakup.status in ('partial', 'pending_window'):
                breakup.status = 'completed'
                breakup.save()
