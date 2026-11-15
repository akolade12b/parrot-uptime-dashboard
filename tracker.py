#!/usr/bin/env python3
"""Background uptime tracker for Parrot Uptime Dashboard.

Intended to run as a systemd *user* service so it needs no root and starts
with the user session (and, when user lingering is enabled, even before
login / after logout).  It is deliberately lightweight:

  * one tick every 60 seconds -- no busy polling, ~0% CPU;
  * each tick reads /proc/uptime and touches a couple of SQLite rows;
  * every 10 minutes it re-syncs with journalctl / `last` to backfill
    historical boot/shutdown records.

It never makes a network request and stores no sensitive data.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from logging.handlers import RotatingFileHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import database
import uptime

log = logging.getLogger("parrot-uptime-tracker")


def setup_logging() -> None:
    try:
        config.ensure_data_dir()
    except OSError:
        pass
    handler = RotatingFileHandler(
        str(config.LOG_PATH), maxBytes=1_000_000, backupCount=2
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def tick() -> int:
    """One tracker heartbeat: ensure the current boot is tracked and record
    that we observed it alive right now."""
    now = time.time()
    session_id = uptime.ensure_current_session()
    database.record_heartbeat(session_id, now)
    return session_id


def main() -> None:
    setup_logging()
    log.info("tracker starting (pid=%d, interval=%ds)",
             os.getpid(), config.TRACKER_INTERVAL)

    def _stop(signum, _frame):
        # On SIGTERM/SIGINT simply exit cleanly.  We deliberately do NOT
        # finalise the open session here: a user-service stop usually means
        # logout (the machine keeps running), and a real shutdown is captured
        # accurately by journald/wtmp on the next reconciliation.
        log.info("received signal %d, exiting cleanly", signum)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    # Backfill history immediately on startup.
    try:
        database.init_db()
        uptime.reconcile()
    except Exception as exc:  # noqa: BLE001 - keep the service alive
        log.error("startup reconcile failed: %s", exc)

    last_reconcile = time.time()
    while True:
        try:
            tick()
            now = time.time()
            if now - last_reconcile >= config.TRACKER_RECONCILE_INTERVAL:
                uptime.reconcile()
                last_reconcile = now
        except Exception as exc:  # noqa: BLE001 - never die on a bad tick
            log.error("tick failed: %s", exc)
        time.sleep(config.TRACKER_INTERVAL)


if __name__ == "__main__":
    main()
