from rest_framework import serializers
from .models import CommissionSettings, ProductCommissionRule, CommissionBreakup, CommissionEntry


class CommissionSettingsSerializer(serializers.ModelSerializer):
    social_work_pct = serializers.DecimalField(max_digits=5, decimal_places=2)
    company_pct     = serializers.DecimalField(max_digits=5, decimal_places=2)
    direction       = serializers.ChoiceField(choices=['direct_first', 'ancestor_first'])

    class Meta:
        model = CommissionSettings
        fields = [
            'id',
            'network_commission_pct',
            'team_commission_pct',
            'social_work_pct',
            'company_pct',
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
    product_name    = serializers.CharField(source='product.name', read_only=True)
    product_mrp     = serializers.DecimalField(
        source='product.mrp', max_digits=12, decimal_places=2, read_only=True)
    social_work_pct = serializers.DecimalField(max_digits=5, decimal_places=2)
    company_pct     = serializers.DecimalField(max_digits=5, decimal_places=2)
    direction       = serializers.ChoiceField(choices=['direct_first', 'ancestor_first'])
    product_pricing = serializers.SerializerMethodField()

    class Meta:
        model = ProductCommissionRule
        fields = [
            'id',
            'product',
            'product_name',
            'product_mrp',
            'product_pricing',
            'is_active',
            'network_commission_pct',
            'team_commission_pct',
            'social_work_pct',
            'company_pct',
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
        read_only_fields = [
            'id', 'product_name', 'product_mrp', 'product_pricing',
            'created_by', 'created_at', 'updated_at',
        ]

    def get_product_pricing(self, obj):
        product = obj.product
        variant = product.variants.filter(purchase_price__isnull=False).first()
        if not variant:
            return None
        selling  = float(variant.mrp or 0)
        purchase = float(variant.purchase_price or 0)
        upa_disc = float(product.upa_discount_override or 0)
        upa_price = selling * (1 - upa_disc / 100)
        if product.other_charges_type == 'flat':
            other = float(product.other_charges or 0)
        else:
            other = selling * float(product.other_charges or 0) / 100
        gst_pct = float(product.gst_percentage or 0)
        gst_amt = selling * gst_pct / 100
        regular_profit = (selling + other) - purchase
        upa_profit     = (upa_price + other) - purchase
        return {
            'purchase_price':    purchase,
            'selling_price':     selling,
            'other_charges':     other,
            'gst_percentage':    gst_pct,
            'gst_amount':        round(gst_amt, 2),
            'upa_discount_pct':  upa_disc,
            'upa_price':         round(upa_price, 2),
            'upa_discount_amt':  round(selling - upa_price, 2),
            'regular_profit':    round(regular_profit, 2),
            'upa_profit':        round(upa_profit, 2),
            'pricing_configured': product.pricing_configured,
        }


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


class CommissionEntryAdminSerializer(serializers.ModelSerializer):
    """Compact entry serializer for embedding inside order detail."""
    class Meta:
        model = CommissionEntry
        fields = [
            'id',
            'recipient_name',
            'recipient_mobile',
            'recipient_upa_id',
            'entry_type',
            'level',
            'leg_position',
            'amount',
            'percentage_applied',
            'status',
        ]
        read_only_fields = fields


class CommissionBreakupAdminSerializer(serializers.ModelSerializer):
    """Compact serializer for embedding in order detail."""
    entries = CommissionEntryAdminSerializer(many=True, read_only=True)

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
            'entries',
        ]
        read_only_fields = fields
