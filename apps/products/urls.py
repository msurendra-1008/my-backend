from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BrandViewSet, CategoryViewSet, ProductViewSet, UPADiscountSettingsViewSet

router = DefaultRouter()
router.register('categories', CategoryViewSet, basename='category')
router.register('brands',     BrandViewSet,    basename='brand')
router.register('products',   ProductViewSet,  basename='product')

urlpatterns = [
    path('', include(router.urls)),
    path('upa-discount/', UPADiscountSettingsViewSet.as_view({
        'get':   'retrieve_settings',
        'patch': 'update_settings',
    }), name='upa-discount'),
]
