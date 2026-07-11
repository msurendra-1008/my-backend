from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DepartmentViewSet, EmployeeProfileViewSet, PayrollMonthViewSet
from .attendance_views import PublicHolidayViewSet, LeaveBalanceViewSet, AttendanceViewSet

router = DefaultRouter()
router.register('departments',     DepartmentViewSet,      basename='department')
router.register('employees',       EmployeeProfileViewSet, basename='employee-profile')
router.register('payroll',         PayrollMonthViewSet,    basename='payroll-month')
router.register('holidays',        PublicHolidayViewSet,   basename='holiday')
router.register('leave-balances',  LeaveBalanceViewSet,    basename='leave-balance')
router.register('attendance',      AttendanceViewSet,      basename='attendance')

urlpatterns = [
    path('', include(router.urls)),
]
