"""
Duty tracking utilities.

All timestamps are stored as UTC in the database (Django standard).
The DutyLog.date field stores the IST date (UTC+5:30).
All display values returned to the frontend are pre-formatted in IST.
"""
import calendar
import pytz
from datetime import date, datetime

from django.utils import timezone

IST = pytz.timezone('Asia/Kolkata')


# ── Timezone helpers ─────────────────────────────────────────────────────────

def to_ist(dt):
    """Convert any datetime to IST timezone-aware. Returns None if dt is None."""
    if dt is None:
        return None
    return dt.astimezone(IST) if timezone.is_aware(dt) else IST.localize(dt)


def format_ist_time(dt):
    """Format datetime as 12-hour IST time string e.g. '09:00 AM'."""
    if dt is None:
        return None
    return to_ist(dt).strftime('%I:%M %p')


def ist_date_range(d):
    """Return (start_utc, end_utc) bracketing an IST calendar day."""
    day_start = IST.localize(datetime(d.year, d.month, d.day, 0, 0, 0))
    day_end   = IST.localize(datetime(d.year, d.month, d.day, 23, 59, 59))
    return day_start.astimezone(pytz.utc), day_end.astimezone(pytz.utc)


# ── Core duty functions ───────────────────────────────────────────────────────

def toggle_duty(partner, new_status):
    """
    Toggle partner duty status.
    Raises ValueError if partner is already in the requested status.
    Returns the created DutyLog.
    """
    from .models import DutyLog

    if new_status not in ('on_duty', 'off_duty'):
        raise ValueError("status must be 'on_duty' or 'off_duty'")

    last_log = DutyLog.objects.filter(partner=partner).order_by('-timestamp').first()
    if last_log and last_log.status == new_status:
        raise ValueError(f'Already {new_status.replace("_", " ")}')

    now     = timezone.now()          # UTC aware
    ist_now = now.astimezone(IST)

    log = DutyLog.objects.create(
        partner   = partner,
        status    = new_status,
        timestamp = now,
        date      = ist_now.date(),   # model.save() also computes this, explicit is clear
    )

    partner.is_on_duty      = (new_status == 'on_duty')
    partner.duty_started_at = now if new_status == 'on_duty' else None
    partner.save(update_fields=['is_on_duty', 'duty_started_at', 'updated_at'])

    return log


def calculate_daily_hours(partner, target_date):
    """
    Calculate duty sessions for a partner on a given IST date.
    Returns a dict with sessions, total_hours, first_in, last_out, etc.
    Sessions contain raw datetime objects; callers format for display.

    Past dates with an unclosed on_duty are capped at 23:59:59 IST of
    that date (partner forgot to toggle off). A single day can never
    exceed 24h. 'Ongoing' only applies to today.
    """
    from .models import DutyLog

    logs = list(
        DutyLog.objects.filter(partner=partner, date=target_date).order_by('timestamp')
    )

    sessions      = []
    total_seconds = 0
    first_in      = None
    last_out      = None
    pending_start = None

    today_ist = timezone.now().astimezone(IST).date()
    is_today  = (target_date == today_ist)

    for log in logs:
        if log.status == 'on_duty':
            pending_start = log.timestamp
            if first_in is None:
                first_in = log.timestamp
        elif log.status == 'off_duty' and pending_start is not None:
            duration_secs = (log.timestamp - pending_start).total_seconds()
            sessions.append({
                'start':      pending_start,
                'end':        log.timestamp,
                'hours':      round(duration_secs / 3600, 2),
                'ongoing':    False,
                'auto_closed': False,
            })
            total_seconds += duration_secs
            last_out       = log.timestamp
            pending_start  = None

    is_currently_on_duty = pending_start is not None

    if is_currently_on_duty:
        if is_today:
            end_time      = timezone.now()
            duration_secs = (end_time - pending_start).total_seconds()
            sessions.append({
                'start':      pending_start,
                'end':        None,
                'hours':      round(duration_secs / 3600, 2),
                'ongoing':    True,
                'auto_closed': False,
            })
            total_seconds += duration_secs
        else:
            # Partner forgot to toggle off — cap at 23:59:59 IST of that date
            day_end_ist = IST.localize(datetime(
                target_date.year, target_date.month, target_date.day, 23, 59, 59,
            ))
            day_end_utc = day_end_ist.astimezone(pytz.utc)

            if pending_start < day_end_utc:
                end_time      = min(day_end_utc, timezone.now())
                duration_secs = (end_time - pending_start).total_seconds()
                sessions.append({
                    'start':      pending_start,
                    'end':        day_end_utc,
                    'hours':      round(duration_secs / 3600, 2),
                    'ongoing':    False,
                    'auto_closed': True,
                })
                total_seconds += duration_secs
                last_out       = day_end_utc

            # Past-date unclosed session is NOT "currently on duty"
            is_currently_on_duty = False

    return {
        'date':                 target_date,
        'sessions':             sessions,
        'total_hours':          round(total_seconds / 3600, 2),
        'session_count':        len(sessions),
        'first_in':             first_in,
        'last_out':             last_out,
        'is_currently_on_duty': is_currently_on_duty,
    }


def get_monthly_ledger(partner, year, month):
    """
    Returns a full monthly duty ledger for a partner.
    All display values are pre-formatted in IST.
    """
    from .models import DeliveryAssignment, DeliverySettings

    _, days_in_month = calendar.monthrange(year, month)
    today_ist        = timezone.now().astimezone(IST).date()

    # Load configurable thresholds once — avoids N DB queries per day
    duty_settings   = DeliverySettings.get()
    full_day_hours  = float(duty_settings.full_day_hours)
    half_day_hours  = float(duty_settings.half_day_hours)
    count_half_days = duty_settings.count_half_days

    # Partner identity — gracefully degrade if no payroll profile
    partner_name = partner.user.full_name
    try:
        emp_code = partner.user.payroll_profile.employee_code
    except Exception:
        emp_code = '—'

    days_entries = []
    full_days = half_days = absent_days = days_worked = 0
    total_seconds_worked = 0.0
    total_delivered = total_failed = 0

    for day_num in range(1, days_in_month + 1):
        d = date(year, month, day_num)

        if d > today_ist:
            days_entries.append({
                'date':             d.isoformat(),
                'day_name':         d.strftime('%A'),
                'status':           'future',
                'total_hours':      None,
                'first_in_display': None,
                'last_out_display': None,
                'session_count':    0,
                'sessions':         [],
            })
            continue

        daily       = calculate_daily_hours(partner, d)
        hours       = daily['total_hours']
        day_seconds = hours * 3600

        if hours >= full_day_hours:
            day_status = 'full_day'
            full_days  += 1
        elif count_half_days and hours >= half_day_hours:
            day_status = 'half_day'
            half_days  += 1
        else:
            day_status   = 'absent'
            absent_days += 1

        if day_status != 'absent':
            days_worked          += 1
            total_seconds_worked += day_seconds

        # Orders on this IST calendar day
        day_start_utc, day_end_utc = ist_date_range(d)
        day_assigned = partner.assignments.filter(
            created_at__gte=day_start_utc,
            created_at__lte=day_end_utc,
        )
        delivered = day_assigned.filter(status='delivered').count()
        failed    = day_assigned.filter(status='failed').count()
        total_delivered += delivered
        total_failed    += failed

        # Serialize sessions with IST display strings
        today_ist = timezone.now().astimezone(IST).date()
        serialized_sessions = []
        for s in daily['sessions']:
            if s['ongoing'] and d == today_ist:
                end_display = 'Ongoing'
            else:
                end_display = format_ist_time(s['end'])
            serialized_sessions.append({
                'start_display': format_ist_time(s['start']),
                'end_display':   end_display,
                'hours':         s['hours'],
                'ongoing':       s['ongoing'],
                'auto_closed':   s.get('auto_closed', False),
            })

        days_entries.append({
            'date':             d.isoformat(),
            'day_name':         d.strftime('%A'),
            'status':           day_status,
            'total_hours':      daily['total_hours'],
            'first_in_display': format_ist_time(daily['first_in']),
            'last_out_display': format_ist_time(daily['last_out']),
            'session_count':    daily['session_count'],
            'sessions':         serialized_sessions,
            'orders_delivered': delivered,
            'orders_failed':    failed,
        })

    total_hours    = round(total_seconds_worked / 3600, 2)
    avg_hours      = round(total_hours / days_worked, 2) if days_worked > 0 else 0.0

    return {
        'partner_name':    partner_name,
        'employee_code':   emp_code,
        'year':            year,
        'month':           month,
        'month_name':      date(year, month, 1).strftime('%B %Y'),
        'days_in_month':   days_in_month,
        'days_worked':     days_worked,
        'full_days':       full_days,
        'half_days':       half_days,
        'absent_days':     absent_days,
        'total_hours':     total_hours,
        'avg_hours_per_day': avg_hours,
        'total_delivered': total_delivered,
        'total_failed':    total_failed,
        'days':            days_entries,
        'timezone':        'IST (UTC+5:30)',
        'duty_thresholds': {
            'full_day_hours':  full_day_hours,
            'half_day_hours':  half_day_hours,
            'count_half_days': count_half_days,
        },
    }


def generate_monthly_report_html(partner, year, month):
    """Returns an HTML string suitable for browser print-to-PDF. All times in IST."""
    data    = get_monthly_ledger(partner, year, month)
    now_ist = timezone.now().astimezone(IST)

    rows_html = ''
    for entry in data['days']:
        if entry['status'] == 'future':
            continue
        color_map = {
            'full_day':  ('#16a34a', 'Full'),
            'half_day':  ('#d97706', 'Half'),
            'absent':    ('#dc2626', 'Absent'),
        }
        color, label = color_map.get(entry['status'], ('#6b7280', entry['status']))
        hours_str    = f"{entry['total_hours']:.2f} h" if entry['total_hours'] is not None else '—'
        sessions_str = ', '.join(
            f"{s['start_display']}–{s['end_display']}" for s in entry['sessions']
        ) or '—'
        rows_html += f"""
        <tr>
          <td>{entry['date']} ({entry['day_name'][:3]})</td>
          <td>{entry.get('first_in_display') or '—'}</td>
          <td>{entry.get('last_out_display') or '—'}</td>
          <td>{entry['session_count']}</td>
          <td>{hours_str}</td>
          <td>{entry.get('orders_delivered', 0)}</td>
          <td>{entry.get('orders_failed', 0)}</td>
          <td><span style="color:{color};font-weight:600">{label}</span></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Duty Report — {data['partner_name']} — {data['month_name']}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #111; }}
    h1   {{ font-size: 1.4em; margin-bottom: 4px; }}
    .meta {{ color: #555; font-size: 0.9em; margin-bottom: 16px; }}
    .stats {{ display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }}
    .stat  {{ background: #f3f4f6; border-radius: 8px; padding: 12px 20px; text-align: center; min-width: 80px; }}
    .stat-val   {{ font-size: 1.6em; font-weight: 700; }}
    .stat-label {{ font-size: 0.8em; color: #555; }}
    .tz-note {{ font-size: 0.78em; color: #888; text-align: right; margin-bottom: 6px; }}
    table  {{ width: 100%; border-collapse: collapse; font-size: 0.88em; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 7px 10px; text-align: left; }}
    th     {{ background: #f9fafb; font-weight: 600; }}
    tr:nth-child(even) {{ background: #f9fafb; }}
    .footer {{ margin-top: 40px; display: flex; justify-content: space-between; }}
    .sign-line {{ border-top: 1px solid #000; width: 160px; margin: 40px auto 4px; }}
    @media print {{ body {{ margin: 16px; }} button {{ display: none; }} }}
  </style>
</head>
<body>
  <button onclick="window.print()"
    style="margin-bottom:12px;padding:8px 20px;background:#333;color:#fff;border:none;cursor:pointer;border-radius:6px;">
    Print / Save as PDF
  </button>
  <h1>Delivery Partner Duty Report</h1>
  <p class="meta">
    <strong>{data['partner_name']}</strong> &nbsp;|&nbsp; Code: {data['employee_code']}
    &nbsp;|&nbsp; {data['month_name']}
  </p>
  <div class="stats">
    <div class="stat"><div class="stat-val" style="color:#16a34a">{data['full_days']}</div><div class="stat-label">Full Days</div></div>
    <div class="stat"><div class="stat-val" style="color:#d97706">{data['half_days']}</div><div class="stat-label">Half Days</div></div>
    <div class="stat"><div class="stat-val" style="color:#dc2626">{data['absent_days']}</div><div class="stat-label">Absent</div></div>
    <div class="stat"><div class="stat-val">{data['total_hours']:.1f}h</div><div class="stat-label">Total Hours</div></div>
    <div class="stat"><div class="stat-val">{data['avg_hours_per_day']}h</div><div class="stat-label">Avg/Day</div></div>
    <div class="stat"><div class="stat-val" style="color:#16a34a">{data['total_delivered']}</div><div class="stat-label">Delivered</div></div>
    <div class="stat"><div class="stat-val" style="color:#dc2626">{data['total_failed']}</div><div class="stat-label">Failed</div></div>
  </div>
  <p class="tz-note">All times in IST (UTC+5:30)</p>
  <table>
    <thead>
      <tr>
        <th>Date</th><th>First In</th><th>Last Out</th>
        <th>Sessions</th><th>Hours</th>
        <th>Delivered</th><th>Failed</th><th>Status</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p style="margin-top:10px;font-size:0.78em;color:#888;text-align:center;">
    Full Day ≥ 6h &nbsp;·&nbsp; Half Day 1–5h &nbsp;·&nbsp; Absent = 0h &nbsp;|&nbsp;
    Generated: {now_ist.strftime('%d %b %Y %I:%M %p IST')}
  </p>
  <div class="footer">
    <div style="text-align:center"><div class="sign-line"></div><div style="font-size:12px;">Partner Signature</div></div>
    <div style="text-align:center"><div class="sign-line"></div><div style="font-size:12px;">Authorized Signatory</div></div>
  </div>
</body>
</html>"""
