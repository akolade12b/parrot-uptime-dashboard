# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-15

### Added

- Native Tkinter dashboard showing live uptime, boot time, and current date.
- Per-day uptime bar charts with 7/30/90-day presets, all-history, and a
  custom start/end range.
- Historical reconstruction from `journalctl --list-boots` and `last reboot`,
  deduplicated by boot id, boot-time proximity, and interval overlap.
- SQLite history at `~/.local/share/parrot-uptime-dashboard/uptime.db`,
  with schema-versioned migrations.
- Background tracker running as a systemd user service (60-second tick,
  10-minute reconciliation with journald/wtmp).
- Installer and uninstaller with MATE launcher integration and optional
  autostart.
- Adaptive light/dark layout, maximised on startup and font-scaled to the
  desktop.
- Offline-by-design: no network access, no telemetry, no root required.
- Unit tests for uptime maths, formatters, parsers, and the database layer.
- CI on Python 3.9–3.13 and CodeQL analysis.
