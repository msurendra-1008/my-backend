from django.contrib import admin

from .models import Category, Product, ProductImage, ProductVariant, UPADiscountSettings


# ── Category ──────────────────────────────────────────────────────────────────

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display   = ('name', 'parent', 'slug', 'is_active', 'created_at')
    list_filter    = ('is_active', 'parent')
    search_fields  = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('id', 'created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'parent', 'is_active'),
        }),
        ('Metadata', {
            'classes': ('collapse',),
            'fields': ('id', 'created_at', 'updated_at'),
        }),
    )


# ── Inlines ───────────────────────────────────────────────────────────────────

class ProductImageInline(admin.TabularInline):
    model          = ProductImage
    extra          = 1
    fields         = ('image', 'alt_text', 'order', 'is_primary')
    readonly_fields = ('id',)


class ProductVariantInline(admin.TabularInline):
    model           = ProductVariant
    extra           = 1
    fields          = ('name', 'variant_type', 'sku', 'mrp', 'upa_price_override', 'stock_quantity', 'is_active')
    readonly_fields = ('id',)
    show_change_link = True


# ── Product ───────────────────────────────────────────────────────────────────

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display   = ('name', 'sku', 'category', 'mrp', 'is_published', 'created_at')
    list_filter    = ('is_published', 'category')
    search_fields  = ('name', 'sku', 'barcode')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('id', 'created_at', 'updated_at', 'created_by')
    inlines        = [ProductImageInline, ProductVariantInline]
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'description', 'category', 'is_published'),
        }),
        ('Pricing', {
            'fields': ('sku', 'barcode', 'mrp', 'upa_discount_override', 'upa_price_override'),
        }),
        ('Metadata', {
            'classes': ('collapse',),
            'fields': ('id', 'created_by', 'created_at', 'updated_at'),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# ── ProductVariant (standalone) ───────────────────────────────────────────────

@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display   = ('name', 'product', 'variant_type', 'sku', 'mrp', 'stock_quantity', 'is_active')
    list_filter    = ('variant_type', 'is_active', 'product__category')
    search_fields  = ('name', 'sku', 'product__name')
    readonly_fields = ('id', 'created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('product', 'name', 'variant_type', 'sku', 'is_active'),
        }),
        ('Pricing & Stock', {
            'fields': ('mrp', 'upa_price_override', 'stock_quantity'),
        }),
        ('Metadata', {
            'classes': ('collapse',),
            'fields': ('id', 'created_at', 'updated_at'),
        }),
    )


# ── UPADiscountSettings ───────────────────────────────────────────────────────

@admin.register(UPADiscountSettings)
class UPADiscountSettingsAdmin(admin.ModelAdmin):
    list_display  = ('global_discount_percent', 'updated_by', 'updated_at')
    readonly_fields = ('updated_by', 'updated_at')

    def has_add_permission(self, request):
        # Singleton — disallow creating a second row
        return not UPADiscountSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
