from rest_framework import serializers

from .models import Category, Product, ProductImage, ProductVariant, UPADiscountSettings
from .utils import get_upa_price


# ── Category ─────────────────────────────────────────────────────────────────

class CategorySerializer(serializers.ModelSerializer):
    parent_id   = serializers.UUIDField(source='parent.id',   read_only=True, allow_null=True)
    parent_name = serializers.CharField(source='parent.name', read_only=True, allow_null=True)
    parent      = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), allow_null=True, required=False, write_only=True,
    )

    class Meta:
        model  = Category
        fields = ['id', 'name', 'slug', 'parent', 'parent_id', 'parent_name', 'is_active']
        read_only_fields = ['slug']


# ── ProductImage ─────────────────────────────────────────────────────────────

class ProductImageSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model  = ProductImage
        fields = ['id', 'image', 'alt_text', 'order', 'is_primary']

    def get_image(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url if obj.image else None


# ── ProductVariant ────────────────────────────────────────────────────────────

class ProductVariantSerializer(serializers.ModelSerializer):
    upa_price_computed = serializers.SerializerMethodField()
    stock_label        = serializers.SerializerMethodField()
    purchase_price     = serializers.DecimalField(
                           max_digits=10, decimal_places=2,
                           required=False, allow_null=True)
    upa_price          = serializers.DecimalField(
                           max_digits=10, decimal_places=2,
                           required=False, allow_null=True)
    variant_profit     = serializers.SerializerMethodField()

    class Meta:
        model  = ProductVariant
        fields = [
            'id', 'name', 'variant_type', 'sku', 'mrp',
            'upa_price_override', 'stock_quantity', 'stock_label',
            'is_active', 'upa_price_computed',
            'purchase_price', 'upa_price', 'variant_profit',
        ]

    def get_upa_price_computed(self, obj):
        return get_upa_price(obj)

    def get_stock_label(self, obj):
        if obj.stock_quantity <= 0:
            return 'Out of Stock'
        if obj.stock_quantity <= 10:
            return 'Low Stock'
        return 'In Stock'

    def get_variant_profit(self, obj):
        if not obj.purchase_price or not obj.mrp:
            return None
        product  = obj.product
        selling  = float(obj.mrp)
        purchase = float(obj.purchase_price)
        if product.other_charges_type == 'flat':
            other = float(product.other_charges or 0)
        else:
            other = selling * float(product.other_charges or 0) / 100
        return round((selling + other) - purchase, 2)


# ── ProductList ───────────────────────────────────────────────────────────────

class ProductListSerializer(serializers.ModelSerializer):
    category_name    = serializers.CharField(source='category.name', read_only=True)
    primary_image    = serializers.SerializerMethodField()
    stock_label      = serializers.SerializerMethodField()
    variant_count    = serializers.SerializerMethodField()
    total_stock      = serializers.SerializerMethodField()
    first_variant_id = serializers.SerializerMethodField()
    pricing_configured = serializers.BooleanField(read_only=True)
    purchase_price   = serializers.DecimalField(
                         max_digits=10, decimal_places=2, read_only=True, allow_null=True)
    profit_amount      = serializers.SerializerMethodField()
    upa_profit_amount  = serializers.SerializerMethodField()
    has_commission_rule = serializers.SerializerMethodField()
    min_variant_mrp     = serializers.SerializerMethodField()

    class Meta:
        model  = Product
        fields = [
            'id', 'name', 'slug', 'sku', 'mrp', 'primary_image',
            'category_name', 'is_published',
            'stock_label', 'total_stock', 'variant_count',
            'first_variant_id', 'min_variant_mrp',
            'pricing_configured', 'purchase_price', 'profit_amount',
            'upa_profit_amount', 'upa_discount_override',
            'has_commission_rule',
        ]

    def get_primary_image(self, obj):
        request = self.context.get('request')
        img = obj.images.filter(is_primary=True).first() or obj.images.first()
        if img and img.image:
            return request.build_absolute_uri(img.image.url) if request else img.image.url
        return None

    def _total_stock(self, obj):
        variants = obj.variants.filter(is_active=True)
        if variants.exists():
            return sum(v.stock_quantity for v in variants)
        return 0

    def get_stock_label(self, obj):
        stock = self._total_stock(obj)
        if stock <= 0:  return 'Out of Stock'
        if stock <= 10: return 'Low Stock'
        return 'In Stock'

    def get_total_stock(self, obj):
        return self._total_stock(obj)

    def get_variant_count(self, obj):
        return obj.variants.filter(is_active=True).count()

    def get_first_variant_id(self, obj):
        variant = obj.variants.filter(is_active=True, stock_quantity__gt=0).first()
        if not variant:
            variant = obj.variants.filter(is_active=True).first()
        return str(variant.id) if variant else None

    def _first_priced_variant(self, obj):
        return obj.variants.filter(purchase_price__isnull=False).first()

    def get_profit_amount(self, obj):
        variant = self._first_priced_variant(obj)
        if not variant:
            return None
        selling  = float(variant.mrp or 0)
        purchase = float(variant.purchase_price or 0)
        if not purchase:
            return None
        if obj.other_charges_type == 'flat':
            other = float(obj.other_charges or 0)
        else:
            other = selling * float(obj.other_charges or 0) / 100
        return round((selling + other) - purchase, 2)

    def get_upa_profit_amount(self, obj):
        variant = self._first_priced_variant(obj)
        if not variant:
            return None
        selling  = float(variant.mrp or 0)
        purchase = float(variant.purchase_price or 0)
        if not purchase:
            return None
        upa_discount = float(obj.upa_discount_override or 0)
        upa_price    = selling * (1 - upa_discount / 100)
        if obj.other_charges_type == 'flat':
            other = float(obj.other_charges or 0)
        else:
            other = upa_price * float(obj.other_charges or 0) / 100
        return round((upa_price + other) - purchase, 2)

    def get_has_commission_rule(self, obj):
        try:
            return obj.commission_rule.is_active
        except Exception:
            return False

    def get_min_variant_mrp(self, obj):
        mrps = [
            v.mrp for v in obj.variants.filter(is_active=True)
            if v.mrp is not None
        ]
        return str(min(mrps)) if mrps else None


# ── ProductDetail ─────────────────────────────────────────────────────────────

class ProductDetailSerializer(serializers.ModelSerializer):
    category    = CategorySerializer(read_only=True)
    images      = ProductImageSerializer(many=True, read_only=True)
    variants    = ProductVariantSerializer(many=True, read_only=True)
    upa_price   = serializers.SerializerMethodField()
    stock_label = serializers.SerializerMethodField()
    total_stock = serializers.SerializerMethodField()
    purchase_price     = serializers.DecimalField(
                           max_digits=10, decimal_places=2, required=False, allow_null=True)
    gst_percentage     = serializers.DecimalField(
                           max_digits=5, decimal_places=2, required=False, default=0)
    other_charges      = serializers.DecimalField(
                           max_digits=10, decimal_places=2, required=False, default=0)
    other_charges_type = serializers.ChoiceField(
                           choices=['flat', 'percent'], required=False, default='flat')
    pricing_configured = serializers.BooleanField(read_only=True)
    profit_amount      = serializers.SerializerMethodField()

    class Meta:
        model  = Product
        fields = [
            'id', 'name', 'slug', 'description', 'category', 'sku', 'barcode',
            'mrp', 'upa_discount_override', 'upa_price_override',
            'is_published', 'created_at', 'updated_at',
            'images', 'variants', 'upa_price', 'stock_label', 'total_stock',
            'purchase_price', 'gst_percentage', 'other_charges',
            'other_charges_type', 'pricing_configured', 'profit_amount',
        ]

    def get_upa_price(self, obj):
        return get_upa_price(obj)

    def _total_stock(self, obj):
        variants = obj.variants.filter(is_active=True)
        return sum(v.stock_quantity for v in variants) if variants.exists() else 0

    def get_stock_label(self, obj):
        s = self._total_stock(obj)
        if s <= 0:  return 'Out of Stock'
        if s <= 10: return 'Low Stock'
        return 'In Stock'

    def get_total_stock(self, obj):
        return self._total_stock(obj)

    def get_profit_amount(self, obj):
        if not obj.purchase_price or not obj.mrp:
            return None
        selling  = float(obj.mrp)
        purchase = float(obj.purchase_price)
        if obj.other_charges_type == 'flat':
            other = float(obj.other_charges or 0)
        else:
            other = selling * float(obj.other_charges or 0) / 100
        return round((selling + other) - purchase, 2)


# ── ProductWrite ─────────────────────────────────────────────────────────────

class ProductWriteSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(max_length=100, required=False, allow_null=True, allow_blank=True)
    mrp = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)

    class Meta:
        model  = Product
        fields = [
            'id', 'slug',
            'name', 'description', 'category', 'sku', 'barcode',
            'mrp', 'upa_discount_override', 'upa_price_override', 'is_published',
        ]
        read_only_fields = ['id', 'slug']

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


# ── ProductVariantWrite ────────────────────────────────────────────────────────

class ProductVariantWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ProductVariant
        fields = ['name', 'variant_type', 'sku', 'mrp', 'upa_price_override', 'stock_quantity', 'is_active']


# ── UPADiscountSettings ───────────────────────────────────────────────────────

class UPADiscountSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model  = UPADiscountSettings
        fields = ['global_discount_percent', 'updated_at']
        read_only_fields = ['updated_at']
