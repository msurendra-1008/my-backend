from django.db.models import Q
from django.http import FileResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.authentication.permissions import HasPermission, IsAdmin, IsAdminOrEmployee

from .models import IncomingShipment, InspectionSettings
from .serializers import (
    IncomingShipmentDetailSerializer,
    IncomingShipmentListSerializer,
    InspectionReportReadSerializer,
    InspectionReportWriteSerializer,
    InspectionSettingsSerializer,
)
from .utils import update_product_stock


# ── Settings (singleton) ──────────────────────────────────────────────────────

class InspectionSettingsViewSet(viewsets.ViewSet):
    """GET/PATCH a singleton settings object."""

    def get_permissions(self):
        if self.action == 'partial_update':
            return [IsAdmin()]
        return [IsAdminOrEmployee()]

    def retrieve(self, request, pk=None):  # noqa: ARG002
        return Response(InspectionSettingsSerializer(InspectionSettings.get_settings()).data)

    def partial_update(self, request, pk=None):  # noqa: ARG002
        obj = InspectionSettings.get_settings()
        ser = InspectionSettingsSerializer(obj, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        obj.updated_by = request.user
        ser.save()
        return Response(ser.data)


# ── Shipments ─────────────────────────────────────────────────────────────────

class IncomingShipmentViewSet(viewsets.ViewSet):

    def get_permissions(self):
        if self.action == 'submit_report':
            return [HasPermission('inspection.perform')]
        if self.action == 'update_stock':
            return [IsAdmin()]
        return [IsAdminOrEmployee()]

    # ── list ─────────────────────────────────────────────────────────────────

    def list(self, request):
        qs = IncomingShipment.objects.select_related(
            'purchase_order__vendor',
            'purchase_order__product',
        ).prefetch_related('report')

        search = request.query_params.get('search', '').strip()
        status_filter = request.query_params.get('status', '').strip()

        if search:
            qs = qs.filter(
                Q(purchase_order__po_number__icontains=search) |
                Q(purchase_order__vendor__company_name__icontains=search),
            )
        if status_filter:
            qs = qs.filter(status=status_filter)

        serializer = IncomingShipmentListSerializer(qs, many=True, context={'request': request})
        return Response({'results': serializer.data, 'count': qs.count()})

    # ── retrieve ──────────────────────────────────────────────────────────────

    def retrieve(self, request, pk=None):
        try:
            shipment = IncomingShipment.objects.select_related(
                'purchase_order__vendor',
                'purchase_order__product',
            ).get(pk=pk)
        except IncomingShipment.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            IncomingShipmentDetailSerializer(shipment, context={'request': request}).data,
        )

    # ── submit-report ─────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='submit-report')
    def submit_report(self, request, pk=None):
        try:
            shipment = IncomingShipment.objects.select_related('purchase_order').get(pk=pk)
        except IncomingShipment.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if shipment.status != 'awaiting_inspection':
            return Response(
                {'detail': 'Shipment must be "awaiting_inspection".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if hasattr(shipment, 'report'):
            return Response(
                {'detail': 'Inspection report already submitted for this shipment.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = InspectionReportWriteSerializer(
            data=request.data,
            context={'request': request, 'shipment': shipment},
        )
        ser.is_valid(raise_exception=True)
        report = ser.save()
        return Response(
            InspectionReportReadSerializer(report, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    # ── update-stock ──────────────────────────────────────────────────────────

    @action(detail=True, methods=['patch'], url_path='update-stock')
    def update_stock(self, request, pk=None):
        try:
            shipment = IncomingShipment.objects.select_related('purchase_order').get(pk=pk)
        except IncomingShipment.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not hasattr(shipment, 'report'):
            return Response(
                {'detail': 'No inspection report for this shipment.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if shipment.report.stock_updated:
            return Response(
                {'detail': 'Stock already updated for this shipment.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rack = None
        rack_id = request.data.get('rack_id')
        if rack_id:
            try:
                from apps.warehouse.models import Rack
                rack = Rack.objects.get(pk=rack_id, is_active=True)
            except Exception:
                return Response({'detail': 'Invalid rack_id.'}, status=status.HTTP_400_BAD_REQUEST)
        update_product_stock(shipment.report, request.user, rack=rack)
        return Response(
            InspectionReportReadSerializer(shipment.report, context={'request': request}).data,
        )

    # ── debit-note ────────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='debit-note')
    def download_debit_note(self, request, pk=None):
        try:
            shipment = IncomingShipment.objects.select_related('purchase_order').get(pk=pk)
        except IncomingShipment.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not hasattr(shipment, 'report') or not shipment.report.debit_note:
            return Response(
                {'detail': 'No debit note available.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return FileResponse(
            shipment.report.debit_note.open('rb'),
            content_type='application/pdf',
            as_attachment=True,
            filename=f'DN-{shipment.purchase_order.po_number}.pdf',
        )
