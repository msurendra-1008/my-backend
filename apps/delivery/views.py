from django.http import HttpResponse
from rest_framework import status, viewsets, generics, serializers as s
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer

from core.mixins import LoginRequiredMixin
from apps.authentication.permissions import IsAdmin
from apps.orders.models import Order
from .models import DeliveryZone, DeliveryPartner, DeliverySettings, DeliveryAssignment
from .permissions import IsDeliveryPartner
from .serializers import (
    DeliveryZoneSerializer, DeliveryPartnerSerializer,
    DeliverySettingsSerializer, DeliveryAssignmentSerializer,
    PartnerAssignmentSerializer, DutyLogSerializer,
)
from .utils import (
    find_eligible_partners, assign_order_to_partner,
    auto_assign_if_enabled, update_delivery_status,
)
from .duty_utils import toggle_duty, get_monthly_ledger, generate_monthly_report_html


# ── Zones ─────────────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(tags=['Delivery']),
    create=extend_schema(tags=['Delivery']),
    retrieve=extend_schema(tags=['Delivery']),
    update=extend_schema(tags=['Delivery']),
    partial_update=extend_schema(tags=['Delivery']),
    destroy=extend_schema(tags=['Delivery']),
)
class DeliveryZoneViewSet(LoginRequiredMixin, viewsets.ModelViewSet):
    permission_classes = [IsAdmin]
    serializer_class   = DeliveryZoneSerializer
    queryset           = DeliveryZone.objects.all()
    http_method_names  = ['get', 'post', 'patch', 'delete', 'head', 'options']


# ── Partners ──────────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(tags=['Delivery']),
    create=extend_schema(tags=['Delivery']),
    retrieve=extend_schema(tags=['Delivery']),
    partial_update=extend_schema(tags=['Delivery']),
)
class DeliveryPartnerViewSet(LoginRequiredMixin, viewsets.ModelViewSet):
    permission_classes = [IsAdmin]
    serializer_class   = DeliveryPartnerSerializer
    http_method_names  = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        return DeliveryPartner.objects.select_related('user').prefetch_related('zones')

    def perform_create(self, serializer):
        serializer.save()


# ── Settings ──────────────────────────────────────────────────────────────────

class DeliverySettingsView(LoginRequiredMixin, generics.RetrieveUpdateAPIView):
    permission_classes = [IsAdmin]
    serializer_class   = DeliverySettingsSerializer

    def get_object(self):
        return DeliverySettings.get()

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


# ── Admin Assignments ─────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(tags=['Delivery']),
    retrieve=extend_schema(tags=['Delivery']),
)
class DeliveryAssignmentViewSet(LoginRequiredMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAdmin]
    serializer_class   = DeliveryAssignmentSerializer

    def get_queryset(self):
        qs = DeliveryAssignment.objects.select_related(
            'order', 'partner__user',
        ).prefetch_related('logs__created_by')

        status_filter = self.request.query_params.get('status', '')
        if status_filter:
            qs = qs.filter(status=status_filter)

        partner_id = self.request.query_params.get('partner', '')
        if partner_id:
            qs = qs.filter(partner_id=partner_id)

        return qs

    @extend_schema(tags=['Delivery'], summary='Suggest a partner for an order')
    @action(detail=False, methods=['get'], url_path='suggest/(?P<order_id>[^/.]+)')
    def suggest(self, request, order_id=None):
        from .utils import suggest_partner_for_order
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=404)

        partners = find_eligible_partners(order)
        data = DeliveryPartnerSerializer(partners, many=True).data
        return Response({'eligible_partners': data})

    @extend_schema(
        tags=['Delivery'], summary='Manually assign a partner to an order',
        request=inline_serializer('AssignRequest', fields={
            'order_id':   s.UUIDField(),
            'partner_id': s.UUIDField(),
        }),
    )
    @action(detail=False, methods=['post'], url_path='assign')
    def assign(self, request):
        order_id   = request.data.get('order_id')
        partner_id = request.data.get('partner_id')

        if not order_id or not partner_id:
            return Response({'detail': 'order_id and partner_id required.'}, status=400)

        try:
            order   = Order.objects.get(pk=order_id)
            partner = DeliveryPartner.objects.get(pk=partner_id)
        except (Order.DoesNotExist, DeliveryPartner.DoesNotExist) as e:
            return Response({'detail': str(e)}, status=404)

        assignment = assign_order_to_partner(order, partner, assigned_by=request.user)
        return Response(DeliveryAssignmentSerializer(assignment).data)

    @extend_schema(
        tags=['Delivery'], summary='Auto-assign delivery partner for an order',
        request=inline_serializer('AutoAssignRequest', fields={'order_id': s.UUIDField()}),
    )
    @action(detail=False, methods=['post'], url_path='auto-assign')
    def auto_assign(self, request):
        order_id = request.data.get('order_id')
        if not order_id:
            return Response({'detail': 'order_id required.'}, status=400)

        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=404)

        assignment = auto_assign_if_enabled(order, assigned_by=request.user)
        if not assignment:
            return Response({'detail': 'No eligible partner found or auto-assign is disabled.'}, status=400)

        return Response(DeliveryAssignmentSerializer(assignment).data)


# ── Admin: unassigned packed orders ───────────────────────────────────────────

class UnassignedOrdersView(LoginRequiredMixin, generics.ListAPIView):
    """Packed orders that have no active (assigned/picked_up) delivery assignment."""
    permission_classes = [IsAdmin]

    def list(self, request, *args, **kwargs):
        orders = (
            Order.objects
            .filter(order_status='packed')
            .exclude(delivery_assignment__status__in=['assigned', 'picked_up'])
            .prefetch_related('items')
            .order_by('-created_at')
        )
        data = [
            {
                'order_id':        str(o.id),
                'order_number':    o.order_number,
                'customer_name':   o.address_name,
                'address_city':    o.address_city,
                'address_pincode': o.address_pincode,
                'total_amount':    str(o.amount_payable),
                'item_count':      o.items.count(),
                'suggested_partner': None,
            }
            for o in orders
        ]
        return Response(data)


# ── Partner (self) endpoints ──────────────────────────────────────────────────

class PartnerMyAssignmentsView(LoginRequiredMixin, generics.ListAPIView):
    """Delivery partner's own assignment list."""
    permission_classes = [IsDeliveryPartner]
    serializer_class   = PartnerAssignmentSerializer

    def get_queryset(self):
        partner = getattr(self.request.user, 'delivery_partner_profile', None)
        if not partner:
            return DeliveryAssignment.objects.none()

        status_filter = self.request.query_params.get('status', '')
        qs = DeliveryAssignment.objects.filter(partner=partner).select_related('order').prefetch_related('logs')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class PartnerUpdateStatusView(LoginRequiredMixin, generics.UpdateAPIView):
    """Delivery partner updates status of their own assignment."""
    permission_classes = [IsDeliveryPartner]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]
    http_method_names  = ['post', 'head', 'options']

    def get_object(self):
        assignment_id = self.kwargs['pk']
        partner = getattr(self.request.user, 'delivery_partner_profile', None)
        if not partner:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('No delivery partner profile found.')
        try:
            return DeliveryAssignment.objects.get(pk=assignment_id, partner=partner)
        except DeliveryAssignment.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound('Assignment not found.')

    @extend_schema(tags=['Delivery'], summary='Update delivery status')
    def post(self, request, *args, **kwargs):
        assignment     = self.get_object()
        new_status     = request.data.get('status', '')
        notes          = request.data.get('notes', '')
        failure_reason = request.data.get('failure_reason', '')
        proof_image    = request.FILES.get('proof_image')

        allowed = [s for s, _ in DeliveryAssignment.STATUS_CHOICES]
        if new_status not in allowed:
            return Response(
                {'detail': f"status must be one of: {', '.join(allowed)}"},
                status=400,
            )

        if new_status == 'delivered' and assignment.status != 'picked_up':
            return Response({'detail': 'Must pick up before marking delivered.'}, status=400)

        if new_status == 'delivered':
            otp_input = request.data.get('otp_input', '').strip()
            if not otp_input:
                return Response(
                    {'detail': 'OTP is required to confirm delivery.'},
                    status=400,
                )
            if otp_input != assignment.otp:
                return Response(
                    {'detail': 'Incorrect OTP. Please ask the customer for the correct code.'},
                    status=400,
                )

        assignment = update_delivery_status(
            assignment, new_status,
            updated_by=request.user,
            notes=notes,
            proof_image=proof_image,
            failure_reason=failure_reason,
        )
        return Response(PartnerAssignmentSerializer(assignment).data)


# ── Duty: Partner endpoints ────────────────────────────────────────────────────

class PartnerToggleDutyView(APIView):
    """Partner toggles on-duty / off-duty."""
    permission_classes = [IsDeliveryPartner]

    @extend_schema(tags=['Delivery'], summary='Toggle duty status (on/off)')
    def post(self, request):
        partner = getattr(request.user, 'delivery_partner_profile', None)
        if not partner:
            return Response({'detail': 'No delivery partner profile.'}, status=403)

        new_status = request.data.get('status', '')
        try:
            log = toggle_duty(partner, new_status)
        except ValueError as e:
            return Response({'detail': str(e)}, status=400)

        return Response({
            'is_on_duty':      partner.is_on_duty,
            'duty_started_at': partner.duty_started_at,
            'log':             DutyLogSerializer(log).data,
        })


class PartnerDutyStatusView(APIView):
    """Partner checks current duty status."""
    permission_classes = [IsDeliveryPartner]

    @extend_schema(tags=['Delivery'], summary='Get current duty status')
    def get(self, request):
        partner = getattr(request.user, 'delivery_partner_profile', None)
        if not partner:
            return Response({'detail': 'No delivery partner profile.'}, status=403)

        return Response({
            'is_on_duty':      partner.is_on_duty,
            'duty_started_at': partner.duty_started_at,
        })


class PartnerDutyLedgerView(APIView):
    """Partner views their own monthly duty ledger."""
    permission_classes = [IsDeliveryPartner]

    @extend_schema(tags=['Delivery'], summary='Get own monthly duty ledger')
    def get(self, request):
        from django.utils import timezone as tz
        partner = getattr(request.user, 'delivery_partner_profile', None)
        if not partner:
            return Response({'detail': 'No delivery partner profile.'}, status=403)

        today = tz.localdate()
        try:
            year  = int(request.query_params.get('year',  today.year))
            month = int(request.query_params.get('month', today.month))
        except (TypeError, ValueError):
            return Response({'detail': 'year and month must be integers'}, status=400)
        if not (1 <= month <= 12):
            return Response({'detail': 'month must be 1–12'}, status=400)

        return Response(get_monthly_ledger(partner, year, month))


# ── Duty: Admin endpoints ──────────────────────────────────────────────────────

class AdminPartnerDutyLedgerView(APIView):
    """Admin views any partner's monthly duty ledger."""
    permission_classes = [IsAdmin]

    @extend_schema(tags=['Delivery'], summary='Admin: get partner monthly duty ledger')
    def get(self, request, partner_id):
        from django.utils import timezone as tz
        try:
            partner = DeliveryPartner.objects.select_related('user').get(pk=partner_id)
        except DeliveryPartner.DoesNotExist:
            return Response({'detail': 'Partner not found.'}, status=404)

        today = tz.localdate()
        try:
            year  = int(request.query_params.get('year',  today.year))
            month = int(request.query_params.get('month', today.month))
        except (TypeError, ValueError):
            return Response({'detail': 'year and month must be integers'}, status=400)
        if not (1 <= month <= 12):
            return Response({'detail': 'month must be 1–12'}, status=400)

        return Response(get_monthly_ledger(partner, year, month))


class AdminPartnerDutyReportView(APIView):
    """Admin downloads an HTML salary-slip-style duty report for a partner."""
    permission_classes = [IsAdmin]

    @extend_schema(tags=['Delivery'], summary='Admin: get partner duty report (HTML)')
    def get(self, request, partner_id):
        from django.utils import timezone as tz
        try:
            partner = DeliveryPartner.objects.select_related('user').get(pk=partner_id)
        except DeliveryPartner.DoesNotExist:
            return Response({'detail': 'Partner not found.'}, status=404)

        today = tz.localdate()
        try:
            year  = int(request.query_params.get('year',  today.year))
            month = int(request.query_params.get('month', today.month))
        except (TypeError, ValueError):
            return Response({'detail': 'year and month must be integers'}, status=400)
        if not (1 <= month <= 12):
            return Response({'detail': 'month must be 1–12'}, status=400)

        html = generate_monthly_report_html(partner, year, month)
        return HttpResponse(html, content_type='text/html')
