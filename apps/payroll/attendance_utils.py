import calendar
import logging
from datetime import date
from decimal import Decimal

logger = logging.getLogger(__name__)


# ── Delivery partner helpers ──────────────────────────────────────────────────

def _find_delivery_partner(employee):
    """
    Return the DeliveryPartner whose user matches this EmployeeProfile's user,
    or None. Uses the shared auth user as the bridge — there is no direct FK
    from DeliveryPartner to EmployeeProfile.
    """
    try:
        from apps.delivery.models import DeliveryPartner
        return DeliveryPartner.objects.get(user=employee.user)
    except Exception:
        return None


def _duty_hours_to_status(hours, duty_settings):
    """Convert duty hours float to an attendance status string."""
    full_h     = float(duty_settings.full_day_hours)
    half_h     = float(duty_settings.half_day_hours)
    count_half = duty_settings.count_half_days

    if hours >= full_h:
        return 'present'
    elif count_half and hours >= half_h:
        return 'half_day'
    else:
        return 'absent'


def _duty_cell(hours, duty_settings):
    """Build a cell-status dict for a delivery-partner day sourced from duty logs."""
    status = _duty_hours_to_status(hours, duty_settings)
    notes  = f'{hours}h on duty' if hours > 0 else ''
    return {
        'status':      status,
        'leave_type':  None,
        'notes':       notes,
        'is_holiday':  False,
        'record_id':   None,
        'duty_hours':  hours,
    }


# ── Core status functions ─────────────────────────────────────────────────────

def get_cell_status(employee, target_date):
    """
    Returns a status dict for a single date (no DB writes).

    Priority:
      1. Sunday          → week_off (always)
      2. Public holiday  → holiday  (always)
      3. Manual AttendanceRecord → use that (manual always wins)
      4. Delivery partner → derive status from duty hours
      5. Future          → future
      6. Default         → absent
    """
    from django.utils import timezone
    from .models import AttendanceRecord, PublicHoliday

    if target_date.weekday() == 6:
        return {'status': 'week_off', 'leave_type': None, 'notes': '', 'is_holiday': False, 'record_id': None}

    try:
        holiday = PublicHoliday.objects.get(date=target_date, is_active=True)
        return {'status': 'holiday', 'leave_type': None, 'notes': holiday.name, 'is_holiday': True, 'record_id': None}
    except PublicHoliday.DoesNotExist:
        pass

    # Manual override always wins over duty-derived status
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

    # Delivery partner: derive attendance from duty hours
    partner = _find_delivery_partner(employee)
    if partner is not None:
        try:
            from apps.delivery.duty_utils import calculate_daily_hours
            from apps.delivery.models import DeliverySettings
            daily         = calculate_daily_hours(partner, target_date)
            duty_settings = DeliverySettings.get()
            return _duty_cell(daily['total_hours'], duty_settings)
        except Exception as exc:
            logger.error('Duty hours lookup failed for %s on %s: %s', employee, target_date, exc)

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

    # Delivery partner setup — fetch once outside the loop
    partner       = _find_delivery_partner(employee)
    duty_settings = None
    if partner is not None:
        try:
            from apps.delivery.models import DeliverySettings
            duty_settings = DeliverySettings.get()
        except Exception:
            partner = None

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
        elif partner is not None and duty_settings is not None:
            try:
                from apps.delivery.duty_utils import calculate_daily_hours
                daily = calculate_daily_hours(partner, d)
                st    = _duty_hours_to_status(daily['total_hours'], duty_settings)
                summary[st] = summary.get(st, 0) + 1
                if st == 'present':
                    summary['paid_days'] += 1
                elif st == 'half_day':
                    summary['paid_days'] += 0.5
            except Exception as exc:
                logger.error('Duty hours lookup failed for %s on %s: %s', employee, d, exc)
                summary['absent'] += 1
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

    # Delivery partner setup — fetch once outside the loop
    partner       = _find_delivery_partner(employee)
    duty_settings = None
    if partner is not None:
        try:
            from apps.delivery.models import DeliverySettings
            duty_settings = DeliverySettings.get()
        except Exception:
            partner = None

    days_list = []

    for day_num in range(1, days_in_month + 1):
        d         = date(year, month, day_num)
        is_future = d > today
        is_sunday = d.weekday() == 6
        duty_hours = None

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
        elif partner is not None and duty_settings is not None:
            try:
                from apps.delivery.duty_utils import calculate_daily_hours
                daily      = calculate_daily_hours(partner, d)
                duty_hours = daily['total_hours']
                cell       = _duty_cell(duty_hours, duty_settings)
                status     = cell['status']
                leave_type = None
                notes      = cell['notes']
                record_id  = None
            except Exception as exc:
                logger.error('Duty hours lookup failed for %s on %s: %s', employee, d, exc)
                status     = 'absent'
                leave_type = None
                notes      = ''
                record_id  = None
        else:
            status     = 'absent'
            leave_type = None
            notes      = ''
            record_id  = None

        entry = {
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
        }
        if duty_hours is not None:
            entry['duty_hours'] = duty_hours
        days_list.append(entry)

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


def mark_leave_range(
        employee, from_date, to_date,
        leave_type, leave_note='',
        include_weekends=False,
        marked_by=None):
    """
    Mark leave for an employee across a date range.

    Rules:
      - Skips weekends (Sat + Sun) by default unless include_weekends=True
      - Always skips active PublicHoliday dates
      - Returns a summary dict of what was marked and skipped
    """
    from datetime import timedelta
    from .models import AttendanceRecord, PublicHoliday, LeaveBalance

    if from_date > to_date:
        raise ValueError('from_date must be before or equal to to_date')

    valid_leave_types = ('casual', 'sick', 'earned', 'unpaid', 'other')
    if leave_type not in valid_leave_types:
        raise ValueError(f'Invalid leave_type: {leave_type}')

    # Fetch all public holiday dates in range once
    holiday_map = {
        h.date: h.name
        for h in PublicHoliday.objects.filter(
            date__gte=from_date, date__lte=to_date, is_active=True
        )
    }

    marked_dates     = []
    skipped_weekends = 0
    skipped_holidays = []
    current          = from_date

    while current <= to_date:
        is_weekend = current.weekday() >= 5  # Sat=5, Sun=6

        if is_weekend and not include_weekends:
            skipped_weekends += 1
            current += timedelta(days=1)
            continue

        if current in holiday_map:
            skipped_holidays.append({
                'date': str(current),
                'name': holiday_map[current],
            })
            current += timedelta(days=1)
            continue

        AttendanceRecord.objects.update_or_create(
            employee=employee,
            date=current,
            defaults={
                'status':     'leave',
                'leave_type': leave_type,
                'notes':      leave_note or '',
                'marked_by':  marked_by,
            },
        )
        marked_dates.append(str(current))
        current += timedelta(days=1)

    # Return leave balance for the from_date year if it exists
    year = from_date.year
    balance_qs = LeaveBalance.objects.filter(employee=employee, year=year).first()
    leave_balance_after = None
    if balance_qs:
        leave_balance_after = {
            'year':         year,
            'casual_leave': float(balance_qs.casual_leave),
            'sick_leave':   float(balance_qs.sick_leave),
            'earned_leave': float(balance_qs.earned_leave),
        }

    return {
        'marked_dates':      marked_dates,
        'total_marked':      len(marked_dates),
        'skipped_weekends':  skipped_weekends,
        'skipped_holidays':  skipped_holidays,
        'leave_type':        leave_type,
        'leave_balance_after': leave_balance_after,
    }


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
