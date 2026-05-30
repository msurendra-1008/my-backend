from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.permissions import IsAdmin, IsAdminOrEmployee
from .models import CommissionSettings, ProductCommissionRule, CommissionBreakup, CommissionEntry
from .serializers import (
    CommissionSettingsSerializer,
    ProductCommissionRuleSerializer,
    CommissionBreakupSerializer,
    CommissionEntrySerializer,
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
        expired_qs = CommissionBreakup.objects.filter(
            status='pending_window',
            return_window_expires__lte=now,
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
    serializer_class = CommissionEntrySerializer

    def get_permissions(self):
        return [IsAdminOrEmployee()]

    def get_queryset(self):
        qs = CommissionEntry.objects.select_related(
            'recipient', 'breakup__order_item__order', 'wallet_transaction'
        ).filter(status__in=['pending', 'vacant'])

        entry_type = self.request.query_params.get('entry_type')
        if entry_type:
            qs = qs.filter(entry_type=entry_type)

        entry_status = self.request.query_params.get('status')
        if entry_status:
            qs = qs.filter(status=entry_status)

        return qs

    @action(detail=True, methods=['patch'], url_path='credit')
    def credit(self, request, pk=None):
        entry = self.get_object()
        try:
            credit_pending_entry(entry, credited_by=request.user)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        entry.refresh_from_db()
        return Response(CommissionEntrySerializer(entry).data)

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
        return Response({
            'credited': credited_ids,
            'errors':   errors,
        })

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        from django.db.models import Sum, Count
        from decimal import Decimal

        all_entries = CommissionEntry.objects.all()

        def _agg(qs):
            result = qs.aggregate(count=Count('id'), total=Sum('amount'))
            return {
                'count': result['count'] or 0,
                'total': str(result['total'] or Decimal('0')),
            }

        return Response({
            'pending': _agg(all_entries.filter(status='pending')),
            'vacant':  _agg(all_entries.filter(status='vacant')),
            'credited': _agg(all_entries.filter(status='credited')),
            'total':    _agg(all_entries),
        })
