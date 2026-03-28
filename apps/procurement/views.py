from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.authentication.permissions import IsAdmin, IsAdminOrEmployee, IsApprovedVendor
from .models import ProcurementRequirement, PurchaseOrder, VendorResponse
from .serializers import (
    ProcurementRequirementCreateSerializer,
    ProcurementRequirementListSerializer,
    ProcurementRequirementSerializer,
    ProcurementRequirementUpdateSerializer,
    ProcurementRequirementVendorSerializer,
    PurchaseOrderSerializer,
    VendorResponseSerializer,
)
from .utils import generate_po_number


class _Pagination(PageNumberPagination):
    page_size            = 20
    page_size_query_param = 'page_size'
    max_page_size        = 100


# ── Admin: ProcurementRequirementViewSet ─────────────────────────────────────

class ProcurementRequirementViewSet(viewsets.ViewSet):

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAdminOrEmployee()]
        return [IsAdmin()]

    def list(self, request):
        qs = ProcurementRequirement.objects.select_related('vendor', 'product', 'vendor_product')

        search        = request.query_params.get('search', '').strip()
        status_filter = request.query_params.get('status', '').strip()
        vendor_filter = request.query_params.get('vendor', '').strip()
        product_filter = request.query_params.get('product', '').strip()

        if search:
            qs = qs.filter(
                Q(product__name__icontains=search) |
                Q(vendor__company_name__icontains=search)
            )
        if status_filter:
            qs = qs.filter(status=status_filter)
        if vendor_filter:
            qs = qs.filter(vendor_id=vendor_filter)
        if product_filter:
            qs = qs.filter(product_id=product_filter)

        # Stats
        from .models import ProcurementRequirement as PR
        stats = {
            'total':                 PR.objects.count(),
            'sent':                  PR.objects.filter(status='sent').count(),
            'awaiting_confirmation': PR.objects.filter(
                status__in=('vendor_responded', 'negotiating')
            ).count(),
            'po_generated':          PR.objects.filter(status='po_generated').count(),
        }

        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = ProcurementRequirementListSerializer(page, many=True, context={'request': request})
        resp = paginator.get_paginated_response(serializer.data)
        resp.data['stats'] = stats
        return resp

    def create(self, request):
        serializer = ProcurementRequirementCreateSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        req = serializer.save()
        return Response(
            ProcurementRequirementSerializer(req, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    def retrieve(self, request, pk=None):
        try:
            req = ProcurementRequirement.objects.select_related(
                'vendor', 'product', 'vendor_product', 'created_by', 'confirmed_by',
            ).prefetch_related(
                'vendor_response', 'purchase_order',
            ).get(pk=pk)
        except ProcurementRequirement.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ProcurementRequirementSerializer(req, context={'request': request}).data)

    def partial_update(self, request, pk=None):
        try:
            req = ProcurementRequirement.objects.get(pk=pk)
        except ProcurementRequirement.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if req.status != 'draft':
            return Response({'detail': 'Only draft requirements can be edited.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = ProcurementRequirementUpdateSerializer(req, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProcurementRequirementSerializer(req, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='send')
    def send(self, request, pk=None):
        try:
            req = ProcurementRequirement.objects.get(pk=pk)
        except ProcurementRequirement.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if req.status != 'draft':
            return Response({'detail': 'Only draft requirements can be sent.'}, status=status.HTTP_400_BAD_REQUEST)
        req.status  = 'sent'
        req.sent_at = timezone.now()
        req.save(update_fields=['status', 'sent_at'])
        return Response(ProcurementRequirementSerializer(req, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='negotiate')
    def negotiate(self, request, pk=None):
        try:
            req = ProcurementRequirement.objects.get(pk=pk)
        except ProcurementRequirement.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if req.status not in ('vendor_responded', 'negotiating'):
            return Response(
                {'detail': 'Can only negotiate on vendor_responded or negotiating requirements.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        notes = request.data.get('negotiation_notes', '').strip()
        if not notes:
            return Response({'detail': 'negotiation_notes is required.'}, status=status.HTTP_400_BAD_REQUEST)
        req.status            = 'negotiating'
        req.negotiation_notes = notes
        req.save(update_fields=['status', 'negotiation_notes'])
        return Response(ProcurementRequirementSerializer(req, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='confirm')
    def confirm(self, request, pk=None):
        try:
            req = ProcurementRequirement.objects.select_related('vendor', 'product').get(pk=pk)
        except ProcurementRequirement.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if req.status not in ('vendor_responded', 'negotiating'):
            return Response(
                {'detail': 'Requirement must be in vendor_responded or negotiating status.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            vr = req.vendor_response
        except VendorResponse.DoesNotExist:
            return Response({'detail': 'No vendor response exists for this requirement.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            po_number   = generate_po_number()
            total_amount = vr.supply_quantity * vr.price_per_unit
            po = PurchaseOrder.objects.create(
                po_number        = po_number,
                requirement      = req,
                vendor           = req.vendor,
                product          = req.product,
                quantity         = vr.supply_quantity,
                price_per_unit   = vr.price_per_unit,
                total_amount     = total_amount,
                monthly_breakdown = vr.monthly_breakdown,
                dispatch_date    = vr.dispatch_date,
                status           = 'generated',
            )
            req.status       = 'po_generated'
            req.confirmed_at = timezone.now()
            req.confirmed_by = request.user
            req.save(update_fields=['status', 'confirmed_at', 'confirmed_by'])

        return Response(ProcurementRequirementSerializer(req, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='cancel')
    def cancel(self, request, pk=None):
        try:
            req = ProcurementRequirement.objects.get(pk=pk)
        except ProcurementRequirement.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if req.status in ('po_generated', 'cancelled'):
            return Response({'detail': 'Cannot cancel a completed or already cancelled requirement.'}, status=status.HTTP_400_BAD_REQUEST)
        reason = request.data.get('cancellation_reason', '').strip()
        if not reason:
            return Response({'detail': 'cancellation_reason is required.'}, status=status.HTTP_400_BAD_REQUEST)
        req.status              = 'cancelled'
        req.cancellation_reason = reason
        req.cancelled_at        = timezone.now()
        req.save(update_fields=['status', 'cancellation_reason', 'cancelled_at'])
        return Response(ProcurementRequirementSerializer(req, context={'request': request}).data)


# ── Vendor: VendorRequirementViewSet ─────────────────────────────────────────

class VendorRequirementViewSet(viewsets.ViewSet):

    def get_permissions(self):
        return [IsApprovedVendor()]

    def _vendor_profile(self, request):
        return request.user.vendor_profile

    def list(self, request):
        vendor = self._vendor_profile(request)
        qs = ProcurementRequirement.objects.filter(
            vendor=vendor,
            status__in=('sent', 'vendor_responded', 'negotiating', 'po_generated'),
        ).select_related('product', 'vendor_product').prefetch_related('vendor_response')
        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = ProcurementRequirementVendorSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    def retrieve(self, request, pk=None):
        vendor = self._vendor_profile(request)
        try:
            req = ProcurementRequirement.objects.select_related(
                'product', 'vendor_product',
            ).prefetch_related('vendor_response', 'purchase_order').get(pk=pk, vendor=vendor)
        except ProcurementRequirement.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ProcurementRequirementVendorSerializer(req, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='respond')
    def respond(self, request, pk=None):
        vendor = self._vendor_profile(request)
        try:
            req = ProcurementRequirement.objects.get(pk=pk, vendor=vendor)
        except ProcurementRequirement.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if req.status != 'sent':
            return Response({'detail': 'Requirement must be in "sent" status to respond.'}, status=status.HTTP_400_BAD_REQUEST)
        if hasattr(req, 'vendor_response'):
            return Response({'detail': 'Response already submitted. Use update-response instead.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = VendorResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vr = VendorResponse.objects.create(requirement=req, **serializer.validated_data)
        req.status = 'vendor_responded'
        req.save(update_fields=['status'])
        return Response(
            ProcurementRequirementVendorSerializer(req, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['patch'], url_path='update-response')
    def update_response(self, request, pk=None):
        vendor = self._vendor_profile(request)
        try:
            req = ProcurementRequirement.objects.get(pk=pk, vendor=vendor)
        except ProcurementRequirement.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if req.status not in ('vendor_responded', 'negotiating'):
            return Response(
                {'detail': 'Response can only be updated when status is vendor_responded or negotiating.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            vr = req.vendor_response
        except VendorResponse.DoesNotExist:
            return Response({'detail': 'No existing response found.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = VendorResponseSerializer(vr, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for attr, value in serializer.validated_data.items():
            setattr(vr, attr, value)
        vr.update_count += 1
        vr.save()
        # If was negotiating, go back to vendor_responded
        if req.status == 'negotiating':
            req.status = 'vendor_responded'
            req.negotiation_notes = ''
            req.save(update_fields=['status', 'negotiation_notes'])
        return Response(ProcurementRequirementVendorSerializer(req, context={'request': request}).data)


# ── PurchaseOrderViewSet ──────────────────────────────────────────────────────

class PurchaseOrderViewSet(viewsets.ViewSet):

    def get_permissions(self):
        if self.action in ('vendor_list', 'vendor_detail', 'acknowledge', 'mark_dispatched'):
            return [IsApprovedVendor()]
        return [IsAdminOrEmployee()]

    def list(self, request):
        qs = PurchaseOrder.objects.select_related('vendor', 'product')
        vendor_filter  = request.query_params.get('vendor', '').strip()
        status_filter  = request.query_params.get('status', '').strip()
        product_filter = request.query_params.get('product', '').strip()
        search         = request.query_params.get('search', '').strip()

        if vendor_filter:
            qs = qs.filter(vendor_id=vendor_filter)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if product_filter:
            qs = qs.filter(product_id=product_filter)
        if search:
            qs = qs.filter(
                Q(po_number__icontains=search) |
                Q(vendor__company_name__icontains=search) |
                Q(product__name__icontains=search)
            )

        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = PurchaseOrderSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            po = PurchaseOrder.objects.select_related('vendor', 'product').get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(PurchaseOrderSerializer(po, context={'request': request}).data)

    @action(detail=False, methods=['get'], url_path='vendor')
    def vendor_list(self, request):
        vendor = request.user.vendor_profile
        qs = PurchaseOrder.objects.filter(vendor=vendor).select_related('product')
        paginator = _Pagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = PurchaseOrderSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    @action(detail=False, methods=['get'], url_path=r'vendor/(?P<po_pk>[^/.]+)')
    def vendor_detail(self, request, po_pk=None):
        vendor = request.user.vendor_profile
        try:
            po = PurchaseOrder.objects.select_related('product').get(pk=po_pk, vendor=vendor)
        except PurchaseOrder.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(PurchaseOrderSerializer(po, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='acknowledge')
    def acknowledge(self, request, pk=None):
        vendor = request.user.vendor_profile
        try:
            po = PurchaseOrder.objects.get(pk=pk, vendor=vendor)
        except PurchaseOrder.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if po.status != 'generated':
            return Response({'detail': 'PO must be in "generated" status to acknowledge.'}, status=status.HTTP_400_BAD_REQUEST)
        po.status          = 'acknowledged'
        po.acknowledged_at = timezone.now()
        po.save(update_fields=['status', 'acknowledged_at'])
        return Response(PurchaseOrderSerializer(po, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='dispatch')
    def mark_dispatched(self, request, pk=None):
        vendor = request.user.vendor_profile
        try:
            po = PurchaseOrder.objects.get(pk=pk, vendor=vendor)
        except PurchaseOrder.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if po.status != 'acknowledged':
            return Response({'detail': 'PO must be acknowledged before marking as dispatched.'}, status=status.HTTP_400_BAD_REQUEST)
        notes = request.data.get('vendor_notes', '').strip()
        po.status        = 'dispatched'
        po.dispatched_at = timezone.now()
        if notes:
            po.vendor_notes = notes
        po.save(update_fields=['status', 'dispatched_at', 'vendor_notes'])

        # Auto-create incoming shipment for inspection
        from apps.inspection.models import IncomingShipment
        IncomingShipment.objects.get_or_create(
            purchase_order=po,
            defaults={'expected_quantity': po.quantity, 'status': 'awaiting_inspection'},
        )

        return Response(PurchaseOrderSerializer(po, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='admin-status',
            permission_classes=[IsAdminOrEmployee])
    def update_status(self, request, pk=None):
        """Admin updates PO status. PATCH /purchase-orders/{id}/admin-status/"""
        try:
            po = PurchaseOrder.objects.get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        new_status = request.data.get('status', '').strip()
        valid = [s[0] for s in PurchaseOrder._meta.get_field('status').choices]
        if new_status not in valid:
            return Response({'detail': f'Invalid status. Choices: {valid}'}, status=status.HTTP_400_BAD_REQUEST)
        po.status = new_status
        notes = request.data.get('admin_notes', '').strip()
        if notes:
            po.admin_notes = notes
        po.save(update_fields=['status', 'admin_notes'])
        return Response(PurchaseOrderSerializer(po, context={'request': request}).data)
