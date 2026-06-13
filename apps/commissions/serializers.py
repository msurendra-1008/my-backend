from rest_framework import serializers
from .models import CommissionSettings, ProductCommissionRule, CommissionBreakup, CommissionEntry


class PendingCommissionSerializer(serializers.ModelSerializer):
    order_number          = serializers.SerializerMethodField()
    product_name          = serializers.SerializerMethodField()
    buyer_name            = serializers.SerializerMethodField()
    buyer_upa_id          = serializers.SerializerMethodField()
    upa_profit            = serializers.SerializerMethodField()
    pool_amount           = serializers.SerializerMethodField()
    pending_since         = serializers.SerializerMethodField()
    recipient_is_active   = serializers.SerializerMethodField()
    upline_chain          = serializers.SerializerMethodField()
    return_window_expires = serializers.DateTimeField(source='breakup.return_window_expires', read_only=True)

    class Meta:
        model  = CommissionEntry
        fields = [
            'id', 'entry_type', 'level', 'leg_position',
            'recipient_name', 'recipient_mobile',
            'recipient_upa_id', 'amount',
            'percentage_applied', 'status',
            'order_number', 'product_name',
            'buyer_name', 'buyer_upa_id',
            'upa_profit', 'pool_amount',
            'pending_since', 'recipient_is_active',
            'upline_chain', 'return_window_expires',
        ]

    def get_order_number(self, obj):
        return obj.breakup.order_item.order.order_number

    def get_product_name(self, obj):
        return obj.breakup.order_item.product_name

    def get_buyer_name(self, obj):
        buyer = obj.breakup.order_item.order.user
        return buyer.full_name if buyer else ''

    def get_buyer_upa_id(self, obj):
        buyer = obj.breakup.order_item.order.user
        return (getattr(buyer, 'upa_id', '') or '') if buyer else ''

    def get_upa_profit(self, obj):
        snap = obj.breakup.rule_snapshot or {}
        return snap.get('profit', 0)

    def get_pool_amount(self, obj):
        if obj.entry_type == 'network_upline':
            return float(obj.breakup.network_pool)
        elif obj.entry_type == 'team_downline':
            return float(obj.breakup.team_pool)
        return 0

    def get_pending_since(self, obj):
        return obj.breakup.order_item.order.created_at

    def get_recipient_is_active(self, obj):
        if not obj.recipient:
            return False
        return obj.recipient.is_active

    def get_upline_chain(self, obj):
        buyer_name   = self.get_buyer_name(obj)
        buyer_upa_id = self.get_buyer_upa_id(obj)
        if obj.entry_type == 'network_upline':
            return {
                'type':         'upline',
                'level':        obj.level,
                'buyer_name':   buyer_name,
                'buyer_upa_id': buyer_upa_id,
            }
        elif obj.entry_type == 'team_downline':
            return {
                'type':         'downline',
                'leg':          obj.leg_position,
                'buyer_name':   buyer_name,
                'buyer_upa_id': buyer_upa_id,
            }
        return None


class CommissionSettingsSerializer(serializers.ModelSerializer):
    social_work_pct         = serializers.DecimalField(max_digits=5, decimal_places=2)
    company_pct             = serializers.DecimalField(max_digits=5, decimal_places=2)
    direction               = serializers.ChoiceField(choices=['direct_first', 'ancestor_first'])
    self_commission_enabled = serializers.BooleanField()
    self_commission_pct     = serializers.DecimalField(max_digits=5, decimal_places=2)
    delivery_packaging_pct  = serializers.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        model = CommissionSettings
        fields = [
            'id',
            'network_commission_pct',
            'team_commission_pct',
            'social_work_pct',
            'company_pct',
            'self_commission_enabled',
            'self_commission_pct',
            'delivery_packaging_pct',
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
    product_name            = serializers.CharField(source='product.name', read_only=True)
    product_mrp             = serializers.DecimalField(
        source='product.mrp', max_digits=12, decimal_places=2, read_only=True)
    social_work_pct         = serializers.DecimalField(max_digits=5, decimal_places=2)
    company_pct             = serializers.DecimalField(max_digits=5, decimal_places=2)
    direction               = serializers.ChoiceField(choices=['direct_first', 'ancestor_first'])
    self_commission_enabled = serializers.BooleanField()
    self_commission_pct     = serializers.DecimalField(max_digits=5, decimal_places=2)
    delivery_packaging_pct  = serializers.DecimalField(max_digits=5, decimal_places=2)
    product_pricing         = serializers.SerializerMethodField()

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
            'self_commission_enabled',
            'self_commission_pct',
            'delivery_packaging_pct',
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
        from apps.products.utils import get_upa_price
        product = obj.product
        if not product.pricing_configured:
            return None
        variant = product.variants.filter(purchase_price__isnull=False).first()
        purchase = float(variant.purchase_price) if variant else float(product.purchase_price or 0)
        if purchase == 0:
            return None
        price_data = get_upa_price(product)
        selling   = float(price_data['mrp'])
        upa_price = float(price_data['upa_price'])
        upa_disc  = float(price_data['discount_percent'])
        if product.other_charges_type == 'flat':
            other = float(product.other_charges or 0)
        else:
            other = upa_price * float(product.other_charges or 0) / 100
        gst_pct = float(product.gst_percentage or 0)
        gst_amt = upa_price * gst_pct / 100
        regular_profit = (selling + other) - purchase
        upa_profit     = (upa_price + other) - purchase
        return {
            'purchase_price':     purchase,
            'selling_price':      selling,
            'other_charges':      round(other, 2),
            'gst_percentage':     gst_pct,
            'gst_amount':         round(gst_amt, 2),
            'upa_discount_pct':   round(upa_disc, 2),
            'upa_price':          round(upa_price, 2),
            'upa_discount_amt':   round(selling - upa_price, 2),
            'regular_profit':     round(regular_profit, 2),
            'upa_profit':         round(upa_profit, 2),
            'pricing_configured': True,
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
            'entry_type',
            'level',
            'leg_position',
            'recipient_name',
            'recipient_mobile',
            'recipient_upa_id',
            'amount',
            'percentage_applied',
            'status',
            'credited_at',
        ]
        read_only_fields = fields


class CommissionBreakupAdminSerializer(serializers.ModelSerializer):
    """Full serializer for embedding in order detail — includes profit breakdown."""
    entries         = CommissionEntryAdminSerializer(many=True, read_only=True)
    profit_data     = serializers.SerializerMethodField()
    network_entries = serializers.SerializerMethodField()
    team_entries    = serializers.SerializerMethodField()
    social_entries  = serializers.SerializerMethodField()
    company_entries = serializers.SerializerMethodField()
    self_entries    = serializers.SerializerMethodField()

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
            'rule_snapshot',
            'profit_data',
            'entries',
            'network_entries',
            'team_entries',
            'social_entries',
            'company_entries',
            'self_entries',
        ]
        read_only_fields = fields

    def get_profit_data(self, obj):
        snap = obj.rule_snapshot or {}
        return {
            'profit':                   snap.get('profit', 0),
            'upa_price':                snap.get('upa_price', 0),
            'purchase_total':           snap.get('purchase_total', 0),
            'other_total':              snap.get('other_total', 0),
            'network_pct':              snap.get('network_pct', 0),
            'team_pct':                 snap.get('team_pct', 0),
            'social_pct':               snap.get('social_pct', 0),
            'company_pct':              snap.get('company_pct', 0),
            'self_commission_enabled':  snap.get('self_commission_enabled', False),
            'self_pct':                 snap.get('self_pct', 0),
            'delivery_pct':             snap.get('delivery_pct', 0),
        }

    def get_network_entries(self, obj):
        return CommissionEntryAdminSerializer(
            obj.entries.filter(entry_type='network_upline').order_by('level'),
            many=True,
        ).data

    def get_team_entries(self, obj):
        return CommissionEntryAdminSerializer(
            obj.entries.filter(entry_type='team_downline'),
            many=True,
        ).data

    def get_social_entries(self, obj):
        return CommissionEntryAdminSerializer(
            obj.entries.filter(entry_type='social_work'),
            many=True,
        ).data

    def get_company_entries(self, obj):
        return CommissionEntryAdminSerializer(
            obj.entries.filter(entry_type='company'),
            many=True,
        ).data

    def get_self_entries(self, obj):
        return CommissionEntryAdminSerializer(
            obj.entries.filter(entry_type='self_commission'),
            many=True,
        ).data
