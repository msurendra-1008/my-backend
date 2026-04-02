from django.contrib import admin
from .models import Tender, TenderItem, VendorBid, VendorBidItem, NegotiationLog


class TenderItemInline(admin.TabularInline):
    model = TenderItem
    extra = 0
    readonly_fields = ('product', 'required_quantity',
                       'awarded_to', 'awarded_bid')


class VendorBidInline(admin.TabularInline):
    model = VendorBid
    extra = 0
    readonly_fields = ('vendor', 'status', 'update_count', 'submitted_at')
    can_delete = False


@admin.register(Tender)
class TenderAdmin(admin.ModelAdmin):
    list_display   = ('tender_number', 'title', 'status',
                      'get_items', 'get_bids',
                      'bidding_deadline', 'created_at')
    list_filter    = ('status',)
    search_fields  = ('tender_number', 'title')
    readonly_fields = ('tender_number', 'created_by', 'created_at',
                       'closed_at', 'awarded_at')
    inlines        = [TenderItemInline, VendorBidInline]

    def get_items(self, obj): return obj.items.count()
    get_items.short_description = 'Products'

    def get_bids(self, obj): return obj.bids.count()
    get_bids.short_description = 'Bids'


@admin.register(NegotiationLog)
class NegotiationLogAdmin(admin.ModelAdmin):
    list_display    = ('get_tender', 'actor_role', 'get_vendor',
                       'message', 'created_at')
    list_filter     = ('actor_role',)
    readonly_fields = ('bid', 'actor', 'actor_role', 'message', 'created_at')

    def get_tender(self, obj):
        return obj.bid.tender.tender_number
    get_tender.short_description = 'Tender'

    def get_vendor(self, obj):
        return obj.bid.vendor.company_name
    get_vendor.short_description = 'Vendor'
