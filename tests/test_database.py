"""Tests for the SQLite storage layer, run against a throwaway database."""

import tempfile
import unittest
from pathlib import Path

import config
import database


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_data_dir = config.DATA_DIR
        self._old_db_path = config.DB_PATH
        config.DATA_DIR = Path(self._tmp.name)
        config.DB_PATH = config.DATA_DIR / "test.db"
        database.init_db()

    def tearDown(self):
        config.DATA_DIR = self._old_data_dir
        config.DB_PATH = self._old_db_path
        self._tmp.cleanup()


class SchemaTests(DatabaseTestCase):
    def test_schema_version_is_stored(self):
        self.assertEqual(database.schema_version(), config.SCHEMA_VERSION)

    def test_starts_empty(self):
        self.assertEqual(database.count_boot_sessions(), 0)
        self.assertIsNone(database.earliest_boot_time())
        self.assertIsNone(database.get_daily_summary("2026-01-01"))


class BootSessionTests(DatabaseTestCase):
    def test_insert_and_find_by_boot_id(self):
        boot_id = "a" * 32
        database.upsert_boot_session(1_700_000_000.0, boot_id=boot_id)
        found = database.find_session_by_boot_id(boot_id)
        self.assertIsNotNone(found)
        self.assertEqual(found["boot_time"], 1_700_000_000.0)

    def test_boot_time_proximity_merges(self):
        first = database.upsert_boot_session(1_700_000_000.0)
        second = database.upsert_boot_session(1_700_000_030.0)
        self.assertEqual(first, second)
        self.assertEqual(database.count_boot_sessions(), 1)

    def test_boot_time_outside_tolerance_does_not_merge(self):
        database.upsert_boot_session(1_700_000_000.0)
        database.upsert_boot_session(1_700_100_000.0)
        self.assertEqual(database.count_boot_sessions(), 2)

    def test_overlapping_closed_sessions_merge(self):
        database.upsert_boot_session(1_700_000_000.0, shutdown_time=1_700_010_000.0)
        database.upsert_boot_session(1_700_005_000.0, shutdown_time=1_700_020_000.0)
        self.assertEqual(database.count_boot_sessions(), 1)
        session = database.list_boot_sessions()[0]
        self.assertEqual(session["boot_time"], 1_700_000_000.0)
        self.assertEqual(session["shutdown_time"], 1_700_020_000.0)

    def test_finalize_session_sets_shutdown(self):
        session_id = database.upsert_boot_session(1_700_000_000.0)
        database.finalize_session(session_id, 1_700_001_000.0)
        session = database.list_boot_sessions()[0]
        self.assertEqual(session["shutdown_time"], 1_700_001_000.0)

    def test_list_filters_by_overlapping_range(self):
        database.upsert_boot_session(1_700_000_000.0, shutdown_time=1_700_001_000.0)
        database.upsert_boot_session(1_700_100_000.0, shutdown_time=1_700_101_000.0)
        rows = database.list_boot_sessions(
            start=1_700_000_500.0, end=1_700_002_000.0
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["boot_time"], 1_700_000_000.0)

    def test_clear_boot_sessions(self):
        database.upsert_boot_session(1_700_000_000.0)
        database.set_daily_summary("2026-01-01", 3600.0)
        database.clear_boot_sessions()
        self.assertEqual(database.count_boot_sessions(), 0)
        self.assertIsNone(database.get_daily_summary("2026-01-01"))


class DailySummaryTests(DatabaseTestCase):
    def test_round_trip(self):
        database.set_daily_summary("2026-01-01", 1234.5)
        self.assertEqual(database.get_daily_summary("2026-01-01"), 1234.5)

    def test_overwrite(self):
        database.set_daily_summary("2026-01-01", 100.0)
        database.set_daily_summary("2026-01-01", 200.0)
        self.assertEqual(database.get_daily_summary("2026-01-01"), 200.0)


if __name__ == "__main__":
    unittest.main()
