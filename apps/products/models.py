import re
from decimal import Decimal
from itertools import product as cartesian_product

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from core.models import BaseModel


# ── Category ──────────────────────────────────────────────────────────────────

class Category(BaseModel):
    DEPTH_CHOICES = [
        (0, 'Category Group'),
        (1, 'Parent Category'),
        (2, 'Sub Category'),
        (3, 'Product Category'),
    ]

    name         = models.CharField(max_length=120)
    slug         = models.SlugField(max_length=140, unique=True, blank=True)
    short_code   = models.CharField(
        max_length=10, blank=True,
        help_text='Short uppercase code used in auto-generated SKUs e.g. GR, RC',
    )
    parent       = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='children',
    )
    depth        = models.PositiveSmallIntegerField(default=0, choices=DEPTH_CHOICES)
    field_schema = models.JSONField(
        default=dict, blank=True,
        help_text='Only used at depth=3. Defines dynamic product fields and variant attributes.',
    )
    is_active    = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'categories'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug = base
            n = 1
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def level_name(self):
        return dict(self.DEPTH_CHOICES).get(self.depth, 'Unknown')

    def get_ancestor_chain(self):
        """Return list from root ancestor to self (inclusive)."""
        chain = []
        current = self
        while current is not None:
            chain.append(current)
            current = current.parent
        chain.reverse()
        return chain


# ── Brand ─────────────────────────────────────────────────────────────────────

class Brand(BaseModel):
    name      = models.CharField(max_length=120)
    slug      = models.SlugField(max_length=140, unique=True, blank=True)
    logo      = models.ImageField(upload_to='brands/', null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug = base
            n = 1
            while Brand.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)


# ── Product ───────────────────────────────────────────────────────────────────

class Product(BaseModel):
    name                   = models.CharField(max_length=255)
    slug                   = models.SlugField(max_length=280, unique=True, blank=True)
    description            = models.TextField(blank=True)
    category               = models.ForeignKey(
        Category, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='products',
    )
    brand                  = models.ForeignKey(
        Brand, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='products',
    )
    extra_fields           = models.JSONField(
        default=dict, blank=True,
        help_text='Dynamic field values defined by the Product Category field_schema',
    )
    sku                    = models.CharField(max_length=100, unique=True, null=True, blank=True)
    barcode                = models.CharField(max_length=100, blank=True)
    mrp                    = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        help_text='Synced from lowest variant MRP when pricing is set',
    )
    upa_discount_override  = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='If set, overrides global UPA discount % for this product.',
    )
    upa_price_override     = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='If set, UPA users pay exactly this price (ignores % logic).',
    )
    is_published           = models.BooleanField(default=False)
    created_by             = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_products',
    )

    # ── Pricing (set via Pricing page, not product creation) ──────────────────
    purchase_price     = models.DecimalField(
                           max_digits=10, decimal_places=2,
                           null=True, blank=True,
                           help_text='Cost company pays to procure')
    gst_percentage     = models.DecimalField(
                           max_digits=5, decimal_places=2,
                           default=0,
                           help_text='GST % charged to customer, goes to govt')
    other_charges      = models.DecimalField(
                           max_digits=10, decimal_places=2,
                           default=0,
                           help_text='Shipping/packaging — company keeps')
    other_charges_type = models.CharField(
                           max_length=10,
                           choices=[
                               ('flat',    'Flat amount'),
                               ('percent', 'Percentage of selling price'),
                           ],
                           default='flat')
    pricing_configured = models.BooleanField(
                           default=False,
                           help_text='True when admin has set pricing')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug = base
            n = 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)


# ── ProductImage ─────────────────────────────────────────────────────────────

class ProductImage(BaseModel):
    product    = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image      = models.ImageField(upload_to='products/')
    alt_text   = models.CharField(max_length=255, blank=True)
    order      = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ['order', 'created_at']

    def __str__(self):
        return f"Image({self.product.name}, order={self.order})"


# ── ProductVariant ────────────────────────────────────────────────────────────

class ProductVariant(BaseModel):
    VARIANT_TYPES = [
        ('size',   'Size'),
        ('colour', 'Colour'),
        ('weight', 'Weight'),
        ('other',  'Other'),
    ]

    product            = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    name               = models.CharField(max_length=120)
    variant_type       = models.CharField(max_length=10, choices=VARIANT_TYPES, default='other')
    attributes         = models.JSONField(
        default=dict, blank=True,
        help_text='Attribute key-value pairs e.g. {"weight": "1kg", "color": "Red"}',
    )
    sku                = models.CharField(max_length=100, unique=True)
    mrp                = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        help_text='Set via Pricing page',
    )
    upa_price_override = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
    )
    stock_quantity     = models.IntegerField(default=0)
    is_active          = models.BooleanField(default=True)
    purchase_price     = models.DecimalField(
                           max_digits=10, decimal_places=2,
                           null=True, blank=True,
                           help_text='Cost to procure this variant')
    upa_price          = models.DecimalField(
                           max_digits=10, decimal_places=2,
                           null=True, blank=True,
                           help_text='Calculated UPA price after discount')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.product.name} — {self.name}"


# ── SKU Utilities ─────────────────────────────────────────────────────────────

def _clean_code(value: str, max_len: int = 5) -> str:
    return re.sub(r'[^A-Z0-9]', '', value.upper())[:max_len]


def generate_product_sku(product: 'Product') -> str:
    """
    Build: CODE0-CODE1-CODE2-CODE3-BRAND-001
    Each code comes from category.short_code or first 3 chars of name.
    """
    parts = []
    if product.category:
        for cat in product.category.get_ancestor_chain():
            code = _clean_code(cat.short_code or cat.name[:3])
            if code:
                parts.append(code)
    if product.brand:
        parts.append(_clean_code(product.brand.name[:4]))

    base = '-'.join(parts) if parts else 'PRD'
    seq  = 1
    sku  = f'{base}-{seq:03d}'
    while Product.objects.filter(sku=sku).exclude(pk=product.pk).exists():
        seq += 1
        sku = f'{base}-{seq:03d}'
    return sku


def generate_variant_sku(variant: 'ProductVariant', product_sku: str) -> str:
    """Build: {product_sku}-{ATTRVAL}"""
    attr_code = ''
    if variant.attributes:
        first_val = next(iter(variant.attributes.values()), '')
        attr_code = _clean_code(str(first_val), max_len=6)

    base = f'{product_sku}-{attr_code}' if attr_code else f'{product_sku}-VAR'
    sku  = base
    seq  = 1
    while ProductVariant.objects.filter(sku=sku).exclude(pk=variant.pk).exists():
        sku = f'{base}-{seq}'
        seq += 1
    return sku


def build_variant_combinations(variant_attributes: list) -> list:
    """
    Input:  [{"key": "weight", "values": ["500g", "1kg"]}, ...]
    Output: [{"weight": "500g"}, {"weight": "1kg"}, ...]
    """
    if not variant_attributes:
        return [{}]

    keys   = [attr['key']    for attr in variant_attributes]
    values = [attr['values'] for attr in variant_attributes]

    return [
        dict(zip(keys, combo))
        for combo in cartesian_product(*values)
    ]


# ── UPADiscountSettings (singleton) ──────────────────────────────────────────

class UPADiscountSettings(models.Model):
    """Singleton table — only one row ever exists."""
    global_discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='upa_discount_updates',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'UPA Discount Settings'

    def __str__(self):
        return f"Global UPA Discount: {self.global_discount_percent}%"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> 'UPADiscountSettings':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
