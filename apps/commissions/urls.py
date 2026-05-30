from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CommissionSettingsView,
    ProductCommissionRuleViewSet,
    CommissionBreakupViewSet,
    PendingCommissionViewSet,
)

router = DefaultRouter()
router.register('rules',    ProductCommissionRuleViewSet, basename='commission-rules')
router.register('breakups', CommissionBreakupViewSet,     basename='commission-breakups')
router.register('pending',  PendingCommissionViewSet,     basename='pending-commissions')

urlpatterns = [
    path('settings/', CommissionSettingsView.as_view(), name='commission-settings'),
    path('', include(router.urls)),
]
