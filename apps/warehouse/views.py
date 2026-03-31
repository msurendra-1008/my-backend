from django.db import transaction
from django.db.models import Q, Sum
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.authentication.permissions import IsAdmin, IsAdminOrEmployee

from .models import Warehouse, Zone, Rack, RackStock, StockMovement, StockTransfer
from .serializers import (
    WarehouseSerializer, ZoneSerializer, RackSerializer,
    RackStockSerializer, StockMovementSerializer,
    StockTransferSerializer, StockTransferCreateSerializer,
    AssignStockSerializer, ManualAdjustSerializer, ProductVariantLiteSerializer,
)
from .utils import assign_stock_to_rack, transfer_stock, sync_variant_stock


class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAdminOrEmployee()]
        return [IsAdmin()]


class ZoneViewSet(viewsets.ModelViewSet):
    serializer_class = ZoneSerializer

    def get_queryset(self):
        qs = Zone.objects.select_related('warehouse').all()
        warehouse_id = self.request.query_params.get('warehouse')
        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)
        return qs

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAdminOrEmployee()]
        return [IsAdmin()]


class RackViewSet(viewsets.ModelViewSet):
    serializer_class = RackSerializer

    def get_queryset(self):
        qs = Rack.objects.select_related('zone__warehouse').all()
        zone_id = self.request.query_params.get('zone')
        warehouse_id = self.request.query_params.get('warehouse')
        if zone_id:
            qs = qs.filter(zone_id=zone_id)
        if warehouse_id:
            qs = qs.filter(zone__warehouse_id=warehouse_id)
        return qs

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAdminOrEmployee()]
        return [IsAdmin()]


class StockViewSet(viewsets.GenericViewSet):
    """
    Stock-level endpoints:
    - GET  /stock/            List all RackStock entries
    - POST /stock/assign/     Inbound stock to a rack
    - POST /stock/adjust/     Manual add/remove with reason
    - POST /stock/transfer/   Transfer between racks
    - GET  /stock/movements/  List StockMovements
    - GET  /stock/transfers/  List StockTransfers
    - GET  /stock/variants/   Search ProductVariants for admin picker
    """
    permission_classes = [IsAdminOrEmployee]

    def get_queryset(self):
        return RackStock.objects.select_related(
            'rack__zone__warehouse', 'variant__product',
        ).all()

    def list(self, request):
        qs = self.get_queryset()
        warehouse_id = request.query_params.get('warehouse')
        zone_id      = request.query_params.get('zone')
        rack_id      = request.query_params.get('rack')
        variant_id   = request.query_params.get('variant')
        search       = request.query_params.get('search', '').strip()

        if warehouse_id:
            qs = qs.filter(rack__zone__warehouse_id=warehouse_id)
        if zone_id:
            qs = qs.filter(rack__zone_id=zone_id)
        if rack_id:
            qs = qs.filter(rack_id=rack_id)
        if variant_id:
            qs = qs.filter(variant_id=variant_id)
        if search:
            qs = qs.filter(variant__product__name__icontains=search)

        serializer = RackStockSerializer(qs, many=True, context={'request': request})
        data = serializer.data
        return Response({'count': len(data), 'results': data, 'next': None, 'previous': None})

    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])
    def assign(self, request):
        ser = AssignStockSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        try:
            rack_stock, capacity_warning = assign_stock_to_rack(
                rack=d['rack'],
                variant=d['variant'],
                quantity=d['quantity'],
                performed_by=request.user,
                reference=d.get('reference', ''),
                notes=d.get('notes', ''),
            )
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                'rack_stock': RackStockSerializer(rack_stock, context={'request': request}).data,
                'capacity_warning': capacity_warning,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])
    def adjust(self, request):
        """
        Manual stock adjustment (add or remove) with a required reason.
        Body: { rack, variant, adjustment_type: 'add'|'remove', quantity, reason }
        """
        ser = ManualAdjustSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        rack     = d['rack']
        variant  = d['variant']
        qty      = d['quantity']
        adj_type = d['adjustment_type']
        reason   = d['reason']

        with transaction.atomic():
            rack_stock, _ = RackStock.objects.select_for_update().get_or_create(
                rack=rack, variant=variant, defaults={'quantity': 0},
            )

            if adj_type == 'remove':
                if rack_stock.quantity < qty:
                    return Response(
                        {'detail': 'Insufficient stock in this rack.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                rack_stock.quantity -= qty
            else:
                # add — enforce capacity hard limit
                if rack.capacity > 0:
                    current_total = (
                        RackStock.objects.filter(rack=rack)
                        .aggregate(total=Sum('quantity'))['total'] or 0
                    )
                    new_total = current_total + qty
                    if new_total > rack.capacity:
                        available = rack.capacity - current_total
                        return Response(
                            {
                                'error': (
                                    f'This rack has a capacity of {rack.capacity} units. '
                                    f'Currently has {current_total} units. '
                                    f'Cannot add {qty} more units. '
                                    f'Available space: {available} units'
                                )
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                rack_stock.quantity += qty

            rack_stock.save(update_fields=['quantity', 'last_updated'])

            StockMovement.objects.create(
                rack=rack,
                variant=variant,
                movement_type='adjustment',
                quantity=qty,
                reference='manual-adjust',
                notes=reason,
                performed_by=request.user,
            )
            sync_variant_stock(variant)
            variant.refresh_from_db()

        return Response({
            'rack_stock': RackStockSerializer(rack_stock, context={'request': request}).data,
            'variant_stock_quantity': variant.stock_quantity,
        })

    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])
    def transfer(self, request):
        ser = StockTransferCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        # Hard-block if destination rack would be over capacity
        to_rack = d['to_rack']
        if to_rack.capacity > 0:
            current_total = (
                RackStock.objects.filter(rack=to_rack)
                .aggregate(total=Sum('quantity'))['total'] or 0
            )
            new_total = current_total + d['quantity']
            if new_total > to_rack.capacity:
                available = to_rack.capacity - current_total
                return Response(
                    {
                        'error': (
                            f'This rack has a capacity of {to_rack.capacity} units. '
                            f'Currently has {current_total} units. '
                            f'Cannot add {d["quantity"]} more units. '
                            f'Available space: {available} units'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            transfer_obj, capacity_warning = transfer_stock(
                from_rack=d['from_rack'],
                to_rack=to_rack,
                variant=d['variant'],
                quantity=d['quantity'],
                performed_by=request.user,
                notes=d.get('notes', ''),
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                'transfer': StockTransferSerializer(transfer_obj).data,
                'capacity_warning': capacity_warning,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['get'], url_path='movements')
    def movements(self, request):
        qs = StockMovement.objects.select_related(
            'rack__zone__warehouse', 'variant__product', 'performed_by',
        ).all()
        warehouse_id  = request.query_params.get('warehouse')
        rack_id       = request.query_params.get('rack')
        variant_id    = request.query_params.get('variant')
        movement_type = request.query_params.get('movement_type')
        search        = request.query_params.get('search', '').strip()

        if warehouse_id:
            qs = qs.filter(rack__zone__warehouse_id=warehouse_id)
        if rack_id:
            qs = qs.filter(rack_id=rack_id)
        if variant_id:
            qs = qs.filter(variant_id=variant_id)
        if movement_type:
            qs = qs.filter(movement_type=movement_type)
        if search:
            qs = qs.filter(variant__product__name__icontains=search)

        serializer = StockMovementSerializer(qs[:200], many=True)
        data = serializer.data
        return Response({'count': len(data), 'results': data, 'next': None, 'previous': None})

    @action(detail=False, methods=['get'], url_path='transfers')
    def transfers(self, request):
        qs = StockTransfer.objects.select_related(
            'from_rack__zone__warehouse', 'to_rack__zone__warehouse',
            'variant__product', 'initiated_by',
        ).all()
        serializer = StockTransferSerializer(qs[:200], many=True)
        data = serializer.data
        return Response({'count': len(data), 'results': data, 'next': None, 'previous': None})

    @action(detail=False, methods=['get'], url_path='variants')
    def variants(self, request):
        """Search ProductVariants for the admin stock-entry picker."""
        from apps.products.models import ProductVariant
        qs = ProductVariant.objects.select_related('product').filter(is_active=True)
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(product__name__icontains=search) | Q(sku__icontains=search)
            )
        serializer = ProductVariantLiteSerializer(qs[:50], many=True)
        return Response(serializer.data)
