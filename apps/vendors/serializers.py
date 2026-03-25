from django.utils.text import slugify
from django.utils import timezone
from rest_framework import serializers

from accounts.models import User
from apps.products.models import Category
from .models import (
    VendorDocument, VendorProfile,
    VendorProduct, VendorProductVariant, VendorProductImage,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

class CategoryBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name']


class VendorDocumentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = VendorDocument
        fields = ['id', 'label', 'file_url', 'uploaded_at']

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url if obj.file else None


# ── Auth ──────────────────────────────────────────────────────────────────────

class VendorRegisterSerializer(serializers.Serializer):
    company_name  = serializers.CharField(max_length=200)
    gst_number    = serializers.CharField(max_length=20)
    contact_name  = serializers.CharField(max_length=150)
    mobile        = serializers.CharField(max_length=15, required=False, allow_blank=True)
    email         = serializers.EmailField(required=False, allow_blank=True)
    address_line1 = serializers.CharField(max_length=255)
    address_line2 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city          = serializers.CharField(max_length=100)
    state         = serializers.CharField(max_length=100)
    pincode       = serializers.CharField(max_length=10)
    category_ids  = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    password      = serializers.CharField(write_only=True, min_length=8)

    def validate_gst_number(self, value):
        if VendorProfile.objects.filter(gst_number=value).exists():
            raise serializers.ValidationError('A vendor with this GST number already exists.')
        return value

    def validate(self, data):
        email  = data.get('email', '').strip() or None
        mobile = data.get('mobile', '').strip() or None
        if not email and not mobile:
            raise serializers.ValidationError('At least one of email or mobile is required.')
        if email and User.objects.filter(email=email).exists():
            raise serializers.ValidationError({'email': 'Email already in use.'})
        if mobile and User.objects.filter(mobile=mobile).exists():
            raise serializers.ValidationError({'mobile': 'Mobile already in use.'})
        data['email']  = email
        data['mobile'] = mobile
        return data

    def create(self, validated_data):
        category_ids = validated_data.pop('category_ids')
        password     = validated_data.pop('password')
        contact_name = validated_data['contact_name']

        first_name, *rest = contact_name.split(' ', 1)
        last_name = rest[0] if rest else ''

        user = User.objects.create_user(
            password=password,
            role='vendor',
            first_name=first_name,
            last_name=last_name,
            email=validated_data.pop('email'),
            mobile=validated_data.pop('mobile'),
        )

        profile = VendorProfile.objects.create(user=user, **validated_data)
        categories = Category.objects.filter(id__in=category_ids)
        profile.categories.set(categories)
        return profile


class VendorLoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password   = serializers.CharField(write_only=True)

    def validate(self, data):
        identifier = data['identifier']
        password   = data['password']

        user = User.objects.filter(email=identifier).first()
        if not user:
            user = User.objects.filter(mobile=identifier).first()

        if not user or not user.check_password(password):
            raise serializers.ValidationError('Invalid credentials.')
        if user.role != 'vendor':
            raise serializers.ValidationError('Invalid credentials.')
        if not user.is_active:
            raise serializers.ValidationError('Account is disabled.')

        data['user'] = user
        return data


# ── Profile read/write ────────────────────────────────────────────────────────

class VendorProfileSerializer(serializers.ModelSerializer):
    documents  = VendorDocumentSerializer(many=True, read_only=True)
    categories = CategoryBriefSerializer(many=True, read_only=True)
    mobile     = serializers.SerializerMethodField()
    email      = serializers.SerializerMethodField()

    class Meta:
        model = VendorProfile
        fields = [
            'id', 'company_name', 'gst_number', 'contact_name',
            'mobile', 'email',
            'address_line1', 'address_line2', 'city', 'state', 'pincode',
            'categories', 'status', 'rejection_reason', 'admin_notes',
            'documents', 'approved_at', 'created_at', 'updated_at',
        ]

    def get_mobile(self, obj):
        return obj.user.mobile

    def get_email(self, obj):
        return obj.user.email


class VendorProfileUpdateSerializer(serializers.ModelSerializer):
    category_ids = serializers.ListField(child=serializers.UUIDField(), write_only=True, required=False)

    class Meta:
        model = VendorProfile
        fields = [
            'contact_name', 'address_line1', 'address_line2',
            'city', 'state', 'pincode', 'category_ids',
        ]

    def validate(self, data):
        # Disallow company_name or gst_number changes
        for forbidden in ('company_name', 'gst_number'):
            if forbidden in self.initial_data:
                raise serializers.ValidationError(
                    {forbidden: f'Cannot change {forbidden} after registration.'}
                )
        return data

    def update(self, instance, validated_data):
        category_ids = validated_data.pop('category_ids', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if category_ids is not None:
            instance.categories.set(Category.objects.filter(id__in=category_ids))
        instance.save()
        return instance


# ── Admin ─────────────────────────────────────────────────────────────────────

class VendorListSerializer(serializers.ModelSerializer):
    mobile         = serializers.SerializerMethodField()
    email          = serializers.SerializerMethodField()
    category_names = serializers.SerializerMethodField()

    class Meta:
        model = VendorProfile
        fields = [
            'id', 'company_name', 'gst_number', 'contact_name', 'mobile', 'email',
            'status', 'category_names', 'created_at',
        ]

    def get_mobile(self, obj):
        return obj.user.mobile

    def get_email(self, obj):
        return obj.user.email

    def get_category_names(self, obj):
        return list(obj.categories.values_list('name', flat=True))


class VendorAdminSerializer(serializers.ModelSerializer):
    documents      = VendorDocumentSerializer(many=True, read_only=True)
    categories     = CategoryBriefSerializer(many=True, read_only=True)
    mobile         = serializers.SerializerMethodField()
    email          = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = VendorProfile
        fields = [
            'id', 'company_name', 'gst_number', 'contact_name',
            'mobile', 'email',
            'address_line1', 'address_line2', 'city', 'state', 'pincode',
            'categories', 'status', 'rejection_reason', 'admin_notes',
            'documents', 'approved_by_name', 'approved_at', 'created_at', 'updated_at',
        ]

    def get_mobile(self, obj):
        return obj.user.mobile

    def get_email(self, obj):
        return obj.user.email

    def get_approved_by_name(self, obj):
        if obj.approved_by:
            return obj.approved_by.get_full_name()
        return None


# ── Vendor Products ───────────────────────────────────────────────────────────

class VendorProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model  = VendorProductVariant
        fields = ['id', 'name', 'variant_type', 'sku', 'mrp', 'is_active']


class VendorProductImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model  = VendorProductImage
        fields = ['id', 'image_url', 'alt_text', 'order', 'is_primary', 'uploaded_at']

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url if obj.image else None


class VendorProductWriteSerializer(serializers.ModelSerializer):
    """Used by vendors to create / edit their product submissions."""
    category_id   = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    category_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    variants      = VendorProductVariantSerializer(many=True)

    class Meta:
        model  = VendorProduct
        fields = [
            'name', 'description', 'category_id', 'category_name',
            'sku', 'barcode', 'monthly_capacity', 'yearly_capacity',
            'variants',
        ]

    def validate(self, data):
        # Only validate variant count when variants are explicitly provided
        if 'variants' in data and len(data['variants']) < 1:
            raise serializers.ValidationError({'variants': 'At least one variant is required.'})
        return data

    def _resolve_category(self, category_id, category_name):
        if category_id:
            try:
                return Category.objects.get(pk=category_id)
            except Category.DoesNotExist:
                raise serializers.ValidationError({'category_id': 'Category not found.'})
        if category_name:
            name = category_name.strip()
            base_slug = slugify(name)
            slug = base_slug
            n = 1
            while Category.objects.filter(slug=slug).exists():
                slug = f'{base_slug}-{n}'
                n += 1
            cat, _ = Category.objects.get_or_create(
                name__iexact=name,
                defaults={'name': name, 'slug': slug},
            )
            return cat
        return None

    def create(self, validated_data):
        variants_data = validated_data.pop('variants')
        category_id   = validated_data.pop('category_id', None)
        category_name = validated_data.pop('category_name', None)
        category      = self._resolve_category(category_id, category_name)

        vendor  = self.context['vendor']
        product = VendorProduct.objects.create(
            vendor=vendor,
            category=category,
            status='pending_approval',
            **validated_data,
        )
        for v in variants_data:
            VendorProductVariant.objects.create(vendor_product=product, **v)
        return product

    def update(self, instance, validated_data):
        variants_data = validated_data.pop('variants', None)
        category_id   = validated_data.pop('category_id', None)
        category_name = validated_data.pop('category_name', None)

        if category_id is not None or category_name is not None:
            instance.category = self._resolve_category(category_id, category_name)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # Re-submit for review if was approved or rejected
        if instance.status in ('approved', 'rejected'):
            instance.status = 'pending_approval'

        instance.save()

        if variants_data is not None:
            instance.variants.all().delete()
            for v in variants_data:
                VendorProductVariant.objects.create(vendor_product=instance, **v)

        return instance


class VendorProductReadSerializer(serializers.ModelSerializer):
    """Full detail for vendor viewing their own product."""
    category = CategoryBriefSerializer(read_only=True)
    variants = VendorProductVariantSerializer(many=True, read_only=True)
    images   = VendorProductImageSerializer(many=True, read_only=True)

    class Meta:
        model  = VendorProduct
        fields = [
            'id', 'name', 'description', 'category',
            'sku', 'barcode', 'monthly_capacity', 'yearly_capacity',
            'status', 'rejection_reason', 'admin_notes',
            'variants', 'images', 'submitted_at', 'reviewed_at',
        ]


class VendorProductListSerializer(serializers.ModelSerializer):
    """Compact list row for vendor dashboard."""
    category_name = serializers.SerializerMethodField()
    primary_image = serializers.SerializerMethodField()
    variant_count = serializers.SerializerMethodField()
    mrp_range     = serializers.SerializerMethodField()

    class Meta:
        model  = VendorProduct
        fields = [
            'id', 'name', 'category_name', 'sku', 'status',
            'primary_image', 'variant_count', 'mrp_range', 'submitted_at',
        ]

    def get_category_name(self, obj):
        return obj.category.name if obj.category else None

    def get_primary_image(self, obj):
        img = obj.images.filter(is_primary=True).first() or obj.images.first()
        if not img:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(img.image.url) if request else img.image.url

    def get_variant_count(self, obj):
        return obj.variants.count()

    def get_mrp_range(self, obj):
        variants = obj.variants.filter(is_active=True)
        mrps = [v.mrp for v in variants]
        if not mrps:
            return None
        lo, hi = min(mrps), max(mrps)
        return {'min': str(lo), 'max': str(hi)}


class VendorProductAdminSerializer(serializers.ModelSerializer):
    """Admin detail view — includes catalog link and reviewer info."""
    category          = CategoryBriefSerializer(read_only=True)
    variants          = VendorProductVariantSerializer(many=True, read_only=True)
    images            = VendorProductImageSerializer(many=True, read_only=True)
    vendor_name       = serializers.SerializerMethodField()
    reviewed_by_name  = serializers.SerializerMethodField()
    catalog_product_id = serializers.SerializerMethodField()

    class Meta:
        model  = VendorProduct
        fields = [
            'id', 'vendor_name', 'name', 'description', 'category',
            'sku', 'barcode', 'monthly_capacity', 'yearly_capacity',
            'status', 'rejection_reason', 'admin_notes',
            'variants', 'images',
            'catalog_product_id', 'reviewed_by_name', 'reviewed_at', 'submitted_at',
        ]

    def get_vendor_name(self, obj):
        return obj.vendor.company_name

    def get_reviewed_by_name(self, obj):
        if obj.reviewed_by:
            return obj.reviewed_by.get_full_name()
        return None

    def get_catalog_product_id(self, obj):
        return str(obj.catalog_product_id) if obj.catalog_product_id else None


class VendorProductAdminListSerializer(serializers.ModelSerializer):
    """Compact list row for admin vendor-products page."""
    category_name = serializers.SerializerMethodField()
    vendor_name   = serializers.SerializerMethodField()
    primary_image = serializers.SerializerMethodField()
    variant_count = serializers.SerializerMethodField()
    mrp_range     = serializers.SerializerMethodField()

    class Meta:
        model  = VendorProduct
        fields = [
            'id', 'vendor_name', 'name', 'category_name', 'sku', 'status',
            'primary_image', 'variant_count', 'mrp_range', 'submitted_at',
        ]

    def get_category_name(self, obj):
        return obj.category.name if obj.category else None

    def get_vendor_name(self, obj):
        return obj.vendor.company_name

    def get_primary_image(self, obj):
        img = obj.images.filter(is_primary=True).first() or obj.images.first()
        if not img:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(img.image.url) if request else img.image.url

    def get_variant_count(self, obj):
        return obj.variants.count()

    def get_mrp_range(self, obj):
        variants = obj.variants.filter(is_active=True)
        mrps = [v.mrp for v in variants]
        if not mrps:
            return None
        lo, hi = min(mrps), max(mrps)
        return {'min': str(lo), 'max': str(hi)}
