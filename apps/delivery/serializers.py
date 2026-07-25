from rest_framework import serializers
from .models import DeliveryZone, DeliveryPartner, DeliverySettings, DeliveryAssignment, DeliveryStatusLog, DutyLog


class DeliveryZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DeliveryZone
        fields = ['id', 'name', 'pincodes', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']


class DeliveryPartnerSerializer(serializers.ModelSerializer):
    full_name          = serializers.SerializerMethodField()
    email              = serializers.SerializerMethodField()
    mobile             = serializers.SerializerMethodField()
    zones              = DeliveryZoneSerializer(many=True, read_only=True)
    zone_ids           = serializers.PrimaryKeyRelatedField(
        source='zones', many=True,
        queryset=DeliveryZone.objects.all(),
        required=False, write_only=True,
    )
    active_assignments = serializers.SerializerMethodField()

    class Meta:
        model  = DeliveryPartner
        fields = [
            'id', 'user', 'full_name', 'email', 'mobile',
            'vehicle_type', 'vehicle_number',
            'zones', 'zone_ids',
            'is_active', 'is_on_duty', 'duty_started_at',
            'active_assignments', 'created_at',
        ]
        read_only_fields = [
            'id', 'created_at', 'full_name', 'email', 'mobile',
            'zones', 'active_assignments', 'is_on_duty', 'duty_started_at',
        ]

    def get_full_name(self, obj):
        return obj.user.full_name

    def get_email(self, obj):
        return obj.user.email

    def get_mobile(self, obj):
        return obj.user.mobile

    def get_active_assignments(self, obj):
        return obj.assignments.filter(status='assigned').count()


class DeliverySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DeliverySettings
        fields = [
            'auto_assign', 'assignment_mode', 'default_proof_type',
            'max_orders_per_partner',
            'full_day_hours', 'half_day_hours', 'count_half_days',
            'updated_at',
        ]
        read_only_fields = ['updated_at']

    def validate(self, data):
        full = float(data.get('full_day_hours', getattr(self.instance, 'full_day_hours', 6.0)))
        half = float(data.get('half_day_hours', getattr(self.instance, 'half_day_hours', 3.0)))

        if half >= full:
            raise serializers.ValidationError({
                'half_day_hours': f'Half day hours ({half}h) must be less than full day hours ({full}h)',
            })
        if full > 24:
            raise serializers.ValidationError({
                'full_day_hours': 'Full day hours cannot exceed 24',
            })
        if half < 0.5:
            raise serializers.ValidationError({
                'half_day_hours': 'Half day hours must be at least 0.5',
            })
        return data


class DeliveryStatusLogSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = DeliveryStatusLog
        fields = ['id', 'status', 'notes', 'created_at', 'created_by_name']
        read_only_fields = ['id', 'created_at']

    def get_created_by_name(self, obj):
        return obj.created_by.full_name if obj.created_by else None


def _order_from_assignment(obj):
    """Return the Order associated with the assignment regardless of type."""
    if obj.assignment_type == 'exchange' and obj.exchange_request:
        return obj.exchange_request.order_item.order
    return obj.order


class DeliveryAssignmentSerializer(serializers.ModelSerializer):
    partner_name      = serializers.SerializerMethodField()
    partner_mobile    = serializers.SerializerMethodField()
    partner_vehicle   = serializers.SerializerMethodField()
    order_number      = serializers.SerializerMethodField()
    customer_name     = serializers.SerializerMethodField()
    delivery_address  = serializers.SerializerMethodField()
    assignment_type   = serializers.CharField(read_only=True)
    exchange_item     = serializers.SerializerMethodField()
    logs              = DeliveryStatusLogSerializer(many=True, read_only=True)

    class Meta:
        model  = DeliveryAssignment
        fields = [
            'id', 'assignment_type', 'order', 'order_number',
            'exchange_item', 'customer_name', 'delivery_address',
            'partner', 'partner_name', 'partner_mobile', 'partner_vehicle',
            'otp', 'status', 'assigned_at', 'picked_up_at', 'delivered_at',
            'proof_image', 'failure_reason', 'notes', 'logs',
        ]
        read_only_fields = ['id', 'otp', 'assigned_at', 'assignment_type']

    def get_partner_name(self, obj):
        return obj.partner.user.full_name if obj.partner else None

    def get_partner_mobile(self, obj):
        return obj.partner.user.mobile if obj.partner else None

    def get_partner_vehicle(self, obj):
        return obj.partner.vehicle_type if obj.partner else None

    def get_order_number(self, obj):
        o = _order_from_assignment(obj)
        return o.order_number if o else None

    def get_customer_name(self, obj):
        o = _order_from_assignment(obj)
        return o.address_name if o else None

    def get_delivery_address(self, obj):
        o = _order_from_assignment(obj)
        if not o:
            return None
        return f'{o.address_line}, {o.address_city}, {o.address_state} - {o.address_pincode}'

    def get_exchange_item(self, obj):
        if obj.assignment_type == 'exchange' and obj.exchange_request:
            item = obj.exchange_request.order_item
            return {
                'product_name': item.product_name,
                'variant_name': item.variant_name,
                'quantity':     obj.exchange_request.return_qty,
            }
        return None


class PartnerAssignmentSerializer(serializers.ModelSerializer):
    """Partner's own view of their assignments."""
    assignment_type  = serializers.CharField(read_only=True)
    order_number     = serializers.SerializerMethodField()
    customer_name    = serializers.SerializerMethodField()
    customer_phone   = serializers.SerializerMethodField()
    delivery_address = serializers.SerializerMethodField()
    exchange_item    = serializers.SerializerMethodField()
    logs             = DeliveryStatusLogSerializer(many=True, read_only=True)

    class Meta:
        model  = DeliveryAssignment
        fields = [
            'id', 'assignment_type', 'order_number', 'exchange_item',
            'customer_name', 'customer_phone', 'delivery_address',
            'status', 'assigned_at', 'picked_up_at', 'delivered_at',
            'proof_image', 'failure_reason', 'notes', 'logs',
        ]
        read_only_fields = ['id', 'assigned_at']

    def get_order_number(self, obj):
        o = _order_from_assignment(obj)
        return o.order_number if o else None

    def get_customer_name(self, obj):
        o = _order_from_assignment(obj)
        return o.address_name if o else None

    def get_customer_phone(self, obj):
        o = _order_from_assignment(obj)
        return o.address_phone if o else None

    def get_delivery_address(self, obj):
        o = _order_from_assignment(obj)
        if not o:
            return None
        return f'{o.address_line}, {o.address_city}, {o.address_state} - {o.address_pincode}'

    def get_exchange_item(self, obj):
        if obj.assignment_type == 'exchange' and obj.exchange_request:
            item = obj.exchange_request.order_item
            return {
                'product_name': item.product_name,
                'variant_name': item.variant_name,
                'quantity':     obj.exchange_request.return_qty,
            }
        return None


class DutyLogSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DutyLog
        fields = ['id', 'status', 'timestamp', 'date']
        read_only_fields = ['id', 'timestamp', 'date']
