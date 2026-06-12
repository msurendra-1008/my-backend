from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DiscountCodeViewSet, BillingViewSet

router = DefaultRouter()
router.register('discount-codes', DiscountCodeViewSet, basename='discount-codes')
router.register('', BillingViewSet, basename='billing')

urlpatterns = [path('', include(router.urls))]
