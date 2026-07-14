from decimal import Decimal

from rest_framework import serializers

from apps.products.utils import get_upa_price
from apps.commissions.serializers import CommissionBreakupAdminSerializer
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
    upa_price             = serializers.SerializerMethodField()
    primary_image         = serializers.SerializerMethodField()
    other_charges_amount  = serializers.SerializerMethodField()
    gst_amount            = serializers.SerializerMethodField()
    amount_payable        = serializers.SerializerMethodField()

    class Meta:
        model  = CartItem
        fields = [
            "id", "variant_id", "variant_name", "variant_type",
            "product_name", "product_slug", "sku", "stock",
            "mrp", "upa_price", "primary_image", "quantity",
            "other_charges_amount", "gst_amount", "amount_payable",
        ]

    def get_upa_price(self, obj):
        return get_upa_price(obj.variant)["upa_price"]

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

    def _upa_price_float(self, obj):
        return float(get_upa_price(obj.variant)["upa_price"])

    def get_other_charges_amount(self, obj):
        product   = obj.variant.product
        upa_price = self._upa_price_float(obj)
        if product.other_charges_type == 'flat':
            return round(float(product.other_charges or 0), 2)
        return round(upa_price * float(product.other_charges or 0) / 100, 2)

    def get_gst_amount(self, obj):
        upa_price = self._upa_price_float(obj)
        gst_pct   = float(obj.variant.product.gst_percentage or 0)
        return round(upa_price * gst_pct / 100, 2)

    def get_amount_payable(self, obj):
        upa_price = self._upa_price_float(obj)
        other     = self.get_other_charges_amount(obj)
        gst       = self.get_gst_amount(obj)
        return round((upa_price + other + gst) * obj.quantity, 2)


class CartSerializer(serializers.ModelSerializer):
    items    = CartItemSerializer(many=True, read_only=True)
    totals   = serializers.SerializerMethodField()

    class Meta:
        model  = Cart
        fields = ["id", "items", "totals"]

    def get_totals(self, obj):
        subtotal      = Decimal("0")
        discount      = Decimal("0")
        other_charges = Decimal("0")
        gst           = Decimal("0")

        for item in obj.items.select_related("variant__product").all():
            price_data = get_upa_price(item.variant)
            mrp        = Decimal(price_data["mrp"])
            upa        = Decimal(price_data["upa_price"])
            product    = item.variant.product
            qty        = item.quantity

            subtotal += mrp * qty
            discount += (mrp - upa) * qty

            if product.other_charges_type == 'flat':
                other_per_unit = Decimal(str(product.other_charges or 0))
            else:
                other_per_unit = upa * Decimal(str(product.other_charges or 0)) / 100
            other_charges += other_per_unit * qty

            gst_pct = Decimal(str(product.gst_percentage or 0))
            gst += upa * gst_pct / 100 * qty

        q       = lambda d: str(d.quantize(Decimal("0.01")))  # noqa: E731
        payable = subtotal - discount + other_charges + gst
        return {
            "subtotal":       q(subtotal),
            "upa_discount":   q(discount),
            "other_charges":  q(other_charges),
            "gst":            q(gst),
            "amount_payable": q(payable),
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
    variant_id          = serializers.UUIDField(source="variant.id",           read_only=True, allow_null=True)
    product_slug        = serializers.CharField(source="variant.product.slug", read_only=True, allow_null=True)
    return_status       = serializers.SerializerMethodField()
    return_admin_notes  = serializers.SerializerMethodField()
    commission_breakup  = serializers.SerializerMethodField()

    class Meta:
        model  = OrderItem
        fields = [
            "id", "product_name", "variant_name", "sku",
            "mrp", "upa_price", "quantity", "line_total",
            "status", "delivered_at", "variant_id", "product_slug",
            "return_rejection_count", "return_status", "return_admin_notes",
            "return_window_blocked", "commission_breakup",
        ]

    def get_return_status(self, obj):
        rr = obj.return_requests.order_by("-created_at").first()
        return rr.status if rr else None

    def get_return_admin_notes(self, obj):
        rr = obj.return_requests.order_by("-created_at").first()
        return (rr.admin_notes or "") if rr else ""

    def get_commission_breakup(self, obj):
        try:
            return CommissionBreakupAdminSerializer(obj.commission_breakup).data
        except Exception:
            return None


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
            "is_offline",
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
    items               = OrderItemSerializer(many=True, read_only=True)
    customer_name       = serializers.SerializerMethodField()
    customer_mobile     = serializers.SerializerMethodField()
    offline_bill_number = serializers.SerializerMethodField()
    billed_by_name      = serializers.SerializerMethodField()

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
            "is_satisfied", "satisfied_at",
            "is_offline", "offline_bill_number", "billed_by_name",
            "customer_name", "customer_mobile",
            "items", "created_at", "updated_at",
        ]

    def get_customer_name(self, obj):
        return obj.user.full_name if obj.user else obj.address_name

    def get_customer_mobile(self, obj):
        return (obj.user.mobile or "") if obj.user else obj.address_phone

    def get_offline_bill_number(self, obj):
        try:
            return obj.offline_bill.bill_number
        except Exception:
            return None

    def get_billed_by_name(self, obj):
        try:
            return obj.offline_bill.billed_by.full_name or ''
        except Exception:
            return None


class AdminOrderUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Order
        fields = ["order_status", "tracking_number"]
