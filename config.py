"""Central configuration for Parrot Uptime Dashboard.

Holds application identity, data-directory paths, and schema version.
No sensitive data is stored anywhere; the app works fully offline.
"""

import os
from pathlib import Path

APP_NAME = "Parrot Uptime Dashboard"
APP_ID = "parrot-uptime-dashboard"
VERSION = "1.0.0"

# Database schema version. Bumped whenever the schema changes so the
# database module can migrate (or refuse) gracefully.
SCHEMA_VERSION = 1

SECONDS_PER_DAY = 86400

# Tracker polling interval in seconds. 60s is a good balance: the tracker
# stays responsive to boot/reboot detection while consuming essentially
# no CPU (a single time.sleep between ticks).
TRACKER_INTERVAL = 60
# How often the tracker re-syncs with journalctl / `last` (seconds).
TRACKER_RECONCILE_INTERVAL = 10 * 60


def _default_data_dir() -> Path:
    """Return the XDG data directory, defaulting to ~/.local/share."""
    home = Path.home()
    base = os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share"))
    return Path(base) / APP_ID


DATA_DIR = _default_data_dir()
DB_PATH = DATA_DIR / "uptime.db"
LOG_PATH = DATA_DIR / "tracker.log"


def ensure_data_dir() -> Path:
    """Create (if needed) and return the data directory."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
