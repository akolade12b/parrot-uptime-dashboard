"""Tests for reconcile(): merging journald and wtmp records into the DB."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import database
import uptime


def journal_session(boot_time, shutdown_time, boot_id="a" * 32):
    return {
        "boot_time": boot_time,
        "shutdown_time": shutdown_time,
        "boot_id": boot_id,
        "source": "journal",
        "shutdown_estimated": False,
    }


def last_session(boot_time, shutdown_time):
    return {
        "boot_time": boot_time,
        "shutdown_time": shutdown_time,
        "boot_id": None,
        "source": "last",
        "shutdown_estimated": False,
    }


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_data_dir = config.DATA_DIR
        self._old_db_path = config.DB_PATH
        config.DATA_DIR = Path(self._tmp.name)
        config.DB_PATH = config.DATA_DIR / "test.db"

    def tearDown(self):
        config.DATA_DIR = self._old_data_dir
        config.DB_PATH = self._old_db_path
        self._tmp.cleanup()

    def reconcile_with(self, journal, last):
        with mock.patch.object(uptime, "parse_journal_boots", return_value=journal), \
                mock.patch.object(uptime, "parse_last_reboot", return_value=last), \
                mock.patch.object(uptime, "get_current_boot_time", return_value=None):
            return uptime.reconcile()

    def test_same_boot_from_both_sources_is_merged(self):
        boot = 1_700_000_000.0
        shutdown = 1_700_007_200.0
        count = self.reconcile_with(
            [journal_session(boot, shutdown)],
            [last_session(boot + 30, shutdown)],
        )
        self.assertEqual(count, 1)
        session = database.list_boot_sessions()[0]
        self.assertEqual(session["boot_id"], "a" * 32)
        self.assertEqual(session["boot_time"], boot)

    def test_distinct_boots_stay_separate(self):
        count = self.reconcile_with(
            [journal_session(1_700_000_000.0, 1_700_007_200.0)],
            [last_session(1_701_000_000.0, 1_701_007_200.0)],
        )
        self.assertEqual(count, 2)

    def test_empty_sources(self):
        self.assertEqual(self.reconcile_with([], []), 0)

    def test_reconcile_is_idempotent(self):
        journal = [journal_session(1_700_000_000.0, 1_700_007_200.0)]
        last = [last_session(1_701_000_000.0, 1_701_007_200.0)]
        first = self.reconcile_with(journal, last)
        second = self.reconcile_with(journal, last)
        self.assertEqual(first, second)
        self.assertEqual(first, 2)


if __name__ == "__main__":
    unittest.main()
