from django.contrib import admin
from .models import DiscountCode, OfflineBill, OfflineReturn, BillingSettings


@admin.register(DiscountCode)
class DiscountCodeAdmin(admin.ModelAdmin):
    list_display  = ('code', 'type', 'value', 'used_count', 'max_uses', 'is_active', 'valid_till')
    list_filter   = ('type', 'is_active')
    search_fields = ('code',)


@admin.register(OfflineBill)
class OfflineBillAdmin(admin.ModelAdmin):
    list_display    = ('bill_number', 'customer_type', 'payment_method', 'billed_by', 'created_at')
    search_fields   = ('bill_number',)
    readonly_fields = ('bill_number', 'order', 'created_at')


@admin.register(OfflineReturn)
class OfflineReturnAdmin(admin.ModelAdmin):
    list_display = ('get_bill', 'status', 'total_refund', 'created_at')
    list_filter  = ('status',)

    def get_bill(self, obj):
        return obj.bill.bill_number
    get_bill.short_description = 'Bill'


@admin.register(BillingSettings)
class BillingSettingsAdmin(admin.ModelAdmin):
    list_display    = ('return_window_enabled', 'return_window_days', 'updated_at', 'updated_by')
    readonly_fields = ('updated_at', 'updated_by')

    def has_add_permission(self, request):
        return not BillingSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
