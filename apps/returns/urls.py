from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import ReturnRequestViewSet, ReturnSettingsViewSet

router = DefaultRouter()
router.register(r"returns", ReturnRequestViewSet, basename="return")

settings_view = ReturnSettingsViewSet.as_view({
    "get":   "list",
    "patch": "update_settings",
})

urlpatterns = [
    path("return-settings/", settings_view, name="return-settings"),
    path("", include(router.urls)),
]
