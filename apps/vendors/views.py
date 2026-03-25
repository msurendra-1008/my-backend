from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.permissions import IsAdmin, IsVendor
from .models import VendorDocument, VendorProfile
from .serializers import (
    VendorAdminSerializer,
    VendorDocumentSerializer,
    VendorListSerializer,
    VendorLoginSerializer,
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
