from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AddressViewSet,
    CartViewSet,
    CheckoutInitiateView,
    CheckoutConfirmView,
    UserOrderViewSet,
    AdminOrderViewSet,
)

router = DefaultRouter()
router.register(r"addresses", AddressViewSet, basename="address")
router.register(r"cart",      CartViewSet,    basename="cart")
router.register(r"orders",    UserOrderViewSet, basename="order")
router.register(r"admin/orders", AdminOrderViewSet, basename="admin-order")

urlpatterns = [
    path("checkout/initiate/", CheckoutInitiateView.as_view(), name="checkout-initiate"),
    path("checkout/confirm/",  CheckoutConfirmView.as_view(),  name="checkout-confirm"),
    path("", include(router.urls)),
]
