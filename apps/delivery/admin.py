from django.contrib import admin
from .models import DeliveryZone, DeliveryPartner, DeliverySettings, DeliveryAssignment, DeliveryStatusLog


@admin.register(DeliveryZone)
class DeliveryZoneAdmin(admin.ModelAdmin):
    list_display  = ('name', 'is_active', 'created_at')
    list_filter   = ('is_active',)
    search_fields = ('name', 'pincodes')


@admin.register(DeliveryPartner)
class DeliveryPartnerAdmin(admin.ModelAdmin):
    list_display  = ('__str__', 'vehicle_type', 'vehicle_number', 'is_active', 'created_at')
    list_filter   = ('vehicle_type', 'is_active')
    search_fields = ('user__first_name', 'user__last_name', 'user__email', 'vehicle_number')
    filter_horizontal = ('zones',)


@admin.register(DeliverySettings)
class DeliverySettingsAdmin(admin.ModelAdmin):
    list_display = ('auto_assign', 'assignment_mode', 'updated_at')


class DeliveryStatusLogInline(admin.TabularInline):
    model  = DeliveryStatusLog
    extra  = 0
    fields = ('status', 'notes', 'created_by', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(DeliveryAssignment)
class DeliveryAssignmentAdmin(admin.ModelAdmin):
    list_display  = ('order', 'partner', 'status', 'assigned_at', 'delivered_at')
    list_filter   = ('status',)
    search_fields = ('order__order_number', 'partner__user__first_name')
    inlines       = [DeliveryStatusLogInline]
    readonly_fields = ('otp', 'assigned_at')


@admin.register(DeliveryStatusLog)
class DeliveryStatusLogAdmin(admin.ModelAdmin):
    list_display = ('assignment', 'status', 'created_at', 'created_by')
    list_filter  = ('status',)
