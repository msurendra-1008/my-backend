from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from accounts.models import User
from .models import EmployeeProfile


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display  = ['email', 'mobile', 'full_name', 'role', 'upa_id', 'is_active', 'date_joined']
    list_filter   = ['role', 'is_active', 'is_staff']
    search_fields = ['email', 'mobile', 'first_name', 'last_name', 'upa_id']
    ordering      = ['-date_joined']
    fieldsets = (
        (None,           {'fields': ('email', 'mobile', 'password')}),
        ('Personal',     {'fields': ('first_name', 'last_name', 'photo')}),
        ('Role & UPA',   {'fields': ('role', 'upa_id')}),
        ('Permissions',  {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Dates',        {'fields': ('date_joined',)}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'mobile', 'first_name', 'last_name', 'role', 'password1', 'password2')}),
    )
    readonly_fields = ['date_joined']


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display  = ['user', 'department', 'created_by', 'created_at']
    search_fields = ['user__email', 'user__mobile', 'department']
