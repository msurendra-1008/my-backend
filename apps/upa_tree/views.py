from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from core.mixins import LoginRequiredMixin
from apps.authentication.permissions import IsAdmin, IsUPAUser
from .models import UPATree
from .utils import get_tree_stats, get_subtree
from .serializers import (
    MyConnectionsSerializer, UPANodeSerializer,
    UPAProfileSerializer, UPASearchSerializer,
)


class _SearchPagination(PageNumberPagination):
    page_size = 20


class _BrowsePagination(PageNumberPagination):
    page_size = 10


class UPATreeViewSet(LoginRequiredMixin, viewsets.ModelViewSet):
    queryset         = UPATree.objects.select_related('user', 'parent_user', 'user__wallet')
    lookup_field     = 'user__upa_id'
    lookup_url_kwarg = 'upa_id'

    # Only GET + PATCH — no create/update/destroy via default routes
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_permissions(self):
        if self.action == 'my_connections':
            return [IsUPAUser()]
        return [IsAdmin()]

    def get_serializer_class(self):
        if self.action == 'my_connections': return MyConnectionsSerializer
        if self.action == 'search':         return UPASearchSerializer
        if self.action == 'profile':        return UPAProfileSerializer
        return UPANodeSerializer

    # Disable default list / retrieve — only custom actions are exposed
    def list(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def retrieve(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    # ── User-facing ──────────────────────────────────────────────────────────

    @extend_schema(tags=['UPA Tree'])
    @action(detail=False, methods=['get'], url_path='my-connections')
    def my_connections(self, request):
        """Logged-in UPA user's parent + 3 legs."""
        try:
            node = UPATree.objects.select_related(
                'user', 'parent_user',
            ).get(user=request.user)
        except UPATree.DoesNotExist:
            return Response({
                'upa_id': None, 'depth_level': None,
                'parent': None,
                'legs': {'L': None, 'M': None, 'R': None},
            })
        return Response(MyConnectionsSerializer(node, context={'request': request}).data)

    # ── Admin ─────────────────────────────────────────────────────────────────

    @extend_schema(tags=['UPA Tree'])
    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        """Platform-wide UPA tree statistics."""
        return Response(get_tree_stats())

    @extend_schema(tags=['UPA Tree'])
    @action(detail=False, methods=['get'], url_path='search')
    def search(self, request):
        """Search UPA users by ?q= (UPA ID, name, mobile). Paginated 20/page."""
        q = request.query_params.get('q', '').strip()
        if not q:
            return Response({'count': 0, 'next': None, 'previous': None, 'results': []})
        qs = (
            UPATree.objects
            .select_related('user', 'parent_user')
            .filter(user__role='upa_user')
            .filter(
                Q(user__upa_id__icontains=q)    |
                Q(user__first_name__icontains=q) |
                Q(user__last_name__icontains=q)  |
                Q(user__mobile__icontains=q)
            )
            .order_by('joined_at')
        )
        paginator = _SearchPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = UPASearchSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(tags=['UPA Tree'])
    @action(detail=False, methods=['get'], url_path='browse')
    def browse(self, request):
        """Paginated root nodes (10/page) each with 1 level of children."""
        qs = (
            UPATree.objects
            .filter(parent_user__isnull=True)
            .select_related('user', 'parent_user')
            .order_by('joined_at')
        )
        paginator = _BrowsePagination()
        page = paginator.paginate_queryset(qs, request)
        data = []
        for node in page:
            node_data = UPANodeSerializer(node, context={'request': request}).data
            node_data['children'] = {
                leg: UPANodeSerializer(child, context={'request': request}).data if child else None
                for leg, child in node.get_children().items()
            }
            data.append(node_data)
        return paginator.get_paginated_response(data)

    @extend_schema(tags=['UPA Tree'])
    @action(detail=True, methods=['get'], url_path='subtree')
    def subtree(self, request, upa_id=None):
        """Full subtree rooted at upa_id, max 5 levels deep."""
        node = get_object_or_404(UPATree, user__upa_id=upa_id)
        return Response(get_subtree(node.user, max_depth=5))

    @extend_schema(tags=['UPA Tree'])
    @action(detail=True, methods=['get'], url_path='profile')
    def profile(self, request, upa_id=None):
        """Full profile: node fields + wallet balance + children summary."""
        node = get_object_or_404(
            UPATree.objects.select_related('user', 'parent_user', 'user__wallet'),
            user__upa_id=upa_id,
        )
        return Response(UPAProfileSerializer(node, context={'request': request}).data)

    @extend_schema(tags=['UPA Tree'])
    @action(detail=True, methods=['patch'], url_path='toggle-active')
    def toggle_active(self, request, upa_id=None):
        """Flip user.is_active for the given upa_id."""
        node = get_object_or_404(UPATree.objects.select_related('user'), user__upa_id=upa_id)
        user = node.user
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        return Response({
            'upa_id':    user.upa_id,
            'is_active': user.is_active,
            'message':   f"User {'activated' if user.is_active else 'deactivated'} successfully.",
        })
