from rest_framework import serializers
from .models import DiscountCode, OfflineBill, OfflineReturn, BillingSettings


class DiscountCodeSerializer(serializers.ModelSerializer):
    is_valid_now = serializers.SerializerMethodField()

    class Meta:
        model  = DiscountCode
        fields = [
            'id', 'code', 'type', 'value',
            'max_uses', 'used_count', 'valid_from',
            'valid_till', 'is_active', 'is_valid_now',
        ]

    def get_is_valid_now(self, obj):
        valid, _ = obj.is_valid()
        return valid


class ValidateDiscountSerializer(serializers.Serializer):
    code       = serializers.CharField()
    cart_total = serializers.DecimalField(max_digits=15, decimal_places=2)


class BillItemSerializer(serializers.Serializer):
    variant_id = serializers.UUIDField()
    quantity   = serializers.IntegerField(min_value=1)


class CreateBillSerializer(serializers.Serializer):
    customer_type    = serializers.ChoiceField(choices=['walkin', 'upa', 'regular'])
    customer_user_id = serializers.UUIDField(required=False, allow_null=True)
    walkin_name      = serializers.CharField(required=False, allow_blank=True, default='')
    walkin_mobile    = serializers.CharField(required=False, allow_blank=True, default='')
    items            = BillItemSerializer(many=True)
    payment_method   = serializers.ChoiceField(choices=['cash', 'upi', 'card'])
    cash_received    = serializers.DecimalField(
        max_digits=15, decimal_places=2, required=False, allow_null=True,
    )
    discount_code    = serializers.CharField(required=False, allow_blank=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError('At least one item required')
        return value


class OfflineBillSerializer(serializers.ModelSerializer):
    order_number   = serializers.CharField(source='order.order_number', read_only=True)
    amount_payable = serializers.DecimalField(
        source='order.amount_payable', max_digits=15, decimal_places=2, read_only=True,
    )
    items          = serializers.SerializerMethodField()
    billed_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = OfflineBill
        fields = [
            'id', 'bill_number', 'order_number',
            'customer_type', 'walkin_name', 'walkin_mobile',
            'payment_method', 'cash_received', 'change_given',
            'discount_amount', 'amount_payable',
            'items', 'billed_by_name', 'created_at',
        ]

    def get_billed_by_name(self, obj):
        if obj.billed_by:
            return obj.billed_by.full_name
        return ''

    def get_items(self, obj):
        from apps.orders.serializers import OrderItemSerializer
        return OrderItemSerializer(
            obj.order.items.all(),
            many=True,
            context=self.context,
        ).data


class OfflineReturnSerializer(serializers.ModelSerializer):
    bill_number = serializers.CharField(source='bill.bill_number', read_only=True)

    class Meta:
        model  = OfflineReturn
        fields = [
            'id', 'bill_number', 'status',
            'items', 'total_refund', 'bill_photo',
            'review_notes', 'created_at',
        ]


class BillingSettingsSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.SerializerMethodField()
    effective_days  = serializers.SerializerMethodField()

    class Meta:
        model  = BillingSettings
        fields = [
            'id',
            'return_window_enabled',
            'return_window_days',
            'effective_days',
            'updated_at',
            'updated_by_name',
        ]

    def get_updated_by_name(self, obj):
        return obj.updated_by.full_name if obj.updated_by else None

    def get_effective_days(self, obj):
        return BillingSettings.get_return_days()


class UpdateBillingSettingsSerializer(serializers.Serializer):
    return_window_enabled = serializers.BooleanField()
    return_window_days    = serializers.IntegerField(min_value=1, max_value=30)

    def validate(self, data):
        if data.get('return_window_enabled') and data.get('return_window_days', 0) < 1:
            raise serializers.ValidationError(
                'return_window_days must be at least 1 when enabled')
        return data
