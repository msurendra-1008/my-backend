import logging
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from apps.company_wallet.models import CompanyWallet, CompanyTransaction, GSTLedgerEntry
from apps.company_wallet.serializers import (
    CompanyWalletSerializer, CompanyTransactionSerializer,
    GSTLedgerEntrySerializer, ManualEntrySerializer,
)

logger = logging.getLogger(__name__)


class _Pagination(PageNumberPagination):
    page_size            = 30
    page_size_query_param = 'page_size'
    max_page_size        = 200


class CompanyWalletViewSet(viewsets.ViewSet):
    permission_classes = [IsAdminUser]

    @action(detail=False, methods=['get'], url_path='overview')
    def overview(self, request):
        wallet = CompanyWallet.get()
        return Response(CompanyWalletSerializer(wallet).data)

    @action(detail=False, methods=['get'], url_path='transactions')
    def transactions(self, request):
        qs = CompanyTransaction.objects.select_related('order', 'order_item__order').all()

        tx_type = request.query_params.get('type')
        if tx_type:
            qs = qs.filter(transaction_type=tx_type)

        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(CompanyTransactionSerializer(page, many=True).data)

    @action(detail=False, methods=['get'], url_path='gst-ledger')
    def gst_ledger(self, request):
        qs = GSTLedgerEntry.objects.select_related('order_item__order').all()

        gst_type = request.query_params.get('type')
        if gst_type:
            qs = qs.filter(gst_type=gst_type)

        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(GSTLedgerEntrySerializer(page, many=True).data)

    @action(detail=False, methods=['post'], url_path='manual-entry')
    def manual_entry(self, request):
        serializer = ManualEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            from apps.company_wallet.utils import record_manual_entry
            record_manual_entry(
                tx_type      = d['tx_type'],
                amount       = d['amount'],
                description  = d['description'],
                triggered_by = request.user,
            )
        except Exception as e:
            logger.error('Manual company wallet entry failed: %s', e)
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        wallet = CompanyWallet.get()
        return Response(CompanyWalletSerializer(wallet).data)

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        from django.db.models import Sum, Count, Q
        from decimal import Decimal

        wallet = CompanyWallet.get()

        agg = CompanyTransaction.objects.aggregate(
            total_in  = Sum('amount', filter=Q(amount__gt=0)),
            total_out = Sum('amount', filter=Q(amount__lt=0)),
            tx_count  = Count('id'),
        )
        gst_agg = GSTLedgerEntry.objects.aggregate(
            collected = Sum('amount', filter=Q(gst_type='collected')),
            paid      = Sum('amount', filter=Q(gst_type='paid')),
        )

        return Response({
            'balance':       str(wallet.balance),
            'total_in':      str(agg['total_in']  or Decimal('0')),
            'total_out':     str(abs(agg['total_out'] or Decimal('0'))),
            'tx_count':      agg['tx_count'],
            'gst_collected': str(gst_agg['collected'] or Decimal('0')),
            'gst_paid':      str(gst_agg['paid']      or Decimal('0')),
        })
