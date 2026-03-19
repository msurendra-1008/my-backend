from django.contrib import admin
from .models import Address, Cart, CartItem, Order, OrderItem


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ["user", "name", "city", "state", "is_default"]
    list_filter  = ["is_default", "state"]


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ["user", "created_at"]
    inlines = [CartItemInline]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ["product_name", "variant_name", "sku", "mrp", "upa_price", "quantity", "line_total", "status"]
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display  = ["order_number", "user", "order_status", "payment_status", "amount_payable", "created_at"]
    list_filter   = ["order_status", "payment_status"]
    search_fields = ["order_number", "user__mobile", "user__first_name"]
    inlines       = [OrderItemInline]
    readonly_fields = [
        "order_number", "subtotal", "upa_discount", "amount_payable",
        "wallet_used", "razorpay_amount", "razorpay_order_id",
        "razorpay_payment_id", "razorpay_signature",
    ]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display  = ["order", "product_name", "variant_name", "quantity", "upa_price", "status"]
    list_filter   = ["status"]
    search_fields = ["order__order_number", "product_name"]
