# Parrot Uptime Dashboard

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