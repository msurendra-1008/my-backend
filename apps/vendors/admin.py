from django.contrib import admin
from .models import VendorDocument, VendorProfile


class VendorDocumentInline(admin.TabularInline):
    model = VendorDocument
    extra = 0
    readonly_fields = ('label', 'file', 'uploaded_at')
    can_delete = False


@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display   = ('company_name', 'contact_name', 'get_mobile', 'status', 'created_at')
    list_filter    = ('status',)
    search_fields  = ('company_name', 'gst_number', 'user__mobile', 'user__email')
    readonly_fields = ('approved_by', 'approved_at', 'created_at')
    inlines        = [VendorDocumentInline]

    def get_mobile(self, obj):
        return obj.user.mobile
    get_mobile.short_description = 'Mobile'


@admin.register(VendorDocument)
class VendorDocumentAdmin(admin.ModelAdmin):
    list_display  = ('label', 'vendor', 'uploaded_at')
    search_fields = ('label', 'vendor__company_name')
    readonly_fields = ('uploaded_at',)
