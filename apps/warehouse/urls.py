from rest_framework.routers import DefaultRouter

from .views import WarehouseViewSet, ZoneViewSet, RackViewSet, StockViewSet

router = DefaultRouter()
router.register(r'warehouses',  WarehouseViewSet, basename='warehouse')
router.register(r'zones',       ZoneViewSet,      basename='zone')
router.register(r'racks',       RackViewSet,      basename='rack')
router.register(r'stock',       StockViewSet,     basename='stock')

urlpatterns = router.urls
