from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DepartmentViewSet, EmployeeProfileViewSet, PayrollMonthViewSet

router = DefaultRouter()
router.register('departments',  DepartmentViewSet,      basename='department')
router.register('employees',    EmployeeProfileViewSet, basename='employee-profile')
router.register('payroll',      PayrollMonthViewSet,    basename='payroll-month')

urlpatterns = [
    path('', include(router.urls)),
]
