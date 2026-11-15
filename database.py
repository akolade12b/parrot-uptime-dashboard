"""SQLite storage for Parrot Uptime Dashboard.

The database lives at ~/.local/share/parrot-uptime-dashboard/uptime.db and
holds three tables:

  * boot_sessions   -- one row per boot/uptime period (the core data)
  * daily_summaries -- cached per-day uptime totals (denormalised for speed)
  * meta            -- schema version and other small key/value state

All timestamps are stored as Unix epoch seconds (REAL).  ``None`` for
shutdown_time means the session is still running.

Merging duplicate records is deliberately careful.  journald's "FIRST ENTRY"
is the time of the first *log line*, which can be later than the real boot
(journald starts late / sparse early logs), while ``last`` (wtmp) records the
true boot time.  Two records for the *same* boot can therefore have
different boot times, so sessions are unified by three independent signals:
exact journald boot id, boot-time proximity, and interval overlap between two
closed sessions.

For bulk import (the reconcile path) most write functions accept an optional
shared ``conn`` so hundreds of sessions can be committed in a single
transaction instead of one fsync each.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Optional

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS boot_sessions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    boot_id            TEXT,                -- journald boot ID, may be NULL
    boot_time          REAL NOT NULL,       -- unix epoch seconds
    shutdown_time      REAL,                -- NULL while still running
    shutdown_estimated INTEGER NOT NULL DEFAULT 0,  -- 1 if shutdown inferred
    last_heartbeat     REAL,                -- last time tracker saw it alive
    source             TEXT NOT NULL,       -- journal|last|tracker|proc
    created_at         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_boot_sessions_boot_time
    ON boot_sessions (boot_time);
CREATE INDEX IF NOT EXISTS idx_boot_sessions_shutdown
    ON boot_sessions (shutdown_time);

CREATE TABLE IF NOT EXISTS daily_summaries (
    date            TEXT PRIMARY KEY,       -- YYYY-MM-DD (local calendar day)
    uptime_seconds  REAL NOT NULL,
    computed_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Overlap (in seconds) below which two closed sessions are NOT treated as the
# same boot.  Real sessions never overlap at all, so a >60s overlap between
# two closed sessions is effectively always duplicate data about one boot.
_MIN_OVERLAP = 60.0


class DatabaseError(Exception):
    """Raised when the database cannot be opened or is irreparably corrupt."""


def get_connection() -> sqlite3.Connection:
    """Open (creating if needed) the SQLite database with WAL mode."""
    try:
        config.ensure_data_dir()
    except OSError as exc:
        raise DatabaseError(
            f"Could not create data directory {config.DATA_DIR}: {exc}"
        ) from exc

    conn = sqlite3.connect(str(config.DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
    except sqlite3.Error as exc:
        conn.close()
        raise DatabaseError(f"Could not configure database: {exc}") from exc
    return conn


def init_db() -> None:
    """Create the schema and record the schema version."""
    conn = get_connection()
    try:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", str(config.SCHEMA_VERSION)),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Could not initialise database: {exc}") from exc
    finally:
        conn.close()


def schema_version() -> Optional[int]:
    """Return the stored schema version, or None if unknown."""
    try:
        conn = get_connection()
        row = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        conn.close()
        return int(row["value"]) if row else None
    except (sqlite3.Error, DatabaseError):
        return None


def find_session_by_boot_id(boot_id: str, conn=None):
    """Return a session by journald boot id, or None."""
    if not boot_id:
        return None
    close = conn is None
    conn = conn or get_connection()
    try:
        return conn.execute(
            "SELECT * FROM boot_sessions WHERE boot_id = ?", (boot_id,)
        ).fetchone()
    finally:
        if close:
            conn.close()


def find_session_by_boot_time(boot_time: float, tolerance: float = 90.0,
                              conn=None):
    """Return the session whose boot_time is closest to ``boot_time`` within
    ``tolerance`` seconds, or None.

    Uses a range query so the index on boot_time is used, instead of a full
    table scan + sort (which would be O(n log n) on every upsert).
    """
    close = conn is None
    conn = conn or get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM boot_sessions WHERE boot_time BETWEEN ? AND ? "
            "ORDER BY boot_time ASC",
            (boot_time - tolerance, boot_time + tolerance),
        ).fetchall()
        if not rows:
            return None
        return min(rows, key=lambda r: abs(r["boot_time"] - boot_time))
    finally:
        if close:
            conn.close()


def find_overlapping_closed_session(boot_time: float, shutdown_time: float,
                                    conn=None):
    """Return the CLOSED session that most overlaps [boot_time, shutdown_time],
    or None if no closed session overlaps by more than _MIN_OVERLAP seconds.

    Open (still-running) sessions are deliberately excluded: they belong to
    the current boot and are never a duplicate of a historical one.
    """
    close = conn is None
    conn = conn or get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM boot_sessions WHERE shutdown_time IS NOT NULL "
            "AND boot_time < ? AND shutdown_time > ?",
            (shutdown_time, boot_time),
        ).fetchall()
    finally:
        if close:
            conn.close()

    best = None
    best_overlap = 0.0
    for r in rows:
        overlap = min(shutdown_time, r["shutdown_time"]) - max(
            boot_time, r["boot_time"]
        )
        if overlap > best_overlap:
            best_overlap = overlap
            best = r
    return best if (best is not None and best_overlap > _MIN_OVERLAP) else None


def get_open_sessions() -> list:
    """Return all still-running sessions (shutdown_time IS NULL), newest first."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM boot_sessions WHERE shutdown_time IS NULL "
            "ORDER BY boot_time DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def upsert_boot_session(
    boot_time: float,
    shutdown_time: Optional[float] = None,
    boot_id: Optional[str] = None,
    source: str = "tracker",
    shutdown_estimated: bool = False,
    tolerance: float = 90.0,
    conn=None,
) -> int:
    """Insert or merge a boot session.

    Match order: exact boot id, boot-time proximity, then interval overlap
    between closed sessions.  Merge rules:

      * boot time   -> keep the earliest (journald can lag the real boot)
      * shutdown    -> a measured time beats an estimated one; between two of
                       the same class, keep the later (longer) time
      * boot id     -> adopt the journald id when available

    If ``conn`` is supplied, the write is left uncommitted so the caller can
    batch many upserts in a single transaction; otherwise it commits.
    """
    close = conn is None
    conn = conn or get_connection()
    try:
        existing = find_session_by_boot_id(boot_id, conn)
        overlap_merge = False
        if existing is None:
            existing = find_session_by_boot_time(boot_time, tolerance, conn)
        if existing is None and shutdown_time is not None:
            candidate = find_overlapping_closed_session(
                boot_time, shutdown_time, conn
            )
            if candidate is not None:
                existing = candidate
                overlap_merge = True

        now = time.time()

        if existing is not None:
            new_boot_time = (
                min(existing["boot_time"], boot_time)
                if overlap_merge
                else existing["boot_time"]
            )

            merged_shutdown = existing["shutdown_time"]
            merged_estimated = bool(existing["shutdown_estimated"])
            if shutdown_time is not None:
                if merged_shutdown is None:
                    merged_shutdown = shutdown_time
                    merged_estimated = shutdown_estimated
                else:
                    incoming_is_estimate = shutdown_estimated
                    existing_is_estimate = merged_estimated
                    if existing_is_estimate and not incoming_is_estimate:
                        merged_shutdown = shutdown_time
                        merged_estimated = False
                    elif existing_is_estimate == incoming_is_estimate:
                        if shutdown_time > merged_shutdown:
                            merged_shutdown = shutdown_time
                            merged_estimated = incoming_is_estimate

            new_boot_id = boot_id or existing["boot_id"]
            conn.execute(
                "UPDATE boot_sessions SET boot_id=?, boot_time=?, "
                "shutdown_time=?, shutdown_estimated=?, source=? WHERE id=?",
                (new_boot_id, new_boot_time, merged_shutdown,
                 int(merged_estimated), source, existing["id"]),
            )
            if close:
                conn.commit()
            return existing["id"]

        cur = conn.execute(
            "INSERT INTO boot_sessions "
            "(boot_id, boot_time, shutdown_time, shutdown_estimated, "
            " source, created_at) VALUES (?,?,?,?,?,?)",
            (boot_id, boot_time, shutdown_time, int(shutdown_estimated),
             source, now),
        )
        if close:
            conn.commit()
        return cur.lastrowid
    finally:
        if close:
            conn.close()


def finalize_session(session_id: int, shutdown_time: float,
                     estimated: bool = False) -> None:
    """Set the shutdown time of a session."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE boot_sessions SET shutdown_time=?, shutdown_estimated=? "
            "WHERE id=?",
            (shutdown_time, int(estimated), session_id),
        )
        conn.commit()
    finally:
        conn.close()


def record_heartbeat(session_id: int, ts: Optional[float] = None) -> None:
    """Record that the tracker saw this session alive at ``ts``."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE boot_sessions SET last_heartbeat=? WHERE id=?",
            (time.time() if ts is None else ts, session_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_boot_sessions(start: Optional[float] = None,
                       end: Optional[float] = None) -> list:
    """Return boot sessions ordered by boot_time, optionally filtered to
    sessions that overlap [start, end]."""
    conn = get_connection()
    try:
        if start is not None and end is not None:
            rows = conn.execute(
                "SELECT * FROM boot_sessions WHERE boot_time < ? AND "
                "(shutdown_time IS NULL OR shutdown_time > ?) "
                "ORDER BY boot_time ASC",
                (end, start),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM boot_sessions ORDER BY boot_time ASC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_boot_sessions() -> int:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM boot_sessions"
        ).fetchone()["n"]
    finally:
        conn.close()


def earliest_boot_time() -> Optional[float]:
    """Earliest boot time in the database, or None if empty."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT MIN(boot_time) AS m FROM boot_sessions"
        ).fetchone()
        return row["m"]
    finally:
        conn.close()


def clear_boot_sessions() -> None:
    """Delete all boot sessions and cached summaries (data wipe)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM boot_sessions")
        conn.execute("DELETE FROM daily_summaries")
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# daily_summaries cache
# --------------------------------------------------------------------------

def get_daily_summary(date: str) -> Optional[float]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT uptime_seconds FROM daily_summaries WHERE date=?", (date,)
        ).fetchone()
        return float(row["uptime_seconds"]) if row else None
    finally:
        conn.close()


def set_daily_summary(date: str, seconds: float, conn=None) -> None:
    """Cache a day total.  Accepts a shared ``conn`` for batched commits."""
    close = conn is None
    conn = conn or get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO daily_summaries "
            "(date, uptime_seconds, computed_at) VALUES (?,?,?)",
            (date, seconds, time.time()),
        )
        if close:
            conn.commit()
    finally:
        if close:
            conn.close()
