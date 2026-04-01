from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TenderViewSet, VendorTenderViewSet

router = DefaultRouter()
router.register('vendor', VendorTenderViewSet, basename='vendor-tender')
router.register('', TenderViewSet, basename='tender')

urlpatterns = [path('', include(router.urls))]
