from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts.views import MeViewSet
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

me_view = MeViewSet.as_view({"get": "retrieve", "patch": "partial_update"})

urlpatterns = [
    path('admin/', admin.site.urls),
    # Legacy
    path('api/auth/', include('accounts.urls')),
    path('api/me/', me_view, name='me'),
    # v1
    path('api/v1/', include('apps.authentication.urls')),
    path('api/v1/tree/', include('apps.upa_tree.urls')),
    path('api/v1/wallet/', include('apps.wallet.urls')),
    path('api/v1/',        include('apps.products.urls')),
    path('api/v1/',        include('apps.orders.urls')),
    path('api/v1/',        include('apps.returns.urls')),
    path('api/v1/vendor/', include('apps.vendors.urls')),
    path('api/v1/procurement/', include('apps.procurement.urls')),
    path('api/v1/inspection/', include('apps.inspection.urls')),
    path('api/v1/warehouse/', include('apps.warehouse.urls')),
    path('api/v1/tender/', include('apps.tender.urls')),
    # Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
