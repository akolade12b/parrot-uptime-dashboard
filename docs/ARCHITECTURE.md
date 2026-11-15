# Architecture

Parrot Uptime Dashboard is a small, offline desktop application. It has two
processes that share one SQLite database:

```
            ┌─────────────────────┐        ┌──────────────────────────┐
            │  app.py (GUI)       │        │ tracker.py (user service)│
            │  Tkinter + chart.py │        │  60s tick                │
            └─────────┬───────────┘        └────────────┬─────────────┘
                      │                                 │
                      ▼                                 ▼
            ┌───────────────────────────────────────────────────────┐
            │ uptime.py — current boot, journald/wtmp reconstruction │
            │             session splitting, statistics              │
            └───────────────────────────┬───────────────────────────┘
                                        ▼
            ┌───────────────────────────────────────────────────────┐
            │ database.py — SQLite (boot_sessions, daily_summaries)  │
            └───────────────────────────────────────────────────────┘
```

## Modules

| File | Responsibility |
|------|----------------|
| `config.py` | Identity, XDG data paths, intervals, schema version. |
| `database.py` | Schema, migrations, session upsert/merge, daily-summary cache. |
| `uptime.py` | `/proc/uptime`, journald and wtmp parsing, reconciliation, daily totals, formatters. |
| `chart.py` | Matplotlib bar chart, light/dark palettes, label thinning. |
| `app.py` | Tkinter window, range controls, stat tiles, refresh loop. |
| `tracker.py` | Headless heartbeat and periodic reconciliation. |

## Data model

`boot_sessions` stores one row per boot:

* `boot_id` — journald boot id when known (32 hex characters);
* `boot_time`, `shutdown_time` — unix timestamps; `shutdown_time` is NULL
  while the boot is still running;
* `shutdown_estimated` — whether the shutdown time was inferred;
* `source` — `journal`, `last`, or `tracker`.

`daily_summaries` caches per-day totals, and `meta` stores the schema
version. The cache is rebuildable from `boot_sessions` at any time.

## Reconciliation

`uptime.reconcile()` reads both historical sources and upserts every boot.
`database.upsert_boot_session()` then merges duplicates in this order:

1. exact `boot_id` match;
2. boot-time proximity (default 90 s);
3. overlap between two closed intervals (more than 60 s of overlap).

Merge rules keep the earliest boot time, prefer a measured shutdown over an
estimated one, keep the later shutdown time otherwise, and adopt the
journald boot id when it becomes available.

## Daily totals

`session_daily_seconds()` walks each session across local midnight
boundaries and returns `{date: seconds}`. `daily_uptime_between()` sums the
sessions overlapping a range, clamps each day to 24 h, and marks a day as
`covered` only when the database has records reaching back to it. Days
before the earliest record are *unknown*, not zero.

## Invariants

* **Offline**: no module imports a network library or performs I/O outside
  `/proc`, journald, wtmp, and the data directory.
* **No invented values**: missing history is reported as missing.
* **User-only**: no root, no system-wide service. The tracker is a systemd
  *user* unit.
* **Idempotent history**: reconciliation can run any number of times; the
  merge rules make it converge.
