from decimal import Decimal
from django.db import transaction
from django.utils import timezone


@transaction.atomic
def process_salary_payment(payroll_month, paid_by):
    """Debit company wallet and mark PayrollMonth as paid."""
    from apps.company_wallet.utils import _get_wallet, _record

    wallet = _get_wallet()
    amount = Decimal(str(payroll_month.net_salary))

    if amount <= 0:
        raise ValueError('Net salary must be positive')

    employee_name = payroll_month.employee.user.full_name
    label = f'{payroll_month.month:02d}/{payroll_month.year}'

    _record(
        wallet,
        tx_type      = 'salary_paid',
        amount       = -amount,
        description  = f'Salary {label} — {employee_name}',
        triggered_by = paid_by,
    )

    payroll_month.status  = 'paid'
    payroll_month.paid_at = timezone.now()
    payroll_month.paid_by = paid_by
    payroll_month.save()


def generate_payroll_for_month(month, year):
    """
    Create PayrollMonth records for all active employees who have a salary
    structure. Skips employees that already have a record for the month.
    Returns (created_count, skipped_count).
    """
    from apps.payroll.models import EmployeeProfile, PayrollMonth

    created = 0
    skipped = 0

    employees = EmployeeProfile.objects.filter(is_active=True).select_related('salary_structure')

    for emp in employees:
        try:
            structure = emp.salary_structure
        except EmployeeProfile.salary_structure.RelatedObjectDoesNotExist:
            skipped += 1
            continue

        _, was_created = PayrollMonth.objects.get_or_create(
            employee = emp,
            month    = month,
            year     = year,
            defaults = {
                'basic':            structure.basic,
                'hra':              structure.hra,
                'da':               structure.da,
                'transport':        structure.transport,
                'other_allowance':  structure.other_allowance,
                'gross_salary':     structure.gross_salary,
                'pf_deduction':     structure.pf_deduction,
                'esi_deduction':    structure.esi_deduction,
                'tds_deduction':    structure.tds_deduction,
                'other_deduction':  structure.other_deduction,
                'total_deductions': structure.total_deductions,
                'net_salary':       structure.net_salary,
            },
        )
        if was_created:
            created += 1
        else:
            skipped += 1

    return created, skipped


def generate_salary_slip_html(payroll_month):
    """Return a basic HTML salary slip string for the given PayrollMonth."""
    emp  = payroll_month.employee
    user = emp.user
    dept = emp.department.name if emp.department else '—'
    label = f'{payroll_month.month:02d}/{payroll_month.year}'

    rows_earning = [
        ('Basic', payroll_month.basic),
        ('HRA',   payroll_month.hra),
        ('DA',    payroll_month.da),
        ('Transport Allowance', payroll_month.transport),
        ('Other Allowance',     payroll_month.other_allowance),
    ]
    rows_deduction = [
        ('PF',              payroll_month.pf_deduction),
        ('ESI',             payroll_month.esi_deduction),
        ('TDS',             payroll_month.tds_deduction),
        ('Other Deduction', payroll_month.other_deduction),
    ]

    def tr(label, val):
        return f'<tr><td>{label}</td><td style="text-align:right">₹{val}</td></tr>'

    earning_html   = ''.join(tr(l, v) for l, v in rows_earning)
    deduction_html = ''.join(tr(l, v) for l, v in rows_deduction)

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Salary Slip {label}</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 13px; margin: 20px; }}
  h2   {{ text-align: center; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; }}
  th {{ background: #f5f5f5; }}
  .net {{ font-weight: bold; font-size: 15px; }}
</style>
</head>
<body>
  <h2>Salary Slip — {label}</h2>
  <p><b>Employee:</b> {user.full_name} &nbsp;&nbsp;
     <b>Code:</b> {emp.employee_code} &nbsp;&nbsp;
     <b>Department:</b> {dept} &nbsp;&nbsp;
     <b>Designation:</b> {emp.designation or '—'}</p>
  <table>
    <tr><th colspan="2">Earnings</th><th colspan="2">Deductions</th></tr>
    <tr>
      <td colspan="2">
        <table>{earning_html}
          <tr class="net"><td>Gross Salary</td><td style="text-align:right">₹{payroll_month.gross_salary}</td></tr>
        </table>
      </td>
      <td colspan="2">
        <table>{deduction_html}
          <tr class="net"><td>Total Deductions</td><td style="text-align:right">₹{payroll_month.total_deductions}</td></tr>
        </table>
      </td>
    </tr>
    <tr class="net"><td colspan="3">Net Salary</td><td style="text-align:right">₹{payroll_month.net_salary}</td></tr>
  </table>
  <p style="margin-top:20px;font-size:11px;color:#888">
    Status: {payroll_month.get_status_display()}
    {f' | Paid on: {payroll_month.paid_at.strftime("%d %b %Y") if payroll_month.paid_at else ""}' if payroll_month.status == 'paid' else ''}
  </p>
</body>
</html>
"""
