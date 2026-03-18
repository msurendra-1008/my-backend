from decimal import Decimal

from rest_framework import serializers

from apps.products.utils import get_upa_price
from .models import Address, Cart, CartItem, Order, OrderItem


# ── Address ───────────────────────────────────────────────────────────────────

class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Address
        fields = [
            "id", "name", "phone", "address_line",
            "city", "state", "pincode", "is_default",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


# ── Cart ──────────────────────────────────────────────────────────────────────

class CartItemSerializer(serializers.ModelSerializer):
    variant_id   = serializers.UUIDField(source="variant.id",           read_only=True)
    variant_name = serializers.CharField(source="variant.name",         read_only=True)
    variant_type = serializers.CharField(source="variant.variant_type", read_only=True)
    product_name = serializers.CharField(source="variant.product.name", read_only=True)
    product_slug = serializers.CharField(source="variant.product.slug", read_only=True)
    sku          = serializers.CharField(source="variant.sku",          read_only=True)
    stock        = serializers.IntegerField(source="variant.stock_quantity", read_only=True)
    mrp          = serializers.DecimalField(
        source="variant.mrp", max_digits=12, decimal_places=2, read_only=True
    )
    upa_price    = serializers.SerializerMethodField()
    primary_image = serializers.SerializerMethodField()

    class Meta:
        model  = CartItem
        fields = [
            "id", "variant_id", "variant_name", "variant_type",
            "product_name", "product_slug", "sku", "stock",
            "mrp", "upa_price", "primary_image", "quantity",
        ]

    def get_upa_price(self, obj):
        price_data = get_upa_price(obj.variant)
        return price_data["upa_price"]

    def get_primary_image(self, obj):
        request = self.context.get("request")
        img = obj.variant.product.images.filter(is_primary=True).first()
        if not img:
            img = obj.variant.product.images.first()
        if img and img.image:
            if request:
                return request.build_absolute_uri(img.image.url)
            return img.image.url
        return None


class CartSerializer(serializers.ModelSerializer):
    items    = CartItemSerializer(many=True, read_only=True)
    totals   = serializers.SerializerMethodField()

    class Meta:
        model  = Cart
        fields = ["id", "items", "totals"]

    def get_totals(self, obj):
        subtotal = Decimal("0")
        discount = Decimal("0")
        for item in obj.items.select_related("variant__product").all():
            price_data = get_upa_price(item.variant)
            mrp       = Decimal(price_data["mrp"])
            upa       = Decimal(price_data["upa_price"])
            subtotal += mrp * item.quantity
            discount += (mrp - upa) * item.quantity
        payable = subtotal - discount
        return {
            "subtotal":       str(subtotal.quantize(Decimal("0.01"))),
            "upa_discount":   str(discount.quantize(Decimal("0.01"))),
            "amount_payable": str(payable.quantize(Decimal("0.01"))),
            "item_count":     obj.items.count(),
        }


# ── Checkout ──────────────────────────────────────────────────────────────────

class CheckoutInitiateSerializer(serializers.Serializer):
    address_id    = serializers.UUIDField()
    wallet_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), default=Decimal("0")
    )


class CheckoutConfirmSerializer(serializers.Serializer):
    internal_order_id   = serializers.UUIDField()
    address_id          = serializers.UUIDField()
    wallet_amount       = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), default=Decimal("0")
    )
    razorpay_order_id   = serializers.CharField(allow_blank=True)
    razorpay_payment_id = serializers.CharField(allow_blank=True)
    razorpay_signature  = serializers.CharField(allow_blank=True)


# ── Order ─────────────────────────────────────────────────────────────────────

class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model  = OrderItem
        fields = [
            "id", "product_name", "variant_name", "sku",
            "mrp", "upa_price", "quantity", "line_total",
        ]


class OrderListSerializer(serializers.ModelSerializer):
    first_item_name = serializers.SerializerMethodField()
    item_count      = serializers.SerializerMethodField()
    customer_name   = serializers.SerializerMethodField()
    customer_mobile = serializers.SerializerMethodField()

    class Meta:
        model  = Order
        fields = [
            "id", "order_number", "order_status", "payment_status",
            "amount_payable", "wallet_used", "razorpay_amount",
            "item_count", "first_item_name",
            "customer_name", "customer_mobile",
            "created_at",
        ]

    def get_first_item_name(self, obj):
        item = obj.items.first()
        if item:
            return f"{item.product_name} — {item.variant_name}"
        return ""

    def get_item_count(self, obj):
        return obj.items.count()

    def get_customer_name(self, obj):
        if obj.user:
            return obj.user.full_name
        return obj.address_name

    def get_customer_mobile(self, obj):
        if obj.user:
            return obj.user.mobile or ""
        return obj.address_phone


class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    customer_name   = serializers.SerializerMethodField()
    customer_mobile = serializers.SerializerMethodField()

    class Meta:
        model  = Order
        fields = [
            "id", "order_number", "order_status", "payment_status",
            "subtotal", "upa_discount", "amount_payable",
            "wallet_used", "razorpay_amount", "razorpay_order_id",
            "razorpay_payment_id",
            "address_name", "address_phone", "address_line",
            "address_city", "address_state", "address_pincode",
            "tracking_number",
            "customer_name", "customer_mobile",
            "items", "created_at", "updated_at",
        ]

    def get_customer_name(self, obj):
        return obj.user.full_name if obj.user else obj.address_name

    def get_customer_mobile(self, obj):
        return (obj.user.mobile or "") if obj.user else obj.address_phone


class AdminOrderUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Order
        fields = ["order_status", "tracking_number"]
