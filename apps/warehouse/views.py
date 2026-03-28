from django.db import transaction
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.authentication.permissions import IsAdmin, IsAdminOrEmployee

from .models import Warehouse, Zone, Rack, RackStock, StockMovement, StockTransfer
from .serializers import (
    WarehouseSerializer, ZoneSerializer, RackSerializer,
    RackStockSerializer, StockMovementSerializer,
    StockTransferSerializer, StockTransferCreateSerializer,
    AssignStockSerializer, AdjustStockSerializer,
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
    - GET  /stock/           List all RackStock entries
    - POST /stock/assign/    Assign (inbound) stock to a rack
    - POST /stock/adjust/    Set a rack's stock to a new absolute quantity
    - POST /stock/transfer/  Transfer stock between racks
    - GET  /stock/movements/ List StockMovements
    - GET  /stock/transfers/ List StockTransfers
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
        return Response(serializer.data)

    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])
    def assign(self, request):
        ser = AssignStockSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        rack_stock, capacity_warning = assign_stock_to_rack(
            rack=d['rack'],
            variant=d['variant'],
            quantity=d['quantity'],
            performed_by=request.user,
            reference=d.get('reference', ''),
            notes=d.get('notes', ''),
        )
        return Response(
            {
                'rack_stock': RackStockSerializer(rack_stock, context={'request': request}).data,
                'capacity_warning': capacity_warning,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])
    def adjust(self, request):
        ser = AdjustStockSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        with transaction.atomic():
            from .models import RackStock, StockMovement

            rack_stock, _ = RackStock.objects.select_for_update().get_or_create(
                rack=d['rack'], variant=d['variant'], defaults={'quantity': 0},
            )
            old_qty = rack_stock.quantity
            new_qty = d['new_quantity']
            diff = new_qty - old_qty

            rack_stock.quantity = new_qty
            rack_stock.save(update_fields=['quantity', 'last_updated'])

            if diff != 0:
                StockMovement.objects.create(
                    rack=d['rack'],
                    variant=d['variant'],
                    movement_type='adjustment',
                    quantity=abs(diff),
                    notes=d.get('notes', f'Adjusted from {old_qty} to {new_qty}'),
                    performed_by=request.user,
                )
                sync_variant_stock(d['variant'])

        return Response(RackStockSerializer(rack_stock, context={'request': request}).data)

    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])
    def transfer(self, request):
        ser = StockTransferCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        try:
            transfer_obj, capacity_warning = transfer_stock(
                from_rack=d['from_rack'],
                to_rack=d['to_rack'],
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
        warehouse_id   = request.query_params.get('warehouse')
        rack_id        = request.query_params.get('rack')
        variant_id     = request.query_params.get('variant')
        movement_type  = request.query_params.get('movement_type')
        search         = request.query_params.get('search', '').strip()

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
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='transfers')
    def transfers(self, request):
        qs = StockTransfer.objects.select_related(
            'from_rack__zone__warehouse', 'to_rack__zone__warehouse',
            'variant__product', 'initiated_by',
        ).all()
        serializer = StockTransferSerializer(qs[:200], many=True)
        return Response(serializer.data)
