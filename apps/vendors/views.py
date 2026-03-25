from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.permissions import IsAdmin, IsApprovedVendor, IsVendor
from apps.products.models import Product, ProductImage, ProductVariant
from .models import VendorDocument, VendorProfile, VendorProduct, VendorProductImage
from .serializers import (
    VendorAdminSerializer,
    VendorDocumentSerializer,
    VendorListSerializer,
    VendorLoginSerializer,
    VendorProductAdminListSerializer,
    VendorProductAdminSerializer,
    VendorProductImageSerializer,
    VendorProductListSerializer,
    VendorProductReadSerializer,
    VendorProductWriteSerializer,
    VendorProfileSerializer,
    VendorProfileUpdateSerializer,
    VendorRegisterSerializer,
)


def _tokens(user):
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}


class _VendorPagination(PageNumberPagination):
    page_size = 20


# ── Public auth ───────────────────────────────────────────────────────────────

class VendorAuthViewSet(viewsets.ViewSet):

    @action(detail=False, methods=['post'], url_path='register', permission_classes=[AllowAny])
    def register(self, request):
        serializer = VendorRegisterSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        return Response(
            {
                **_tokens(profile.user),
                'profile': VendorProfileSerializer(profile, context={'request': request}).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['post'], url_path='login', permission_classes=[AllowAny])
    def login(self, request):
        serializer = VendorLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        profile = getattr(user, 'vendor_profile', None)
        return Response({
            **_tokens(user),
            'profile': VendorProfileSerializer(profile, context={'request': request}).data if profile else None,
        })


# ── Vendor manages own profile ────────────────────────────────────────────────

class VendorProfileViewSet(viewsets.ViewSet):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        return [IsVendor()]

    @action(detail=False, methods=['get'], url_path='me')
    def me(self, request):
        profile = getattr(request.user, 'vendor_profile', None)
        if not profile:
            return Response({'detail': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(VendorProfileSerializer(profile, context={'request': request}).data)

    @action(detail=False, methods=['patch'], url_path='me/update')
    def update_profile(self, request):
        profile = getattr(request.user, 'vendor_profile', None)
        if not profile:
            return Response({'detail': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = VendorProfileUpdateSerializer(
            profile, data=request.data, partial=True, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(VendorProfileSerializer(profile, context={'request': request}).data)

    @action(detail=False, methods=['post'], url_path='me/documents')
    def upload_document(self, request):
        profile = getattr(request.user, 'vendor_profile', None)
        if not profile:
            return Response({'detail': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        label = request.data.get('label', '').strip()
        file  = request.FILES.get('file')
        if not label:
            return Response({'detail': 'Label is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not file:
            return Response({'detail': 'File is required.'}, status=status.HTTP_400_BAD_REQUEST)
        doc = VendorDocument.objects.create(vendor=profile, label=label, file=file)
        return Response(
            VendorDocumentSerializer(doc, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['delete'], url_path='documents')
    def delete_document(self, request, pk=None):
        profile = getattr(request.user, 'vendor_profile', None)
        if not profile:
            return Response({'detail': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            doc = VendorDocument.objects.get(pk=pk, vendor=profile)
        except VendorDocument.DoesNotExist:
            return Response({'detail': 'Document not found.'}, status=status.HTTP_404_NOT_FOUND)
        doc.file.delete(save=False)
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Admin manages vendors ─────────────────────────────────────────────────────

class VendorAdminViewSet(viewsets.ViewSet):

    def get_permissions(self):
        return [IsAdmin()]

    def list(self, request):
        qs = VendorProfile.objects.select_related('user').prefetch_related('categories')
        search = request.query_params.get('search', '').strip()
        status_filter = request.query_params.get('status', '').strip()
        category_filter = request.query_params.get('category', '').strip()

        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(company_name__icontains=search) |
                Q(user__mobile__icontains=search) |
                Q(user__email__icontains=search) |
                Q(gst_number__icontains=search)
            )
        if status_filter:
            qs = qs.filter(status=status_filter)
        if category_filter:
            qs = qs.filter(categories__id=category_filter)

        # Stats
        from .models import VendorProfile as VP
        stats = {
            'total':         VP.objects.count(),
            'pending':       VP.objects.filter(status='pending').count(),
            'approved':      VP.objects.filter(status='approved').count(),
            'rejected':      VP.objects.filter(status='rejected').count(),
            'docs_requested': VP.objects.filter(status='docs_requested').count(),
        }

        paginator = _VendorPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = VendorListSerializer(page, many=True, context={'request': request})
        response = paginator.get_paginated_response(serializer.data)
        response.data['stats'] = stats
        return response

    def retrieve(self, request, pk=None):
        try:
            profile = VendorProfile.objects.select_related('user', 'approved_by').prefetch_related('categories', 'documents').get(pk=pk)
        except VendorProfile.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(VendorAdminSerializer(profile, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='approve')
    def approve(self, request, pk=None):
        try:
            profile = VendorProfile.objects.get(pk=pk)
        except VendorProfile.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        profile.status      = 'approved'
        profile.approved_by = request.user
        profile.approved_at = timezone.now()
        profile.rejection_reason = ''
        profile.save(update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason'])
        return Response(VendorAdminSerializer(profile, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='reject')
    def reject(self, request, pk=None):
        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response({'detail': 'Rejection reason is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            profile = VendorProfile.objects.get(pk=pk)
        except VendorProfile.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        profile.status           = 'rejected'
        profile.rejection_reason = reason
        profile.save(update_fields=['status', 'rejection_reason'])
        return Response(VendorAdminSerializer(profile, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='request-docs')
    def request_docs(self, request, pk=None):
        notes = request.data.get('admin_notes', '').strip()
        if not notes:
            return Response({'detail': 'admin_notes is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            profile = VendorProfile.objects.get(pk=pk)
        except VendorProfile.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        profile.status      = 'docs_requested'
        profile.admin_notes = notes
        profile.save(update_fields=['status', 'admin_notes'])
        return Response(VendorAdminSerializer(profile, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='notes')
    def admin_notes(self, request, pk=None):
        notes = request.data.get('admin_notes', '').strip()
        try:
            profile = VendorProfile.objects.get(pk=pk)
        except VendorProfile.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        profile.admin_notes = notes
        profile.save(update_fields=['admin_notes'])
        return Response({'admin_notes': profile.admin_notes})


# ── Vendor manages own products ───────────────────────────────────────────────

class VendorProductViewSet(viewsets.ViewSet):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        return [IsApprovedVendor()]

    def _get_vendor(self, request):
        return getattr(request.user, 'vendor_profile', None)

    def list(self, request):
        vendor = self._get_vendor(request)
        qs = VendorProduct.objects.filter(vendor=vendor).prefetch_related('variants', 'images', 'category')
        status_filter = request.query_params.get('status', '').strip()
        if status_filter:
            qs = qs.filter(status=status_filter)
        paginator = _VendorPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = VendorProductListSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    def create(self, request):
        vendor = self._get_vendor(request)
        serializer = VendorProductWriteSerializer(data=request.data, context={'request': request, 'vendor': vendor})
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        return Response(VendorProductReadSerializer(product, context={'request': request}).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        vendor = self._get_vendor(request)
        try:
            product = VendorProduct.objects.prefetch_related('variants', 'images', 'category').get(pk=pk, vendor=vendor)
        except VendorProduct.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(VendorProductReadSerializer(product, context={'request': request}).data)

    def _update(self, request, pk):
        vendor = self._get_vendor(request)
        try:
            product = VendorProduct.objects.get(pk=pk, vendor=vendor)
        except VendorProduct.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if product.status == 'not_continued':
            return Response({'detail': 'Cannot edit a product marked as not continued.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = VendorProductWriteSerializer(product, data=request.data, partial=True, context={'request': request, 'vendor': vendor})
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        return Response(VendorProductReadSerializer(product, context={'request': request}).data)

    def update(self, request, pk=None):
        return self._update(request, pk)

    def partial_update(self, request, pk=None):
        return self._update(request, pk)

    @action(detail=True, methods=['post'], url_path='images')
    def upload_image(self, request, pk=None):
        vendor = self._get_vendor(request)
        try:
            product = VendorProduct.objects.get(pk=pk, vendor=vendor)
        except VendorProduct.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        file = request.FILES.get('image')
        if not file:
            return Response({'detail': 'Image file is required.'}, status=status.HTTP_400_BAD_REQUEST)
        alt_text   = request.data.get('alt_text', '').strip()
        order      = int(request.data.get('order', 0))
        is_primary = request.data.get('is_primary', 'false').lower() == 'true'
        if is_primary:
            product.images.filter(is_primary=True).update(is_primary=False)
        img = VendorProductImage.objects.create(
            vendor_product=product, image=file, alt_text=alt_text,
            order=order, is_primary=is_primary,
        )
        return Response(VendorProductImageSerializer(img, context={'request': request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path=r'images/(?P<image_pk>[^/.]+)')
    def delete_image(self, request, pk=None, image_pk=None):
        vendor = self._get_vendor(request)
        try:
            product = VendorProduct.objects.get(pk=pk, vendor=vendor)
        except VendorProduct.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            img = VendorProductImage.objects.get(pk=image_pk, vendor_product=product)
        except VendorProductImage.DoesNotExist:
            return Response({'detail': 'Image not found.'}, status=status.HTTP_404_NOT_FOUND)
        img.image.delete(save=False)
        img.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['patch'], url_path='deactivate')
    def deactivate(self, request, pk=None):
        vendor = self._get_vendor(request)
        try:
            product = VendorProduct.objects.get(pk=pk, vendor=vendor)
        except VendorProduct.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        product.status = 'not_continued'
        product.save(update_fields=['status'])
        return Response(VendorProductReadSerializer(product, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='reactivate')
    def reactivate(self, request, pk=None):
        vendor = self._get_vendor(request)
        try:
            product = VendorProduct.objects.get(pk=pk, vendor=vendor)
        except VendorProduct.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if product.status != 'not_continued':
            return Response({'detail': 'Product is not deactivated.'}, status=status.HTTP_400_BAD_REQUEST)
        product.status = 'pending_approval'
        product.save(update_fields=['status'])
        return Response(VendorProductReadSerializer(product, context={'request': request}).data)


# ── Admin manages vendor products ─────────────────────────────────────────────

class VendorProductAdminViewSet(viewsets.ViewSet):

    def get_permissions(self):
        return [IsAdmin()]

    def list(self, request):
        qs = VendorProduct.objects.select_related('vendor', 'category').prefetch_related('variants', 'images')
        search        = request.query_params.get('search', '').strip()
        status_filter = request.query_params.get('status', '').strip()
        vendor_filter = request.query_params.get('vendor', '').strip()

        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(sku__icontains=search) |
                Q(vendor__company_name__icontains=search)
            )
        if status_filter:
            qs = qs.filter(status=status_filter)
        if vendor_filter:
            qs = qs.filter(vendor__id=vendor_filter)

        from .models import VendorProduct as VP
        stats = {
            'total':            VP.objects.count(),
            'pending_approval': VP.objects.filter(status='pending_approval').count(),
            'approved':         VP.objects.filter(status='approved').count(),
            'rejected':         VP.objects.filter(status='rejected').count(),
            'not_continued':    VP.objects.filter(status='not_continued').count(),
        }

        paginator = _VendorPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = VendorProductAdminListSerializer(page, many=True, context={'request': request})
        response = paginator.get_paginated_response(serializer.data)
        response.data['stats'] = stats
        return response

    def retrieve(self, request, pk=None):
        try:
            product = VendorProduct.objects.select_related('vendor', 'category', 'reviewed_by').prefetch_related('variants', 'images').get(pk=pk)
        except VendorProduct.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(VendorProductAdminSerializer(product, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='approve')
    def approve(self, request, pk=None):
        from django.db import transaction
        import shutil, os
        from django.core.files.base import ContentFile

        try:
            vp = VendorProduct.objects.select_related('vendor', 'category').prefetch_related('variants', 'images').get(pk=pk)
        except VendorProduct.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if vp.status == 'approved' and vp.catalog_product:
            return Response({'detail': 'Already approved.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Determine a unique SKU for the catalog product
            base_sku = vp.sku
            sku = base_sku
            n = 1
            while Product.objects.filter(sku=sku).exists():
                sku = f'{base_sku}-{n}'
                n += 1

            # Use min MRP across variants as product-level MRP
            variant_mrps = list(vp.variants.values_list('mrp', flat=True))
            product_mrp = min(variant_mrps) if variant_mrps else 0

            catalog = Product.objects.create(
                name=vp.name,
                description=vp.description,
                category=vp.category,
                sku=sku,
                barcode=vp.barcode,
                mrp=product_mrp,
                is_published=False,
                created_by=request.user,
            )

            for v in vp.variants.all():
                var_sku = v.sku
                n = 1
                while ProductVariant.objects.filter(sku=var_sku).exists():
                    var_sku = f'{v.sku}-{n}'
                    n += 1
                ProductVariant.objects.create(
                    product=catalog,
                    name=v.name,
                    variant_type=v.variant_type,
                    sku=var_sku,
                    mrp=v.mrp,
                    stock_quantity=0,
                    is_active=v.is_active,
                )

            for img in vp.images.all():
                if img.image:
                    img.image.open()
                    content = img.image.read()
                    img.image.close()
                    filename = os.path.basename(img.image.name)
                    pimg = ProductImage(
                        product=catalog,
                        alt_text=img.alt_text,
                        order=img.order,
                        is_primary=img.is_primary,
                    )
                    pimg.image.save(filename, ContentFile(content), save=True)

            vp.catalog_product = catalog
            vp.status          = 'approved'
            vp.reviewed_by     = request.user
            vp.reviewed_at     = timezone.now()
            vp.save(update_fields=['catalog_product', 'status', 'reviewed_by', 'reviewed_at'])

        return Response(VendorProductAdminSerializer(vp, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='reject')
    def reject(self, request, pk=None):
        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response({'detail': 'Rejection reason is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            vp = VendorProduct.objects.get(pk=pk)
        except VendorProduct.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        vp.status           = 'rejected'
        vp.rejection_reason = reason
        vp.reviewed_by      = request.user
        vp.reviewed_at      = timezone.now()
        vp.save(update_fields=['status', 'rejection_reason', 'reviewed_by', 'reviewed_at'])
        return Response(VendorProductAdminSerializer(vp, context={'request': request}).data)

    @action(detail=True, methods=['patch'], url_path='notes')
    def admin_notes(self, request, pk=None):
        notes = request.data.get('admin_notes', '').strip()
        try:
            vp = VendorProduct.objects.get(pk=pk)
        except VendorProduct.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        vp.admin_notes = notes
        vp.save(update_fields=['admin_notes'])
        return Response({'admin_notes': vp.admin_notes})
