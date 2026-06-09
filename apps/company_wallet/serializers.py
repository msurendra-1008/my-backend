from decimal import Decimal
from rest_framework import serializers
from apps.company_wallet.models import CompanyWallet, CompanyTransaction, GSTLedgerEntry


class CompanyWalletSerializer(serializers.ModelSerializer):
    class Meta:
        model  = CompanyWallet
        fields = ['id', 'balance', 'updated_at']


class CompanyTransactionSerializer(serializers.ModelSerializer):
    order_number = serializers.SerializerMethodField()

    class Meta:
        model  = CompanyTransaction
        fields = [
            'id', 'transaction_type', 'amount', 'balance_after',
            'description', 'order_number', 'created_at',
        ]

    def get_order_number(self, obj):
        if obj.order_id:
            return obj.order.order_number
        if obj.order_item_id:
            return obj.order_item.order.order_number
        return None


class GSTLedgerEntrySerializer(serializers.ModelSerializer):
    order_number = serializers.SerializerMethodField()

    class Meta:
        model  = GSTLedgerEntry
        fields = ['id', 'gst_type', 'amount', 'description', 'reference', 'order_number', 'created_at']

    def get_order_number(self, obj):
        if obj.order_item_id:
            return obj.order_item.order.order_number
        return obj.reference or None


class ManualEntrySerializer(serializers.Serializer):
    tx_type     = serializers.ChoiceField(choices=['manual_credit', 'manual_debit'])
    amount      = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    description = serializers.CharField(max_length=255)
