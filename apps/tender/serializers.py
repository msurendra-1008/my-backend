from rest_framework import serializers
from .models import Tender, TenderItem, VendorBid, VendorBidItem, NegotiationLog
from apps.products.models import Product
from apps.vendors.models import VendorProfile
from django.utils import timezone


class TenderItemWriteSerializer(serializers.Serializer):
    product_id        = serializers.UUIDField()
    required_quantity = serializers.IntegerField(min_value=1)
    target_price      = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True)
    notes             = serializers.CharField(required=False, allow_blank=True)

    def validate_product_id(self, value):
        try:
            Product.objects.get(id=value, is_published=True)
        except Product.DoesNotExist:
            raise serializers.ValidationError("Product not found or not published.")
        return value


class TenderCreateSerializer(serializers.Serializer):
    title             = serializers.CharField()
    description       = serializers.CharField(required=False, allow_blank=True)
    bidding_deadline  = serializers.DateTimeField(required=False, allow_null=True)
    items             = TenderItemWriteSerializer(many=True)
    open_immediately  = serializers.BooleanField(default=False)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one product required.")
        return value

    def create(self, validated_data):
        from apps.tender.utils import generate_tender_number
        items_data       = validated_data.pop('items')
        open_immediately = validated_data.pop('open_immediately', False)
        request          = self.context['request']

        tender = Tender.objects.create(
            tender_number = generate_tender_number(),
            status        = 'open' if open_immediately else 'draft',
            created_by    = request.user,
            **validated_data
        )
        for item in items_data:
            product = Product.objects.get(id=item['product_id'])
            TenderItem.objects.create(
                tender            = tender,
                product           = product,
                required_quantity = item['required_quantity'],
                target_price      = item.get('target_price'),
                notes             = item.get('notes', '')
            )
        return tender


class TenderItemSerializer(serializers.ModelSerializer):
    product_name    = serializers.CharField(source='product.name', read_only=True)
    product_image   = serializers.SerializerMethodField()
    bid_count       = serializers.SerializerMethodField()
    awarded_to_name = serializers.CharField(
        source='awarded_to.company_name', read_only=True, allow_null=True)

    class Meta:
        model  = TenderItem
        fields = ['id', 'product_id', 'product_name', 'product_image',
                  'required_quantity', 'target_price', 'notes',
                  'awarded_to', 'awarded_to_name', 'bid_count']

    def get_product_image(self, obj):
        request = self.context.get('request')
        img = obj.product.images.filter(is_primary=True).first()
        if img and request:
            return request.build_absolute_uri(img.image.url)
        return None

    def get_bid_count(self, obj):
        return obj.bid_items.count()


class VendorBidItemSerializer(serializers.ModelSerializer):
    class Meta:
        model  = VendorBidItem
        fields = ['id', 'tender_item', 'supply_quantity',
                  'price_per_unit', 'dispatch_date',
                  'monthly_breakdown', 'notes']

    def validate(self, data):
        breakdown  = data.get('monthly_breakdown', [])
        supply_qty = data.get('supply_quantity', 0)
        if breakdown:
            total = sum(b.get('quantity', 0) for b in breakdown)
            if total != supply_qty:
                raise serializers.ValidationError(
                    f"Monthly breakdown total ({total}) must equal "
                    f"supply quantity ({supply_qty}).")
        if data.get('dispatch_date') and data['dispatch_date'] < timezone.now().date():
            raise serializers.ValidationError(
                "Dispatch date must be in the future.")
        return data


class VendorBidWriteSerializer(serializers.Serializer):
    overall_notes = serializers.CharField(required=False, allow_blank=True)
    items         = VendorBidItemSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Must bid on all products.")
        return value


class NegotiationLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model  = NegotiationLog
        fields = ['id', 'actor_role', 'actor_name', 'message', 'created_at']

    def get_actor_name(self, obj):
        if not obj.actor:
            return 'Unknown'
        if obj.actor_role == 'admin':
            return obj.actor.get_full_name() or obj.actor.email or 'Admin'
        vendor_profile = getattr(obj.actor, 'vendor_profile', None)
        return (vendor_profile.company_name if vendor_profile
                else obj.actor.get_full_name() or obj.actor.email or 'Vendor')


class VendorBidSerializer(serializers.ModelSerializer):
    items              = VendorBidItemSerializer(many=True, read_only=True)
    vendor_name        = serializers.CharField(
                           source='vendor.company_name', read_only=True)
    negotiation_logs   = NegotiationLogSerializer(many=True, read_only=True)

    class Meta:
        model  = VendorBid
        fields = ['id', 'vendor', 'vendor_name', 'status',
                  'overall_notes', 'negotiation_notes',
                  'negotiation_logs',
                  'items', 'submitted_at', 'updated_at', 'update_count']


class TenderListSerializer(serializers.ModelSerializer):
    item_count = serializers.SerializerMethodField()
    bid_count  = serializers.SerializerMethodField()

    class Meta:
        model  = Tender
        fields = ['id', 'tender_number', 'title', 'status',
                  'item_count', 'bid_count',
                  'bidding_deadline', 'created_at']

    def get_item_count(self, obj): return obj.items.count()
    def get_bid_count(self, obj):  return obj.bids.count()


class TenderDetailSerializer(serializers.ModelSerializer):
    items = TenderItemSerializer(many=True, read_only=True)
    bids  = VendorBidSerializer(many=True, read_only=True)

    class Meta:
        model  = Tender
        fields = '__all__'


class TenderDetailVendorSerializer(serializers.ModelSerializer):
    items   = TenderItemSerializer(many=True, read_only=True)
    own_bid = serializers.SerializerMethodField()

    class Meta:
        model  = Tender
        fields = ['id', 'tender_number', 'title', 'description',
                  'status', 'bidding_deadline', 'items', 'own_bid']

    def get_own_bid(self, obj):
        request = self.context.get('request')
        if not request or not hasattr(request.user, 'vendor_profile'):
            return None
        bid = obj.bids.filter(vendor=request.user.vendor_profile).first()
        return VendorBidSerializer(bid, context=self.context).data if bid else None


class BidComparisonSerializer(serializers.Serializer):
    def to_representation(self, tender):
        result = []
        for item in tender.items.all():
            bids_data = []
            for bid_item in item.bid_items.select_related('bid__vendor'):
                bid   = bid_item.bid
                total = bid_item.supply_quantity * bid_item.price_per_unit
                vs_target = None
                if item.target_price:
                    vs_target = float(bid_item.price_per_unit) - float(item.target_price)
                bids_data.append({
                    'bid_id':           str(bid.id),
                    'vendor_name':      bid.vendor.company_name,
                    'bid_status':       bid.status,
                    'supply_quantity':  bid_item.supply_quantity,
                    'price_per_unit':   str(bid_item.price_per_unit),
                    'total_value':      str(total),
                    'vs_target':        vs_target,
                    'dispatch_date':    str(bid_item.dispatch_date),
                    'notes':            bid_item.notes,
                })
            result.append({
                'tender_item': {
                    'id':               str(item.id),
                    'product_name':     item.product.name,
                    'required_quantity': item.required_quantity,
                    'target_price':     str(item.target_price) if item.target_price else None,
                },
                'bids': bids_data,
            })
        return result


class AwardTenderSerializer(serializers.Serializer):
    awarded_items = serializers.ListField(
        child=serializers.DictField())

    def validate_awarded_items(self, value):
        if not value:
            raise serializers.ValidationError("awarded_items cannot be empty.")
        tender = self.context['tender']
        tender_item_ids = set(
            str(i.id) for i in tender.items.all())
        covered = set()
        for entry in value:
            tid    = str(entry.get('tender_item_id', ''))
            bid_id = str(entry.get('vendor_bid_id', ''))
            if tid not in tender_item_ids:
                raise serializers.ValidationError(
                    f"tender_item {tid} does not belong to this tender.")
            if not tender.bids.filter(id=bid_id).exists():
                raise serializers.ValidationError(
                    f"vendor_bid {bid_id} does not belong to this tender.")
            covered.add(tid)
        if covered != tender_item_ids:
            raise serializers.ValidationError(
                "All tender items must be awarded.")
        return value
