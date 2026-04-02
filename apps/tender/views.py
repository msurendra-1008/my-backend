from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db import transaction

from apps.authentication.permissions import (
    IsAdmin, IsAdminOrEmployee, IsApprovedVendor)
from .models import Tender, TenderItem, VendorBid, VendorBidItem, NegotiationLog
from .serializers import (
    TenderListSerializer, TenderDetailSerializer,
    TenderDetailVendorSerializer, TenderCreateSerializer,
    VendorBidWriteSerializer, VendorBidSerializer,
    BidComparisonSerializer, AwardTenderSerializer)
from .utils import (
    check_and_close_expired_tenders, finalize_tender_award)


class TenderViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrEmployee]

    def get_queryset(self):
        check_and_close_expired_tenders()
        qs = Tender.objects.prefetch_related('items', 'bids').all()
        status_filter = self.request.query_params.get('status')
        search        = self.request.query_params.get('search')
        if status_filter:
            qs = qs.filter(status=status_filter)
        if search:
            qs = qs.filter(title__icontains=search) | \
                 qs.filter(tender_number__icontains=search)
        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action in ('list',):
            return TenderListSerializer
        if self.action in ('create',):
            return TenderCreateSerializer
        return TenderDetailSerializer

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update',
                           'destroy', 'open', 'close', 'award',
                           'cancel', 'negotiate'):
            return [IsAdmin()]
        return [IsAdminOrEmployee()]

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['patch'])
    def open(self, request, pk=None):
        tender = self.get_object()
        if tender.status != 'draft':
            return Response({'error': 'Only draft tenders can be opened.'},
                            status=400)
        tender.status = 'open'
        tender.save()
        return Response(TenderDetailSerializer(
            tender, context={'request': request}).data)

    @action(detail=True, methods=['patch'])
    def close(self, request, pk=None):
        tender = self.get_object()
        if tender.status != 'open':
            return Response({'error': 'Only open tenders can be closed.'},
                            status=400)
        tender.status    = 'closed'
        tender.closed_at = timezone.now()
        tender.closed_by = request.user
        tender.save()
        return Response(TenderDetailSerializer(
            tender, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def award(self, request, pk=None):
        tender = self.get_object()
        if tender.status != 'closed':
            return Response({'error': 'Only closed tenders can be awarded.'},
                            status=400)
        serializer = AwardTenderSerializer(
            data=request.data, context={'tender': tender, 'request': request})
        serializer.is_valid(raise_exception=True)
        pos = finalize_tender_award(
            tender, serializer.validated_data['awarded_items'],
            request.user)
        return Response({
            'message': f'Tender awarded. {len(pos)} PO(s) generated.',
            'po_numbers': [po.po_number for po in pos]
        })

    @action(detail=True, methods=['patch'])
    def cancel(self, request, pk=None):
        tender = self.get_object()
        if tender.status in ('awarded', 'cancelled'):
            return Response({'error': 'Cannot cancel this tender.'}, status=400)
        reason = request.data.get('reason', '')
        tender.status              = 'cancelled'
        tender.cancellation_reason = reason
        tender.save()
        return Response({'status': 'cancelled'})

    @action(detail=True, methods=['patch'],
            url_path='bids/(?P<bid_id>[^/.]+)/negotiate')
    def negotiate(self, request, pk=None, bid_id=None):
        tender = self.get_object()
        notes  = request.data.get('negotiation_notes', '').strip()
        if not notes:
            return Response({'error': 'negotiation_notes required.'}, status=400)
        try:
            bid = tender.bids.get(id=bid_id)
        except VendorBid.DoesNotExist:
            return Response({'error': 'Bid not found.'}, status=404)
        bid.negotiation_notes = notes
        bid.status            = 'under_negotiation'
        bid.save()
        NegotiationLog.objects.create(
            bid=bid, actor=request.user, actor_role='admin', message=notes)
        return Response(VendorBidSerializer(
            bid, context={'request': request}).data)

    @action(detail=True, methods=['get'])
    def comparison(self, request, pk=None):
        tender = self.get_object()
        data   = BidComparisonSerializer().to_representation(tender)
        return Response(data)


class VendorTenderViewSet(viewsets.ViewSet):
    permission_classes = [IsApprovedVendor]

    def list(self, request):
        check_and_close_expired_tenders()
        vendor = request.user.vendor_profile
        open_tenders = Tender.objects.filter(
            status='open').prefetch_related('items', 'bids')
        own_tenders  = Tender.objects.filter(
            bids__vendor=vendor).exclude(
            status='open').prefetch_related('items', 'bids')
        all_tenders  = (open_tenders | own_tenders).distinct()
        return Response(TenderDetailVendorSerializer(
            all_tenders, many=True,
            context={'request': request}).data)

    def retrieve(self, request, pk=None):
        check_and_close_expired_tenders()
        try:
            tender = Tender.objects.get(pk=pk)
        except Tender.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        if tender.status not in ('open',):
            vendor = request.user.vendor_profile
            if not tender.bids.filter(vendor=vendor).exists():
                return Response({'error': 'Not found.'}, status=404)
        return Response(TenderDetailVendorSerializer(
            tender, context={'request': request}).data)

    @action(detail=True, methods=['post', 'patch', 'delete'],
            url_path='bid', url_name='bid')
    def bid(self, request, pk=None):
        if request.method == 'POST':
            return self._submit_bid(request, pk)
        if request.method == 'PATCH':
            return self._update_bid(request, pk)
        return self._withdraw_bid(request, pk)

    def _submit_bid(self, request, pk):
        try:
            tender = Tender.objects.get(pk=pk, status='open')
        except Tender.DoesNotExist:
            return Response({'error': 'Tender not open.'}, status=400)
        vendor = request.user.vendor_profile
        if tender.bids.filter(vendor=vendor).exists():
            return Response({'error': 'Bid already submitted.'}, status=400)

        serializer = VendorBidWriteSerializer(
            data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        tender_item_ids = set(str(i.id) for i in tender.items.all())
        submitted_ids   = set(
            str(i['tender_item'].id)
            for i in serializer.validated_data['items'])
        if tender_item_ids != submitted_ids:
            return Response(
                {'error': 'Must bid on all products in the tender.'},
                status=400)

        with transaction.atomic():
            bid = VendorBid.objects.create(
                tender        = tender,
                vendor        = vendor,
                overall_notes = serializer.validated_data.get('overall_notes', ''),
                status        = 'bid_submitted',
            )
            for item_data in serializer.validated_data['items']:
                VendorBidItem.objects.create(bid=bid, **item_data)
            overall_notes = serializer.validated_data.get('overall_notes', '').strip()
            if overall_notes:
                NegotiationLog.objects.create(
                    bid=bid, actor=request.user,
                    actor_role='vendor', message=overall_notes)

        return Response(
            VendorBidSerializer(bid, context={'request': request}).data,
            status=status.HTTP_201_CREATED)

    def _update_bid(self, request, pk):
        try:
            tender = Tender.objects.get(pk=pk, status='open')
        except Tender.DoesNotExist:
            return Response({'error': 'Tender not open.'}, status=400)
        vendor = request.user.vendor_profile
        try:
            bid = tender.bids.get(vendor=vendor)
        except VendorBid.DoesNotExist:
            return Response({'error': 'No bid found.'}, status=404)
        if bid.status not in ('bid_submitted', 'under_negotiation'):
            return Response(
                {'error': 'Bid cannot be updated at this stage.'}, status=400)

        serializer = VendorBidWriteSerializer(
            data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            bid.overall_notes = serializer.validated_data.get(
                'overall_notes', bid.overall_notes)
            bid.status        = 'bid_revised'
            bid.update_count += 1
            bid.save()
            bid.items.all().delete()
            for item_data in serializer.validated_data['items']:
                VendorBidItem.objects.create(bid=bid, **item_data)
            vendor_note = serializer.validated_data.get('overall_notes', '').strip()
            if vendor_note:
                NegotiationLog.objects.create(
                    bid=bid, actor=request.user,
                    actor_role='vendor', message=vendor_note)

        return Response(VendorBidSerializer(bid, context={'request': request}).data)

    def _withdraw_bid(self, request, pk):
        try:
            tender = Tender.objects.get(pk=pk, status='open')
        except Tender.DoesNotExist:
            return Response({'error': 'Tender not open.'}, status=400)
        vendor   = request.user.vendor_profile
        deleted, _ = tender.bids.filter(
            vendor=vendor, status='bid_submitted').delete()
        if not deleted:
            return Response({'error': 'No withdrawable bid found.'}, status=404)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='comment')
    def add_comment(self, request, pk=None):
        try:
            tender = Tender.objects.get(pk=pk)
        except Tender.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)

        vendor = request.user.vendor_profile
        try:
            bid = tender.bids.get(vendor=vendor)
        except VendorBid.DoesNotExist:
            return Response({'error': 'No bid found.'}, status=404)

        if bid.status != 'under_negotiation':
            return Response(
                {'error': 'Can only reply when admin has '
                          'requested information.'},
                status=400)

        message = request.data.get('message', '').strip()
        if not message:
            return Response({'error': 'message is required.'}, status=400)

        NegotiationLog.objects.create(
            bid=bid, actor=request.user,
            actor_role='vendor', message=message)

        bid.status = 'bid_revised'
        bid.save()

        return Response({'message': 'Reply sent.'}, status=201)
