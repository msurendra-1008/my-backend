from django.contrib import admin
from apps.company_wallet.models import CompanyWallet, CompanyTransaction, GSTLedgerEntry


@admin.register(CompanyWallet)
class CompanyWalletAdmin(admin.ModelAdmin):
    list_display  = ('id', 'balance', 'updated_at')
    readonly_fields = ('id', 'balance', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return not CompanyWallet.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CompanyTransaction)
class CompanyTransactionAdmin(admin.ModelAdmin):
    list_display   = ('transaction_type', 'amount', 'balance_after', 'description', 'created_at')
    list_filter    = ('transaction_type',)
    search_fields  = ('description',)
    readonly_fields = ('id', 'wallet', 'balance_after', 'created_at', 'updated_at')
    ordering       = ('-created_at',)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(GSTLedgerEntry)
class GSTLedgerEntryAdmin(admin.ModelAdmin):
    list_display  = ('gst_type', 'amount', 'description', 'reference', 'created_at')
    list_filter   = ('gst_type',)
    search_fields = ('description', 'reference')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering      = ('-created_at',)
