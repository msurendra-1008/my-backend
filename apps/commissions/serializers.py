from rest_framework import serializers
from .models import CommissionSettings, ProductCommissionRule, CommissionBreakup, CommissionEntry


class CommissionSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommissionSettings
        fields = [
            'id',
            'network_commission_pct',
            'team_commission_pct',
            'max_upline_levels',
            'use_max_levels',
            'direction',
            'level_percentages',
            'left_leg_pct',
            'middle_leg_pct',
            'right_leg_pct',
            'trigger_mode',
            'updated_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'updated_by', 'created_at', 'updated_at']


class ProductCommissionRuleSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_mrp  = serializers.DecimalField(
        source='product.mrp', max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = ProductCommissionRule
        fields = [
            'id',
            'product',
            'product_name',
            'product_mrp',
            'is_active',
            'network_commission_pct',
            'team_commission_pct',
            'max_upline_levels',
            'use_max_levels',
            'direction',
            'level_percentages',
            'left_leg_pct',
            'middle_leg_pct',
            'right_leg_pct',
            'created_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'product_name', 'product_mrp', 'created_by', 'created_at', 'updated_at']


class CommissionEntrySerializer(serializers.ModelSerializer):
    return_window_expires = serializers.DateTimeField(
        source='breakup.return_window_expires', read_only=True)
    order_number = serializers.SerializerMethodField()

    class Meta:
        model = CommissionEntry
        fields = [
            'id',
            'return_window_expires',
            'order_number',
            'recipient',
            'recipient_upa_id',
            'recipient_name',
            'recipient_mobile',
            'entry_type',
            'level',
            'leg_position',
            'amount',
            'percentage_applied',
            'status',
            'credited_at',
            'wallet_transaction',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_order_number(self, obj):
        try:
            return obj.breakup.order_item.order.order_number
        except Exception:
            return ''


class CommissionBreakupSerializer(serializers.ModelSerializer):
    entries      = CommissionEntrySerializer(many=True, read_only=True)
    product_name = serializers.CharField(source='order_item.product_name', read_only=True)
    order_number = serializers.CharField(source='order_item.order.order_number', read_only=True)

    class Meta:
        model = CommissionBreakup
        fields = [
            'id',
            'order_item',
            'product_name',
            'order_number',
            'total_base_amount',
            'network_pool',
            'team_pool',
            'status',
            'return_window_expires',
            'processed_at',
            'entries',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class CommissionBreakupAdminSerializer(serializers.ModelSerializer):
    """Compact serializer for embedding in order detail."""
    class Meta:
        model = CommissionBreakup
        fields = [
            'id',
            'total_base_amount',
            'network_pool',
            'team_pool',
            'status',
            'return_window_expires',
            'processed_at',
        ]
        read_only_fields = fields
