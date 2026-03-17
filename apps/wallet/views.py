from decimal import Decimal, InvalidOperation

from django.db.models import Sum
from django.utils import timezone

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from core.mixins import LoginRequiredMixin
from apps.authentication.permissions import IsAdmin, IsUPAUser
from .models import Wallet, WalletTransaction
from .serializers import WalletSerializer, WalletTransactionSerializer


class _TxnPagination(PageNumberPagination):
    page_size = 20


class WalletViewSet(LoginRequiredMixin, viewsets.ModelViewSet):
    queryset         = Wallet.objects.select_related('user')
    lookup_field     = 'user_id'
    lookup_url_kwarg = 'user_id'

    http_method_names = ['get', 'post', 'head', 'options']

    def get_permissions(self):
        if self.action in ('my_wallet', 'my_transactions'):
            return [IsUPAUser()]
        return [IsAdmin()]

    def list(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def retrieve(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    # ── UPA User ──────────────────────────────────────────────────────────────

    @extend_schema(tags=['Wallet'])
    @action(detail=False, methods=['get'], url_path='my-wallet')
    def my_wallet(self, request):
        """Logged-in UPA user's wallet + last 20 transactions."""
        try:
            wallet = Wallet.objects.select_related('user').get(user=request.user)
        except Wallet.DoesNotExist:
            return Response({'detail': 'Wallet not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(WalletSerializer(wallet).data)

    @extend_schema(tags=['Wallet'])
    @action(detail=False, methods=['get'], url_path='my-transactions')
    def my_transactions(self, request):
        """Full paginated transaction history for the logged-in UPA user."""
        try:
            wallet = Wallet.objects.get(user=request.user)
        except Wallet.DoesNotExist:
            return Response({'count': 0, 'next': None, 'previous': None, 'results': []})
        qs = wallet.transactions.select_related('triggered_by').all()
        paginator = _TxnPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(
            WalletTransactionSerializer(page, many=True).data
        )

    # ── Admin ─────────────────────────────────────────────────────────────────

    @extend_schema(tags=['Wallet'])
    @action(detail=False, methods=['get'], url_path='admin-overview')
    def admin_overview(self, request):
        """Platform wallet summary: total balance + total credited this month."""
        now         = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        total_balance = (
            Wallet.objects.aggregate(total=Sum('balance'))['total'] or Decimal('0.00')
        )
        credited_this_month = (
            WalletTransaction.objects
            .filter(type='credit', created_at__gte=month_start)
            .aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        )
        return Response({
            'total_balance':       str(total_balance),
            'credited_this_month': str(credited_this_month),
            'total_wallets':       Wallet.objects.count(),
        })

    @extend_schema(tags=['Wallet'])
    @action(detail=True, methods=['get'], url_path='user-wallet')
    def user_wallet(self, request, user_id=None):
        """Specific user's wallet + last 20 transactions (admin only)."""
        wallet = self.get_object()
        return Response(WalletSerializer(wallet).data)

    @extend_schema(tags=['Wallet'])
    @action(detail=True, methods=['post'], url_path='manual-adjust')
    def manual_adjust(self, request, user_id=None):
        """Credit or debit a wallet (admin only)."""
        txn_type = request.data.get('type')
        raw_amt  = request.data.get('amount')
        reason   = request.data.get('reason', '').strip()

        if txn_type not in ('credit', 'debit'):
            return Response(
                {'detail': 'type must be "credit" or "debit".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            amount = Decimal(str(raw_amt))
            if amount <= 0:
                raise ValueError
        except (TypeError, ValueError, InvalidOperation):
            return Response(
                {'detail': 'amount must be a positive number.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not reason:
            return Response(
                {'detail': 'reason is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        wallet = self.get_object()

        if txn_type == 'debit' and wallet.balance < amount:
            return Response(
                {'detail': f'Insufficient balance. Current balance is ₹{wallet.balance}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if txn_type == 'credit':
            wallet.balance += amount
        else:
            wallet.balance -= amount
        wallet.save()

        txn = WalletTransaction.objects.create(
            wallet=wallet,
            type=txn_type,
            amount=amount,
            reason=reason,
            triggered_by=request.user,
        )

        return Response({
            'balance':     str(wallet.balance),
            'transaction': WalletTransactionSerializer(txn).data,
            'message':     f'Wallet {txn_type}ed ₹{amount} successfully.',
        })
