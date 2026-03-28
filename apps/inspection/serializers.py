from rest_framework import serializers

from .models import InspectionReport, InspectionSettings, IncomingShipment
from .utils import REJECTION_REASONS, generate_debit_note_pdf, update_product_stock


# ── Settings ──────────────────────────────────────────────────────────────────

class InspectionSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model  = InspectionSettings
        fields = ['auto_stock_update']


# ── Report (read) ─────────────────────────────────────────────────────────────

class InspectionReportReadSerializer(serializers.ModelSerializer):
    inspected_by_name         = serializers.SerializerMethodField()
    stock_updated_by_name     = serializers.SerializerMethodField()
    debit_note_url            = serializers.SerializerMethodField()
    rejection_breakdown_labeled = serializers.SerializerMethodField()

    class Meta:
        model  = InspectionReport
        fields = [
            'id',
            'received_quantity', 'accepted_quantity',
            'rejected_quantity', 'missing_quantity',
            'rejection_breakdown', 'rejection_breakdown_labeled',
            'rejection_other_notes', 'general_notes',
            'inspected_by_name', 'inspected_at',
            'stock_updated', 'stock_updated_at', 'stock_updated_by_name',
            'debit_note_url', 'debit_note_generated_at',
        ]

    def get_inspected_by_name(self, obj):
        return obj.inspected_by.get_full_name() or str(obj.inspected_by.mobile)

    def get_stock_updated_by_name(self, obj):
        if obj.stock_updated_by:
            return obj.stock_updated_by.get_full_name() or str(obj.stock_updated_by.mobile)
        return None

    def get_debit_note_url(self, obj):
        if not obj.debit_note:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.debit_note.url)
        return obj.debit_note.url

    def get_rejection_breakdown_labeled(self, obj):
        return {REJECTION_REASONS.get(k, k): v for k, v in obj.rejection_breakdown.items()}


# ── Shipment (list) ───────────────────────────────────────────────────────────

class IncomingShipmentListSerializer(serializers.ModelSerializer):
    po_number         = serializers.CharField(source='purchase_order.po_number')
    vendor_company    = serializers.CharField(source='purchase_order.vendor.company_name')
    product_name      = serializers.CharField(source='purchase_order.product.name')
    product_image_url = serializers.SerializerMethodField()
    has_report        = serializers.SerializerMethodField()
    stock_updated     = serializers.SerializerMethodField()

    class Meta:
        model  = IncomingShipment
        fields = [
            'id', 'po_number', 'vendor_company', 'product_name', 'product_image_url',
            'expected_quantity', 'status', 'created_at', 'has_report', 'stock_updated',
        ]

    def get_product_image_url(self, obj):
        request = self.context.get('request')
        product = obj.purchase_order.product
        img = product.images.filter(is_primary=True).first()
        if img and img.image and request:
            return request.build_absolute_uri(img.image.url)
        return None

    def get_has_report(self, obj):
        return hasattr(obj, 'report')

    def get_stock_updated(self, obj):
        return obj.report.stock_updated if hasattr(obj, 'report') else False


# ── Shipment (detail) ─────────────────────────────────────────────────────────

class IncomingShipmentDetailSerializer(serializers.ModelSerializer):
    po_number         = serializers.CharField(source='purchase_order.po_number')
    vendor_company    = serializers.CharField(source='purchase_order.vendor.company_name')
    product_name      = serializers.CharField(source='purchase_order.product.name')
    product_image_url = serializers.SerializerMethodField()
    price_per_unit    = serializers.DecimalField(
        source='purchase_order.price_per_unit', max_digits=12, decimal_places=2,
    )
    total_amount      = serializers.DecimalField(
        source='purchase_order.total_amount', max_digits=14, decimal_places=2,
    )
    report            = serializers.SerializerMethodField()

    class Meta:
        model  = IncomingShipment
        fields = [
            'id', 'po_number', 'vendor_company', 'product_name', 'product_image_url',
            'price_per_unit', 'total_amount',
            'expected_quantity', 'status', 'created_at', 'report',
        ]

    def get_product_image_url(self, obj):
        request = self.context.get('request')
        product = obj.purchase_order.product
        img = product.images.filter(is_primary=True).first()
        if img and img.image and request:
            return request.build_absolute_uri(img.image.url)
        return None

    def get_report(self, obj):
        if hasattr(obj, 'report'):
            return InspectionReportReadSerializer(obj.report, context=self.context).data
        return None


# ── Report (write / submit) ───────────────────────────────────────────────────

class InspectionReportWriteSerializer(serializers.Serializer):
    received_quantity     = serializers.IntegerField(min_value=0)
    accepted_quantity     = serializers.IntegerField(min_value=0)
    rejected_quantity     = serializers.IntegerField(min_value=0)
    rejection_breakdown   = serializers.DictField(
        child=serializers.IntegerField(min_value=0), required=False, default=dict,
    )
    rejection_other_notes = serializers.CharField(required=False, allow_blank=True, default='')
    general_notes         = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        shipment = self.context['shipment']
        expected = shipment.expected_quantity
        received = data['received_quantity']
        accepted = data['accepted_quantity']
        rejected = data['rejected_quantity']
        breakdown = data.get('rejection_breakdown', {})

        if received > expected:
            raise serializers.ValidationError({
                'received_quantity': (
                    f'Received ({received}) cannot exceed expected ({expected}).'
                ),
            })

        if accepted + rejected != received:
            raise serializers.ValidationError({
                'accepted_quantity': (
                    f'accepted ({accepted}) + rejected ({rejected}) must equal '
                    f'received ({received}).'
                ),
            })

        if rejected > 0:
            if not breakdown:
                raise serializers.ValidationError({
                    'rejection_breakdown': (
                        'rejection_breakdown is required when rejected_quantity > 0.'
                    ),
                })
            invalid = [k for k in breakdown if k not in REJECTION_REASONS]
            if invalid:
                raise serializers.ValidationError({
                    'rejection_breakdown': (
                        f'Invalid reason keys: {invalid}. '
                        f'Valid: {list(REJECTION_REASONS.keys())}'
                    ),
                })
            bd_sum = sum(breakdown.values())
            if bd_sum != rejected:
                raise serializers.ValidationError({
                    'rejection_breakdown': (
                        f'Breakdown total ({bd_sum}) must equal '
                        f'rejected_quantity ({rejected}).'
                    ),
                })
            if breakdown.get('other', 0) > 0:
                notes = data.get('rejection_other_notes', '').strip()
                if len(notes) < 10:
                    raise serializers.ValidationError({
                        'rejection_other_notes': (
                            'Notes required (min 10 chars) when "other" reason is used.'
                        ),
                    })

        return data

    def create(self, validated_data):
        from django.utils import timezone as tz

        shipment     = self.context['shipment']
        user         = self.context['request'].user
        settings_obj = InspectionSettings.get_settings()

        missing = shipment.expected_quantity - validated_data['received_quantity']

        report = InspectionReport.objects.create(
            shipment               = shipment,
            received_quantity      = validated_data['received_quantity'],
            accepted_quantity      = validated_data['accepted_quantity'],
            rejected_quantity      = validated_data['rejected_quantity'],
            missing_quantity       = missing,
            rejection_breakdown    = validated_data.get('rejection_breakdown', {}),
            rejection_other_notes  = validated_data.get('rejection_other_notes', ''),
            general_notes          = validated_data.get('general_notes', ''),
            inspected_by           = user,
        )

        shipment.status = 'completed'
        shipment.save(update_fields=['status'])

        po = shipment.purchase_order
        po.status = 'inspection_pending'
        po.save(update_fields=['status'])

        if report.rejected_quantity > 0:
            try:
                generate_debit_note_pdf(report)
            except Exception:
                pass  # PDF failure must not roll back the report

        if settings_obj.auto_stock_update:
            update_product_stock(report, user)

        return report
