from datetime import date
from rest_framework import serializers
from .models import PublicHoliday, LeaveBalance, AttendanceRecord, EmployeeProfile


class PublicHolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model  = PublicHoliday
        fields = ['id', 'date', 'name', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_date(self, value):
        if value.year < 2000 or value.year > 2100:
            raise serializers.ValidationError('Year must be between 2000 and 2100.')
        return value


class LeaveBalanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_code = serializers.SerializerMethodField()

    class Meta:
        model  = LeaveBalance
        fields = [
            'id', 'employee', 'employee_name', 'employee_code',
            'year', 'casual_leave', 'sick_leave', 'earned_leave', 'updated_at',
        ]
        read_only_fields = ['id', 'updated_at', 'employee_name', 'employee_code']

    def get_employee_name(self, obj):
        return obj.employee.user.full_name

    def get_employee_code(self, obj):
        return obj.employee.employee_code

    def validate_year(self, value):
        if value < 2000 or value > 2100:
            raise serializers.ValidationError('Year must be between 2000 and 2100.')
        return value


class AttendanceRecordSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_code = serializers.SerializerMethodField()
    marked_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = AttendanceRecord
        fields = [
            'id', 'employee', 'employee_name', 'employee_code',
            'date', 'status', 'leave_type', 'notes',
            'marked_by', 'marked_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'marked_by', 'employee_name', 'employee_code', 'marked_by_name']

    def get_employee_name(self, obj):
        return obj.employee.user.full_name

    def get_employee_code(self, obj):
        return obj.employee.employee_code

    def get_marked_by_name(self, obj):
        return obj.marked_by.full_name if obj.marked_by else None

    def validate(self, data):
        status     = data.get('status', getattr(self.instance, 'status', None))
        leave_type = data.get('leave_type', getattr(self.instance, 'leave_type', None))

        if status == 'leave' and not leave_type:
            raise serializers.ValidationError({'leave_type': 'leave_type is required when status is "leave".'})
        if status != 'leave' and leave_type:
            data['leave_type'] = None

        return data


class BulkMarkAttendanceSerializer(serializers.Serializer):
    employee_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=500,
    )
    date       = serializers.DateField()
    status     = serializers.ChoiceField(choices=AttendanceRecord.STATUS_CHOICES)
    leave_type = serializers.ChoiceField(choices=AttendanceRecord.LEAVE_TYPE_CHOICES, required=False, allow_null=True)
    notes      = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        if data.get('status') == 'leave' and not data.get('leave_type'):
            raise serializers.ValidationError({'leave_type': 'leave_type is required when status is "leave".'})
        return data
