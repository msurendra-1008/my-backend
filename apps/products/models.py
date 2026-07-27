import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from core.models import BaseModel


# ── Category ──────────────────────────────────────────────────────────────────

class Category(BaseModel):
    name      = models.CharField(max_length=120)
    slug      = models.SlugField(max_length=140, unique=True, blank=True)
    parent    = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='subcategories',
    )
    is_active = models.BooleanField(default=True)

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


# ── Product ───────────────────────────────────────────────────────────────────

class Product(BaseModel):
    name                   = models.CharField(max_length=255)
    slug                   = models.SlugField(max_length=280, unique=True, blank=True)
    description            = models.TextField(blank=True)
    category               = models.ForeignKey(
        Category, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='products',
    )
    sku                    = models.CharField(max_length=100, unique=True, null=True, blank=True)
    barcode                = models.CharField(max_length=100, blank=True)
    mrp                    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
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

    # ── Pricing ───────────────────────────────────────────────────────────────
    purchase_price     = models.DecimalField(
                           max_digits=10, decimal_places=2,
                           null=True, blank=True,
                           help_text="Cost company pays to procure")
    gst_percentage     = models.DecimalField(
                           max_digits=5, decimal_places=2,
                           default=0,
                           help_text="GST % charged to customer, goes to govt")
    other_charges      = models.DecimalField(
                           max_digits=10, decimal_places=2,
                           default=0,
                           help_text="Shipping/packaging — company keeps")
    other_charges_type = models.CharField(
                           max_length=10,
                           choices=[
                               ('flat',    'Flat amount'),
                               ('percent', 'Percentage of selling price'),
                           ],
                           default='flat')
    pricing_configured = models.BooleanField(
                           default=False,
                           help_text="True when admin has set pricing")

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
    sku                = models.CharField(max_length=100, unique=True)
    mrp                = models.DecimalField(max_digits=12, decimal_places=2)
    upa_price_override = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
    )
    stock_quantity     = models.IntegerField(default=0)
    is_active          = models.BooleanField(default=True)
    purchase_price     = models.DecimalField(
                           max_digits=10, decimal_places=2,
                           null=True, blank=True,
                           help_text="Cost to procure this variant")
    upa_price          = models.DecimalField(
                           max_digits=10, decimal_places=2,
                           null=True, blank=True,
                           help_text="Calculated UPA price after discount")

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.product.name} — {self.name}"


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
        # Enforce singleton — always use pk=1
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> 'UPADiscountSettings':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
