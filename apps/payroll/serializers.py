from rest_framework import serializers
from .models import Department, EmployeeProfile, SalaryStructure, PayrollMonth


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Department
        fields = ['id', 'name']


class SalaryStructureSerializer(serializers.ModelSerializer):
    gross_salary     = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total_deductions = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    net_salary       = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model  = SalaryStructure
        fields = [
            'id', 'basic', 'hra', 'da', 'transport', 'other_allowance',
            'pf_deduction', 'esi_deduction', 'tds_deduction', 'other_deduction',
            'gross_salary', 'total_deductions', 'net_salary',
            'effective_from', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class EmployeeProfileSerializer(serializers.ModelSerializer):
    full_name       = serializers.SerializerMethodField()
    email           = serializers.SerializerMethodField()
    mobile          = serializers.SerializerMethodField()
    role            = serializers.SerializerMethodField()
    department_name = serializers.SerializerMethodField()
    salary_structure = SalaryStructureSerializer(read_only=True)

    class Meta:
        model  = EmployeeProfile
        fields = [
            'id', 'user', 'full_name', 'email', 'mobile', 'role',
            'employee_code', 'department', 'department_name', 'designation',
            'employment_type', 'date_of_joining',
            'bank_name', 'bank_account', 'bank_ifsc',
            'is_active', 'salary_structure', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_full_name(self, obj):
        return obj.user.full_name

    def get_email(self, obj):
        return obj.user.email

    def get_mobile(self, obj):
        return obj.user.mobile

    def get_role(self, obj):
        return obj.user.role

    def get_department_name(self, obj):
        return obj.department.name if obj.department else None


class CreateEmployeeProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model  = EmployeeProfile
        fields = [
            'user', 'employee_code', 'department', 'designation',
            'employment_type', 'date_of_joining',
            'bank_name', 'bank_account', 'bank_ifsc',
        ]

    def validate_user(self, value):
        if EmployeeProfile.objects.filter(user=value).exists():
            raise serializers.ValidationError('Employee profile already exists for this user.')
        return value


class UpdateEmployeeProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model  = EmployeeProfile
        fields = [
            'employee_code', 'department', 'designation',
            'employment_type', 'date_of_joining',
            'bank_name', 'bank_account', 'bank_ifsc', 'is_active',
        ]


class PayrollMonthSerializer(serializers.ModelSerializer):
    employee_name    = serializers.SerializerMethodField()
    employee_code    = serializers.SerializerMethodField()
    department_name  = serializers.SerializerMethodField()
    designation      = serializers.SerializerMethodField()
    paid_by_name     = serializers.SerializerMethodField()

    class Meta:
        model  = PayrollMonth
        fields = [
            'id', 'employee', 'employee_name', 'employee_code',
            'department_name', 'designation',
            'month', 'year',
            'basic', 'hra', 'da', 'transport', 'other_allowance',
            'gross_salary', 'pf_deduction', 'esi_deduction', 'tds_deduction',
            'other_deduction', 'total_deductions', 'net_salary',
            'status', 'paid_at', 'paid_by', 'paid_by_name', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'status', 'paid_at', 'paid_by', 'created_at', 'updated_at',
        ]

    def get_employee_name(self, obj):
        return obj.employee.user.full_name

    def get_employee_code(self, obj):
        return obj.employee.employee_code

    def get_department_name(self, obj):
        return obj.employee.department.name if obj.employee.department else None

    def get_designation(self, obj):
        return obj.employee.designation

    def get_paid_by_name(self, obj):
        return obj.paid_by.full_name if obj.paid_by else None
