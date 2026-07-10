"""
Comprehensive test cases for duty tracking system.
Tests timezone correctness, session pairing, edge cases,
and monthly ledger calculations.

Key model facts (differ from task prompt):
  - DeliveryPartner.user  (OneToOne to User, not 'employee')
  - EmployeeProfile.related_name = 'payroll_profile' (not 'employee_profile')
  - EmployeeProfile.date_of_joining (not 'joining_date')
  - User has first_name/last_name fields (not 'name')
  - DeliveryAssignment.partner FK (not 'delivery_partner')
"""
from datetime import date, datetime
from unittest.mock import patch

import pytz
from django.test import TestCase
from django.utils import timezone

IST = pytz.timezone('Asia/Kolkata')


def make_utc(year, month, day, hour, minute):
    """Return UTC-aware datetime."""
    return pytz.utc.localize(datetime(year, month, day, hour, minute, 0))


def make_ist(year, month, day, hour, minute):
    """Return IST-aware datetime."""
    return IST.localize(datetime(year, month, day, hour, minute, 0))


def make_utc_from_ist(year, month, day, hour, minute):
    """Return UTC datetime for an IST clock reading."""
    return make_ist(year, month, day, hour, minute).astimezone(pytz.utc)


def _make_partner(email_suffix):
    """Create a minimal DeliveryPartner for testing."""
    from django.contrib.auth import get_user_model
    from apps.delivery.models import DeliveryPartner

    User = get_user_model()
    user = User.objects.create_user(
        email      = f'test_{email_suffix}@example.com',
        password   = 'testpass123',
        first_name = 'Test',
        last_name  = f'Partner {email_suffix}',
        role       = 'delivery_partner',
    )
    return DeliveryPartner.objects.create(user=user, vehicle_type='bike')


# ─── DutyLog date field ───────────────────────────────────────────────────────

class TestDutyLogDateField(TestCase):
    """DutyLog.date must store the IST date, not the UTC date."""

    def setUp(self):
        self.partner = _make_partner('date1')

    def test_midnight_ist_stores_correct_date(self):
        """
        12:01 AM IST on 4 Jul  =  6:31 PM UTC on 3 Jul.
        date field must store 4 Jul (IST), not 3 Jul (UTC).
        """
        from apps.delivery.models import DutyLog

        utc_time = make_utc_from_ist(2026, 7, 4, 0, 1)
        self.assertEqual(utc_time.date(), date(2026, 7, 3), 'sanity: UTC date is 3 Jul')

        log = DutyLog.objects.create(
            partner=self.partner, status='on_duty',
            timestamp=utc_time,
            date=date(2026, 7, 4),  # will be overwritten by save() — that's fine
        )
        log.refresh_from_db()
        self.assertEqual(log.date, date(2026, 7, 4))

    def test_late_night_ist_stores_correct_date(self):
        """11:59 PM IST on 4 Jul stores date as 4 Jul."""
        from apps.delivery.models import DutyLog

        utc_time = make_utc_from_ist(2026, 7, 4, 23, 59)
        log = DutyLog.objects.create(
            partner=self.partner, status='off_duty',
            timestamp=utc_time,
            date=date(2026, 7, 4),
        )
        log.refresh_from_db()
        self.assertEqual(log.date, date(2026, 7, 4))

    def test_toggle_duty_saves_ist_date(self):
        """
        toggle_duty() must save IST date on the DutyLog.
        Mock timezone.now() to return a UTC time whose IST
        equivalent falls on the NEXT calendar day.
        11:00 PM UTC on 3 Jul  =  4:30 AM IST on 4 Jul.
        """
        from apps.delivery.duty_utils import toggle_duty

        mock_utc = make_utc(2026, 7, 3, 23, 0)
        expected_ist_date = date(2026, 7, 4)

        with patch('apps.delivery.duty_utils.timezone.now', return_value=mock_utc):
            log = toggle_duty(self.partner, 'on_duty')

        self.assertEqual(log.date, expected_ist_date)
        self.assertEqual(log.status, 'on_duty')


# ─── calculate_daily_hours ───────────────────────────────────────────────────

class TestCalculateDailyHours(TestCase):
    """Session pairing and hour calculation."""

    def setUp(self):
        self.partner   = _make_partner('hours1')
        self.test_date = date(2026, 7, 4)

    def _log(self, status, ist_h, ist_m):
        from apps.delivery.models import DutyLog
        utc = make_utc_from_ist(2026, 7, 4, ist_h, ist_m)
        return DutyLog.objects.create(
            partner=self.partner, status=status,
            timestamp=utc, date=self.test_date,
        )

    def test_single_session_8_hours(self):
        """ON 09:00 IST → OFF 17:00 IST = 8 h."""
        from apps.delivery.duty_utils import calculate_daily_hours

        self._log('on_duty',  9, 0)
        self._log('off_duty', 17, 0)

        r = calculate_daily_hours(self.partner, self.test_date)
        self.assertEqual(r['session_count'], 1)
        self.assertAlmostEqual(r['total_hours'], 8.0, places=1)
        self.assertFalse(r['is_currently_on_duty'])

    def test_two_sessions_lunch_break(self):
        """ON 09:00–13:00 (4h) + ON 14:00–19:00 (5h) = 9 h."""
        from apps.delivery.duty_utils import calculate_daily_hours

        self._log('on_duty',  9, 0)
        self._log('off_duty', 13, 0)
        self._log('on_duty',  14, 0)
        self._log('off_duty', 19, 0)

        r = calculate_daily_hours(self.partner, self.test_date)
        self.assertEqual(r['session_count'], 2)
        self.assertAlmostEqual(r['total_hours'], 9.0, places=1)

    def test_ongoing_session_counted(self):
        """ON with no OFF on today = ongoing; hours > 0; session marked ongoing."""
        from apps.delivery.duty_utils import calculate_daily_hours

        self._log('on_duty', 9, 0)

        # Freeze "now" to noon on the same date so calculate_daily_hours
        # treats self.test_date as today and keeps the session ongoing.
        fake_now = make_utc_from_ist(2026, 7, 4, 12, 0)
        with patch('apps.delivery.duty_utils.timezone') as mock_tz:
            mock_tz.now.return_value = fake_now
            mock_tz.is_aware = timezone.is_aware
            r = calculate_daily_hours(self.partner, self.test_date)

        self.assertTrue(r['is_currently_on_duty'])
        self.assertEqual(r['session_count'], 1)
        self.assertGreater(r['total_hours'], 0)
        self.assertTrue(r['sessions'][0]['ongoing'])

    def test_absent_day_returns_zero(self):
        """No logs = 0 hours, no sessions, no first_in."""
        from apps.delivery.duty_utils import calculate_daily_hours

        r = calculate_daily_hours(self.partner, date(2026, 7, 5))
        self.assertEqual(r['total_hours'], 0.0)
        self.assertEqual(r['session_count'], 0)
        self.assertIsNone(r['first_in'])
        self.assertFalse(r['is_currently_on_duty'])

    def test_sessions_dont_bleed_across_dates(self):
        """Logs stored with date=4 Jul must NOT appear on 3 Jul or 5 Jul."""
        from apps.delivery.duty_utils import calculate_daily_hours
        from apps.delivery.models import DutyLog

        utc = make_utc_from_ist(2026, 7, 4, 10, 0)
        DutyLog.objects.create(
            partner=self.partner, status='on_duty',
            timestamp=utc, date=date(2026, 7, 4),
        )

        r3 = calculate_daily_hours(self.partner, date(2026, 7, 3))
        r5 = calculate_daily_hours(self.partner, date(2026, 7, 5))
        self.assertEqual(r3['total_hours'], 0.0)
        self.assertEqual(r5['total_hours'], 0.0)

    def test_midnight_ist_session_on_correct_date(self):
        """
        ON 00:01 IST 4 Jul, OFF 01:00 IST 4 Jul → ~59 min under 4 Jul,
        zero minutes under 3 Jul.
        """
        from apps.delivery.duty_utils import calculate_daily_hours
        from apps.delivery.models import DutyLog

        on_utc  = make_utc_from_ist(2026, 7, 4, 0, 1)
        off_utc = make_utc_from_ist(2026, 7, 4, 1, 0)
        DutyLog.objects.create(
            partner=self.partner, status='on_duty',
            timestamp=on_utc, date=date(2026, 7, 4),
        )
        DutyLog.objects.create(
            partner=self.partner, status='off_duty',
            timestamp=off_utc, date=date(2026, 7, 4),
        )

        r4 = calculate_daily_hours(self.partner, date(2026, 7, 4))
        r3 = calculate_daily_hours(self.partner, date(2026, 7, 3))
        self.assertAlmostEqual(r4['total_hours'], 0.98, delta=0.05)
        self.assertEqual(r3['total_hours'], 0.0)

    def test_first_in_last_out_populated(self):
        """first_in and last_out are set correctly."""
        from apps.delivery.duty_utils import calculate_daily_hours

        on_utc  = make_utc_from_ist(2026, 7, 4, 9, 0)
        off_utc = make_utc_from_ist(2026, 7, 4, 17, 0)
        self._log('on_duty',  9, 0)
        self._log('off_duty', 17, 0)

        r = calculate_daily_hours(self.partner, self.test_date)
        self.assertEqual(r['first_in'], on_utc)
        self.assertEqual(r['last_out'], off_utc)

    def test_past_day_ongoing_capped_at_midnight(self):
        """
        If partner toggled ON on a past date but never toggled OFF,
        hours must be capped at 23:59:59 IST of that date — NOT counted
        up to today. Max possible hours for any single day = ~15h here
        (09:00 to 23:59 IST).
        """
        from apps.delivery.duty_utils import calculate_daily_hours
        from apps.delivery.models import DutyLog

        past_date = date(2026, 7, 3)

        on_ist = make_utc_from_ist(2026, 7, 3, 9, 0)
        DutyLog.objects.create(
            partner   = self.partner,
            status    = 'on_duty',
            timestamp = on_ist,
            date      = past_date,
        )

        result = calculate_daily_hours(self.partner, past_date)

        # Capped at 23:59:59 IST on Jul 3 → ~15h (09:00 to 23:59)
        self.assertLessEqual(result['total_hours'], 15.1)
        self.assertGreater(result['total_hours'], 14.9)

        # Past date must NOT be marked as currently on duty
        self.assertFalse(result['is_currently_on_duty'])

        # The session should be marked auto_closed
        self.assertTrue(result['sessions'][0].get('auto_closed', False))


# ─── toggle_duty ─────────────────────────────────────────────────────────────

class TestToggleDuty(TestCase):

    def setUp(self):
        self.partner = _make_partner('toggle1')

    def test_toggle_on(self):
        from apps.delivery.duty_utils import toggle_duty

        log = toggle_duty(self.partner, 'on_duty')
        self.assertEqual(log.status, 'on_duty')
        self.partner.refresh_from_db()
        self.assertTrue(self.partner.is_on_duty)
        self.assertIsNotNone(self.partner.duty_started_at)

    def test_toggle_off(self):
        from apps.delivery.duty_utils import toggle_duty

        toggle_duty(self.partner, 'on_duty')
        log = toggle_duty(self.partner, 'off_duty')
        self.assertEqual(log.status, 'off_duty')
        self.partner.refresh_from_db()
        self.assertFalse(self.partner.is_on_duty)
        self.assertIsNone(self.partner.duty_started_at)

    def test_duplicate_status_raises_value_error(self):
        """Toggling to the same status must raise ValueError."""
        from apps.delivery.duty_utils import toggle_duty

        toggle_duty(self.partner, 'on_duty')
        with self.assertRaises(ValueError):
            toggle_duty(self.partner, 'on_duty')

    def test_full_on_off_on_off_sequence(self):
        """Four toggles create four DutyLog records in correct order."""
        from apps.delivery.duty_utils import toggle_duty
        from apps.delivery.models import DutyLog

        toggle_duty(self.partner, 'on_duty')
        toggle_duty(self.partner, 'off_duty')
        toggle_duty(self.partner, 'on_duty')
        toggle_duty(self.partner, 'off_duty')

        logs     = DutyLog.objects.filter(partner=self.partner).order_by('timestamp')
        statuses = list(logs.values_list('status', flat=True))
        self.assertEqual(logs.count(), 4)
        self.assertEqual(statuses, ['on_duty', 'off_duty', 'on_duty', 'off_duty'])

    def test_duty_started_at_cleared_on_off(self):
        """duty_started_at is cleared when partner goes off duty."""
        from apps.delivery.duty_utils import toggle_duty

        toggle_duty(self.partner, 'on_duty')
        self.partner.refresh_from_db()
        self.assertIsNotNone(self.partner.duty_started_at)

        toggle_duty(self.partner, 'off_duty')
        self.partner.refresh_from_db()
        self.assertIsNone(self.partner.duty_started_at)


# ─── monthly ledger ───────────────────────────────────────────────────────────

class TestMonthlyLedger(TestCase):

    def setUp(self):
        self.partner = _make_partner('ledger1')

    def _full_day(self, year, month, day):
        """Create an 8-hour duty session on an IST date."""
        from apps.delivery.models import DutyLog

        d = date(year, month, day)
        DutyLog.objects.create(
            partner=self.partner, status='on_duty',
            timestamp=make_utc_from_ist(year, month, day, 9, 0), date=d,
        )
        DutyLog.objects.create(
            partner=self.partner, status='off_duty',
            timestamp=make_utc_from_ist(year, month, day, 17, 0), date=d,
        )

    def _half_day(self, year, month, day):
        """Create a 3-hour duty session on an IST date."""
        from apps.delivery.models import DutyLog

        d = date(year, month, day)
        DutyLog.objects.create(
            partner=self.partner, status='on_duty',
            timestamp=make_utc_from_ist(year, month, day, 10, 0), date=d,
        )
        DutyLog.objects.create(
            partner=self.partner, status='off_duty',
            timestamp=make_utc_from_ist(year, month, day, 13, 0), date=d,
        )

    def test_ledger_has_all_days_in_month(self):
        """July has 31 days — ledger must have 31 entries."""
        from apps.delivery.duty_utils import get_monthly_ledger

        result = get_monthly_ledger(self.partner, 2026, 7)
        self.assertEqual(len(result['days']), 31)

    def test_absent_days_count_with_one_worked_day(self):
        """Work 1 day in a past month → (days_in_month - 1) absent days.
        Uses Jan 2026 (fully past, 31 days) so no 'future' days interfere."""
        from apps.delivery.duty_utils import get_monthly_ledger

        self._full_day(2026, 1, 1)
        result = get_monthly_ledger(self.partner, 2026, 1)
        self.assertEqual(result['days_worked'], 1)
        self.assertEqual(result['absent_days'], 30)

    def test_full_day_status(self):
        """8-hour session → status = 'full_day', total_hours = 8.0."""
        from apps.delivery.duty_utils import get_monthly_ledger

        self._full_day(2026, 7, 1)
        result = get_monthly_ledger(self.partner, 2026, 7)
        day1 = result['days'][0]
        self.assertEqual(day1['status'], 'full_day')
        self.assertAlmostEqual(day1['total_hours'], 8.0, places=1)

    def test_half_day_status(self):
        """3-hour session → status = 'half_day'."""
        from apps.delivery.duty_utils import get_monthly_ledger

        self._half_day(2026, 7, 2)
        result = get_monthly_ledger(self.partner, 2026, 7)
        day2 = result['days'][1]
        self.assertEqual(day2['status'], 'half_day')

    def test_monthly_totals_three_full_days(self):
        """3 full days (8 h each) → 24 h total, avg 8 h/day."""
        from apps.delivery.duty_utils import get_monthly_ledger

        self._full_day(2026, 7, 1)
        self._full_day(2026, 7, 2)
        self._full_day(2026, 7, 3)
        result = get_monthly_ledger(self.partner, 2026, 7)

        self.assertEqual(result['days_worked'], 3)
        self.assertEqual(result['full_days'], 3)
        self.assertAlmostEqual(result['total_hours'], 24.0, places=1)
        self.assertAlmostEqual(result['avg_hours_per_day'], 8.0, places=1)

    def test_ist_display_times(self):
        """first_in_display and last_out_display must contain IST clock times."""
        from apps.delivery.duty_utils import get_monthly_ledger

        self._full_day(2026, 7, 1)
        result = get_monthly_ledger(self.partner, 2026, 7)
        day1 = result['days'][0]

        # 09:00 IST → '09:00 AM'
        self.assertIsNotNone(day1['first_in_display'])
        self.assertIn('09:00', day1['first_in_display'])

        # 17:00 IST → '05:00 PM'
        self.assertIsNotNone(day1['last_out_display'])
        self.assertIn('05:00', day1['last_out_display'])

    def test_absent_day_null_display_times(self):
        """Absent days have no first_in/last_out display."""
        from apps.delivery.duty_utils import get_monthly_ledger

        result = get_monthly_ledger(self.partner, 2026, 7)
        day1 = result['days'][0]
        self.assertEqual(day1['status'], 'absent')
        self.assertIsNone(day1['first_in_display'])
        self.assertIsNone(day1['last_out_display'])

    def test_future_days_excluded_from_counts(self):
        """Days after today must have status='future' and not affect counts."""
        from apps.delivery.duty_utils import get_monthly_ledger

        # Use a far-future month so all days are future
        result = get_monthly_ledger(self.partner, 2030, 1)
        self.assertEqual(result['days_worked'], 0)
        self.assertEqual(result['full_days'], 0)
        self.assertEqual(result['absent_days'], 0)
        for day in result['days']:
            self.assertEqual(day['status'], 'future')

    def test_ledger_timezone_field(self):
        """Response includes timezone note."""
        from apps.delivery.duty_utils import get_monthly_ledger

        result = get_monthly_ledger(self.partner, 2026, 7)
        self.assertEqual(result['timezone'], 'IST (UTC+5:30)')

    def test_session_display_in_ledger(self):
        """Sessions inside a day entry have start_display and end_display."""
        from apps.delivery.duty_utils import get_monthly_ledger

        self._full_day(2026, 7, 1)
        result = get_monthly_ledger(self.partner, 2026, 7)
        sessions = result['days'][0]['sessions']

        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertIn('start_display', s)
        self.assertIn('end_display', s)
        self.assertFalse(s['ongoing'])
        self.assertIn('09:00', s['start_display'])
        self.assertIn('05:00', s['end_display'])


# ─── duty hours settings ──────────────────────────────────────────────────────

class TestDutyHoursSettings(TestCase):
    """Test that day status respects DeliverySettings thresholds."""

    def setUp(self):
        from apps.delivery.models import DeliverySettings
        self.partner  = _make_partner('settings1')
        self.settings = DeliverySettings.get()
        self.settings.full_day_hours  = 6.0
        self.settings.half_day_hours  = 3.0
        self.settings.count_half_days = True
        self.settings.save()

    def _session(self, day, start_h, end_h):
        from apps.delivery.models import DutyLog
        d   = date(2026, 7, day)
        on  = make_ist(2026, 7, day, start_h, 0).astimezone(pytz.utc)
        off = make_ist(2026, 7, day, end_h,   0).astimezone(pytz.utc)
        DutyLog.objects.create(partner=self.partner, status='on_duty',  timestamp=on,  date=d)
        DutyLog.objects.create(partner=self.partner, status='off_duty', timestamp=off, date=d)

    def test_default_thresholds(self):
        """8h→full, 4h→half, 1h→absent, 0h→absent with defaults (6h full / 3h half)."""
        from apps.delivery.duty_utils import get_monthly_ledger

        self._session(1, 9, 17)   # 8h → full_day
        self._session(2, 9, 13)   # 4h → half_day
        self._session(3, 9, 10)   # 1h → absent (< 3h threshold)
        # day 4 no session → absent

        result = get_monthly_ledger(self.partner, 2026, 7)
        self.assertEqual(result['days'][0]['status'], 'full_day')
        self.assertEqual(result['days'][1]['status'], 'half_day')
        self.assertEqual(result['days'][2]['status'], 'absent')
        self.assertEqual(result['days'][3]['status'], 'absent')

    def test_custom_full_day_threshold(self):
        """Admin raises full_day to 8h → 7h session becomes half_day."""
        from apps.delivery.duty_utils import get_monthly_ledger

        self.settings.full_day_hours = 8.0
        self.settings.half_day_hours = 4.0
        self.settings.save()

        self._session(1, 9, 16)   # 7h < 8h → half_day now

        result = get_monthly_ledger(self.partner, 2026, 7)
        self.assertEqual(result['days'][0]['status'], 'half_day')

    def test_count_half_days_off(self):
        """count_half_days=False: a 4h session is absent, not half_day."""
        from apps.delivery.duty_utils import get_monthly_ledger

        self.settings.count_half_days = False
        self.settings.save()

        self._session(1, 9, 13)   # 4h, but half days disabled

        result = get_monthly_ledger(self.partner, 2026, 7)
        self.assertEqual(result['days'][0]['status'], 'absent')

    def test_thresholds_in_response(self):
        """get_monthly_ledger returns duty_thresholds so frontend can display them."""
        from apps.delivery.duty_utils import get_monthly_ledger

        self.settings.full_day_hours  = 7.0
        self.settings.half_day_hours  = 3.5
        self.settings.count_half_days = True
        self.settings.save()

        result = get_monthly_ledger(self.partner, 2026, 7)
        t = result['duty_thresholds']
        self.assertEqual(t['full_day_hours'],  7.0)
        self.assertEqual(t['half_day_hours'],  3.5)
        self.assertTrue(t['count_half_days'])

    def test_validation_half_gte_full_rejected(self):
        """half_day_hours >= full_day_hours must be rejected by the serializer."""
        from apps.delivery.serializers import DeliverySettingsSerializer

        ser = DeliverySettingsSerializer(
            self.settings,
            data={'full_day_hours': 5.0, 'half_day_hours': 5.0, 'count_half_days': True},
            partial=True,
        )
        self.assertFalse(ser.is_valid())
        self.assertIn('half_day_hours', ser.errors)
