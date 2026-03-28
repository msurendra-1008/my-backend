from django.contrib import admin

from .models import IncomingShipment, InspectionReport, InspectionSettings


@admin.register(InspectionSettings)
class InspectionSettingsAdmin(admin.ModelAdmin):
    list_display = ('auto_stock_update', 'updated_at')

    def has_add_permission(self, request):
        return not InspectionSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IncomingShipment)
class IncomingShipmentAdmin(admin.ModelAdmin):
    list_display   = ('get_po', 'get_vendor', 'get_product', 'expected_quantity', 'status', 'created_at')
    list_filter    = ('status',)
    search_fields  = ('purchase_order__po_number', 'purchase_order__vendor__company_name')
    readonly_fields = ('purchase_order', 'created_at')

    def get_po(self, obj):
        return obj.purchase_order.po_number
    get_po.short_description = 'PO Number'

    def get_vendor(self, obj):
        return obj.purchase_order.vendor.company_name
    get_vendor.short_description = 'Vendor'

    def get_product(self, obj):
        return obj.purchase_order.product.name
    get_product.short_description = 'Product'


@admin.register(InspectionReport)
class InspectionReportAdmin(admin.ModelAdmin):
    list_display    = (
        'get_po', 'received_quantity', 'accepted_quantity',
        'rejected_quantity', 'missing_quantity', 'stock_updated', 'inspected_at',
    )
    list_filter     = ('stock_updated',)
    readonly_fields = (
        'shipment', 'inspected_by', 'inspected_at',
        'stock_updated_at', 'stock_updated_by', 'missing_quantity',
    )

    def get_po(self, obj):
        return obj.shipment.purchase_order.po_number
    get_po.short_description = 'PO Number'
