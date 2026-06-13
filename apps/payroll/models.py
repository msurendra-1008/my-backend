import uuid
from django.conf import settings
from django.db import models


class Department(models.Model):
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class EmployeeProfile(models.Model):
    EMPLOYMENT_TYPE_CHOICES = [
        ('full_time',  'Full Time'),
        ('part_time',  'Part Time'),
        ('contract',   'Contract'),
        ('intern',     'Intern'),
    ]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user            = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payroll_profile',
    )
    employee_code   = models.CharField(max_length=20, unique=True)
    department      = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='employees',
    )
    designation     = models.CharField(max_length=100, blank=True)
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, default='full_time')
    date_of_joining = models.DateField(null=True, blank=True)
    bank_name       = models.CharField(max_length=100, blank=True)
    bank_account    = models.CharField(max_length=30, blank=True)
    bank_ifsc       = models.CharField(max_length=15, blank=True)
    is_active       = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user.full_name} ({self.employee_code})'


class SalaryStructure(models.Model):
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee        = models.OneToOneField(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name='salary_structure',
    )
    basic           = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hra             = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    da              = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pf_deduction    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    esi_deduction   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tds_deduction   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    effective_from  = models.DateField()
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    @property
    def gross_salary(self):
        return self.basic + self.hra + self.da + self.transport + self.other_allowance

    @property
    def total_deductions(self):
        return self.pf_deduction + self.esi_deduction + self.tds_deduction + self.other_deduction

    @property
    def net_salary(self):
        return self.gross_salary - self.total_deductions

    def __str__(self):
        return f'Salary structure for {self.employee}'


class PayrollMonth(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid',    'Paid'),
    ]

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee        = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.PROTECT,
        related_name='payroll_months',
    )
    month           = models.PositiveSmallIntegerField()
    year            = models.PositiveSmallIntegerField()
    basic           = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hra             = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    da              = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_salary    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pf_deduction    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    esi_deduction   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tds_deduction   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_salary      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    paid_at         = models.DateTimeField(null=True, blank=True)
    paid_by         = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='payroll_payments_made',
    )
    notes           = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('employee', 'month', 'year')
        ordering        = ['-year', '-month']

    def __str__(self):
        return f'{self.employee} — {self.month}/{self.year}'
