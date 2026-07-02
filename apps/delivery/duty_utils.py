import calendar
from datetime import date, timedelta

from django.utils import timezone

from .models import DutyLog


def toggle_duty(partner, new_status):
    """
    Toggle a partner's duty status.
    Returns (DutyLog, error_str|None).
    error_str is set when the request is a no-op (same status).
    """
    current = 'on_duty' if partner.is_on_duty else 'off_duty'
    if current == new_status:
        return None, f'Already {new_status.replace("_", " ")}'

    now = timezone.now()
    log = DutyLog.objects.create(
        partner=partner,
        status=new_status,
        timestamp=now,
        date=now.date(),
    )

    if new_status == 'on_duty':
        partner.is_on_duty = True
        partner.duty_started_at = now
    else:
        partner.is_on_duty = False
        partner.duty_started_at = None

    partner.save(update_fields=['is_on_duty', 'duty_started_at', 'updated_at'])
    return log, None


def calculate_daily_hours(partner, target_date):
    """
    Returns total duty seconds for a given date.
    Handles multiple on/off sessions; ongoing session counted to now().
    """
    logs = list(
        DutyLog.objects.filter(partner=partner, date=target_date).order_by('timestamp')
    )

    total_seconds = 0
    session_start = None

    for log in logs:
        if log.status == 'on_duty':
            session_start = log.timestamp
        elif log.status == 'off_duty' and session_start is not None:
            total_seconds += (log.timestamp - session_start).total_seconds()
            session_start = None

    # Ongoing session — count up to now
    if session_start is not None:
        now = timezone.now()
        if now.date() == target_date:
            total_seconds += (now - session_start).total_seconds()

    return total_seconds


def _classify_day(seconds):
    hours = seconds / 3600
    if hours >= 6:
        return 'full'
    if hours >= 1:
        return 'half'
    return 'absent'


def get_monthly_ledger(partner, year, month):
    """
    Returns a dict with per-day breakdown and aggregate stats for a given month.
    """
    _, days_in_month = calendar.monthrange(year, month)
    today = timezone.localdate()

    daily = []
    full_days = half_days = absent_days = 0
    total_seconds = 0

    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        if d > today:
            daily.append({'date': d.isoformat(), 'type': 'future', 'hours': None, 'sessions': []})
            continue

        seconds = calculate_daily_hours(partner, d)
        day_type = _classify_day(seconds)

        if day_type == 'full':
            full_days += 1
        elif day_type == 'half':
            half_days += 1
        else:
            absent_days += 1

        total_seconds += seconds

        logs = list(
            DutyLog.objects.filter(partner=partner, date=d).order_by('timestamp')
        )
        sessions = _build_sessions(logs, d, today)

        daily.append({
            'date':     d.isoformat(),
            'type':     day_type,
            'hours':    round(seconds / 3600, 2),
            'sessions': sessions,
        })

    return {
        'year':          year,
        'month':         month,
        'days':          daily,
        'full_days':     full_days,
        'half_days':     half_days,
        'absent_days':   absent_days,
        'total_hours':   round(total_seconds / 3600, 2),
    }


def _build_sessions(logs, d, today):
    sessions = []
    session_start = None

    for log in logs:
        if log.status == 'on_duty':
            session_start = log.timestamp
        elif log.status == 'off_duty' and session_start is not None:
            duration = (log.timestamp - session_start).total_seconds()
            sessions.append({
                'start':    session_start.strftime('%H:%M'),
                'end':      log.timestamp.strftime('%H:%M'),
                'duration': round(duration / 3600, 2),
                'ongoing':  False,
            })
            session_start = None

    if session_start is not None:
        now = timezone.now()
        if d == today:
            duration = (now - session_start).total_seconds()
            sessions.append({
                'start':    session_start.strftime('%H:%M'),
                'end':      None,
                'duration': round(duration / 3600, 2),
                'ongoing':  True,
            })

    return sessions


def generate_monthly_report_html(partner, year, month):
    """Returns an HTML string suitable for browser print-to-PDF."""
    ledger = get_monthly_ledger(partner, year, month)
    month_name = date(year, month, 1).strftime('%B %Y')

    try:
        emp_code = partner.user.employee_profile.employee_code
    except Exception:
        emp_code = '—'

    partner_name = partner.user.full_name

    rows_html = ''
    for entry in ledger['days']:
        if entry['type'] == 'future':
            continue
        badge_color = {'full': '#16a34a', 'half': '#d97706', 'absent': '#dc2626'}.get(entry['type'], '#6b7280')
        badge_label = entry['type'].capitalize()
        hours_str = f"{entry['hours']:.2f} h" if entry['hours'] is not None else '—'
        sessions_str = ', '.join(
            f"{s['start']}–{s['end'] or 'ongoing'}" for s in entry['sessions']
        ) or '—'
        rows_html += f"""
        <tr>
          <td>{entry['date']}</td>
          <td><span style="color:{badge_color};font-weight:600">{badge_label}</span></td>
          <td>{hours_str}</td>
          <td style="color:#6b7280;font-size:0.85em">{sessions_str}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Duty Report — {partner_name} — {month_name}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #111; }}
    h1   {{ font-size: 1.4em; margin-bottom: 4px; }}
    .meta {{ color: #555; font-size: 0.9em; margin-bottom: 24px; }}
    .stats {{ display: flex; gap: 24px; margin-bottom: 24px; }}
    .stat  {{ background: #f3f4f6; border-radius: 8px; padding: 12px 20px; text-align: center; }}
    .stat-val  {{ font-size: 1.6em; font-weight: 700; }}
    .stat-label {{ font-size: 0.8em; color: #555; }}
    table  {{ width: 100%; border-collapse: collapse; font-size: 0.92em; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px 12px; text-align: left; }}
    th     {{ background: #f9fafb; font-weight: 600; }}
    tr:nth-child(even) {{ background: #f9fafb; }}
    @media print {{ body {{ margin: 16px; }} }}
  </style>
</head>
<body>
  <h1>Duty Report</h1>
  <p class="meta">
    <strong>{partner_name}</strong> &nbsp;|&nbsp; Code: {emp_code}
    &nbsp;|&nbsp; Period: {month_name}
  </p>
  <div class="stats">
    <div class="stat">
      <div class="stat-val" style="color:#16a34a">{ledger['full_days']}</div>
      <div class="stat-label">Full Days</div>
    </div>
    <div class="stat">
      <div class="stat-val" style="color:#d97706">{ledger['half_days']}</div>
      <div class="stat-label">Half Days</div>
    </div>
    <div class="stat">
      <div class="stat-val" style="color:#dc2626">{ledger['absent_days']}</div>
      <div class="stat-label">Absent Days</div>
    </div>
    <div class="stat">
      <div class="stat-val">{ledger['total_hours']:.1f}</div>
      <div class="stat-label">Total Hours</div>
    </div>
  </div>
  <table>
    <thead>
      <tr><th>Date</th><th>Status</th><th>Hours</th><th>Sessions</th></tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</body>
</html>"""
