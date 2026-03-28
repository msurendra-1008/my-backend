from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import ProcurementRequirementViewSet, VendorRequirementViewSet, PurchaseOrderViewSet

router = DefaultRouter()

# Admin requirements — /api/v1/procurement/requirements/
router.register(r'requirements', ProcurementRequirementViewSet, basename='procurement-requirements')

# Vendor requirements — /api/v1/procurement/vendor-requirements/
router.register(r'vendor-requirements', VendorRequirementViewSet, basename='vendor-requirements')

# Purchase orders — /api/v1/procurement/purchase-orders/
router.register(r'purchase-orders', PurchaseOrderViewSet, basename='purchase-orders')

urlpatterns = [
    path('', include(router.urls)),
]
