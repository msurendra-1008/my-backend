from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import AuthViewSet, EmployeeViewSet, UPAUserViewSet, UserSearchView, QuickUserCreateView

router = DefaultRouter()
router.register('auth',      AuthViewSet,    basename='auth')
router.register('employees', EmployeeViewSet, basename='employee')
router.register('upa-users', UPAUserViewSet,  basename='upa-user')

urlpatterns = [
    path('', include(router.urls)),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('auth/users/', UserSearchView.as_view(), name='user-search'),
    path('auth/quick-create/', QuickUserCreateView.as_view(), name='user-quick-create'),
]
