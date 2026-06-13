import calendar
from datetime import timedelta, date

from django.contrib.auth import get_user_model
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

User = get_user_model()


class DashboardStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        period    = request.query_params.get('period', 'month')
        date_from = request.query_params.get('date_from')
        date_to   = request.query_params.get('date_to')

        today = timezone.now().date()

        if date_from and date_to:
            try:
                start = date.fromisoformat(date_from)
                end   = date.fromisoformat(date_to)
            except ValueError:
                start = today.replace(day=1)
                end   = today
        elif period == 'today':
            start = end = today
        elif period == 'week':
            start = today - timedelta(days=7)
            end   = today
        elif period == 'month':
            start = today.replace(day=1)
            end   = today
        elif period == 'year':
            start = today.replace(month=1, day=1)
            end   = today
        else:
            start = today.replace(day=1)
            end   = today

        delta      = max((end - start).days, 1)
        prev_end   = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=delta)

        def pct_change(current, previous):
            try:
                if not previous:
                    return None
                return round((float(current) - float(previous)) / float(previous) * 100, 1)
            except Exception:
                return None

        # ── ORDERS ─────────────────────────────────────────────────────────────
        from apps.orders.models import Order, OrderItem

        orders_qs   = Order.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
        orders_prev = Order.objects.filter(created_at__date__gte=prev_start, created_at__date__lte=prev_end)

        total_orders      = orders_qs.count()
        total_orders_prev = orders_prev.count()
        revenue           = orders_qs.aggregate(t=Sum('amount_payable'))['t'] or 0
        revenue_prev      = orders_prev.aggregate(t=Sum('amount_payable'))['t'] or 0

        upa_orders  = orders_qs.filter(user__role='upa_user')
        reg_orders  = orders_qs.exclude(user__role='upa_user')
        upa_revenue = upa_orders.aggregate(t=Sum('amount_payable'))['t'] or 0
        reg_revenue = reg_orders.aggregate(t=Sum('amount_payable'))['t'] or 0

        offline_orders_qs = orders_qs.filter(is_offline=True)
        online_orders_qs  = orders_qs.filter(is_offline=False)
        offline_count     = offline_orders_qs.count()
        offline_revenue   = offline_orders_qs.aggregate(t=Sum('amount_payable'))['t'] or 0
        online_count      = online_orders_qs.count()
        online_revenue    = online_orders_qs.aggregate(t=Sum('amount_payable'))['t'] or 0

        status_breakdown = {}
        for s in ['pending', 'confirmed', 'packed', 'shipped', 'delivered', 'cancelled']:
            status_breakdown[s] = orders_qs.filter(order_status=s).count()

        # ── UPA USERS ──────────────────────────────────────────────────────────
        total_upa    = User.objects.filter(role='upa_user').count()
        active_upa   = User.objects.filter(role='upa_user', is_active=True).count()
        inactive_upa = User.objects.filter(role='upa_user', is_active=False).count()
        new_upa      = User.objects.filter(
            role='upa_user',
            date_joined__date__gte=start,
            date_joined__date__lte=end,
        ).count()

        try:
            from apps.upa_tree.models import UPATree
            standalone = UPATree.objects.filter(parent_user__isnull=True).count()
        except Exception:
            standalone = 0

        monthly_upa = []
        for i in range(11, -1, -1):
            d = (today.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
            last_day = calendar.monthrange(d.year, d.month)[1]
            m_end    = d.replace(day=last_day)
            count    = User.objects.filter(
                role='upa_user',
                date_joined__date__gte=d,
                date_joined__date__lte=m_end,
            ).count()
            monthly_upa.append({'month': d.strftime('%b %y'), 'count': count})

        total_employees = User.objects.filter(role='employee').count()

        # ── COMMISSIONS ────────────────────────────────────────────────────────
        try:
            from apps.commissions.models import CommissionEntry
            pending_commission_amount = (
                CommissionEntry.objects.filter(status__in=['pending', 'vacant'])
                .aggregate(t=Sum('amount'))['t'] or 0
            )
            pending_commission_count = CommissionEntry.objects.filter(status__in=['pending', 'vacant']).count()
            inactive_count = CommissionEntry.objects.filter(status='pending').count()
            vacant_count   = CommissionEntry.objects.filter(status='vacant').count()
            comm_distributed = (
                CommissionEntry.objects.filter(
                    status='credited',
                    credited_at__date__gte=start,
                    credited_at__date__lte=end,
                ).aggregate(t=Sum('amount'))['t'] or 0
            )

            def comm_by_type(entry_type):
                return CommissionEntry.objects.filter(
                    status='credited', entry_type=entry_type,
                    credited_at__date__gte=start,
                    credited_at__date__lte=end,
                ).aggregate(t=Sum('amount'))['t'] or 0

            comm_breakdown = {
                'network': float(comm_by_type('network_upline')),
                'team':    float(comm_by_type('team_downline')),
                'social':  float(comm_by_type('social_work')),
                'company': float(comm_by_type('company')),
                'self':    float(comm_by_type('self_commission')),
            }
        except Exception:
            pending_commission_amount = 0
            pending_commission_count  = 0
            inactive_count            = 0
            vacant_count              = 0
            comm_distributed          = 0
            comm_breakdown            = {}

        # ── COMPANY WALLET ─────────────────────────────────────────────────────
        wallet_balance = 0
        wallet_in      = 0
        wallet_out     = 0
        gst_pending    = 0
        try:
            from apps.company_wallet.models import CompanyWallet, CompanyTransaction, GSTLedgerEntry
            wallet         = CompanyWallet.get()
            wallet_balance = float(wallet.balance)
            wallet_in  = float(
                CompanyTransaction.objects.filter(
                    amount__gt=0,
                    created_at__date__gte=start,
                    created_at__date__lte=end,
                ).aggregate(t=Sum('amount'))['t'] or 0
            )
            wallet_out = abs(float(
                CompanyTransaction.objects.filter(
                    amount__lt=0,
                    created_at__date__gte=start,
                    created_at__date__lte=end,
                ).aggregate(t=Sum('amount'))['t'] or 0
            ))
            gst_pending = float(
                GSTLedgerEntry.objects.filter(gst_type='collected')
                .aggregate(t=Sum('amount'))['t'] or 0
            )
        except Exception:
            pass

        # ── PRODUCTS ───────────────────────────────────────────────────────────
        total_products  = 0
        no_pricing      = 0
        no_rule         = 0
        low_stock_list  = []
        out_stock_list  = []
        no_pricing_list = []
        no_rule_list    = []
        try:
            from apps.products.models import Product
            total_products = Product.objects.filter(is_published=True).count()
            no_pricing     = Product.objects.filter(is_published=True, pricing_configured=False).count()
            no_rule        = Product.objects.filter(is_published=True).exclude(commission_rule__is_active=True).count()

            for p in Product.objects.filter(is_published=True, pricing_configured=False)[:3]:
                no_pricing_list.append({'id': str(p.id), 'name': p.name, 'type': 'no_pricing'})

            for p in Product.objects.filter(is_published=True).exclude(commission_rule__is_active=True)[:3]:
                no_rule_list.append({'id': str(p.id), 'name': p.name, 'type': 'no_rule'})

            for p in Product.objects.filter(
                is_published=True,
                variants__stock_quantity__gt=0,
                variants__stock_quantity__lte=10,
            ).distinct()[:5]:
                stock = p.variants.aggregate(t=Sum('stock_quantity'))['t'] or 0
                low_stock_list.append({'id': str(p.id), 'name': p.name, 'stock': stock, 'type': 'low_stock'})

            for p in Product.objects.filter(
                is_published=True,
                variants__isnull=False,
            ).filter(
                variants__stock_quantity__lte=0
            ).exclude(
                variants__stock_quantity__gt=0
            ).distinct()[:5]:
                out_stock_list.append({'id': str(p.id), 'name': p.name, 'stock': 0, 'type': 'out_of_stock'})
        except Exception:
            pass

        # ── TOP PRODUCTS ───────────────────────────────────────────────────────
        top_products_list = []
        try:
            top_products = (
                OrderItem.objects.filter(
                    order__created_at__date__gte=start,
                    order__created_at__date__lte=end,
                ).values('product_name')
                .annotate(order_count=Count('id'), revenue=Sum('line_total'))
                .order_by('-order_count')[:5]
            )
            top_products_list = [
                {
                    'product_name': p['product_name'],
                    'order_count':  p['order_count'],
                    'revenue':      float(p['revenue'] or 0),
                }
                for p in top_products
            ]
        except Exception:
            pass

        # ── DAILY REVENUE ──────────────────────────────────────────────────────
        # Use created_at__date= filter per day — avoids TruncDate key-type
        # mismatches that differ across DB backends (PostgreSQL/SQLite/MySQL).
        daily_revenue = []
        try:
            current = start
            count   = 0
            while current <= end and count < 60:
                rev = float(
                    orders_qs.filter(created_at__date=current)
                    .aggregate(t=Sum('amount_payable'))['t'] or 0
                )
                daily_revenue.append({'date': current.strftime('%d %b'), 'revenue': rev})
                current += timedelta(days=1)
                count   += 1
        except Exception:
            pass

        # ── TENDERS ────────────────────────────────────────────────────────────
        open_tenders = 0
        try:
            from apps.tender.models import Tender
            open_tenders = Tender.objects.filter(status='open').count()
        except Exception:
            pass

        # ── RECENT ORDERS ──────────────────────────────────────────────────────
        recent_orders_data = []
        try:
            for o in Order.objects.select_related('user').order_by('-created_at')[:5]:
                recent_orders_data.append({
                    'id':           str(o.id),
                    'order_number': o.order_number,
                    'customer':     o.user.full_name if o.user else '',
                    'total':        float(o.amount_payable),
                    'status':       o.order_status,
                    'order_type':   'upa' if (o.user and o.user.role == 'upa_user') else 'regular',
                    'created_at':   o.created_at.isoformat(),
                })
        except Exception:
            pass

        return Response({
            'period': {
                'label': period,
                'start': start.isoformat(),
                'end':   end.isoformat(),
            },
            'orders': {
                'total':            total_orders,
                'total_change':     pct_change(total_orders, total_orders_prev),
                'revenue':          float(revenue),
                'revenue_change':   pct_change(revenue, revenue_prev),
                'upa_count':        upa_orders.count(),
                'upa_revenue':      float(upa_revenue),
                'regular_count':    reg_orders.count(),
                'regular_revenue':  float(reg_revenue),
                'offline_count':    offline_count,
                'offline_revenue':  float(offline_revenue),
                'online_count':     online_count,
                'online_revenue':   float(online_revenue),
                'status_breakdown': status_breakdown,
            },
            'upa': {
                'total':      total_upa,
                'active':     active_upa,
                'inactive':   inactive_upa,
                'standalone': standalone,
                'new':        new_upa,
                'monthly':    monthly_upa,
            },
            'employees':   {'total': total_employees},
            'commissions': {
                'pending_amount': float(pending_commission_amount),
                'pending_count':  pending_commission_count,
                'inactive_count': inactive_count,
                'vacant_count':   vacant_count,
                'distributed':    float(comm_distributed),
                'breakdown':      comm_breakdown,
            },
            'wallet': {
                'balance':     wallet_balance,
                'period_in':   wallet_in,
                'period_out':  wallet_out,
                'gst_pending': gst_pending,
            },
            'products': {
                'total':      total_products,
                'no_pricing': no_pricing,
                'no_rule':    no_rule,
                'alerts':     low_stock_list + out_stock_list + no_pricing_list + no_rule_list,
            },
            'top_products':  top_products_list,
            'daily_revenue': daily_revenue,
            'recent_orders': recent_orders_data,
            'tenders':       {'open': open_tenders},
            **({
                '_debug': {
                    'period_start':         start.isoformat(),
                    'period_end':           end.isoformat(),
                    'orders_in_period':     total_orders,
                    'revenue_in_period':    float(revenue),
                    'daily_revenue_sample': daily_revenue[:5],
                    'daily_nonzero_days':   sum(1 for d in daily_revenue if d['revenue'] > 0),
                    'recent_order_dates':   [
                        o.created_at.isoformat()
                        for o in Order.objects.order_by('-created_at')[:5]
                    ],
                }
            } if request.query_params.get('debug') == '1' else {}),
        })
