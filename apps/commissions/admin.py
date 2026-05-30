from django.contrib import admin
from .models import CommissionSettings, ProductCommissionRule, CommissionBreakup, CommissionEntry


@admin.register(CommissionSettings)
class CommissionSettingsAdmin(admin.ModelAdmin):
    list_display  = ['id', 'network_commission_pct', 'team_commission_pct', 'direction', 'trigger_mode', 'updated_by']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(ProductCommissionRule)
class ProductCommissionRuleAdmin(admin.ModelAdmin):
    list_display   = ['product', 'is_active', 'network_commission_pct', 'team_commission_pct', 'direction']
    list_filter    = ['is_active', 'direction']
    search_fields  = ['product__name']
    readonly_fields = ['id', 'created_at', 'updated_at']


class CommissionEntryInline(admin.TabularInline):
    model           = CommissionEntry
    extra           = 0
    readonly_fields = [
        'id', 'recipient', 'recipient_upa_id', 'recipient_name', 'recipient_mobile',
        'entry_type', 'level', 'leg_position', 'amount', 'percentage_applied',
        'status', 'credited_at', 'wallet_transaction', 'created_at',
    ]
    can_delete = False


@admin.register(CommissionBreakup)
class CommissionBreakupAdmin(admin.ModelAdmin):
    list_display    = ['order_item', 'total_base_amount', 'network_pool', 'team_pool', 'status', 'return_window_expires', 'processed_at']
    list_filter     = ['status']
    search_fields   = ['order_item__product_name', 'order_item__order__order_number']
    readonly_fields = ['id', 'created_at', 'updated_at']
    inlines         = [CommissionEntryInline]


@admin.register(CommissionEntry)
class CommissionEntryAdmin(admin.ModelAdmin):
    list_display   = ['entry_type', 'level', 'leg_position', 'recipient_name', 'amount', 'percentage_applied', 'status', 'credited_at']
    list_filter    = ['entry_type', 'status']
    search_fields  = ['recipient_name', 'recipient_upa_id', 'recipient_mobile']
    readonly_fields = ['id', 'created_at', 'updated_at']
