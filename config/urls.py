from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts.views import MeViewSet
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from apps.dashboard.views import DashboardStatsView

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
    path('api/v1/commissions/', include('apps.commissions.urls')),
    path('api/v1/company-wallet/', include('apps.company_wallet.urls')),
    path('api/v1/dashboard/stats/', DashboardStatsView.as_view(), name='dashboard-stats'),
    path('api/v1/billing/', include('apps.billing.urls')),
    path('api/v1/hr/', include('apps.payroll.urls')),
    path('api/v1/delivery/', include('apps.delivery.urls')),
    # Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
