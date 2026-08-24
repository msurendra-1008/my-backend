from rest_framework import serializers

from .models import (
    Brand, Category, Product, ProductImage, ProductVariant, UPADiscountSettings,
    generate_product_sku, generate_variant_sku, build_variant_combinations,
)
from .utils import get_upa_price


# ── Category ─────────────────────────────────────────────────────────────────

class CategorySerializer(serializers.ModelSerializer):
    parent_id      = serializers.UUIDField(source='parent.id',   read_only=True, allow_null=True)
    parent_name    = serializers.CharField(source='parent.name', read_only=True, allow_null=True)
    parent         = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), allow_null=True, required=False, write_only=True,
    )
    level_name     = serializers.CharField(read_only=True)
    children_count = serializers.SerializerMethodField()

    class Meta:
        model  = Category
        fields = [
            'id', 'name', 'slug', 'short_code', 'depth', 'level_name',
            'parent', 'parent_id', 'parent_name',
            'field_schema', 'is_active', 'children_count',
        ]
        read_only_fields = ['slug']

    def get_children_count(self, obj):
        return obj.children.count()

    def validate(self, data):
        parent = data.get('parent')
        depth  = data.get('depth', getattr(self.instance, 'depth', 0))

        if depth == 0 and parent is not None:
            raise serializers.ValidationError('Category Group (depth=0) must have no parent.')

        if parent is not None:
            expected_parent_depth = depth - 1
            if parent.depth != expected_parent_depth:
                raise serializers.ValidationError(
                    f'A depth-{depth} category must have a depth-{expected_parent_depth} parent. '
                    f'Selected parent "{parent.name}" is at depth-{parent.depth}.'
                )

        return data


class CategoryTreeSerializer(serializers.ModelSerializer):
    """Lightweight full-tree serializer for navigation dropdowns."""
    children   = serializers.SerializerMethodField()
    level_name = serializers.CharField(read_only=True)

    class Meta:
        model  = Category
        fields = ['id', 'name', 'slug', 'short_code', 'depth', 'level_name', 'is_active', 'children']

    def get_children(self, obj):
        qs = obj.children.order_by('name')
        return CategoryTreeSerializer(qs, many=True).data


# ── Brand ─────────────────────────────────────────────────────────────────────

class BrandSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model  = Brand
        fields = ['id', 'name', 'slug', 'logo', 'logo_url', 'is_active']
        read_only_fields = ['slug']
        extra_kwargs = {'logo': {'write_only': True, 'required': False}}

    def get_logo_url(self, obj):
        request = self.context.get('request')
        if obj.logo and request:
            return request.build_absolute_uri(obj.logo.url)
        return obj.logo.url if obj.logo else None


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
            'id', 'name', 'variant_type', 'attributes', 'sku', 'mrp',
            'upa_price_override', 'stock_quantity', 'stock_label',
            'is_active', 'order', 'upa_price_computed',
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


class ProductVariantWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ProductVariant
        fields = ['name', 'variant_type', 'attributes', 'sku', 'mrp',
                  'upa_price_override', 'stock_quantity', 'is_active', 'order']
        extra_kwargs = {
            'sku':  {'required': False},
            'name': {'required': False},
            'mrp':  {'required': False},
        }


# ── ProductList ───────────────────────────────────────────────────────────────

class ProductListSerializer(serializers.ModelSerializer):
    category_name    = serializers.CharField(source='category.name', read_only=True)
    brand_name       = serializers.CharField(source='brand.name', read_only=True, allow_null=True)
    primary_image    = serializers.SerializerMethodField()
    stock_label      = serializers.SerializerMethodField()
    variant_count    = serializers.SerializerMethodField()
    total_stock      = serializers.SerializerMethodField()
    first_variant_id = serializers.SerializerMethodField()
    pricing_configured       = serializers.BooleanField(read_only=True)
    purchase_price           = serializers.DecimalField(
                                 max_digits=10, decimal_places=2, read_only=True, allow_null=True)
    profit_amount            = serializers.SerializerMethodField()
    upa_profit_amount        = serializers.SerializerMethodField()
    has_commission_rule      = serializers.SerializerMethodField()
    configured_variant_count = serializers.SerializerMethodField()
    mrp_min                  = serializers.SerializerMethodField()
    mrp_max                  = serializers.SerializerMethodField()
    profit_min               = serializers.SerializerMethodField()
    profit_max               = serializers.SerializerMethodField()
    upa_profit_min           = serializers.SerializerMethodField()
    upa_profit_max           = serializers.SerializerMethodField()
    min_variant_upa_price    = serializers.SerializerMethodField()
    max_discount_percent     = serializers.SerializerMethodField()
    min_variant_mrp          = serializers.SerializerMethodField()

    class Meta:
        model  = Product
        fields = [
            'id', 'name', 'slug', 'sku', 'mrp', 'primary_image',
            'category_name', 'brand_name', 'is_published',
            'stock_label', 'total_stock', 'variant_count',
            'first_variant_id',
            'pricing_configured', 'purchase_price', 'profit_amount',
            'upa_profit_amount', 'upa_discount_override',
            'has_commission_rule',
            'configured_variant_count',
            'mrp_min', 'mrp_max',
            'profit_min', 'profit_max',
            'upa_profit_min', 'upa_profit_max',
            'min_variant_upa_price', 'max_discount_percent',
            'min_variant_mrp',
        ]

    def get_primary_image(self, obj):
        request = self.context.get('request')
        img = obj.images.filter(is_primary=True).first() or obj.images.first()
        if img and img.image:
            return request.build_absolute_uri(img.image.url) if request else img.image.url
        return None

    def _total_stock(self, obj):
        variants = obj.variants.filter(is_active=True)
        return sum(v.stock_quantity for v in variants) if variants.exists() else 0

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
        if not variant or not variant.mrp:
            return None
        selling  = float(variant.mrp)
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
        if not variant or not variant.mrp:
            return None
        selling  = float(variant.mrp)
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

    # ── Variant pricing range helpers ─────────────────────────────────────────

    def _variant_metrics(self, obj):
        """Compute min/max MRP and profit across all fully-priced active variants.
        Results are cached per object to avoid repeated queries."""
        if not hasattr(self, '_vmetrics_cache'):
            self._vmetrics_cache = {}
        if obj.id in self._vmetrics_cache:
            return self._vmetrics_cache[obj.id]

        priced = [
            v for v in obj.variants.filter(is_active=True)
            if v.purchase_price and v.mrp
        ]

        empty = {
            'count': 0,
            'mrp_min': None, 'mrp_max': None,
            'profit_min': None, 'profit_max': None,
            'upa_profit_min': None, 'upa_profit_max': None,
        }
        if not priced:
            self._vmetrics_cache[obj.id] = empty
            return empty

        upa_discount = float(obj.upa_discount_override or 0)
        other_raw    = float(obj.other_charges or 0)
        other_type   = obj.other_charges_type

        mrps, profits, upa_profits = [], [], []
        for v in priced:
            selling  = float(v.mrp)
            purchase = float(v.purchase_price)
            other    = other_raw if other_type == 'flat' else selling * other_raw / 100
            profits.append(round((selling + other) - purchase, 2))
            mrps.append(selling)

            upa_price = selling * (1 - upa_discount / 100)
            upa_other = other_raw if other_type == 'flat' else upa_price * other_raw / 100
            upa_profits.append(round((upa_price + upa_other) - purchase, 2))

        result = {
            'count':          len(priced),
            'mrp_min':        str(round(min(mrps), 2)),
            'mrp_max':        str(round(max(mrps), 2)),
            'profit_min':     min(profits),
            'profit_max':     max(profits),
            'upa_profit_min': min(upa_profits),
            'upa_profit_max': max(upa_profits),
        }
        self._vmetrics_cache[obj.id] = result
        return result

    def get_configured_variant_count(self, obj):
        return self._variant_metrics(obj)['count']

    def get_mrp_min(self, obj):
        return self._variant_metrics(obj)['mrp_min']

    def get_mrp_max(self, obj):
        return self._variant_metrics(obj)['mrp_max']

    def get_profit_min(self, obj):
        return self._variant_metrics(obj)['profit_min']

    def get_profit_max(self, obj):
        return self._variant_metrics(obj)['profit_max']

    def get_upa_profit_min(self, obj):
        return self._variant_metrics(obj)['upa_profit_min']

    def get_upa_profit_max(self, obj):
        return self._variant_metrics(obj)['upa_profit_max']

    def get_min_variant_upa_price(self, obj):
        prices = [
            float(v.upa_price)
            for v in obj.variants.all()
            if v.is_active and v.upa_price is not None
        ]
        return str(round(min(prices), 2)) if prices else None

    def get_max_discount_percent(self, obj):
        pcts = []
        for v in obj.variants.all():
            if v.is_active and v.upa_price is not None and v.mrp:
                pct = (1 - float(v.upa_price) / float(v.mrp)) * 100
                pcts.append(pct)
        return str(round(max(pcts), 2)) if pcts else None

    def get_min_variant_mrp(self, obj):
        mrps = [float(v.mrp) for v in obj.variants.all() if v.is_active and v.mrp]
        return str(round(min(mrps), 2)) if mrps else None


# ── ProductDetail ─────────────────────────────────────────────────────────────

class ProductDetailSerializer(serializers.ModelSerializer):
    category    = CategorySerializer(read_only=True)
    brand       = BrandSerializer(read_only=True)
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
            'id', 'name', 'slug', 'description', 'category', 'brand',
            'extra_fields', 'sku', 'barcode',
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
    """
    Handles product creation with auto-variant generation.

    POST body:
    {
        "name": "India Gate Basmati Rice",
        "description": "...",
        "category": "<uuid>",           # must be depth=3 (Product Category)
        "brand": "<uuid>",              # optional
        "extra_fields": {"origin": "Punjab"},
        "variant_combinations": [
            {"attributes": {"weight": "500g"}, "stock_quantity": 50},
            {"attributes": {"weight": "1kg"},  "stock_quantity": 30}
        ]
    }
    """
    variant_combinations = serializers.ListField(
        child=serializers.DictField(), write_only=True, required=False, default=list,
    )
    brand = serializers.PrimaryKeyRelatedField(
        queryset=Brand.objects.all(), allow_null=True, required=False,
    )

    class Meta:
        model  = Product
        fields = [
            'name', 'description', 'category', 'brand', 'extra_fields',
            'barcode', 'upa_discount_override', 'upa_price_override',
            'is_published', 'variant_combinations',
        ]

    def validate_category(self, value):
        if value is not None and value.depth != 3:
            raise serializers.ValidationError(
                f'Product must be assigned to a Product Category (depth=3). '
                f'"{value.name}" is at depth-{value.depth}.'
            )
        return value

    def validate_extra_fields(self, value):
        return value if value else {}

    def validate(self, data):
        # Only enforce required extra_fields on create, or when extra_fields is
        # explicitly included in a PATCH payload. Omitting extra_fields on PATCH
        # means "don't touch them", so we must not re-validate stale required keys.
        if 'extra_fields' not in data and self.instance:
            return data

        category = data.get('category') or (self.instance.category if self.instance else None)
        if category and category.field_schema:
            required_keys = [
                f['key'] for f in category.field_schema.get('product_fields', [])
                if f.get('required')
            ]
            extra   = data.get('extra_fields', {})
            missing = [k for k in required_keys if not extra.get(k)]
            if missing:
                raise serializers.ValidationError({
                    'extra_fields': f'Required fields missing: {", ".join(missing)}'
                })
        return data

    def create(self, validated_data):
        from django.db import transaction

        variant_combinations = validated_data.pop('variant_combinations', [])
        validated_data['created_by'] = self.context['request'].user

        with transaction.atomic():
            product     = Product(**validated_data)
            product.sku = generate_product_sku(product)
            product.save()

            for combo in variant_combinations:
                attrs        = combo.get('attributes', {})
                stock_qty    = combo.get('stock_quantity', 0)
                variant_type = combo.get('variant_type', 'other')
                name         = (combo.get('name') or
                                ', '.join(f'{k}: {v}' for k, v in attrs.items()) or
                                'Default')

                variant             = ProductVariant(
                    product=product,
                    name=name,
                    variant_type=variant_type,
                    attributes=attrs,
                    stock_quantity=stock_qty,
                    sku='__placeholder__',
                )
                variant.sku = generate_variant_sku(variant, product.sku)
                variant.save()

        return product

    def update(self, instance, validated_data):
        from django.db import transaction

        variant_combinations = validated_data.pop('variant_combinations', None)

        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            if variant_combinations is not None:
                instance.variants.all().delete()
                for combo in variant_combinations:
                    attrs        = combo.get('attributes', {})
                    stock_qty    = combo.get('stock_quantity', 0)
                    variant_type = combo.get('variant_type', 'other')
                    name         = (combo.get('name') or
                                    ', '.join(f'{k}: {v}' for k, v in attrs.items()) or
                                    'Default')
                    variant   = ProductVariant(
                        product=instance,
                        name=name,
                        variant_type=variant_type,
                        attributes=attrs,
                        stock_quantity=stock_qty,
                        sku='__placeholder__',
                    )
                    variant.sku = generate_variant_sku(variant, instance.sku)
                    variant.save()

        return instance


# ── UPADiscountSettings ───────────────────────────────────────────────────────

class UPADiscountSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model  = UPADiscountSettings
        fields = ['global_discount_percent', 'updated_at']
        read_only_fields = ['updated_at']
