from django.contrib import admin
from .models import Department, EmployeeProfile, SalaryStructure, PayrollMonth


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


class SalaryStructureInline(admin.StackedInline):
    model  = SalaryStructure
    extra  = 0
    fields = (
        'basic', 'hra', 'da', 'transport', 'other_allowance',
        'pf_deduction', 'esi_deduction', 'tds_deduction', 'other_deduction',
        'effective_from',
    )


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display   = ('employee_code', 'user', 'department', 'designation', 'employment_type', 'is_active')
    list_filter    = ('department', 'employment_type', 'is_active')
    search_fields  = ('employee_code', 'user__first_name', 'user__last_name', 'user__email')
    inlines        = [SalaryStructureInline]
    raw_id_fields  = ('user',)


@admin.register(PayrollMonth)
class PayrollMonthAdmin(admin.ModelAdmin):
    list_display  = ('employee', 'month', 'year', 'net_salary', 'status', 'paid_at', 'paid_by')
    list_filter   = ('status', 'year', 'month')
    search_fields = ('employee__employee_code', 'employee__user__first_name', 'employee__user__last_name')
    readonly_fields = ('paid_at', 'paid_by', 'created_at', 'updated_at')
