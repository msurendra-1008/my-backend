from rest_framework import serializers

from .models import Warehouse, Zone, Rack, RackStock, StockMovement, StockTransfer

_PV = __import__('apps.products.models', fromlist=['ProductVariant']).ProductVariant


class WarehouseSerializer(serializers.ModelSerializer):
    zone_count = serializers.SerializerMethodField()

    class Meta:
        model = Warehouse
        fields = ['id', 'name', 'location', 'is_active', 'zone_count', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_zone_count(self, obj):
        return obj.zones.count()


class ZoneSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)
    rack_count = serializers.SerializerMethodField()

    class Meta:
        model = Zone
        fields = ['id', 'warehouse', 'warehouse_name', 'name', 'is_active', 'rack_count', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_rack_count(self, obj):
        return obj.racks.count()


class RackSerializer(serializers.ModelSerializer):
    zone_name           = serializers.CharField(source='zone.name', read_only=True)
    warehouse_name      = serializers.CharField(source='zone.warehouse.name', read_only=True)
    warehouse_id        = serializers.UUIDField(source='zone.warehouse.id', read_only=True)
    current_stock       = serializers.IntegerField(read_only=True)
    capacity_percentage = serializers.SerializerMethodField()

    class Meta:
        model = Rack
        fields = [
            'id', 'zone', 'zone_name', 'warehouse_id', 'warehouse_name',
            'code', 'capacity', 'is_active',
            'current_stock', 'capacity_percentage', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_capacity_percentage(self, obj):
        if obj.capacity == 0:
            return None
        return round(obj.current_stock / obj.capacity * 100)


class RackStockSerializer(serializers.ModelSerializer):
    rack_code      = serializers.CharField(source='rack.code', read_only=True)
    zone_name      = serializers.CharField(source='rack.zone.name', read_only=True)
    warehouse_name = serializers.CharField(source='rack.zone.warehouse.name', read_only=True)
    warehouse_id   = serializers.UUIDField(source='rack.zone.warehouse.id', read_only=True)
    variant_name   = serializers.CharField(source='variant.name', read_only=True)
    product_name   = serializers.CharField(source='variant.product.name', read_only=True)
    product_image  = serializers.SerializerMethodField()
    sku            = serializers.CharField(source='variant.sku', read_only=True)

    class Meta:
        model = RackStock
        fields = [
            'id', 'rack', 'rack_code', 'zone_name', 'warehouse_id', 'warehouse_name',
            'variant', 'variant_name', 'product_name', 'product_image', 'sku',
            'quantity', 'last_updated',
        ]
        read_only_fields = ['id', 'last_updated']

    def get_product_image(self, obj):
        request = self.context.get('request')
        try:
            img = obj.variant.product.images.filter(is_primary=True).first()
            if img and img.image and request:
                return request.build_absolute_uri(img.image.url)
        except Exception:
            pass
        return None


class StockMovementSerializer(serializers.ModelSerializer):
    rack_code      = serializers.CharField(source='rack.code', read_only=True)
    zone_name      = serializers.CharField(source='rack.zone.name', read_only=True)
    warehouse_name = serializers.CharField(source='rack.zone.warehouse.name', read_only=True)
    variant_name   = serializers.CharField(source='variant.name', read_only=True)
    product_name   = serializers.CharField(source='variant.product.name', read_only=True)
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = [
            'id', 'rack', 'rack_code', 'zone_name', 'warehouse_name',
            'variant', 'variant_name', 'product_name',
            'movement_type', 'quantity', 'reference', 'notes',
            'performed_by', 'performed_by_name', 'created_at',
        ]
        read_only_fields = fields

    def get_performed_by_name(self, obj):
        if obj.performed_by:
            return obj.performed_by.get_full_name() or obj.performed_by.email
        return None


class StockTransferSerializer(serializers.ModelSerializer):
    from_rack_code = serializers.CharField(source='from_rack.code', read_only=True)
    to_rack_code   = serializers.CharField(source='to_rack.code', read_only=True)
    from_warehouse = serializers.CharField(source='from_rack.zone.warehouse.name', read_only=True)
    to_warehouse   = serializers.CharField(source='to_rack.zone.warehouse.name', read_only=True)
    variant_name   = serializers.CharField(source='variant.name', read_only=True)
    product_name   = serializers.CharField(source='variant.product.name', read_only=True)
    initiated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StockTransfer
        fields = [
            'id', 'from_rack', 'from_rack_code', 'from_warehouse',
            'to_rack', 'to_rack_code', 'to_warehouse',
            'variant', 'variant_name', 'product_name',
            'quantity', 'status', 'notes',
            'initiated_by', 'initiated_by_name',
            'completed_at', 'created_at',
        ]
        read_only_fields = ['id', 'status', 'completed_at', 'created_at', 'initiated_by']

    def get_initiated_by_name(self, obj):
        if obj.initiated_by:
            return obj.initiated_by.get_full_name() or obj.initiated_by.email
        return None


class StockTransferCreateSerializer(serializers.Serializer):
    from_rack = serializers.PrimaryKeyRelatedField(queryset=Rack.objects.filter(is_active=True))
    to_rack   = serializers.PrimaryKeyRelatedField(queryset=Rack.objects.filter(is_active=True))
    variant   = serializers.PrimaryKeyRelatedField(queryset=_PV.objects.all())
    quantity  = serializers.IntegerField(min_value=1)
    notes     = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        if data['from_rack'] == data['to_rack']:
            raise serializers.ValidationError('Source and destination racks must be different.')
        return data


class AssignStockSerializer(serializers.Serializer):
    rack      = serializers.PrimaryKeyRelatedField(queryset=Rack.objects.filter(is_active=True))
    variant   = serializers.PrimaryKeyRelatedField(queryset=_PV.objects.all())
    quantity  = serializers.IntegerField(min_value=1)
    reference = serializers.CharField(required=False, allow_blank=True, default='')
    notes     = serializers.CharField(required=False, allow_blank=True, default='')


class ManualAdjustSerializer(serializers.Serializer):
    rack            = serializers.PrimaryKeyRelatedField(queryset=Rack.objects.filter(is_active=True))
    variant         = serializers.PrimaryKeyRelatedField(queryset=_PV.objects.all())
    adjustment_type = serializers.ChoiceField(choices=['add', 'remove'])
    quantity        = serializers.IntegerField(min_value=1)
    reason          = serializers.CharField(min_length=10)


class ProductVariantLiteSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = _PV
        fields = ['id', 'name', 'sku', 'product_name', 'stock_quantity']
