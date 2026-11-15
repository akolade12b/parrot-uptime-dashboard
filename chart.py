"""Matplotlib chart rendering for the dashboard.

Draws a per-day uptime bar chart (0-24h) from the daily-uptime entries
produced by :mod:`uptime`.  The palette adapts to light/dark desktop themes
so the chart looks native under either MATE appearance, and it handles any
range length — a week, a month, or a year of history — by thinning the
x-axis labels accordingly.
"""

from __future__ import annotations

import config

# Light / dark palettes.  A single brand-neutral green accent reads well on
# both backgrounds.
_LIGHT = {
    "figure": "#ffffff",
    "axes": "#ffffff",
    "text": "#1f2328",
    "muted": "#6a737d",
    "grid": "#e3e6ea",
    "bar": "#1f8a70",
    "bar_top": "#2ea382",
    "off": "#d0d7de",
    "unknown": "#c7ccd1",
}
_DARK = {
    "figure": "#1e1f22",
    "axes": "#1e1f22",
    "text": "#e6e6e6",
    "muted": "#9aa0a6",
    "grid": "#33353a",
    "bar": "#3fb27f",
    "bar_top": "#55c395",
    "off": "#3a3b3f",
    "unknown": "#45464b",
}


def palette(dark: bool) -> dict:
    return _DARK if dark else _LIGHT


def _x_labels(daily: list) -> list:
    """Sparse x-axis labels adapted to however many bars there are.

    A week shows weekday names; a month shows day numbers; a year thins down
    to month abbreviations so the labels never crowd each other.
    """
    n = len(daily)
    if n <= 1:
        return [d["datetime"].strftime("%a %b %d") for d in daily]
    if n <= 7:
        return [d["datetime"].strftime("%a") for d in daily]

    step = max(1, n // 12)
    if n <= 62:
        fmt = "%d"
    elif n <= 200:
        fmt = "%b %d"
    else:
        fmt = "%b"
    labels = []
    for i, d in enumerate(daily):
        labels.append(d["datetime"].strftime(fmt) if i % step == 0 else "")
    return labels


def render(fig, daily: list, dark: bool, scale: float = 1.0) -> None:
    """Draw the uptime bar chart onto ``fig``.

    ``daily`` is the list from uptime.daily_uptime()/daily_uptime_between().
    ``scale`` scales fonts so the chart stays readable as the window grows.
    """
    p = palette(dark)
    fig.patch.set_facecolor(p["figure"])
    fig.clear()
    ax = fig.add_subplot(111)
    ax.set_facecolor(p["axes"])

    n = len(daily)
    x = list(range(n))
    hours = [min(d["seconds"], config.SECONDS_PER_DAY) / 3600.0 for d in daily]

    bar_colors = []
    for d in daily:
        if d["has_data"]:
            bar_colors.append(p["bar"])
        elif d["covered"]:
            bar_colors.append(p["off"])
        else:
            bar_colors.append(p["unknown"])

    width = 0.8 if n <= 7 else 0.72
    ax.bar(x, hours, color=bar_colors, width=width, zorder=3,
           edgecolor="none")

    # Small value labels above bars that actually have uptime.  Skipped for
    # long ranges where they would overlap into an unreadable mess.
    if n <= 40:
        for i, d in enumerate(daily):
            if d["has_data"] and d["seconds"] > 0:
                label = f"{d['seconds'] / 3600.0:.1f}"
                ax.text(i, hours[i] + 0.4, label, ha="center", va="bottom",
                        fontsize=9 * scale, color=p["muted"])

    ax.set_ylim(0, 24)
    ax.set_yticks([0, 4, 8, 12, 16, 20, 24])
    ax.set_ylabel("Hours", color=p["muted"], fontsize=10 * scale)
    ax.set_xticks(x)
    ax.set_xticklabels(_x_labels(daily), color=p["text"], fontsize=10 * scale)

    ax.tick_params(colors=p["muted"], length=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(p["grid"])

    ax.grid(axis="y", color=p["grid"], linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    # (The section header above the chart is a themed tk label in app.py,
    # so no in-figure title is needed here.)

    fig.tight_layout(pad=1.2)
