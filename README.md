# Parrot Uptime Dashboard

<p align="center">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Linux%20%C2%B7%20Parrot%20OS-2ea382?style=flat-square&logo=linux&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="GUI" src="https://img.shields.io/badge/GUI-Tkinter-ff6f00?style=flat-square&logo=python&logoColor=white">
  <img alt="Charts" src="https://img.shields.io/badge/charts-Matplotlib-11557c?style=flat-square">
  <img alt="Storage" src="https://img.shields.io/badge/storage-SQLite-003b57?style=flat-square&logo=sqlite&logoColor=white">
  <img alt="Offline" src="https://img.shields.io/badge/network-offline%20%C2%B7%20no%20telemetry-4c8c4a?style=flat-square">
  <img alt="Root" src="https://img.shields.io/badge/root-not%20required-success?style=flat-square">
</p>

<p align="center">
  <a href="https://github.com/akolade12b/parrot-uptime-dashboard/releases"><img alt="Release" src="https://img.shields.io/github/v/release/akolade12b/parrot-uptime-dashboard?style=flat-square&logo=github"></a>
  <img alt="Release date" src="https://img.shields.io/github/release-date/akolade12b/parrot-uptime-dashboard?style=flat-square">
  <img alt="Last commit" src="https://img.shields.io/github/last-commit/akolade12b/parrot-uptime-dashboard?style=flat-square&logo=git&logoColor=white">
  <img alt="Commit activity" src="https://img.shields.io/github/commit-activity/m/akolade12b/parrot-uptime-dashboard?style=flat-square">
  <img alt="Stars" src="https://img.shields.io/github/stars/akolade12b/parrot-uptime-dashboard?style=flat-square&logo=github">
  <img alt="Forks" src="https://img.shields.io/github/forks/akolade12b/parrot-uptime-dashboard?style=flat-square&logo=github">
  <img alt="Watchers" src="https://img.shields.io/github/watchers/akolade12b/parrot-uptime-dashboard?style=flat-square&logo=github">
  <img alt="Issues" src="https://img.shields.io/github/issues/akolade12b/parrot-uptime-dashboard?style=flat-square&logo=github">
  <img alt="Pull requests" src="https://img.shields.io/github/issues-pr/akolade12b/parrot-uptime-dashboard?style=flat-square&logo=github">
  <img alt="Contributors" src="https://img.shields.io/github/contributors/akolade12b/parrot-uptime-dashboard?style=flat-square&logo=github">
  <img alt="Repository size" src="https://img.shields.io/github/repo-size/akolade12b/parrot-uptime-dashboard?style=flat-square">
  <img alt="Code size" src="https://img.shields.io/github/languages/code-size/akolade12b/parrot-uptime-dashboard?style=flat-square">
  <img alt="Top language" src="https://img.shields.io/github/languages/top/akolade12b/parrot-uptime-dashboard?style=flat-square">
  <img alt="Followers" src="https://img.shields.io/github/followers/akolade12b?style=flat-square&logo=github">
</p>

<p align="center">
  <a href="https://github.com/akolade12b/parrot-uptime-dashboard/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/akolade12b/parrot-uptime-dashboard/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="https://github.com/akolade12b/parrot-uptime-dashboard/actions/workflows/codeql.yml"><img alt="CodeQL" src="https://github.com/akolade12b/parrot-uptime-dashboard/actions/workflows/codeql.yml/badge.svg?branch=main"></a>
  <img alt="Commits since release" src="https://img.shields.io/github/commits-since/akolade12b/parrot-uptime-dashboard/v1.0.0?style=flat-square&logo=git&logoColor=white">
</p>

A native graphical uptime dashboard for the Parrot OS **MATE** desktop.
It shows how long the computer has been running, with historical uptime
graphed per day, and keeps accumulating reliable history automatically.

![screenshot placeholder](assets/parrot-uptime-dashboard.svg)

## Features

* **Current status** — live uptime, boot time, and current date/time.
* **Responsive, full-screen layout** — opens maximised and rescales its fonts,
  layout, and chart to fill any desktop size.
* **Flexible date ranges** — 7 / 30 / 90-day presets, "All history", and a
  custom start/end date range, each with a matching daily bar chart.
* **Bar charts** of daily uptime (0–24h, real matplotlib chart, any range).
* **Statistics** — today, range total, daily average, longest continuous
  session, boot count, and active days.
* **Historical reconstruction** — builds boot/shutdown history from
  `journalctl --list-boots` and `last reboot` (wtmp).  No invented values.
* **Persistent history** — SQLite database at
  `~/.local/share/parrot-uptime-dashboard/uptime.db`.
* **Background tracking** — a lightweight systemd *user* service records
  uptime even when the GUI is closed (60s tick, ~0% CPU).
* **MATE integration** — desktop launcher in the System ▸ Monitor category,
  optional autostart, and light/dark theme adaptation.
* **Fully offline** — no network access, no telemetry, no root required.

## Project layout

```
parrot-uptime-dashboard/
├── app.py            # GUI (Tkinter + Matplotlib)
├── database.py       # SQLite storage & session merging
├── uptime.py         # uptime maths + journald/wtmp reconstruction
├── tracker.py        # background tracker (systemd user service)
├── chart.py          # Matplotlib chart rendering
├── config.py         # paths & constants
├── requirements.txt
├── README.md
├── install.sh        # installer
├── uninstall.sh      # uninstaller
└── assets/           # icon
```

## Install

```bash
cd parrot-uptime-dashboard
./install.sh                # install launcher + tracker (no autostart)
# or
./install.sh --autostart    # also launch the dashboard at login
```

The installer uses your normal user account.  The only time it may prompt for
`sudo` is to install a missing `python3-tk` / `python3-matplotlib` package.

## Run the GUI

```bash
python3 app.py
```

or launch **Parrot Uptime Dashboard** from the MATE menu
(**System ▸ Parrot Uptime Dashboard**).

## How uptime is calculated

Each *boot session* has a start (boot) time and, once the machine shuts down
or reboots, an end (shutdown) time.  Daily uptime is the total running time
of all sessions during each local calendar day, split across midnight
boundaries, clamped to at most 24h.  Today's number grows live from the
current session.

## How historical uptime is reconstructed

Two system sources are merged (deduplicated by journald boot id, boot-time
proximity, and interval overlap):

* **journald** — `journalctl --list-boots` gives boot id + first/last entry.
* **wtmp** — `last reboot` gives boot/shutdown times, and often reaches
  further back than journald.

Days before the earliest record are marked **no data** (not zero); days the
machine was off are correctly shown as **0h**.  The tracker then keeps the
database growing reliably going forward.

## Background tracker

`tracker.py` runs as `parrot-uptime-tracker.service` in your systemd *user*
session:

```bash
systemctl --user status parrot-uptime-tracker
systemctl --user restart parrot-uptime-tracker
systemctl --user stop    parrot-uptime-tracker   # disable recording
```

It ticks once every 60 seconds (writing a heartbeat and confirming the
current boot), and re-syncs with journald/wtmp every 10 minutes.

## Autostart

Enabled only if you pass `--autostart` to the installer (or copy the launcher
into `~/.config/autostart/`).  To disable:

```bash
rm -f ~/.config/autostart/parrot-uptime-dashboard.desktop
```

## Uninstall

```bash
./uninstall.sh
```

This removes the launcher, the tracker service and the autostart entry, and
asks before deleting the historical database.  The application files
themselves are left in place.

## Notes / limitations

* Historical accuracy is bounded by what journald and wtmp retain.  The
  dashboard shows exactly which days have no data rather than guessing.
* The current boot's uptime is read from `/proc/uptime`, so it is correct
  even if the clock has been changed.
* The GUI itself does not need to stay open — recording is the tracker's job.