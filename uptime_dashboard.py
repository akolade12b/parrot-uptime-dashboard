#!/usr/bin/env python3

import tkinter as tk
from tkinter import ttk
from datetime import datetime, timedelta
import subprocess
import json
import os
import re

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
except ImportError:
    print("Matplotlib is required.")
    print("Install it with: sudo apt install python3-matplotlib")
    raise


APP_DIR = os.path.expanduser("~/uptime-dashboard")
HISTORY_FILE = os.path.join(APP_DIR, "uptime_history.json")

os.makedirs(APP_DIR, exist_ok=True)


def run_command(command):
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return ""


def get_current_uptime():
    output = run_command(["uptime", "-s"])

    if not output:
        return timedelta(0)

    try:
        boot_time = datetime.strptime(output, "%Y-%m-%d %H:%M:%S")
        return datetime.now() - boot_time
    except Exception:
        return timedelta(0)


def format_duration(seconds):
    seconds = int(max(0, seconds))

    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    if days:
        return f"{days}d {hours}h {minutes}m"
    elif hours:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def get_boot_time():
    output = run_command(["uptime", "-s"])

    try:
        return datetime.strptime(output, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now()


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}

    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def update_history():
    history = load_history()

    now = datetime.now()
    boot = get_boot_time()

    current_date = now.date()

    # Record uptime for every day touched by the current boot session.
    day = boot.date()

    while day <= current_date:

        day_start = datetime.combine(day, datetime.min.time())
        day_end = day_start + timedelta(days=1)

        start = max(boot, day_start)
        end = min(now, day_end)

        if end > start:
            seconds = (end - start).total_seconds()

            key = day.isoformat()

            previous = history.get(key, 0)

            # Do not allow the value to become larger than 24 hours.
            history[key] = min(
                86400,
                max(previous, int(seconds))
            )

        day += timedelta(days=1)

    # Keep approximately 90 days of history.
    cutoff = current_date - timedelta(days=90)

    history = {
        date: value
        for date, value in history.items()
        if datetime.strptime(date, "%Y-%m-%d").date() >= cutoff
    }

    save_history(history)

    return history


def get_days(history, days):
    today = datetime.now().date()

    labels = []
    values = []

    for i in range(days - 1, -1, -1):
        date = today - timedelta(days=i)

        labels.append(date.strftime("%a\n%d"))

        values.append(
            history.get(date.isoformat(), 0) / 3600
        )

    return labels, values


class UptimeDashboard:

    def __init__(self, root):

        self.root = root

        self.root.title("Parrot OS Uptime Dashboard")
        self.root.geometry("1000x700")
        self.root.minsize(800, 600)

        self.history = update_history()

        self.create_interface()

        self.refresh()

    def create_interface(self):

        # Header
        header = tk.Frame(
            self.root,
            padx=20,
            pady=15
        )

        header.pack(fill="x")

        title = tk.Label(
            header,
            text="PARROT OS UPTIME",
            font=("Sans", 22, "bold")
        )

        title.pack(side="left")

        self.current_label = tk.Label(
            header,
            text="",
            font=("Sans", 13)
        )

        self.current_label.pack(side="right")

        # Statistics
        stats = tk.Frame(
            self.root,
            padx=20,
            pady=5
        )

        stats.pack(fill="x")

        self.today_var = tk.StringVar()
        self.week_var = tk.StringVar()
        self.month_var = tk.StringVar()

        self.create_stat(
            stats,
            "TODAY",
            self.today_var
        )

        self.create_stat(
            stats,
            "LAST 7 DAYS",
            self.week_var
        )

        self.create_stat(
            stats,
            "LAST 30 DAYS",
            self.month_var
        )

        # Buttons
        controls = tk.Frame(
            self.root,
            padx=20,
            pady=10
        )

        controls.pack(fill="x")

        self.period = tk.IntVar(value=7)

        ttk.Radiobutton(
            controls,
            text="7 Days",
            variable=self.period,
            value=7,
            command=self.refresh_chart
        ).pack(side="left", padx=5)

        ttk.Radiobutton(
            controls,
            text="30 Days",
            variable=self.period,
            value=30,
            command=self.refresh_chart
        ).pack(side="left", padx=5)

        ttk.Button(
            controls,
            text="Refresh",
            command=self.refresh
        ).pack(side="right")

        # Chart
        chart_frame = tk.Frame(
            self.root,
            padx=20,
            pady=5
        )

        chart_frame.pack(
            fill="both",
            expand=True
        )

        self.figure = Figure(
            figsize=(10, 5),
            dpi=100
        )

        self.ax = self.figure.add_subplot(111)

        self.canvas = FigureCanvasTkAgg(
            self.figure,
            master=chart_frame
        )

        self.canvas.get_tk_widget().pack(
            fill="both",
            expand=True
        )

        # Footer
        self.status = tk.Label(
            self.root,
            text="",
            anchor="w",
            padx=20,
            pady=8
        )

        self.status.pack(fill="x")

    def create_stat(self, parent, title, variable):

        frame = tk.Frame(
            parent,
            padx=20,
            pady=10
        )

        frame.pack(
            side="left",
            expand=True,
            fill="x"
        )

        tk.Label(
            frame,
            text=title,
            font=("Sans", 9)
        ).pack()

        tk.Label(
            frame,
            textvariable=variable,
            font=("Sans", 16, "bold")
        ).pack()

    def refresh(self):

        self.history = update_history()

        uptime = get_current_uptime()

        self.current_label.config(
            text=f"Current uptime: {format_duration(uptime.total_seconds())}"
        )

        today = self.history.get(
            datetime.now().date().isoformat(),
            0
        )

        last_7 = 0
        last_30 = 0

        today_date = datetime.now().date()

        for i in range(7):
            date = today_date - timedelta(days=i)

            last_7 += self.history.get(
                date.isoformat(),
                0
            )

        for i in range(30):
            date = today_date - timedelta(days=i)

            last_30 += self.history.get(
                date.isoformat(),
                0
            )

        self.today_var.set(
            format_duration(today)
        )

        self.week_var.set(
            format_duration(last_7)
        )

        self.month_var.set(
            format_duration(last_30)
        )

        self.refresh_chart()

        self.status.config(
            text=f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # Automatically refresh every minute.
        self.root.after(
            60000,
            self.refresh
        )

    def refresh_chart(self):

        days = self.period.get()

        labels, values = get_days(
            self.history,
            days
        )

        self.ax.clear()

        x = range(len(labels))

        self.ax.bar(
            x,
            values
        )

        self.ax.set_title(
            f"System Uptime — Last {days} Days"
        )

        self.ax.set_ylabel(
            "Uptime (hours)"
        )

        self.ax.set_xlabel(
            "Day"
        )

        self.ax.set_xticks(
            list(x)
        )

        self.ax.set_xticklabels(
            labels
        )

        self.ax.set_ylim(
            0,
            24
        )

        self.ax.grid(
            axis="y",
            alpha=0.25
        )

        self.figure.tight_layout()

        self.canvas.draw()


def main():

    root = tk.Tk()

    app = UptimeDashboard(root)

    root.mainloop()


if __name__ == "__main__":
    main()
