"""Tests for the journald and wtmp parsers (command output is stubbed)."""

import unittest
from datetime import datetime, timedelta
from unittest import mock

import uptime


JOURNAL_OUTPUT = """\
IDX BOOT ID                          FIRST ENTRY                  LAST ENTRY
 -2 11111111111111111111111111111111 Tue 2026-01-06 08:00:00 CET  Tue 2026-01-06 10:00:00 CET
 -1 22222222222222222222222222222222 Tue 2026-01-06 11:00:00 CET  Tue 2026-01-06 12:00:00 CET
  0 33333333333333333333333333333333 Tue 2026-01-06 13:00:00 CET  Tue 2026-01-06 14:00:00 CET
"""


class JournalParserTests(unittest.TestCase):
    def parse(self, output):
        with mock.patch.object(uptime, "run_command", return_value=output):
            return uptime.parse_journal_boots()

    def test_parses_every_boot(self):
        sessions = self.parse(JOURNAL_OUTPUT)
        self.assertEqual(len(sessions), 3)
        self.assertEqual(
            [s["boot_id"] for s in sessions],
            ["1" * 32, "2" * 32, "3" * 32],
        )
        self.assertTrue(all(s["source"] == "journal" for s in sessions))

    def test_past_boots_have_shutdown_and_current_boot_is_open(self):
        sessions = self.parse(JOURNAL_OUTPUT)
        self.assertEqual(
            sessions[0]["shutdown_time"],
            datetime(2026, 1, 6, 10, 0, 0).timestamp(),
        )
        self.assertIsNone(sessions[2]["shutdown_time"])

    def test_header_hint_and_garbage_lines_are_ignored(self):
        output = (
            "IDX BOOT ID FIRST ENTRY LAST ENTRY\n"
            "Hint: some hint text\n"
            "\n"
            "not a boot line\n"
            "  0 44444444444444444444444444444444 Tue 2026-01-06 13:00:00 CET  Tue 2026-01-06 14:00:00 CET\n"
        )
        sessions = self.parse(output)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["boot_id"], "4" * 32)

    def test_empty_output(self):
        self.assertEqual(self.parse(""), [])


class LastRebootParserTests(unittest.TestCase):
    def parse(self, output):
        with mock.patch.object(uptime, "run_command", return_value=output):
            return uptime.parse_last_reboot()

    def test_still_running_session_is_open(self):
        past = datetime.now() - timedelta(days=30)
        line = (
            f"reboot   system boot  6.1.0-amd64 "
            f"{past.strftime('%a %b')} {past.day:2d} {past.strftime('%H:%M')}"
            f"   still running\n"
        )
        sessions = self.parse(line + "wtmp begins Tue Jan  1 00:00:00 2026\n")
        self.assertEqual(len(sessions), 1)
        self.assertIsNone(sessions[0]["shutdown_time"])
        self.assertEqual(sessions[0]["source"], "last")

    def test_wtmp_marker_is_ignored(self):
        self.assertEqual(
            self.parse("wtmp begins Tue Jan  1 00:00:00 2026\n"), []
        )


if __name__ == "__main__":
    unittest.main()
