from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DeliveryZoneViewSet, DeliveryPartnerViewSet,
    DeliverySettingsView, DeliveryAssignmentViewSet,
    UnassignedOrdersView,
    PartnerMyAssignmentsView, PartnerUpdateStatusView,
)

router = DefaultRouter()
router.register('zones',       DeliveryZoneViewSet,       basename='delivery-zone')
router.register('partners',    DeliveryPartnerViewSet,    basename='delivery-partner')
router.register('assignments', DeliveryAssignmentViewSet, basename='delivery-assignment')

urlpatterns = [
    path('', include(router.urls)),
    path('settings/', DeliverySettingsView.as_view(), name='delivery-settings'),
    path('admin/unassigned/', UnassignedOrdersView.as_view(), name='delivery-unassigned'),
    path('my-assignments/', PartnerMyAssignmentsView.as_view(), name='partner-assignments'),
    path('my-assignments/<uuid:pk>/update-status/', PartnerUpdateStatusView.as_view(), name='partner-update-status'),
]
