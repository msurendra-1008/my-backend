from django.contrib import admin
from .models import ProcurementRequirement, VendorResponse, PurchaseOrder


class VendorResponseInline(admin.StackedInline):
    model           = VendorResponse
    extra           = 0
    readonly_fields = ('submitted_at', 'updated_at', 'update_count')
    can_delete      = False


@admin.register(ProcurementRequirement)
class ProcurementRequirementAdmin(admin.ModelAdmin):
    list_display    = ('id', 'get_product', 'get_vendor', 'required_quantity', 'status', 'required_by_date', 'created_at')
    list_filter     = ('status',)
    search_fields   = ('product__name', 'vendor__company_name')
    readonly_fields = ('created_by', 'created_at', 'sent_at', 'confirmed_at', 'confirmed_by', 'cancelled_at')
    inlines         = [VendorResponseInline]

    def get_product(self, obj):
        return obj.product.name if obj.product else obj.vendor_product.name
    get_product.short_description = 'Product'

    def get_vendor(self, obj):
        return obj.vendor.company_name
    get_vendor.short_description = 'Vendor'


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display    = ('po_number', 'get_vendor', 'get_product', 'quantity', 'total_amount', 'status', 'generated_at')
    list_filter     = ('status',)
    search_fields   = ('po_number', 'vendor__company_name', 'product__name')
    readonly_fields = ('po_number', 'generated_at', 'acknowledged_at', 'dispatched_at')

    def get_vendor(self, obj):
        return obj.vendor.company_name
    get_vendor.short_description = 'Vendor'

    def get_product(self, obj):
        return obj.product.name
    get_product.short_description = 'Product'
