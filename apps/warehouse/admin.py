from django.contrib import admin

from .models import Warehouse, Zone, Rack, RackStock, StockMovement, StockTransfer


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ['name', 'location', 'is_active', 'created_at']
    list_filter  = ['is_active']
    search_fields = ['name', 'location']


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ['name', 'warehouse', 'is_active', 'created_at']
    list_filter  = ['is_active', 'warehouse']
    search_fields = ['name']


@admin.register(Rack)
class RackAdmin(admin.ModelAdmin):
    list_display = ['code', 'zone', 'capacity', 'is_active', 'created_at']
    list_filter  = ['is_active', 'zone__warehouse']
    search_fields = ['code']


@admin.register(RackStock)
class RackStockAdmin(admin.ModelAdmin):
    list_display = ['rack', 'variant', 'quantity', 'last_updated']
    list_filter  = ['rack__zone__warehouse']
    search_fields = ['variant__name', 'variant__sku']


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display  = ['movement_type', 'quantity', 'variant', 'rack', 'reference', 'created_at']
    list_filter   = ['movement_type']
    search_fields = ['reference', 'variant__name']
    readonly_fields = ['id', 'created_at']


@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display  = ['from_rack', 'to_rack', 'variant', 'quantity', 'status', 'created_at']
    list_filter   = ['status']
    search_fields = ['variant__name']
