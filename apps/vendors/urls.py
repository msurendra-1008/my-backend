from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import VendorAuthViewSet, VendorAdminViewSet, VendorProfileViewSet

router = DefaultRouter()

# Auth — /api/v1/vendor/register/ and /api/v1/vendor/login/
router.register(r'', VendorAuthViewSet, basename='vendor-auth')

# Admin — /api/v1/vendor/admin/
router.register(r'admin', VendorAdminViewSet, basename='vendor-admin')

# Vendor profile — /api/v1/vendor/profile/ (but actions use /me/, /me/update/, etc.)
router.register(r'profile', VendorProfileViewSet, basename='vendor-profile')

urlpatterns = [
    path('', include(router.urls)),
]
