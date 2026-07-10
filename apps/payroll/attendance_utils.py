import calendar
from datetime import date
from decimal import Decimal


def get_cell_status(employee, target_date):
    """Returns a status dict for a single date (no DB writes)."""
    from django.utils import timezone
    from .models import AttendanceRecord, PublicHoliday

    if target_date.weekday() == 6:
        return {'status': 'week_off', 'leave_type': None, 'notes': '', 'is_holiday': False, 'record_id': None}

    try:
        holiday = PublicHoliday.objects.get(date=target_date, is_active=True)
        return {'status': 'holiday', 'leave_type': None, 'notes': holiday.name, 'is_holiday': True, 'record_id': None}
    except PublicHoliday.DoesNotExist:
        pass

    try:
        rec = AttendanceRecord.objects.get(employee=employee, date=target_date)
        return {
            'status':     rec.status,
            'leave_type': rec.leave_type,
            'notes':      rec.notes,
            'is_holiday': False,
            'record_id':  str(rec.id),
        }
    except AttendanceRecord.DoesNotExist:
        pass

    today = timezone.localdate()
    if target_date > today:
        return {'status': 'future', 'leave_type': None, 'notes': '', 'is_holiday': False, 'record_id': None}

    return {'status': 'absent', 'leave_type': None, 'notes': '', 'is_holiday': False, 'record_id': None}


def get_monthly_summary(employee, year, month):
    """Returns aggregate attendance counts for a month."""
    from django.utils import timezone
    from .models import AttendanceRecord, PublicHoliday

    _, days_in_month = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end   = date(year, month, days_in_month)

    records  = {r.date: r for r in AttendanceRecord.objects.filter(
        employee=employee, date__range=(month_start, month_end)
    )}
    holidays = {h.date: h.name for h in PublicHoliday.objects.filter(
        date__range=(month_start, month_end), is_active=True
    )}

    today = timezone.localdate()

    summary = {
        'present': 0, 'absent': 0, 'half_day': 0,
        'leave': 0, 'holiday': 0, 'week_off': 0,
        'working_days': 0, 'paid_days': 0.0,
    }

    for day_num in range(1, days_in_month + 1):
        d = date(year, month, day_num)
        if d > today:
            continue
        if d.weekday() == 6:
            summary['week_off'] += 1
            continue
        if d in holidays:
            summary['holiday'] += 1
            summary['paid_days'] += 1
            continue

        summary['working_days'] += 1

        if d in records:
            rec = records[d]
            st  = rec.status
            summary[st] = summary.get(st, 0) + 1
            if st == 'present':
                summary['paid_days'] += 1
            elif st == 'half_day':
                summary['paid_days'] += 0.5
            elif st == 'leave':
                summary['paid_days'] += 1
        else:
            summary['absent'] += 1

    return summary


DAYS_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
MONTH_NAMES = [
    '', 'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
]


def get_employee_calendar(employee, year, month):
    """Returns a calendar response dict including per-day entries and summary."""
    from django.utils import timezone
    from .models import AttendanceRecord, PublicHoliday

    _, days_in_month = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end   = date(year, month, days_in_month)

    records  = {r.date: r for r in AttendanceRecord.objects.filter(
        employee=employee, date__range=(month_start, month_end)
    )}
    holidays = {h.date: h.name for h in PublicHoliday.objects.filter(
        date__range=(month_start, month_end), is_active=True
    )}

    today = timezone.localdate()
    days_list = []

    for day_num in range(1, days_in_month + 1):
        d         = date(year, month, day_num)
        is_future = d > today
        is_sunday = d.weekday() == 6

        if is_sunday:
            status     = 'week_off'
            leave_type = None
            notes      = ''
            record_id  = None
        elif d in holidays:
            status     = 'holiday'
            leave_type = None
            notes      = holidays[d]
            record_id  = None
        elif d in records:
            rec        = records[d]
            status     = rec.status
            leave_type = rec.leave_type
            notes      = rec.notes
            record_id  = str(rec.id)
        elif is_future:
            status     = 'future'
            leave_type = None
            notes      = ''
            record_id  = None
        else:
            status     = 'absent'
            leave_type = None
            notes      = ''
            record_id  = None

        days_list.append({
            'date':       d.isoformat(),
            'day_num':    day_num,
            'day_name':   DAYS_SHORT[d.weekday()],
            'status':     status,
            'leave_type': leave_type,
            'notes':      notes,
            'is_today':   d == today,
            'is_future':  is_future,
            'is_sunday':  is_sunday,
            'record_id':  record_id,
        })

    return {
        'employee_id':   str(employee.id),
        'employee_name': employee.user.full_name,
        'employee_code': employee.employee_code,
        'year':          year,
        'month':         month,
        'month_name':    MONTH_NAMES[month],
        'days_in_month': days_in_month,
        'days':          days_list,
        'summary':       get_monthly_summary(employee, year, month),
    }


def mark_attendance(employee, target_date, status, leave_type=None, notes='', marked_by=None):
    """Creates or updates an AttendanceRecord. Returns (record, created)."""
    from .models import AttendanceRecord

    record, created = AttendanceRecord.objects.update_or_create(
        employee=employee,
        date=target_date,
        defaults={
            'status':     status,
            'leave_type': leave_type if status == 'leave' else None,
            'notes':      notes or '',
            'marked_by':  marked_by,
        },
    )
    return record, created


def bulk_mark_attendance(employees_qs, target_date, status, notes='', marked_by=None):
    """Marks attendance for multiple employees on the same date."""
    results = {'marked': 0, 'errors': []}
    for emp in employees_qs:
        try:
            mark_attendance(emp, target_date, status, notes=notes, marked_by=marked_by)
            results['marked'] += 1
        except Exception as exc:
            results['errors'].append({'employee_id': str(emp.id), 'error': str(exc)})
    return results


def auto_fill_payroll_from_attendance(employee, month, year):
    """
    Calculates working days and paid days from attendance records.
    Returns a dict; does NOT modify PayrollMonth directly.
    """
    from django.utils import timezone
    from .models import AttendanceRecord, PublicHoliday

    _, days_in_month = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end   = date(year, month, days_in_month)

    today = timezone.localdate()

    records  = {r.date: r for r in AttendanceRecord.objects.filter(
        employee=employee, date__range=(month_start, month_end)
    )}
    holidays = set(PublicHoliday.objects.filter(
        date__range=(month_start, month_end), is_active=True
    ).values_list('date', flat=True))

    working_days = 0
    paid_days    = Decimal('0')

    for day_num in range(1, days_in_month + 1):
        d = date(year, month, day_num)
        if d > today:
            continue
        if d.weekday() == 6:
            continue
        if d in holidays:
            paid_days += Decimal('1')
            continue

        working_days += 1

        if d in records:
            rec = records[d]
            if rec.status == 'present':
                paid_days += Decimal('1')
            elif rec.status == 'half_day':
                paid_days += Decimal('0.5')
            elif rec.status == 'leave':
                paid_days += Decimal('1')

    attendance_rate = (
        round(float(paid_days) / working_days * 100, 2)
        if working_days > 0 else 0
    )

    return {
        'working_days':    working_days,
        'paid_days':       float(paid_days),
        'attendance_rate': attendance_rate,
    }
