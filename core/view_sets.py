from rest_framework import viewsets
from rest_framework import filters as rest_filters
from django_filters import rest_framework as django_filters

from .mixins import LoginRequiredMixin, LogAccessMixin


class BaseModelRefViewSet(LogAccessMixin, viewsets.ModelViewSet, LoginRequiredMixin):
    """
    Base ViewSet for all app ViewSets.

    Features:
    - JWT authentication + IsAuthenticated enforced via LoginRequiredMixin
    - Audit signal fired on every retrieve via LogAccessMixin
    - Search, ordering, and django-filter backends pre-configured
    - lookup_field set to 'ref' for UUID-based public URLs (ignored by
      ViewSets that override get_object(), e.g. MeViewSet)

    Usage:
        class ProductViewSet(BaseModelRefViewSet):
            queryset = Product.objects.all()
            serializer_class = ProductSerializer
            search_fields = ['name']
            filterset_fields = ['status']
            ordering_fields = ['created_at']

    TODO: Un-comment perform_create below when object-level permissions
          (django-guardian) are added to the project.
    """

    filter_backends = (
        rest_filters.SearchFilter,
        rest_filters.OrderingFilter,
        django_filters.DjangoFilterBackend,
    )
    lookup_field = "ref"

    # TODO: Un-comment when django-guardian is installed.
    # def perform_create(self, serializer):
    #     instance = serializer.save()
    #     if self.request.user and self.request.user.is_authenticated:
    #         try:
    #             from core.guardian_utils import assign_creator_permissions
    #             assign_creator_permissions(instance, self.request.user)
    #         except Exception as e:
    #             logger.exception(e)
    #     return instance

    def retrieve(self, request, *args, **kwargs):
        """Retrieve object and fire audit access signal."""
        obj = self.get_object()
        self._fire_accessed(obj)
        return super().retrieve(request, *args, **kwargs)
