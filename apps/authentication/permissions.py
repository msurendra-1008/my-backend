from rest_framework.permissions import BasePermission


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'superadmin')


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in ['superadmin', 'admin'])


class IsAdminOrEmployee(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in ['superadmin', 'admin', 'employee'])


class IsUPAUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'upa_user')


class IsVendor(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'vendor')


class IsApprovedVendor(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == 'vendor' and
            hasattr(request.user, 'vendor_profile') and
            request.user.vendor_profile.status == 'approved'
        )


class HasPermission(BasePermission):
    def __init__(self, perm):
        self.perm = perm

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.role in ['superadmin', 'admin']:
            return True
        try:
            return self.perm in request.user.employee_profile.permissions
        except Exception:
            return False
