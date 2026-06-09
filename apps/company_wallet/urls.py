from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.company_wallet.views import CompanyWalletViewSet

router = DefaultRouter()
router.register(r'', CompanyWalletViewSet, basename='company-wallet')

urlpatterns = [
    path('', include(router.urls)),
]
