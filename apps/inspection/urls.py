from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import IncomingShipmentViewSet, InspectionSettingsViewSet

router = DefaultRouter()
router.register(r'shipments', IncomingShipmentViewSet, basename='shipment')

urlpatterns = router.urls + [
    path(
        'settings/',
        InspectionSettingsViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update'}),
        name='inspection-settings',
    ),
]
