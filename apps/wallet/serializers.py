from rest_framework import serializers
from .models import Wallet, WalletTransaction


class WalletTransactionSerializer(serializers.ModelSerializer):
    triggered_by_upa_id = serializers.SerializerMethodField()
    triggered_by_name   = serializers.SerializerMethodField()

    class Meta:
        model  = WalletTransaction
        fields = [
            'id', 'type', 'amount', 'reason',
            'triggered_by_upa_id', 'triggered_by_name',
            'reference', 'created_at',
        ]

    def get_triggered_by_upa_id(self, obj):
        return obj.triggered_by.upa_id if obj.triggered_by else None

    def get_triggered_by_name(self, obj):
        return obj.triggered_by.full_name if obj.triggered_by else None


class WalletSerializer(serializers.ModelSerializer):
    upa_id       = serializers.CharField(source='user.upa_id')
    transactions = serializers.SerializerMethodField()

    class Meta:
        model  = Wallet
        fields = ['id', 'upa_id', 'balance', 'transactions', 'updated_at']

    def get_transactions(self, obj):
        txns = obj.transactions.select_related('triggered_by').all()[:20]
        return WalletTransactionSerializer(txns, many=True).data
