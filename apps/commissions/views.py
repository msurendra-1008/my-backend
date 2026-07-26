from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.permissions import IsAdmin, IsAdminOrEmployee
from .models import (
    CommissionSettings, ProductCommissionRule, VariantCommissionRule,
    CommissionBreakup, CommissionEntry,
)
from .serializers import (
    CommissionSettingsSerializer,
    ProductCommissionRuleSerializer,
    VariantCommissionRuleSerializer,
    CommissionBreakupSerializer,
    CommissionEntrySerializer,
    PendingCommissionSerializer,
)
from .utils import process_commission_breakup, credit_pending_entry


# ── Commission Settings ───────────────────────────────────────────────────────

class CommissionSettingsView(APIView):
    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAdminOrEmployee()]
        return [IsAdmin()]

    def get(self, request):
        obj = CommissionSettings.get()
        return Response(CommissionSettingsSerializer(obj).data)

    def patch(self, request):
        obj = CommissionSettings.get()
        ser = CommissionSettingsSerializer(obj, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save(updated_by=request.user)
        return Response(CommissionSettingsSerializer(CommissionSettings.get()).data)


# ── Product Commission Rules ──────────────────────────────────────────────────

class ProductCommissionRuleViewSet(viewsets.ModelViewSet):
    queryset         = ProductCommissionRule.objects.select_related('product').all()
    serializer_class = ProductCommissionRuleSerializer
    filterset_fields = ['is_active']

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'by_product'):
            return [IsAdminOrEmployee()]
        return [IsAdmin()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'], url_path='by-product')
    def by_product(self, request):
        product_id = request.query_params.get('product_id')
        if not product_id:
            return Response({'detail': 'product_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            rule = ProductCommissionRule.objects.select_related('product').get(product_id=product_id)
        except ProductCommissionRule.DoesNotExist:
            return Response({'detail': 'No commission rule found for this product.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ProductCommissionRuleSerializer(rule).data)

    @action(detail=True, methods=['get'], url_path='variants-status')
    def variants_status(self, request, pk=None):
        """
        Returns all variants of the product with their commission rule status:
        whether they use the product rule (inherited) or have a variant-level override.
        """
        from apps.products.utils import get_upa_price

        product_rule = self.get_object()
        product = product_rule.product
        variants = product.variants.all().order_by('name')

        result = []
        for variant in variants:
            try:
                price_data = get_upa_price(variant)
                upa_price  = float(price_data['upa_price'])
            except Exception:
                upa_price = float(variant.mrp)

            purchase = float(variant.purchase_price or product.purchase_price or 0)
            if product.other_charges_type == 'flat':
                other = float(product.other_charges or 0)
            else:
                other = upa_price * float(product.other_charges or 0) / 100

            variant_profit = round((upa_price + other) - purchase, 2) if purchase else None

            variant_rule_data = None
            has_override      = False
            try:
                vcr = variant.commission_rule
                has_override      = vcr.is_active
                variant_rule_data = VariantCommissionRuleSerializer(vcr).data
            except Exception:
                pass

            result.append({
                'variant_id':     str(variant.id),
                'variant_name':   variant.name,
                'variant_sku':    variant.sku,
                'variant_mrp':    str(variant.mrp),
                'upa_price':      str(round(upa_price, 2)),
                'variant_profit': variant_profit,
                'is_active':      variant.is_active,
                'stock_quantity': variant.stock_quantity,
                'has_override':   has_override,
                'rule':           variant_rule_data,
            })

        return Response(result)


# ── Variant Commission Rules ──────────────────────────────────────────────────

class VariantCommissionRuleViewSet(viewsets.ModelViewSet):
    serializer_class = VariantCommissionRuleSerializer
    filterset_fields = ['is_active', 'variant__product']

    def get_queryset(self):
        qs = VariantCommissionRule.objects.select_related(
            'variant__product',
        ).all()
        product_id = self.request.query_params.get('product_id')
        if product_id:
            qs = qs.filter(variant__product_id=product_id)
        return qs

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'by_variant'):
            return [IsAdminOrEmployee()]
        return [IsAdmin()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'], url_path='by-variant')
    def by_variant(self, request):
        variant_id = request.query_params.get('variant_id')
        if not variant_id:
            return Response({'detail': 'variant_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            rule = VariantCommissionRule.objects.select_related('variant__product').get(variant_id=variant_id)
        except VariantCommissionRule.DoesNotExist:
            return Response({'detail': 'No commission rule found for this variant.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(VariantCommissionRuleSerializer(rule).data)


# ── Commission Breakups ───────────────────────────────────────────────────────

class CommissionBreakupViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CommissionBreakupSerializer

    def get_permissions(self):
        return [IsAdminOrEmployee()]

    def get_queryset(self):
        qs = CommissionBreakup.objects.select_related(
            'order_item__order'
        ).prefetch_related('entries').all()

        order_id = self.request.query_params.get('order_id')
        if order_id:
            qs = qs.filter(order_item__order_id=order_id)

        breakup_status = self.request.query_params.get('status')
        if breakup_status:
            qs = qs.filter(status=breakup_status)

        return qs

    @action(detail=True, methods=['post'], url_path='process')
    def process(self, request, pk=None):
        breakup = self.get_object()
        if breakup.status == 'completed':
            return Response({'detail': 'Already completed.'}, status=status.HTTP_400_BAD_REQUEST)
        process_commission_breakup(breakup, processed_by=request.user)
        breakup.refresh_from_db()
        return Response(CommissionBreakupSerializer(breakup).data)

    @action(detail=False, methods=['post'], url_path='process-all')
    def process_all(self, request):
        now = timezone.now()
        # Statuses that mean a return/exchange decision is still pending —
        # commission must not be credited until admin resolves the request.
        BLOCKING_ITEM_STATUSES = [
            'return_requested', 'return_approved',
            'exchange_requested', 'exchange_approved',
        ]
        expired_qs = CommissionBreakup.objects.filter(
            status__in=['pending_window', 'exchange_hold'],
            return_window_expires__lte=now,
        ).exclude(
            order_item__status__in=BLOCKING_ITEM_STATUSES,
        )
        processed_ids = []
        errors = []
        for breakup in expired_qs:
            try:
                process_commission_breakup(breakup, processed_by=request.user)
                processed_ids.append(str(breakup.id))
            except Exception as e:
                errors.append({'id': str(breakup.id), 'error': str(e)})
        return Response({
            'processed': processed_ids,
            'errors':    errors,
        })


# ── Pending Commission Entries ────────────────────────────────────────────────

class PendingCommissionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PendingCommissionSerializer

    def get_permissions(self):
        return [IsAdminOrEmployee()]

    def get_queryset(self):
        show_ignored = self.request.query_params.get('show_ignored') == 'true'
        base_statuses = ['pending', 'vacant', 'ignored'] if show_ignored else ['pending', 'vacant']

        qs = CommissionEntry.objects.select_related(
            'recipient',
            'breakup__order_item__order__user',
            'wallet_transaction',
        ).filter(status__in=base_statuses)

        entry_type = self.request.query_params.get('entry_type')
        if entry_type:
            qs = qs.filter(entry_type=entry_type)

        entry_status = self.request.query_params.get('status')
        if entry_status:
            qs = qs.filter(status=entry_status)

        search = self.request.query_params.get('search', '').strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(recipient_name__icontains=search)
                | Q(recipient_upa_id__icontains=search)
                | Q(recipient_mobile__icontains=search)
                | Q(breakup__order_item__order__order_number__icontains=search)
            )

        return qs.order_by('-breakup__order_item__order__created_at')

    @action(detail=True, methods=['patch'], url_path='credit')
    def credit(self, request, pk=None):
        entry = self.get_object()

        if entry.status == 'vacant':
            return Response(
                {'error': 'Cannot credit — leg is still vacant.', 'reason': 'vacant_leg'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if entry.status == 'ignored':
            return Response(
                {'error': 'This entry has been ignored.', 'reason': 'ignored'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if entry.status == 'credited':
            return Response(
                {'error': 'Already credited.', 'reason': 'already_credited'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not entry.recipient or not entry.recipient.is_active:
            return Response(
                {'error': 'Cannot credit — user is still inactive.', 'reason': 'user_inactive'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            credit_pending_entry(entry, credited_by=request.user)
            return Response({'status': 'credited'})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['patch'], url_path='ignore')
    def ignore(self, request, pk=None):
        entry = self.get_object()
        if entry.status not in ('pending', 'vacant'):
            return Response(
                {'error': 'Only pending or vacant entries can be ignored.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entry.status = 'ignored'
        entry.save()
        return Response({'status': 'ignored'})

    @action(detail=False, methods=['post'], url_path='credit-bulk')
    def credit_bulk(self, request):
        pending_qs = CommissionEntry.objects.filter(
            status='pending'
        ).select_related('recipient', 'breakup__order_item__order', 'wallet_transaction')
        credited_ids = []
        errors = []
        for entry in pending_qs:
            if entry.recipient and entry.recipient.is_active:
                try:
                    credit_pending_entry(entry, credited_by=request.user)
                    credited_ids.append(str(entry.id))
                except Exception as e:
                    errors.append({'id': str(entry.id), 'error': str(e)})
        return Response({'credited': credited_ids, 'errors': errors})

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        from django.db.models import Sum
        qs = CommissionEntry.objects.all()
        return Response({
            'total_pending_amount': str(
                qs.filter(status__in=['pending', 'vacant'])
                  .aggregate(t=Sum('amount'))['t'] or 0
            ),
            'pending_count':       qs.filter(status='pending').count(),
            'vacant_count':        qs.filter(status='vacant').count(),
            'ignored_count':       qs.filter(status='ignored').count(),
            'inactive_user_count': qs.filter(status='pending').count(),
            'vacant_leg_count':    qs.filter(status='vacant').count(),
        })
