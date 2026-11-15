"""Uptime calculation and historical reconstruction.

This module is the heart of the dashboard.  It:

  * reads the current boot time from /proc/uptime (the most reliable source,
    independent of any log parsing),
  * reconstructs *historical* boot/shutdown periods from journald
    (``journalctl --list-boots``) and from the wtmp database (``last reboot``),
  * merges those periods into the SQLite database,
  * and turns a set of boot sessions into per-calendar-day uptime totals by
    splitting each session across midnight boundaries.

No value is ever invented: if a source is unavailable or a day has no
record, that day is reported as having no data rather than a made-up number.
"""

from __future__ import annotations

import re
import subprocess
import time
from datetime import datetime, timedelta
from typing import Optional

import config
import database

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# Matches the two "YYYY-MM-DD HH:MM:SS" timestamps in a journalctl
# --list-boots row (FIRST ENTRY and LAST ENTRY).
_JOURNAL_DT_RE = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")
# Matches the 32-hex-char boot id in a journalctl row.
_JOURNAL_BOOT_RE = re.compile(r"^\s*[+-]?\d+\s+([0-9a-f]{32})\b")
# Matches a `last reboot` boot line: "reboot  system boot  <kernel>  <date>".
_LAST_BOOT_RE = re.compile(
    r"reboot\s+system boot\s+\S+\s+\w{3}\s+(\w{3})\s+(\d{1,2})\s+(\d{2}:\d{2})"
)


def now_ts() -> float:
    return time.time()


def local_tz():
    """Return the local timezone object."""
    return datetime.now().astimezone().tzinfo


def run_command(args, timeout: float = 10.0) -> str:
    """Run a command and return stdout, or '' on any failure."""
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


# --------------------------------------------------------------------------
# Current boot time
# --------------------------------------------------------------------------

def read_proc_uptime() -> Optional[float]:
    """Return the boot time (unix seconds) derived from /proc/uptime.

    /proc/uptime's first field is seconds since boot, so
    boot_time = now - uptime_seconds.  This never depends on parsing log
    output and is precise to well under a second.
    """
    try:
        with open("/proc/uptime", "r") as fh:
            up_seconds = float(fh.read().split()[0])
        return now_ts() - up_seconds
    except (OSError, ValueError, IndexError):
        return None


def get_current_boot_time() -> Optional[float]:
    """Best-effort current boot time as a unix timestamp."""
    bt = read_proc_uptime()
    if bt is not None:
        return bt
    # fallback: uptime -s
    out = run_command(["uptime", "-s"])
    try:
        return datetime.strptime(out.strip(), "%Y-%m-%d %H:%M:%S").timestamp()
    except (ValueError, AttributeError):
        pass
    # fallback: who -b
    out = run_command(["who", "-b"])
    m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", out)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            pass
    return None


def get_current_uptime_seconds() -> Optional[float]:
    """Seconds since the current boot, or None if unknown."""
    try:
        with open("/proc/uptime", "r") as fh:
            return float(fh.read().split()[0])
    except (OSError, ValueError, IndexError):
        bt = get_current_boot_time()
        return (now_ts() - bt) if bt else None


# --------------------------------------------------------------------------
# Historical sources
# --------------------------------------------------------------------------

def parse_journal_boots() -> list:
    """Parse ``journalctl --list-boots`` into session dicts.

    Returns a list of dicts with keys boot_time, shutdown_time, boot_id,
    source ('journal'), shutdown_estimated (False).

    The current boot (index 0) has shutdown_time=None because its "last
    entry" is merely the time of the most recent log line, not a shutdown.
    Past boots (negative index) have their LAST ENTRY as a measured shutdown.
    """
    out = run_command(["journalctl", "--list-boots", "--no-pager"])
    sessions = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("IDX") or line.startswith("Hint:"):
            continue
        m_id = _JOURNAL_BOOT_RE.match(line)
        if not m_id:
            continue
        boot_id = m_id.group(1)
        dts = _JOURNAL_DT_RE.findall(line)
        if len(dts) < 1:
            continue
        first = dts[0]
        last = dts[1] if len(dts) >= 2 else None
        try:
            boot_time = datetime.strptime(first, "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            continue

        # Determine whether this is the current boot.
        is_current = m_id.group(0).lstrip().startswith(("0", "+0"))

        shutdown = None
        if last and not is_current:
            try:
                shutdown = datetime.strptime(
                    last, "%Y-%m-%d %H:%M:%S"
                ).timestamp()
            except ValueError:
                shutdown = None

        if shutdown is not None and shutdown < boot_time:
            shutdown = None  # implausible; treat as open

        sessions.append({
            "boot_time": boot_time,
            "shutdown_time": shutdown,
            "boot_id": boot_id,
            "source": "journal",
            "shutdown_estimated": False,
        })
    return sessions


def _resolve_last_year(month: int, day: int, hour: int, minute: int) -> int:
    """Guess the year for a `last` entry (which never prints a year).

    Assume the current year, but step back a year if the resulting datetime
    would be in the future (the Dec/Jan rollover case).
    """
    now = datetime.now()
    year = now.year
    candidate = datetime(year, month, day, hour, minute)
    if candidate - now > timedelta(days=1):
        year -= 1
    return year


def parse_last_reboot() -> list:
    """Parse ``last reboot`` (wtmp) into session dicts.

    `last` is available even when journald has been cleared or is restricted,
    and typically reaches further back.  Its "still running" marker means the
    session is open (shutdown_time=None).
    """
    out = run_command(["last", "reboot"])
    sessions = []
    for line in out.splitlines():
        if "wtmp begins" in line:
            continue
        m = _LAST_BOOT_RE.match(line)
        if not m:
            continue
        month_s, day_s, time_s = m.group(1), m.group(2), m.group(3)
        month = _MONTHS.get(month_s)
        if month is None:
            continue
        try:
            day = int(day_s)
            hour, minute = (int(x) for x in time_s.split(":"))
        except ValueError:
            continue
        year = _resolve_last_year(month, day, hour, minute)
        try:
            boot_time = datetime(year, month, day, hour, minute).timestamp()
        except ValueError:
            continue

        rest = line[m.end():]
        shutdown = None
        estimated = False
        if "still running" in rest:
            shutdown = None
        else:
            # shutdown may be just "HH:MM" (same day) or a full
            # "Day Mon DD HH:MM" (multi-day session).
            m2 = re.search(
                r"-\s+(?:(?:\w{3}\s+\w{3}\s+\d{1,2}\s+)?(\d{2}:\d{2}))",
                rest,
            )
            if m2:
                shut_hm = m2.group(1)
                sh, sm = (int(x) for x in shut_hm.split(":"))
                full = re.search(
                    r"-\s+(\w{3})\s+(\w{3})\s+(\d{1,2})\s+(\d{2}:\d{2})", rest
                )
                if full:
                    try:
                        s_month = _MONTHS.get(full.group(2))
                        s_year = _resolve_last_year(
                            s_month, int(full.group(3)), sh, sm
                        )
                        shutdown = datetime(
                            s_year, s_month, int(full.group(3)), sh, sm
                        ).timestamp()
                    except (ValueError, TypeError):
                        shutdown = None
                else:
                    # same-day shutdown; bump to next day if it crosses midnight
                    bd = datetime.fromtimestamp(boot_time)
                    shutdown = datetime(
                        bd.year, bd.month, bd.day, sh, sm
                    ).timestamp()
                    if shutdown < boot_time:
                        shutdown += config.SECONDS_PER_DAY

        if shutdown is not None and shutdown < boot_time:
            shutdown = None

        sessions.append({
            "boot_time": boot_time,
            "shutdown_time": shutdown,
            "boot_id": None,
            "source": "last",
            "shutdown_estimated": estimated,
        })
    return sessions


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------

def ensure_current_session() -> int:
    """Make sure the current boot has an open session row in the DB.

    Any still-running session belonging to a *different* boot (i.e. the
    machine rebooted since we last ran) is finalised with an estimated
    shutdown time of the new boot -- journald/wtmp can later refine this with
    the true measured time.
    """
    boot_time = get_current_boot_time()
    if boot_time is None:
        raise RuntimeError("Could not determine the current boot time")

    # Finalise any stale open sessions from previous boots; keep the one
    # that matches the current boot time.
    current_id = None
    for open_sess in database.get_open_sessions():
        if abs(open_sess["boot_time"] - boot_time) <= 90:
            current_id = open_sess["id"]
        else:
            database.finalize_session(open_sess["id"], boot_time, estimated=True)

    if current_id is not None:
        return current_id
    return database.upsert_boot_session(boot_time=boot_time, source="proc")


def reconcile() -> int:
    """Pull in historical data from journald and wtmp, merge into the DB,
    ensure the current session is tracked, and refresh daily summaries.

    Returns the number of distinct boot sessions known after the merge.
    """
    database.init_db()

    # 1. Resolve the current (open) session first, so any stale open session
    #    from a previous boot is finalised before historical records arrive.
    try:
        ensure_current_session()
    except RuntimeError:
        pass

    # Merge all historical records inside ONE transaction so hundreds of
    # sessions cost a single commit rather than one fsync each.
    conn = database.get_connection()
    try:
        for session in parse_journal_boots():
            database.upsert_boot_session(
                boot_time=session["boot_time"],
                shutdown_time=session["shutdown_time"],
                boot_id=session["boot_id"],
                source=session["source"],
                shutdown_estimated=session["shutdown_estimated"],
                conn=conn,
            )
        for session in parse_last_reboot():
            database.upsert_boot_session(
                boot_time=session["boot_time"],
                shutdown_time=session["shutdown_time"],
                boot_id=session["boot_id"],
                source=session["source"],
                shutdown_estimated=session["shutdown_estimated"],
                conn=conn,
            )
        conn.commit()
    finally:
        conn.close()

    # 3. Ensure the current session exists even if all sources were empty.
    try:
        ensure_current_session()
    except RuntimeError:
        pass  # tracker handles this; GUI shows current status from /proc anyway

    rebuild_daily_summaries(days=60)

    return database.count_boot_sessions()


# --------------------------------------------------------------------------
# Daily uptime computation
# --------------------------------------------------------------------------

def session_daily_seconds(boot_time: float, shutdown_time: Optional[float],
                          now: Optional[float] = None) -> dict:
    """Split one boot session across local calendar days.

    Returns { 'YYYY-MM-DD': seconds }.  An open session (shutdown_time=None)
    is extended to ``now`` so today's running time is counted.
    """
    if now is None:
        now = now_ts()
    end = shutdown_time if shutdown_time is not None else now
    if end <= boot_time:
        return {}

    tz = local_tz()
    boot_dt = datetime.fromtimestamp(boot_time, tz)
    end_dt = datetime.fromtimestamp(end, tz)

    result: dict = {}
    day_start = boot_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    cursor = day_start
    while cursor < end_dt:
        day_end = cursor + timedelta(days=1)
        seg_start = max(boot_dt, cursor)
        seg_end = min(end_dt, day_end)
        if seg_end > seg_start:
            secs = (seg_end - seg_start).total_seconds()
            key = cursor.strftime("%Y-%m-%d")
            result[key] = result.get(key, 0.0) + secs
        cursor = day_end
    return result


def _today(now: Optional[float] = None) -> datetime:
    """Local-midnight datetime for ``now`` (defaults to the current time)."""
    if now is None:
        now = now_ts()
    return datetime.fromtimestamp(now, local_tz()).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def daily_uptime_between(start_day: datetime, end_day: datetime,
                         now: Optional[float] = None) -> list:
    """Per-day uptime for each local day in [start_day, end_day] (inclusive).

    Same shape as :func:`daily_uptime`, but for an arbitrary contiguous range
    of calendar days rather than only "the last N days".
    """
    if now is None:
        now = now_ts()
    tz = local_tz()
    start_ts = start_day.timestamp()
    end_ts = end_day.timestamp() + config.SECONDS_PER_DAY

    sessions = database.list_boot_sessions(start=start_ts,
                                           end=min(end_ts, now + 1))

    buckets: dict = {}
    for s in sessions:
        for date, secs in session_daily_seconds(
            s["boot_time"], s["shutdown_time"], now
        ).items():
            buckets[date] = buckets.get(date, 0.0) + secs

    earliest = database.earliest_boot_time()
    earliest_day = None
    if earliest is not None:
        earliest_day = datetime.fromtimestamp(earliest, tz).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    today = _today(now)
    out = []
    d = start_day
    while d <= end_day:
        key = d.strftime("%Y-%m-%d")
        secs = min(buckets.get(key, 0.0), config.SECONDS_PER_DAY)
        # "covered" means the day is within our recorded range, so a 0h bar
        # reads as "off" rather than "unknown"; future days stay unknown.
        covered = earliest_day is not None and earliest_day <= d <= today
        out.append({
            "date": key,
            "datetime": d,
            "seconds": secs,
            "covered": covered,
            "has_data": key in buckets,
        })
        d = d + timedelta(days=1)
    return out


def daily_uptime(days: int = 7, now: Optional[float] = None) -> list:
    """Return per-day uptime for the last ``days`` calendar days (incl. today).

    Each entry is {date, datetime, seconds, covered, has_data}:

      * ``seconds`` is the uptime clamped to at most 24h;
      * ``covered`` is True when the day falls inside the range we actually
        have records for (so 0h means "machine was off", not "unknown");
      * ``has_data`` is True when at least one session overlapped the day
        (i.e. the machine was running for part of it).
    """
    today = _today(now)
    start_day = today - timedelta(days=days - 1)
    return daily_uptime_between(start_day, today, now)


def stats_for_window(days: int, now: Optional[float] = None) -> dict:
    """Aggregate statistics for the last ``days`` days."""
    if now is None:
        now = now_ts()
    tz = local_tz()
    today = datetime.fromtimestamp(now, tz).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start_day = today - timedelta(days=days - 1)
    start_ts = start_day.timestamp()

    sessions = database.list_boot_sessions(start=start_ts, end=now + 1)
    daily = daily_uptime(days, now)

    total = sum(d["seconds"] for d in daily)
    today_seconds = daily[-1]["seconds"] if daily else 0.0
    days_with_data = sum(1 for d in daily if d["has_data"])

    boot_count = sum(1 for s in sessions if s["boot_time"] >= start_ts)

    longest = 0.0
    for s in sessions:
        end = s["shutdown_time"] if s["shutdown_time"] is not None else now
        if end > s["boot_time"]:
            longest = max(longest, end - s["boot_time"])

    covered_days = sum(1 for d in daily if d["covered"])
    # Average over the days we actually have coverage for, so unknown days
    # are not silently counted as zero uptime.
    average = total / covered_days if covered_days > 0 else 0.0

    return {
        "today_seconds": today_seconds,
        "total_seconds": total,
        "average_seconds": average,
        "longest_seconds": longest,
        "boot_count": boot_count,
        "days_with_data": days_with_data,
        "covered_days": covered_days,
        "days": days,
    }


def stats_for_range(start_day: datetime, end_day: datetime,
                    now: Optional[float] = None) -> dict:
    """Aggregate statistics for an arbitrary contiguous day range."""
    if now is None:
        now = now_ts()
    start_ts = start_day.timestamp()
    end_ts = end_day.timestamp() + config.SECONDS_PER_DAY

    sessions = database.list_boot_sessions(start=start_ts,
                                           end=min(end_ts, now + 1))
    daily = daily_uptime_between(start_day, end_day, now)

    total = sum(d["seconds"] for d in daily)
    days_with_data = sum(1 for d in daily if d["has_data"])

    boot_count = sum(1 for s in sessions if s["boot_time"] >= start_ts)

    longest = 0.0
    for s in sessions:
        end = s["shutdown_time"] if s["shutdown_time"] is not None else now
        if end > s["boot_time"]:
            longest = max(longest, end - s["boot_time"])

    covered_days = sum(1 for d in daily if d["covered"])
    # Average over the days we actually have coverage for, so unknown days
    # are not silently counted as zero uptime.
    average = total / covered_days if covered_days > 0 else 0.0

    return {
        "total_seconds": total,
        "average_seconds": average,
        "longest_seconds": longest,
        "boot_count": boot_count,
        "days_with_data": days_with_data,
        "covered_days": covered_days,
        "days": len(daily),
    }


def data_coverage() -> dict:
    """Describe how much historical data is available and from where."""
    sessions = database.list_boot_sessions()
    if not sessions:
        return {"earliest": None, "sources": set(), "count": 0}
    earliest = min(s["boot_time"] for s in sessions)
    sources = {s["source"] for s in sessions if s.get("source")}
    # journald contributes boot IDs even after its rows are merged into wtmp
    # rows, so surface it whenever any boot id is present.
    if any(s.get("boot_id") for s in sessions):
        sources.add("journal")
    return {"earliest": earliest, "sources": sources, "count": len(sessions)}


# --------------------------------------------------------------------------
# daily_summaries cache
# --------------------------------------------------------------------------

def rebuild_daily_summaries(days: int = 60) -> None:
    """Recompute and cache per-day totals into daily_summaries."""
    now = now_ts()
    conn = database.get_connection()
    try:
        for entry in daily_uptime(days, now):
            database.set_daily_summary(entry["date"], entry["seconds"], conn=conn)
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

def format_uptime(seconds: Optional[float]) -> str:
    """Human duration, e.g. '4 days 7 hours 32 minutes'."""
    if seconds is None:
        return "unknown"
    seconds = int(max(0, round(seconds)))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return " ".join(parts)


def format_hours(seconds: Optional[float]) -> str:
    """Compact hours-with-one-decimal form for stat tiles, e.g. '12.5 h'."""
    if seconds is None:
        return "—"
    hours = seconds / 3600.0
    if hours < 1:
        return f"{int(seconds // 60)}m"
    if hours < 100:
        return f"{hours:.1f}h"
    return f"{hours:.0f}h"


def format_boot_time(ts: Optional[float]) -> str:
    """Boot time as 'September 13, 2026 — 01:42:15'."""
    if ts is None:
        return "unknown"
    return datetime.fromtimestamp(ts).strftime("%B %d, %Y — %H:%M:%S")


def format_clock(ts: Optional[float] = None) -> str:
    if ts is None:
        ts = now_ts()
    return datetime.fromtimestamp(ts).strftime("%A, %B %d, %Y — %H:%M:%S")
