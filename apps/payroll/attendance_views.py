from django.http import HttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.authentication.permissions import IsAdmin
from .models import PublicHoliday, LeaveBalance, AttendanceRecord, EmployeeProfile
from .attendance_serializers import (
    PublicHolidaySerializer,
    LeaveBalanceSerializer,
    AttendanceRecordSerializer,
    BulkMarkAttendanceSerializer,
    LeaveRangeSerializer,
)
from .attendance_utils import (
    get_employee_calendar,
    mark_attendance,
    bulk_mark_attendance,
    mark_leave_range,
    auto_fill_payroll_from_attendance,
    MONTH_NAMES,
)


class SmallPagination(PageNumberPagination):
    page_size             = 50
    page_size_query_param = 'page_size'
    max_page_size         = 200


class PublicHolidayViewSet(viewsets.ModelViewSet):
    queryset           = PublicHoliday.objects.all()
    serializer_class   = PublicHolidaySerializer
    permission_classes = [IsAdmin]
    pagination_class   = None

    def get_queryset(self):
        qs   = super().get_queryset()
        year = self.request.query_params.get('year')
        if year:
            qs = qs.filter(date__year=year)
        return qs


class LeaveBalanceViewSet(viewsets.ModelViewSet):
    queryset           = LeaveBalance.objects.select_related('employee__user').order_by('-year', 'employee__employee_code')
    serializer_class   = LeaveBalanceSerializer
    permission_classes = [IsAdmin]
    pagination_class   = SmallPagination

    def get_queryset(self):
        qs   = super().get_queryset()
        emp  = self.request.query_params.get('employee')
        year = self.request.query_params.get('year')
        if emp:
            qs = qs.filter(employee_id=emp)
        if year:
            qs = qs.filter(year=year)
        return qs


class AttendanceViewSet(viewsets.ModelViewSet):
    queryset           = AttendanceRecord.objects.select_related('employee__user', 'marked_by').order_by('-date')
    serializer_class   = AttendanceRecordSerializer
    permission_classes = [IsAdmin]
    pagination_class   = SmallPagination

    def get_queryset(self):
        qs    = super().get_queryset()
        emp   = self.request.query_params.get('employee')
        month = self.request.query_params.get('month')
        year  = self.request.query_params.get('year')
        if emp:
            qs = qs.filter(employee_id=emp)
        if month:
            qs = qs.filter(date__month=month)
        if year:
            qs = qs.filter(date__year=year)
        return qs

    def perform_create(self, serializer):
        serializer.save(marked_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(marked_by=self.request.user)

    @action(detail=False, methods=['get'], url_path=r'calendar/(?P<employee_id>[^/.]+)')
    def calendar(self, request, employee_id=None):
        try:
            employee = EmployeeProfile.objects.get(pk=employee_id)
        except EmployeeProfile.DoesNotExist:
            return Response({'error': 'Employee not found.'}, status=404)

        try:
            year  = int(request.query_params.get('year',  0))
            month = int(request.query_params.get('month', 0))
        except (TypeError, ValueError):
            return Response({'error': 'year and month must be integers.'}, status=400)

        if not (1 <= month <= 12) or year < 2000 or year > 2100:
            return Response({'error': 'Invalid year or month.'}, status=400)

        data = get_employee_calendar(employee, year, month)
        return Response(data)

    @action(detail=False, methods=['post'], url_path='mark')
    def mark(self, request):
        """Mark attendance for a single employee on a single date."""
        employee_id = request.data.get('employee')
        date_str    = request.data.get('date')
        att_status  = request.data.get('status')
        leave_type  = request.data.get('leave_type')
        notes       = request.data.get('notes', '')

        if not all([employee_id, date_str, att_status]):
            return Response({'error': 'employee, date, and status are required.'}, status=400)

        try:
            employee = EmployeeProfile.objects.get(pk=employee_id)
        except EmployeeProfile.DoesNotExist:
            return Response({'error': 'Employee not found.'}, status=404)

        from datetime import date as date_cls
        try:
            target_date = date_cls.fromisoformat(date_str)
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

        valid_statuses = [c[0] for c in AttendanceRecord.STATUS_CHOICES]
        if att_status not in valid_statuses:
            return Response({'error': f'status must be one of: {valid_statuses}'}, status=400)

        if att_status == 'leave' and not leave_type:
            return Response({'error': 'leave_type is required when status is "leave".'}, status=400)

        record, created = mark_attendance(
            employee, target_date, att_status,
            leave_type=leave_type, notes=notes, marked_by=request.user,
        )
        return Response(
            AttendanceRecordSerializer(record).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=False, methods=['post'], url_path='bulk-mark')
    def bulk_mark(self, request):
        """Mark attendance for multiple employees on the same date."""
        serializer = BulkMarkAttendanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        employees = EmployeeProfile.objects.filter(id__in=data['employee_ids'], is_active=True)

        results = bulk_mark_attendance(
            employees,
            target_date=data['date'],
            status=data['status'],
            notes=data.get('notes', ''),
            marked_by=request.user,
        )
        return Response(results)

    @action(detail=False, methods=['post'], url_path='mark-leave-range')
    def mark_leave_range_view(self, request):
        """Mark leave for an employee across a date range. Skips weekends and public holidays."""
        ser = LeaveRangeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        try:
            employee = EmployeeProfile.objects.get(id=d['employee_id'])
        except EmployeeProfile.DoesNotExist:
            return Response({'error': 'Employee not found.'}, status=404)

        try:
            result = mark_leave_range(
                employee         = employee,
                from_date        = d['from_date'],
                to_date          = d['to_date'],
                leave_type       = d['leave_type'],
                leave_note       = d.get('leave_note', ''),
                include_weekends = d.get('include_weekends', False),
                marked_by        = request.user,
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

        return Response(result)

    @action(detail=False, methods=['get'], url_path='export')
    def export(self, request):
        """Export attendance as Excel or HTML-PDF."""
        from .attendance_export import export_excel, export_html_pdf

        employee_id  = request.query_params.get('employee')
        month        = request.query_params.get('month')
        year         = request.query_params.get('year')
        export_fmt   = request.query_params.get('format', 'excel')

        if not all([employee_id, month, year]):
            return Response({'error': 'employee, month, and year are required.'}, status=400)

        try:
            employee = EmployeeProfile.objects.get(pk=employee_id)
        except EmployeeProfile.DoesNotExist:
            return Response({'error': 'Employee not found.'}, status=404)

        try:
            month = int(month)
            year  = int(year)
        except (TypeError, ValueError):
            return Response({'error': 'month and year must be integers.'}, status=400)

        if not (1 <= month <= 12):
            return Response({'error': 'month must be 1–12.'}, status=400)

        calendar_data = get_employee_calendar(employee, year, month)

        if export_fmt == 'pdf':
            html = export_html_pdf(calendar_data)
            return HttpResponse(html, content_type='text/html')

        wb = export_excel(calendar_data)
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        month_name = MONTH_NAMES[month]
        response['Content-Disposition'] = (
            f'attachment; filename="attendance_{employee.employee_code}_{month_name}_{year}.xlsx"'
        )
        wb.save(response)
        return response
