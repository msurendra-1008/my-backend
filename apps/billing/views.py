import logging

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.authentication.permissions import IsAdmin, IsAdminOrEmployee
from .models import DiscountCode, OfflineBill, OfflineReturn
from .serializers import (
    DiscountCodeSerializer, CreateBillSerializer,
    OfflineBillSerializer, ValidateDiscountSerializer,
    OfflineReturnSerializer,
)

logger = logging.getLogger(__name__)


class DiscountCodeViewSet(viewsets.ModelViewSet):
    queryset           = DiscountCode.objects.all().order_by('-created_at')
    serializer_class   = DiscountCodeSerializer
    permission_classes = [IsAdminOrEmployee]

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsAdmin()]
        return [IsAdminOrEmployee()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['post'], url_path='validate')
    def validate_code(self, request):
        ser = ValidateDiscountSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        from apps.billing.utils import validate_discount_code
        discount, code_obj, error = validate_discount_code(
            ser.validated_data['code'],
            ser.validated_data['cart_total'],
        )

        if error:
            return Response({'error': error}, status=400)

        return Response({
            'valid':           True,
            'discount_amount': discount,
            'code':            DiscountCodeSerializer(code_obj).data,
        })


class BillingViewSet(viewsets.ViewSet):
    permission_classes = [IsAdminOrEmployee]

    @action(detail=False, methods=['post'], url_path='create-bill')
    def create_bill(self, request):
        ser = CreateBillSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        from apps.billing.utils import create_offline_bill
        try:
            bill = create_offline_bill(ser.validated_data, request.user)
            return Response(
                OfflineBillSerializer(bill, context={'request': request}).data,
                status=status.HTTP_201_CREATED,
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            logger.error('Bill creation failed: %s', e, exc_info=True)
            return Response(
                {'error': 'Bill creation failed. Please try again.'},
                status=500,
            )

    @action(detail=False, methods=['get'], url_path='bills')
    def list_bills(self, request):
        qs     = OfflineBill.objects.select_related('order', 'billed_by').order_by('-created_at')
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(bill_number__icontains=search) | \
                 qs.filter(order__order_number__icontains=search)
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(
            OfflineBillSerializer(page, many=True, context={'request': request}).data,
        )

    @action(detail=False, methods=['get'], url_path='bills/(?P<bill_number>[^/.]+)')
    def get_bill(self, request, bill_number=None):
        try:
            bill = OfflineBill.objects.select_related('order', 'billed_by').get(
                bill_number=bill_number,
            )
            return Response(OfflineBillSerializer(bill, context={'request': request}).data)
        except OfflineBill.DoesNotExist:
            return Response({'error': 'Bill not found'}, status=404)

    @action(detail=False, methods=['get'], url_path='offline-orders')
    def offline_orders(self, request):
        from apps.orders.models import Order
        from apps.orders.serializers import OrderListSerializer

        qs = Order.objects.filter(is_offline=True).select_related('user').prefetch_related(
            'items', 'offline_bill',
        ).order_by('-created_at')

        search = request.query_params.get('search', '').strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(order_number__icontains=search) |
                Q(offline_bill__bill_number__icontains=search)
            )

        date_from = request.query_params.get('date_from', '')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        date_to = request.query_params.get('date_to', '')
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(
            OrderListSerializer(page, many=True).data
        )

    @action(detail=False, methods=['post'], url_path='returns')
    def create_return(self, request):
        bill_number = request.data.get('bill_number')
        items       = request.data.get('items', [])
        bill_photo  = request.FILES.get('bill_photo')

        if not bill_number:
            return Response({'error': 'bill_number required'}, status=400)

        try:
            bill = OfflineBill.objects.get(bill_number=bill_number)
        except OfflineBill.DoesNotExist:
            return Response({'error': 'Bill not found'}, status=404)

        from django.utils import timezone
        from datetime import timedelta
        if timezone.now() > bill.created_at + timedelta(days=2):
            return Response({
                'error':     'Return period of 2 days expired',
                'bill_date': bill.created_at.isoformat(),
            }, status=400)

        from apps.orders.models import OrderItem
        from decimal import Decimal
        total_refund = Decimal('0')
        for item_data in items:
            try:
                oi  = OrderItem.objects.get(id=item_data['order_item_id'], order=bill.order)
                qty = min(int(item_data['qty']), oi.quantity)
                total_refund += oi.line_total / oi.quantity * qty
            except (OrderItem.DoesNotExist, KeyError, ZeroDivisionError):
                pass

        ret = OfflineReturn.objects.create(
            bill         = bill,
            items        = items,
            total_refund = total_refund,
            bill_photo   = bill_photo,
            submitted_by = request.user,
        )

        return Response(OfflineReturnSerializer(ret).data, status=status.HTTP_201_CREATED)

    @action(
        detail=False, methods=['patch'],
        url_path='returns/(?P<return_id>[^/.]+)/review',
        permission_classes=[IsAdmin],
    )
    def review_return(self, request, return_id=None):
        try:
            ret = OfflineReturn.objects.select_related('bill__order').get(id=return_id)
        except OfflineReturn.DoesNotExist:
            return Response({'error': 'Return not found'}, status=404)

        action_type = request.data.get('action')
        notes       = request.data.get('notes', '')

        if action_type not in ('approve', 'reject'):
            return Response({'error': 'action must be approve or reject'}, status=400)

        from django.db import transaction
        with transaction.atomic():
            ret.status       = 'approved' if action_type == 'approve' else 'rejected'
            ret.review_notes = notes
            ret.reviewed_by  = request.user
            ret.save()

            if action_type == 'approve':
                try:
                    from apps.warehouse.utils import find_suggested_rack, assign_stock_to_rack
                    from apps.orders.models import OrderItem
                    for item_data in ret.items:
                        try:
                            oi  = OrderItem.objects.select_related('variant').get(
                                id=item_data['order_item_id'])
                            qty = int(item_data.get('qty', 0))
                            if qty > 0 and oi.variant:
                                rack = find_suggested_rack(oi.variant)
                                if rack:
                                    assign_stock_to_rack(
                                        rack, oi.variant, qty,
                                        reference=f'Return {ret.id}',
                                    )
                        except Exception as e:
                            logger.error('Restock item failed: %s', e)
                except Exception as e:
                    logger.error('Restock failed: %s', e)

                try:
                    from apps.company_wallet.utils import record_refund_paid
                    first_item = ret.bill.order.items.first()
                    if first_item:
                        record_refund_paid(first_item, ret.total_refund)
                except Exception as e:
                    logger.error('Wallet refund failed: %s', e)

        return Response(OfflineReturnSerializer(ret).data)
