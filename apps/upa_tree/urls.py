from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UPATreeViewSet

router = DefaultRouter()
router.register('', UPATreeViewSet, basename='upa-tree')

urlpatterns = [
    path('', include(router.urls)),
]
