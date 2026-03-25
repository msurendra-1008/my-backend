from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    VendorAuthViewSet, VendorAdminViewSet, VendorProfileViewSet,
    VendorProductViewSet, VendorProductAdminViewSet,
)

router = DefaultRouter()

# Auth — /api/v1/vendor/register/ and /api/v1/vendor/login/
router.register(r'', VendorAuthViewSet, basename='vendor-auth')

# Admin — /api/v1/vendor/admin/
router.register(r'admin', VendorAdminViewSet, basename='vendor-admin')

# Vendor profile — /api/v1/vendor/profile/
router.register(r'profile', VendorProfileViewSet, basename='vendor-profile')

# Vendor products — /api/v1/vendor/products/
router.register(r'products', VendorProductViewSet, basename='vendor-products')

# Admin vendor products — /api/v1/vendor/admin-products/
router.register(r'admin-products', VendorProductAdminViewSet, basename='vendor-admin-products')

urlpatterns = [
    path('', include(router.urls)),
]
