#!/usr/bin/env python3
"""Parrot Uptime Dashboard — graphical front-end.

A Tkinter + Matplotlib dashboard focused on uptime history.  It is designed
to run on the MATE desktop and adapts its colours to light/dark themes.  The
window opens maximised and its layout, fonts and chart rescale with the
window so it stays comfortable on any desktop size.

The GUI is *not* responsible for background recording — that is the tracker
service's job.  The GUI only reads the SQLite database and the live
/proc/uptime value, and can trigger a one-off re-sync with journald/wtmp via
the Refresh button.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import font as tkfont
from tkinter import messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import database
import uptime

# --- Matplotlib (must pick the Tk backend before importing Figure) ---------
try:
    import matplotlib
    matplotlib.use("TkAgg")
    # Match the UI face so chart text doesn't fall back to a wide default.
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = [
        "Cantarell", "Liberation Sans", "DejaVu Sans",
    ]
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MATPLOTLIB = True
except Exception as _exc:  # ImportError or backend init failure
    HAS_MATPLOTLIB = False
    MATPLOTLIB_ERROR = str(_exc)

import chart  # noqa: E402


# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------

def detect_dark() -> bool:
    """Guess whether the MATE desktop is using a dark theme."""
    env_theme = os.environ.get("GTK_THEME", "").lower()
    if "dark" in env_theme:
        return True
    for args in (
        ["gsettings", "get", "org.mate.interface", "gtk-theme"],
        ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
        ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
    ):
        try:
            out = subprocess.run(
                args, capture_output=True, text=True, timeout=3
            ).stdout.lower()
        except (OSError, subprocess.SubprocessError):
            continue
        if "dark" in out:
            return True
    return False


def theme_colors(dark: bool) -> dict:
    if dark:
        return {
            "bg": "#1e1f22", "card": "#2a2b2e", "fg": "#e6e6e6",
            "muted": "#9aa0a6", "accent": "#3fb27f", "border": "#3a3b3f",
            "warn": "#e2a33c", "err": "#e05555", "btn_bg": "#34353a",
            "btn_fg": "#e6e6e6", "btn_active": "#3fb27f",
        }
    return {
        "bg": "#f5f6f8", "card": "#ffffff", "fg": "#1f2328",
        "muted": "#6a737d", "accent": "#1f8a70", "border": "#d0d7de",
        "warn": "#b97e00", "err": "#cf222e", "btn_bg": "#e9ecf0",
        "btn_fg": "#1f2328", "btn_active": "#1f8a70",
    }


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def compact(seconds):
    """'5d 3h', '18h 31m', or '42m'."""
    seconds = int(max(0, round(seconds or 0)))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class ToolTip:
    """A minimal, dependency-free tooltip for tk widgets."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _event=None):
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tip, text=self.text, justify="left", background="#ffffe0",
            foreground="#1f2328", relief="solid", borderwidth=1,
            padx=8, pady=4, font=("Cantarell", 9), wraplength=420,
        )
        label.pack()

    def hide(self, _event=None):
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


# --------------------------------------------------------------------------
# About dialog
# --------------------------------------------------------------------------

ABOUT_TEXT = """\
What uptime means
-----------------
Uptime is the amount of time the computer has been powered on and running.

How it is calculated
--------------------
Each boot session is recorded with its start (boot) time and, once the
machine is shut down or rebooted, its end (shutdown) time.  Daily uptime is
the total time all sessions were running during each calendar day, split
across midnight boundaries.  Today's figure grows live from the current
session.  Daily totals never exceed 24 hours.

Historical data
---------------
Historical boot/shutdown periods are reconstructed from two system sources:
  • journald  (journalctl --list-boots)
  • the wtmp log (last reboot)
No values are invented.  Days before the earliest available record are shown
as "no data"; days the machine was off are shown as zero.

Where data is stored
--------------------
SQLite database:  {db}

Background recording
--------------------
A lightweight systemd user service ("parrot-uptime-tracker") keeps recording
uptime even when this window is closed.

This application works entirely offline and stores no sensitive data.
"""


# --------------------------------------------------------------------------
# Main application
# --------------------------------------------------------------------------

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.dark = detect_dark()
        self.tc = theme_colors(self.dark)

        # Selected date range: "days" (last N days), "all", or "custom".
        self.range_kind = "days"
        self.days = 7
        self.custom_start: str | None = None  # "YYYY-MM-DD"
        self.custom_end: str | None = None

        self.db_ok = True
        self.db_error: str | None = None
        self.covered_note = ""

        self._daily = None       # last daily-uptime list, kept for redraws
        self._scale = 1.0        # responsive font scale factor
        self._resize_job = None

        self._init_fonts()

        self._init_database()
        self._build_ui()
        self.refresh(force=True, reconcile=True)
        self._schedule_clock()
        self._schedule_stats()

    # -- fonts (responsive) -------------------------------------------------
    def _init_fonts(self):
        """Named fonts so every widget rescales from one place.

        Cantarell (the GNOME UI face) renders cleanly and compactly on the
        MATE desktop, unlike the wide default 'Sans' alias that looks
        stretched at larger sizes.
        """
        self._font_family = "Cantarell"
        self._base_fonts = {
            "title": 20, "subtitle": 11, "running": 13,
            "status_cap": 12, "status_val": 13,
            "tile_val": 17, "tile_cap": 10,
            "chart_title": 13, "legend": 10, "button": 11, "statusbar": 10,
        }
        self.fonts = {}
        for name, size in self._base_fonts.items():
            self.fonts[name] = tkfont.Font(family=self._font_family, size=size)

    def _apply_scale(self):
        """Rescale all fonts to the window width (debounced on resize)."""
        w = max(1, self.root.winfo_width())
        # Gentle scaling — just enough to feel responsive, but not so much
        # that text balloons and looks stretched on a large display.
        factor = max(0.9, min(1.1, w / 1500.0))
        if abs(factor - self._scale) < 0.03:
            return
        self._scale = factor
        for name, base in self._base_fonts.items():
            self.fonts[name].configure(size=max(7, int(round(base * factor))))
        # Redraw the chart so its matplotlib text scales too.
        if HAS_MATPLOTLIB and self.fig is not None and self._daily is not None:
            self._draw_chart()

    def _on_configure(self, event):
        if event.widget is not self.root:
            return
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(120, self._apply_scale)

    # -- database -----------------------------------------------------------
    def _init_database(self):
        try:
            database.init_db()
            self.db_ok = True
        except database.DatabaseError as exc:
            # Attempt one recovery: move the corrupt file aside and retry.
            self.db_ok = False
            self.db_error = str(exc)
            try:
                if config.DB_PATH.exists():
                    corrupt = config.DB_PATH.with_name(
                        f"uptime.db.corrupt-{int(time.time())}"
                    )
                    config.DB_PATH.rename(corrupt)
                    # also clear the WAL/SHM sidecars
                    for suffix in ("-wal", "-shm"):
                        sidecar = config.DB_PATH.with_name(
                            config.DB_PATH.name + suffix
                        )
                        if sidecar.exists():
                            sidecar.unlink()
                    database.init_db()
                    self.db_ok = True
                    self.db_error = (
                        f"Recovered from a corrupt database (previous file "
                        f"saved as {corrupt.name})."
                    )
            except Exception as exc2:  # noqa: BLE001
                self.db_ok = False
                self.db_error = f"{exc}; recovery failed: {exc2}"

    # -- UI construction ----------------------------------------------------
    def _build_ui(self):
        c = self.tc
        self.root.title(config.APP_NAME)
        self.root.configure(bg=c["bg"])
        self.root.geometry("1100x780")
        self.root.minsize(760, 600)
        # Fill the desktop.  The maximise request must happen *after* the
        # window is mapped, or many window managers (MATE/Marco included)
        # silently ignore it — so defer it to the first idle loop.
        self.root.after(50, self._maximize)

        self._build_menu()

        main = tk.Frame(self.root, bg=c["bg"], padx=22, pady=14)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        # Header
        title = tk.Label(
            main, text=config.APP_NAME, bg=c["bg"], fg=c["fg"],
            font=self.fonts["title"], anchor="w",
        )
        title.grid(row=0, column=0, sticky="w")
        subtitle = tk.Label(
            main, text="System uptime history for your MATE desktop",
            bg=c["bg"], fg=c["muted"], font=self.fonts["subtitle"], anchor="w",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(0, 14))

        # Current status card
        status_card = tk.Frame(main, bg=c["card"], highlightbackground=c["border"],
                               highlightthickness=1, padx=20, pady=16)
        status_card.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        status_card.columnconfigure(1, weight=1)

        self.running_label = tk.Label(
            status_card, text="●  System Running", bg=c["card"], fg=c["accent"],
            font=self.fonts["running"], anchor="w",
        )
        self.running_label.grid(row=0, column=0, columnspan=2, sticky="w",
                                pady=(0, 10))

        self._status_row(status_card, 1, "Current uptime:", "uptime")
        self._status_row(status_card, 2, "Boot time:", "boot")
        self._status_row(status_card, 3, "Current time:", "clock")

        # Stats tiles
        stats_frame = tk.Frame(main, bg=c["bg"])
        stats_frame.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        stats_frame.columnconfigure((0, 1, 2), weight=1, uniform="tile")

        self.stat_values = {}
        self.stat_captions = {}
        tile_specs = [
            ("today", "Today", "Total uptime so far today."),
            ("total", "Total", "Total uptime over the selected range."),
            ("avg", "Average / day", "Average daily uptime over the selected "
                                      "range (days without records excluded)."),
            ("longest", "Longest session", "Longest single continuous uptime "
                                           "in the selected range."),
            ("boots", "Boot count", "Number of times the machine was started "
                                    "in the selected range."),
            ("active", "Days active", "Days in the selected range on which "
                                      "the machine was running."),
        ]
        for i, (key, caption, tip) in enumerate(tile_specs):
            tile = tk.Frame(stats_frame, bg=c["card"],
                            highlightbackground=c["border"],
                            highlightthickness=1, padx=16, pady=13)
            tile.grid(row=i // 3, column=i % 3, sticky="ew", padx=5, pady=5)
            val = tk.Label(tile, text="—", bg=c["card"], fg=c["fg"],
                           font=self.fonts["tile_val"], anchor="w")
            val.pack(anchor="w")
            cap = tk.Label(tile, text=caption, bg=c["card"], fg=c["muted"],
                           font=self.fonts["tile_cap"], anchor="w")
            cap.pack(anchor="w")
            self.stat_values[key] = val
            self.stat_captions[key] = cap
            ToolTip(tile, tip)

        # Chart
        self.chart_title = tk.Label(
            main, text="Uptime — last 7 days", bg=c["bg"], fg=c["fg"],
            font=self.fonts["chart_title"], anchor="w",
        )
        self.chart_title.grid(row=4, column=0, sticky="w", pady=(0, 4))

        self.chart_frame = tk.Frame(main, bg=c["bg"])
        self.chart_frame.grid(row=5, column=0, sticky="nsew")
        main.rowconfigure(5, weight=1)

        self.canvas = None
        self.fig = None
        if HAS_MATPLOTLIB:
            self.fig = Figure(figsize=(8, 3.4), dpi=100)
            self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
            self.canvas.get_tk_widget().pack(fill="both", expand=True)
        else:
            tk.Label(
                self.chart_frame,
                text="Matplotlib is not available — chart disabled.\n"
                     f"({MATPLOTLIB_ERROR})\n\n"
                     "Install it with:  sudo apt install python3-matplotlib",
                bg=c["bg"], fg=c["err"], font=("Sans", 11), justify="left",
            ).pack(anchor="w", pady=20)

        # Legend / note
        legend = tk.Label(
            main,
            text="■ running    ■ off (known)    ■ no data",
            bg=c["bg"], fg=c["muted"], font=self.fonts["legend"], anchor="w",
        )
        legend.grid(row=6, column=0, sticky="w", pady=(6, 0))

        # Controls
        controls = tk.Frame(main, bg=c["bg"])
        controls.grid(row=7, column=0, sticky="ew", pady=(12, 0))

        self.range_buttons = {}
        def _rbtn(text, key, cmd):
            btn = self._button(controls, text, cmd)
            btn.pack(side="left", padx=(0, 8))
            self.range_buttons[key] = btn
            return btn
        _rbtn("7 Days", ("days", 7), lambda: self._set_range("days", 7))
        _rbtn("30 Days", ("days", 30), lambda: self._set_range("days", 30))
        _rbtn("90 Days", ("days", 90), lambda: self._set_range("days", 90))
        _rbtn("All", ("all",), lambda: self._set_range("all"))
        _rbtn("Custom…", ("custom",), self._show_custom_range)

        self._button(controls, "Refresh", self._on_refresh).pack(side="left",
                                                                 padx=(8, 0))
        self._button(controls, "About / Help", self._show_about).pack(
            side="right")

        # Status bar
        self.statusbar = tk.Label(
            main, text="", bg=c["bg"], fg=c["muted"], font=self.fonts["statusbar"],
            anchor="w",
        )
        self.statusbar.grid(row=8, column=0, sticky="ew", pady=(12, 0))

        self._update_button_state()

        # Respond to window resizes (debounced) for the responsive fonts.
        self.root.bind("<Configure>", self._on_configure)

    def _maximize(self):
        """Maximise the window once it has been mapped onto the desktop."""
        try:
            self.root.attributes("-zoomed", True)
        except tk.TclError:
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass

    def _status_row(self, parent, row, caption, key):
        c = self.tc
        cap = tk.Label(parent, text=caption, bg=c["card"], fg=c["muted"],
                       font=self.fonts["status_cap"], anchor="w")
        cap.grid(row=row, column=0, sticky="w", padx=(0, 16), pady=3)
        val = tk.Label(parent, text="—", bg=c["card"], fg=c["fg"],
                       font=self.fonts["status_val"], anchor="w")
        val.grid(row=row, column=1, sticky="w", pady=3)
        setattr(self, f"status_{key}", val)

    def _button(self, parent, text, command):
        c = self.tc
        return tk.Button(
            parent, text=text, command=command, bg=c["btn_bg"], fg=c["btn_fg"],
            activebackground=c["btn_active"], activeforeground="#ffffff",
            relief="flat", padx=14, pady=6, font=self.fonts["button"],
            cursor="hand2", highlightthickness=0,
        )

    def _build_menu(self):
        c = self.tc
        menubar = tk.Menu(self.root)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Refresh", command=self._on_refresh)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=filemenu)

        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(label="About / Help", command=self._show_about)
        menubar.add_cascade(label="Help", menu=helpmenu)
        self.root.config(menu=menubar)

    # -- range selection ----------------------------------------------------
    def _parse_day(self, s: str) -> datetime:
        """Parse a 'YYYY-MM-DD' string into a local-midnight datetime."""
        return datetime.strptime(s.strip(), "%Y-%m-%d").replace(
            tzinfo=uptime.local_tz()
        )

    def _range_days(self):
        """Return (start_day, end_day) local-midnight datetimes for the range."""
        today = datetime.fromtimestamp(time.time(), uptime.local_tz()).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if self.range_kind == "custom":
            if self.custom_start and self.custom_end:
                try:
                    return self._parse_day(self.custom_start), \
                           self._parse_day(self.custom_end)
                except ValueError:
                    pass  # fall back to a week on malformed input
            return today - timedelta(days=6), today
        if self.range_kind == "all":
            earliest = database.earliest_boot_time()
            if earliest is not None:
                start = datetime.fromtimestamp(earliest, uptime.local_tz()).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            else:
                start = today - timedelta(days=6)
            return start, today
        return today - timedelta(days=self.days - 1), today

    def _range_label(self) -> str:
        if self.range_kind == "days":
            return f"last {self.days} days"
        if self.range_kind == "all":
            return "all history"
        start, end = self._range_days()
        if start.year == end.year:
            return f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
        return f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"

    def _active_key(self):
        if self.range_kind == "custom":
            return ("custom",)
        if self.range_kind == "all":
            return ("all",)
        return ("days", self.days)

    def _set_range(self, kind, days=None):
        self.range_kind = kind
        if days is not None:
            self.days = days
        self._update_button_state()
        self._update_stats()

    def _update_button_state(self):
        c = self.tc
        active = self._active_key()
        for key, btn in self.range_buttons.items():
            if key == active:
                btn.config(bg=c["btn_active"], fg="#ffffff")
            else:
                btn.config(bg=c["btn_bg"], fg=c["btn_fg"])

    def _show_custom_range(self):
        c = self.tc
        start_day, end_day = self._range_days()

        win = tk.Toplevel(self.root)
        win.title("Custom date range")
        win.configure(bg=c["bg"])
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        body = tk.Frame(win, bg=c["bg"], padx=20, pady=16)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text="Show uptime between two dates (inclusive).",
            bg=c["bg"], fg=c["muted"], font=self.fonts["subtitle"], anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        start_var = tk.StringVar(value=start_day.strftime("%Y-%m-%d"))
        end_var = tk.StringVar(value=end_day.strftime("%Y-%m-%d"))

        start_entry = self._range_entry(body, 1, "Start date", start_var)
        end_entry = self._range_entry(body, 2, "End date", end_var)

        tk.Label(
            body, text="Format: YYYY-MM-DD   e.g. 2026-09-01",
            bg=c["bg"], fg=c["muted"], font=self.fonts["legend"], anchor="w",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        err = tk.Label(body, text="", bg=c["bg"], fg=c["err"],
                       font=self.fonts["legend"], anchor="w")
        err.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def apply():
            try:
                s = self._parse_day(start_var.get())
                e = self._parse_day(end_var.get())
            except ValueError:
                err.config(text="Invalid date — use the YYYY-MM-DD format.")
                return
            if e < s:
                err.config(text="End date is before the start date.")
                return
            self.custom_start = s.strftime("%Y-%m-%d")
            self.custom_end = e.strftime("%Y-%m-%d")
            self._set_range("custom")
            win.destroy()

        btns = tk.Frame(body, bg=c["bg"])
        btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(14, 0))
        self._button(btns, "Cancel", win.destroy).pack(side="left")
        self._button(btns, "Apply", apply).pack(side="left", padx=(8, 0))

        start_entry.focus_set()

    def _range_entry(self, parent, row, caption, var):
        c = self.tc
        tk.Label(parent, text=caption, bg=c["bg"], fg=c["fg"],
                 font=self.fonts["status_cap"], anchor="w").grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        entry = tk.Entry(
            parent, textvariable=var, bg=c["card"], fg=c["fg"],
            insertbackground=c["fg"], relief="flat",
            highlightbackground=c["border"], highlightthickness=1,
            width=14, font=self.fonts["status_val"],
        )
        entry.grid(row=row, column=1, sticky="w", pady=4)
        return entry

    # -- actions ------------------------------------------------------------
    def _on_refresh(self):
        self.refresh(force=True, reconcile=True)

    def refresh(self, force=False, reconcile=False):
        """Refresh current status and (if force) stats + chart."""
        self._update_current()
        if force:
            self._update_stats()
        if reconcile:
            self._reconcile_async()

    def _reconcile_async(self):
        """Re-sync with journald/wtmp in the background thread-free way:
        it's quick, so run inline but guard against exceptions."""
        if not self.db_ok:
            return
        try:
            uptime.reconcile()
        except Exception as exc:  # noqa: BLE001
            self.statusbar.config(text=f"Re-sync failed: {exc}")

    # -- live updates -------------------------------------------------------
    def _update_current(self):
        c = self.tc
        boot = uptime.get_current_boot_time()
        up_seconds = uptime.get_current_uptime_seconds()

        self.status_uptime.config(text=uptime.format_uptime(up_seconds))
        self.status_boot.config(text=uptime.format_boot_time(boot))
        self.status_clock.config(text=uptime.format_clock())

        if boot is not None:
            self.running_label.config(
                text="●  System Running", fg=c["accent"])
        else:
            self.running_label.config(
                text="●  Status unknown (cannot read boot time)",
                fg=c["warn"])

    def _update_stats(self):
        if not self.db_ok:
            for k in self.stat_values:
                self.stat_values[k].config(text="—")
            self.statusbar.config(
                text=f"History database unavailable: {self.db_error}",
                fg=self.tc["err"])
            return

        try:
            start_day, end_day = self._range_days()
            stats = uptime.stats_for_range(start_day, end_day)
            daily = uptime.daily_uptime_between(start_day, end_day)
            today_stats = uptime.stats_for_window(1)
        except Exception as exc:  # noqa: BLE001
            for k in self.stat_values:
                self.stat_values[k].config(text="—")
            self.statusbar.config(text=f"Could not read history: {exc}",
                                  fg=self.tc["err"])
            return

        self._daily = daily

        # "Today" is the day-split total (correct even if the current boot
        # started before midnight), not the whole current-session length.
        self.stat_values["today"].config(text=compact(today_stats["today_seconds"]))
        self.stat_values["total"].config(text=compact(stats["total_seconds"]))
        self.stat_values["avg"].config(text=compact(stats["average_seconds"]))
        self.stat_values["longest"].config(text=compact(stats["longest_seconds"]))
        self.stat_values["boots"].config(text=str(stats["boot_count"]))
        self.stat_values["active"].config(
            text=f"{stats['days_with_data']} / {stats['days']}")

        label = self._range_label()
        self.stat_captions["total"].config(text=f"Total · {label}")

        # Chart title + redraw
        self.chart_title.config(text=f"Uptime — {label}")
        self._draw_chart()

        # Status bar coverage note
        cov = uptime.data_coverage()
        if cov["count"] == 0:
            note = ("No historical data yet — recording starts now "
                    "(history builds from system logs + the tracker).")
        else:
            note = (f"{cov['count']} boot sessions on record "
                    f"(sources: {', '.join(sorted(cov['sources'])) or 'none'}). "
                    f"Coverage: {stats['covered_days']}/{stats['days']} days "
                    f"in range.")
        if self.db_error:
            note += f"  {self.db_error}"
        self.statusbar.config(text=note, fg=self.tc["muted"])

    def _draw_chart(self):
        if not HAS_MATPLOTLIB or self.fig is None or self._daily is None:
            return
        chart.render(self.fig, self._daily, self.dark, self._scale)
        self.canvas.draw_idle()

    # -- schedules ----------------------------------------------------------
    def _schedule_clock(self):
        self._update_current()
        self.root.after(1000, self._schedule_clock)

    def _schedule_stats(self):
        self._update_stats()
        self.root.after(5000, self._schedule_stats)

    # -- about --------------------------------------------------------------
    def _show_about(self):
        c = self.tc
        win = tk.Toplevel(self.root)
        win.title("About — " + config.APP_NAME)
        win.configure(bg=c["bg"])
        win.geometry("620x560")
        win.transient(self.root)

        text = ABOUT_TEXT.format(db=config.DB_PATH)
        body = tk.Label(win, text=text, justify="left", bg=c["bg"], fg=c["fg"],
                        font=("Cantarell", 10), anchor="nw", padx=18, pady=14)
        body.pack(fill="both", expand=True)

        close = self._button(win, "Close", win.destroy)
        close.pack(anchor="e", padx=18, pady=(0, 14))


def main():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("Tkinter is required but not installed.", file=sys.stderr)
        print("Install it with: sudo apt install python3-tk", file=sys.stderr)
        return 1

    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
