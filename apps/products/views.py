import logging

from django.db import transaction
from django.db.models import Q, Sum, Case, When, IntegerField, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from core.mixins import LoginRequiredMixin
from apps.authentication.mixins import PublicListAuthMixin
from apps.authentication.permissions import IsAdmin, IsAdminOrEmployee, IsUPAUser, HasPermission
from .models import Category, Product, ProductImage, ProductVariant, UPADiscountSettings
from .serializers import (
    CategorySerializer,
    ProductListSerializer, ProductDetailSerializer, ProductWriteSerializer,
    ProductVariantSerializer, ProductVariantWriteSerializer,
    ProductImageSerializer,
    UPADiscountSettingsSerializer,
)
from .utils import get_upa_price


class _ProductPagination(PageNumberPagination):
    page_size = 20


# ── Category ──────────────────────────────────────────────────────────────────

class CategoryViewSet(PublicListAuthMixin, viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    lookup_field     = 'slug'

    def get_queryset(self):
        qs = Category.objects.select_related('parent').order_by('name')
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(name__icontains=search)
        return qs

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        return [IsAdminOrEmployee()]


# ── Product ───────────────────────────────────────────────────────────────────

class ProductViewSet(PublicListAuthMixin, viewsets.ModelViewSet):
    lookup_field   = 'slug'
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        if self.action == 'upa_price':
            return [IsUPAUser()]
        if self.action == 'toggle_publish':
            return [IsAdmin()]
        if self.action in ('destroy',):
            return [IsAdmin()]
        return [HasPermission('products.edit')]

    def get_queryset(self):
        qs = (
            Product.objects
            .select_related('category', 'created_by')
            .prefetch_related('images', 'variants')
        )
        user = self.request.user
        # Public / UPA users see only published products
        is_staff = (
            user.is_authenticated and
            getattr(user, 'role', None) in ('superadmin', 'admin', 'employee')
        )
        if not is_staff:
            qs = qs.filter(is_published=True)

        # Filters
        category_slug = self.request.query_params.get('category')
        search        = self.request.query_params.get('search')
        in_stock      = self.request.query_params.get('in_stock')
        status_filter = self.request.query_params.get('status')
        stock_filter  = self.request.query_params.get('stock')

        if category_slug:
            qs = qs.filter(category__slug=category_slug)

        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(sku__icontains=search))

        # Legacy boolean in_stock param (keep for backward compat)
        if in_stock == 'true':
            qs = qs.filter(variants__stock_quantity__gt=0, variants__is_active=True).distinct()

        # Status filter
        if status_filter == 'published':
            qs = qs.filter(is_published=True)
        elif status_filter == 'unpublished':
            qs = qs.filter(is_published=False)

        # Stock level filter — annotate with total active stock, then filter by threshold
        if stock_filter in ('in_stock', 'low_stock', 'out_of_stock'):
            qs = qs.annotate(
                _active_stock=Coalesce(
                    Sum(
                        Case(
                            When(variants__is_active=True, then='variants__stock_quantity'),
                            default=Value(0),
                            output_field=IntegerField(),
                        )
                    ),
                    Value(0),
                    output_field=IntegerField(),
                )
            )
            if stock_filter == 'in_stock':
                qs = qs.filter(_active_stock__gt=10)
            elif stock_filter == 'low_stock':
                qs = qs.filter(_active_stock__gt=0, _active_stock__lte=10)
            elif stock_filter == 'out_of_stock':
                qs = qs.filter(_active_stock=0)

        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        if self.action in ('create', 'update', 'partial_update'):
            return ProductWriteSerializer
        return ProductDetailSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        paginator = _ProductPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = ProductListSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        product = get_object_or_404(self.get_queryset(), slug=kwargs['slug'])
        return Response(ProductDetailSerializer(product, context={'request': request}).data)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    # ── Custom actions ────────────────────────────────────────────────────────

    @extend_schema(tags=['Products'])
    @action(detail=True, methods=['post'], url_path='upload-image',
            parser_classes=[MultiPartParser, FormParser])
    def upload_image(self, request, slug=None):
        """Upload one image for this product."""
        product = get_object_or_404(Product, slug=slug)
        image_file = request.FILES.get('image')
        if not image_file:
            return Response({'detail': 'No image provided.'}, status=status.HTTP_400_BAD_REQUEST)

        alt_text   = request.data.get('alt_text', '')
        order      = int(request.data.get('order', 0))
        is_primary = request.data.get('is_primary', 'false').lower() == 'true'

        # If marking as primary, unset existing primary
        if is_primary:
            product.images.filter(is_primary=True).update(is_primary=False)

        img = ProductImage.objects.create(
            product=product,
            image=image_file,
            alt_text=alt_text,
            order=order,
            is_primary=is_primary,
        )
        return Response(
            ProductImageSerializer(img, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(tags=['Products'])
    @action(detail=True, methods=['delete'], url_path=r'images/(?P<image_id>[^/.]+)')
    def delete_image(self, request, slug=None, image_id=None):
        """Delete a specific image from this product."""
        product = get_object_or_404(Product, slug=slug)
        img     = get_object_or_404(ProductImage, id=image_id, product=product)
        img.image.delete(save=False)
        img.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(tags=['Products'])
    @action(detail=True, methods=['get'], url_path='upa-price')
    def upa_price(self, request, slug=None):
        """UPA price for all variants of a product (IsUPAUser only)."""
        product = get_object_or_404(Product.objects.prefetch_related('variants'), slug=slug)
        variants = product.variants.filter(is_active=True)
        data = {
            'product': get_upa_price(product),
            'variants': [
                {'id': str(v.id), 'name': v.name, **get_upa_price(v)}
                for v in variants
            ],
        }
        return Response(data)

    @extend_schema(tags=['Products'])
    @action(detail=True, methods=['patch'], url_path='set-pricing')
    def set_pricing(self, request, slug=None):
        """Set purchase price, GST, other charges and variant MRP/UPA prices."""
        from decimal import Decimal
        logger = logging.getLogger(__name__)
        product = get_object_or_404(Product, slug=slug)

        decimal_fields = {'purchase_price', 'gst_percentage', 'other_charges', 'upa_discount_override'}
        product_fields = [
            'purchase_price', 'gst_percentage',
            'other_charges', 'other_charges_type',
            'upa_discount_override',
        ]
        for field in product_fields:
            if field in request.data:
                value = request.data[field]
                if field in decimal_fields and value is not None:
                    value = Decimal(str(value))
                setattr(product, field, value)

        variant_prices = request.data.get('variant_prices', [])

        upa_discount_pct = Decimal(str(
            request.data.get(
                'upa_discount_override',
                product.upa_discount_override or 0,
            )
        ))

        with transaction.atomic():
            for vp in variant_prices:
                try:
                    variant = product.variants.get(id=vp['id'])
                    update_fields = []

                    if 'purchase_price' in vp:
                        variant.purchase_price = Decimal(str(vp['purchase_price']))
                        update_fields.append('purchase_price')

                    if 'selling_price' in vp:
                        selling = Decimal(str(vp['selling_price']))
                        variant.mrp = selling
                        update_fields.append('mrp')

                        if upa_discount_pct > 0:
                            variant.upa_price = (
                                selling * (1 - upa_discount_pct / 100)
                            ).quantize(Decimal('0.01'))
                        else:
                            variant.upa_price = selling
                        update_fields.append('upa_price')

                    if update_fields:
                        variant.save(update_fields=update_fields)
                except Exception as e:
                    logger.error(f'Variant pricing error: {e}')

            has_purchase = (
                any('purchase_price' in vp for vp in variant_prices)
                or product.purchase_price
            )
            if has_purchase:
                product.pricing_configured = True

            # Sync product.mrp to the lowest active variant MRP
            variant_mrps = list(
                product.variants.filter(mrp__isnull=False)
                .values_list('mrp', flat=True)
            )
            if variant_mrps:
                product.mrp = min(variant_mrps)

            product.save()

        from apps.products.serializers import ProductDetailSerializer
        return Response(
            ProductDetailSerializer(product, context={'request': request}).data
        )

    @extend_schema(tags=['Products'])
    @action(detail=True, methods=['patch'], url_path='toggle-publish')
    def toggle_publish(self, request, slug=None):
        """Flip is_published for a product."""
        product = get_object_or_404(Product, slug=slug)
        product.is_published = not product.is_published
        product.save(update_fields=['is_published', 'updated_at'])
        return Response({
            'slug':         product.slug,
            'is_published': product.is_published,
            'message':      f"Product {'published' if product.is_published else 'unpublished'} successfully.",
        })

    @extend_schema(tags=['Products'])
    @action(detail=True, methods=['post'], url_path='variants')
    def add_variant(self, request, slug=None):
        """Add a variant to this product."""
        product    = get_object_or_404(Product, slug=slug)
        serializer = ProductVariantWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        variant = serializer.save(product=product)
        return Response(
            ProductVariantSerializer(variant).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(tags=['Products'])
    @action(detail=True, methods=['patch', 'delete'], url_path=r'variants/(?P<variant_id>[^/.]+)')
    def manage_variant(self, request, slug=None, variant_id=None):
        """Update or delete a specific variant."""
        product = get_object_or_404(Product, slug=slug)
        variant = get_object_or_404(ProductVariant, id=variant_id, product=product)
        if request.method == 'DELETE':
            variant.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = ProductVariantWriteSerializer(variant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProductVariantSerializer(variant).data)


# ── UPADiscountSettings ───────────────────────────────────────────────────────

class UPADiscountSettingsViewSet(LoginRequiredMixin, viewsets.ViewSet):

    def get_permissions(self):
        return [IsAdmin()]

    @extend_schema(tags=['Products'])
    @action(detail=False, methods=['get'], url_path='')
    def retrieve_settings(self, request):
        """GET current global UPA discount settings."""
        obj = UPADiscountSettings.get()
        return Response(UPADiscountSettingsSerializer(obj).data)

    @extend_schema(tags=['Products'])
    @action(detail=False, methods=['patch'], url_path='')
    def update_settings(self, request):
        """PATCH global UPA discount %."""
        obj        = UPADiscountSettings.get()
        serializer = UPADiscountSettingsSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        obj.updated_by = request.user
        serializer.save()
        return Response(serializer.data)
