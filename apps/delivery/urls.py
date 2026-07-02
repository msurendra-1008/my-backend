from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DeliveryZoneViewSet, DeliveryPartnerViewSet,
    DeliverySettingsView, DeliveryAssignmentViewSet,
    UnassignedOrdersView,
    PartnerMyAssignmentsView, PartnerUpdateStatusView,
    PartnerToggleDutyView, PartnerDutyStatusView, PartnerDutyLedgerView,
    AdminPartnerDutyLedgerView, AdminPartnerDutyReportView,
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
    # Duty — partner
    path('my-duty/toggle/',  PartnerToggleDutyView.as_view(),  name='partner-duty-toggle'),
    path('my-duty/status/',  PartnerDutyStatusView.as_view(),  name='partner-duty-status'),
    path('my-duty/ledger/',  PartnerDutyLedgerView.as_view(),  name='partner-duty-ledger'),
    # Duty — admin
    path('admin/partners/<uuid:partner_id>/duty-ledger/', AdminPartnerDutyLedgerView.as_view(), name='admin-partner-duty-ledger'),
    path('admin/partners/<uuid:partner_id>/duty-report/', AdminPartnerDutyReportView.as_view(), name='admin-partner-duty-report'),
]
