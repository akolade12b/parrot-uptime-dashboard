"""Unit tests for the pure uptime maths and formatters."""

import unittest
from datetime import datetime

import uptime


class SessionDailySecondsTests(unittest.TestCase):
    def test_session_splits_across_midnight(self):
        boot = datetime(2026, 1, 5, 22, 0).timestamp()
        shutdown = datetime(2026, 1, 6, 2, 0).timestamp()
        parts = uptime.session_daily_seconds(boot, shutdown)
        self.assertEqual(parts, {"2026-01-05": 7200.0, "2026-01-06": 7200.0})

    def test_open_session_runs_until_now(self):
        boot = datetime(2026, 1, 5, 22, 0).timestamp()
        now = datetime(2026, 1, 6, 1, 0).timestamp()
        parts = uptime.session_daily_seconds(boot, None, now=now)
        self.assertEqual(parts, {"2026-01-05": 7200.0, "2026-01-06": 3600.0})

    def test_session_inside_one_day(self):
        boot = datetime(2026, 1, 5, 8, 0).timestamp()
        shutdown = datetime(2026, 1, 5, 9, 30).timestamp()
        parts = uptime.session_daily_seconds(boot, shutdown)
        self.assertEqual(parts, {"2026-01-05": 5400.0})

    def test_non_positive_interval_is_empty(self):
        ts = datetime(2026, 1, 5, 12, 0).timestamp()
        self.assertEqual(uptime.session_daily_seconds(ts, ts), {})
        self.assertEqual(uptime.session_daily_seconds(ts, ts - 60), {})


class FormatUptimeTests(unittest.TestCase):
    def test_none(self):
        self.assertEqual(uptime.format_uptime(None), "unknown")

    def test_zero_and_singular_plural(self):
        self.assertEqual(uptime.format_uptime(0), "0 minutes")
        self.assertEqual(uptime.format_uptime(60), "1 minute")
        self.assertEqual(uptime.format_uptime(120), "2 minutes")
        self.assertEqual(uptime.format_uptime(3600), "1 hour")
        self.assertEqual(uptime.format_uptime(86400), "1 day")

    def test_combined_units(self):
        self.assertEqual(
            uptime.format_uptime(90061), "1 day 1 hour 1 minute"
        )

    def test_negative_is_clamped(self):
        self.assertEqual(uptime.format_uptime(-5), "0 minutes")


class FormatHoursTests(unittest.TestCase):
    def test_none(self):
        self.assertEqual(uptime.format_hours(None), "—")

    def test_minutes_below_one_hour(self):
        self.assertEqual(uptime.format_hours(1800), "30m")
        self.assertEqual(uptime.format_hours(3599), "59m")

    def test_hours(self):
        self.assertEqual(uptime.format_hours(3600), "1.0h")
        self.assertEqual(uptime.format_hours(5400), "1.5h")

    def test_large_values_drop_the_decimal(self):
        self.assertEqual(uptime.format_hours(360000), "100h")


class FormatBootTimeTests(unittest.TestCase):
    def test_none(self):
        self.assertEqual(uptime.format_boot_time(None), "unknown")


if __name__ == "__main__":
    unittest.main()
