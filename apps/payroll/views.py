from django.http import HttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.authentication.permissions import IsAdmin, IsAdminOrEmployee
from .models import Department, EmployeeProfile, SalaryStructure, PayrollMonth
from .serializers import (
    DepartmentSerializer,
    EmployeeProfileSerializer,
    CreateEmployeeProfileSerializer,
    UpdateEmployeeProfileSerializer,
    SalaryStructureSerializer,
    PayrollMonthSerializer,
)
from .utils import process_salary_payment, generate_payroll_for_month, generate_salary_slip_html


class StandardPagination(PageNumberPagination):
    page_size            = 20
    page_size_query_param = 'page_size'
    max_page_size        = 100


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset           = Department.objects.all().order_by('name')
    serializer_class   = DepartmentSerializer
    permission_classes = [IsAdminOrEmployee]
    pagination_class   = None

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsAdmin()]
        return [IsAdminOrEmployee()]


class EmployeeProfileViewSet(viewsets.ModelViewSet):
    queryset           = EmployeeProfile.objects.select_related(
        'user', 'department', 'salary_structure'
    ).order_by('employee_code')
    permission_classes = [IsAdmin]
    pagination_class   = StandardPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return CreateEmployeeProfileSerializer
        if self.action in ('update', 'partial_update'):
            return UpdateEmployeeProfileSerializer
        return EmployeeProfileSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        dept = self.request.query_params.get('department')
        search = self.request.query_params.get('search')
        active = self.request.query_params.get('is_active')
        if dept:
            qs = qs.filter(department_id=dept)
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(employee_code__icontains=search) |
                Q(designation__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__mobile__icontains=search)
            )
        if active is not None:
            qs = qs.filter(is_active=active.lower() == 'true')
        return qs

    @action(detail=True, methods=['post', 'put', 'patch'], url_path='salary-structure')
    def salary_structure(self, request, pk=None):
        employee = self.get_object()
        try:
            structure = employee.salary_structure
            serializer = SalaryStructureSerializer(structure, data=request.data, partial=True)
        except SalaryStructure.DoesNotExist:
            serializer = SalaryStructureSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        if hasattr(employee, 'salary_structure') and employee.salary_structure.pk:
            serializer.save()
        else:
            serializer.save(employee=employee)

        return Response(serializer.data)


class PayrollMonthViewSet(viewsets.ModelViewSet):
    queryset           = PayrollMonth.objects.select_related(
        'employee__user', 'employee__department', 'paid_by'
    ).order_by('-year', '-month', 'employee__employee_code')
    serializer_class   = PayrollMonthSerializer
    permission_classes = [IsAdmin]
    pagination_class   = StandardPagination

    def get_queryset(self):
        qs = super().get_queryset()
        month = self.request.query_params.get('month')
        year  = self.request.query_params.get('year')
        emp   = self.request.query_params.get('employee')
        stat  = self.request.query_params.get('status')
        if month:
            qs = qs.filter(month=month)
        if year:
            qs = qs.filter(year=year)
        if emp:
            qs = qs.filter(employee_id=emp)
        if stat:
            qs = qs.filter(status=stat)
        return qs

    @action(detail=False, methods=['post'], url_path='generate')
    def generate(self, request):
        month = request.data.get('month')
        year  = request.data.get('year')
        if not month or not year:
            return Response({'error': 'month and year are required'}, status=400)
        try:
            month = int(month)
            year  = int(year)
        except (TypeError, ValueError):
            return Response({'error': 'month and year must be integers'}, status=400)
        if not (1 <= month <= 12):
            return Response({'error': 'month must be 1–12'}, status=400)

        created, skipped = generate_payroll_for_month(month, year)
        return Response({'created': created, 'skipped': skipped})

    @action(detail=True, methods=['post'], url_path='pay')
    def pay(self, request, pk=None):
        pm = self.get_object()
        if pm.status == 'paid':
            return Response({'error': 'Already paid'}, status=400)
        try:
            process_salary_payment(pm, paid_by=request.user)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        return Response(PayrollMonthSerializer(pm).data)

    @action(detail=True, methods=['get'], url_path='slip')
    def slip(self, request, pk=None):
        pm   = self.get_object()
        html = generate_salary_slip_html(pm)
        return HttpResponse(html, content_type='text/html')
