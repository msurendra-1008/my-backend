import re
from datetime import date

from rest_framework import serializers

from apps.vendors.models import VendorProduct
from .models import ProcurementRequirement, VendorResponse, PurchaseOrder

# ── Helpers ───────────────────────────────────────────────────────────────────

ACTIVE_STATUSES = ('draft', 'sent', 'vendor_responded', 'negotiating')


def _product_image(product, request):
    """Return absolute URL of product's primary image (or None)."""
    img = product.images.filter(is_primary=True).first() or product.images.first()
    if not img:
        return None
    return request.build_absolute_uri(img.image.url) if request else img.image.url


# ── VendorResponse ────────────────────────────────────────────────────────────

class VendorResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model  = VendorResponse
        fields = [
            'id', 'supply_quantity', 'price_per_unit', 'dispatch_date',
            'monthly_breakdown', 'notes', 'submitted_at', 'updated_at', 'update_count',
        ]
        read_only_fields = ['id', 'submitted_at', 'updated_at', 'update_count']

    def validate_dispatch_date(self, value):
        if value < date.today():
            raise serializers.ValidationError('Dispatch date must be today or in the future.')
        return value

    def validate_monthly_breakdown(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('monthly_breakdown must be a list.')
        months_seen = set()
        for entry in value:
            if not isinstance(entry, dict) or 'month' not in entry or 'quantity' not in entry:
                raise serializers.ValidationError(
                    'Each breakdown entry must have "month" and "quantity" keys.'
                )
            m = entry['month']
            if not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])', str(m)):
                raise serializers.ValidationError(
                    f'Invalid month format "{m}". Use YYYY-MM.'
                )
            if m in months_seen:
                raise serializers.ValidationError(f'Duplicate month: {m}.')
            months_seen.add(m)
            if not isinstance(entry['quantity'], int) or entry['quantity'] < 0:
                raise serializers.ValidationError('Quantity must be a non-negative integer.')
        return value

    def validate(self, data):
        supply_qty = data.get('supply_quantity')
        breakdown  = data.get('monthly_breakdown', [])
        if supply_qty is not None and breakdown:
            total = sum(e['quantity'] for e in breakdown)
            if total != supply_qty:
                raise serializers.ValidationError(
                    {'monthly_breakdown': (
                        f'Sum of monthly quantities ({total}) must equal '
                        f'supply_quantity ({supply_qty}).'
                    )}
                )
        return data


# ── PurchaseOrder ─────────────────────────────────────────────────────────────

class PurchaseOrderSerializer(serializers.ModelSerializer):
    vendor_company   = serializers.SerializerMethodField()
    product_name     = serializers.SerializerMethodField()
    product_image    = serializers.SerializerMethodField()
    shipment_status  = serializers.SerializerMethodField()
    has_debit_note   = serializers.SerializerMethodField()
    debit_note_url   = serializers.SerializerMethodField()

    class Meta:
        model  = PurchaseOrder
        fields = [
            'id', 'po_number', 'vendor_company', 'product_name', 'product_image',
            'quantity', 'price_per_unit', 'total_amount',
            'monthly_breakdown', 'dispatch_date', 'status',
            'vendor_notes', 'admin_notes',
            'generated_at', 'acknowledged_at', 'dispatched_at',
            'shipment_status', 'has_debit_note', 'debit_note_url',
        ]

    def get_vendor_company(self, obj):
        return obj.vendor.company_name

    def get_product_name(self, obj):
        return obj.product.name

    def get_product_image(self, obj):
        return _product_image(obj.product, self.context.get('request'))

    def get_shipment_status(self, obj):
        try:
            return obj.shipment.status
        except Exception:
            return None

    def get_has_debit_note(self, obj):
        try:
            return bool(obj.shipment.report.debit_note)
        except Exception:
            return False

    def get_debit_note_url(self, obj):
        request = self.context.get('request')
        try:
            dn = obj.shipment.report.debit_note
            if dn and request:
                return request.build_absolute_uri(dn.url)
            if dn:
                return dn.url
        except Exception:
            pass
        return None


# ── ProcurementRequirement (admin read) ──────────────────────────────────────

class ProcurementRequirementSerializer(serializers.ModelSerializer):
    vendor_company   = serializers.SerializerMethodField()
    product_name     = serializers.SerializerMethodField()
    product_image    = serializers.SerializerMethodField()
    vendor_response  = VendorResponseSerializer(read_only=True)
    po               = PurchaseOrderSerializer(source='purchase_order', read_only=True)
    created_by_name  = serializers.SerializerMethodField()

    class Meta:
        model  = ProcurementRequirement
        fields = [
            'id', 'vendor_company', 'product_name', 'product_image',
            'required_quantity', 'required_by_date', 'target_price', 'notes',
            'status', 'negotiation_notes', 'cancellation_reason',
            'vendor_response', 'po',
            'created_by_name', 'created_at', 'sent_at', 'confirmed_at',
        ]

    def get_vendor_company(self, obj):
        return obj.vendor.company_name

    def get_product_name(self, obj):
        return obj.product.name if obj.product else obj.vendor_product.name

    def get_product_image(self, obj):
        if obj.product:
            return _product_image(obj.product, self.context.get('request'))
        return None

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name()
        return None


class ProcurementRequirementListSerializer(serializers.ModelSerializer):
    vendor_company = serializers.SerializerMethodField()
    product_name   = serializers.SerializerMethodField()
    product_image  = serializers.SerializerMethodField()

    class Meta:
        model  = ProcurementRequirement
        fields = [
            'id', 'vendor_company', 'product_name', 'product_image',
            'required_quantity', 'required_by_date', 'target_price',
            'status', 'created_at',
        ]

    def get_vendor_company(self, obj):
        return obj.vendor.company_name

    def get_product_name(self, obj):
        return obj.product.name if obj.product else obj.vendor_product.name

    def get_product_image(self, obj):
        if obj.product:
            return _product_image(obj.product, self.context.get('request'))
        return None


class ProcurementRequirementCreateSerializer(serializers.Serializer):
    vendor_product_id  = serializers.UUIDField()
    required_quantity  = serializers.IntegerField(min_value=1)
    required_by_date   = serializers.DateField()
    target_price       = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    notes              = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_vendor_product_id(self, value):
        try:
            vp = VendorProduct.objects.get(pk=value)
        except VendorProduct.DoesNotExist:
            raise serializers.ValidationError('Vendor product not found.')
        if vp.status != 'approved':
            raise serializers.ValidationError('Vendor product must be approved before creating a requirement.')
        if vp.catalog_product is None:
            raise serializers.ValidationError('Vendor product has no linked catalog product.')
        return value

    def validate(self, data):
        vp_id = data.get('vendor_product_id')
        if vp_id:
            active = ProcurementRequirement.objects.filter(
                vendor_product_id=vp_id,
                status__in=ACTIVE_STATUSES,
            ).exists()
            if active:
                raise serializers.ValidationError(
                    'An active requirement already exists for this vendor product.'
                )
        if data.get('required_by_date') and data['required_by_date'] < date.today():
            raise serializers.ValidationError({'required_by_date': 'Required-by date must be in the future.'})
        return data

    def create(self, validated_data):
        vp = VendorProduct.objects.get(pk=validated_data['vendor_product_id'])
        return ProcurementRequirement.objects.create(
            vendor_product  = vp,
            vendor          = vp.vendor,
            product         = vp.catalog_product,
            required_quantity = validated_data['required_quantity'],
            required_by_date  = validated_data['required_by_date'],
            target_price      = validated_data.get('target_price'),
            notes             = validated_data.get('notes', ''),
            created_by        = self.context['request'].user,
            status            = 'draft',
        )


class ProcurementRequirementUpdateSerializer(serializers.ModelSerializer):
    """Admin edits a draft requirement."""
    class Meta:
        model  = ProcurementRequirement
        fields = ['required_quantity', 'required_by_date', 'target_price', 'notes']


# ── Vendor-facing requirement read ────────────────────────────────────────────

class ProcurementRequirementVendorSerializer(serializers.ModelSerializer):
    product_name      = serializers.SerializerMethodField()
    product_image     = serializers.SerializerMethodField()
    vendor_response   = VendorResponseSerializer(read_only=True)

    class Meta:
        model  = ProcurementRequirement
        fields = [
            'id', 'product_name', 'product_image',
            'required_quantity', 'required_by_date', 'target_price', 'notes',
            'status', 'negotiation_notes',
            'vendor_response', 'sent_at',
        ]

    def get_product_name(self, obj):
        return obj.product.name if obj.product else obj.vendor_product.name

    def get_product_image(self, obj):
        if obj.product:
            return _product_image(obj.product, self.context.get('request'))
        return None
