from django.contrib import admin
from django.utils.html import format_html
from .models import ReturnRequest, ReturnPhoto, ReturnRequestLog, ReturnSettings


class ReturnPhotoInline(admin.TabularInline):
    model = ReturnPhoto
    extra = 0
    readonly_fields = ('photo_preview', 'log', 'created_at')
    fields = ('photo_preview', 'log', 'created_at')
    can_delete = False

    def photo_preview(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" style="height:60px;border-radius:4px;"/>',
                obj.photo.url
            )
        return '-'
    photo_preview.short_description = 'Preview'


class ReturnRequestLogInline(admin.TabularInline):
    model = ReturnRequestLog
    extra = 0
    readonly_fields = ('action', 'actor', 'actor_role', 'notes', 'created_at')
    fields = ('action', 'actor', 'actor_role', 'notes', 'created_at')
    can_delete = False
    ordering = ('created_at',)


@admin.register(ReturnRequestLog)
class ReturnRequestLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'return_request', 'action', 'actor', 'actor_role', 'created_at')
    list_filter  = ('action', 'actor_role')
    search_fields = ('return_request__id', 'actor__mobile', 'notes')
    readonly_fields = ('return_request', 'actor', 'created_at')


@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'get_user', 'get_order_number', 'get_product',
        'request_type', 'status', 'waiting_for', 'attempt_count',
        'return_qty', 'refund_amount', 'created_at'
    )
    list_filter = ('status', 'request_type', 'waiting_for', 'created_at')
    search_fields = (
        'order_item__order__order_number',
        'order_item__order__user__mobile',
        'order_item__order__user__first_name',
        'order_item__product_name',
    )
    readonly_fields = (
        'raised_by', 'created_at', 'reviewed_by',
        'reviewed_at', 'completed_at', 'refund_amount',
        'waiting_for', 'attempt_count',
    )
    inlines = [ReturnPhotoInline, ReturnRequestLogInline]
    ordering = ('-created_at',)

    def get_user(self, obj):
        if obj.raised_by:
            return obj.raised_by.get_full_name() or obj.raised_by.mobile
        return '-'
    get_user.short_description = 'User'

    def get_order_number(self, obj):
        return obj.order_item.order.order_number
    get_order_number.short_description = 'Order'

    def get_product(self, obj):
        return obj.order_item.product_name
    get_product.short_description = 'Product'


@admin.register(ReturnSettings)
class ReturnSettingsAdmin(admin.ModelAdmin):
    list_display = ('return_window_days', 'updated_by', 'updated_at')

    def has_add_permission(self, request):
        # Only allow one row — disable Add button if record exists
        return not ReturnSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
