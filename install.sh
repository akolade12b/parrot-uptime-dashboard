#!/usr/bin/env bash
#
# Installer for Parrot Uptime Dashboard.
#
# What it does (all as the current user, no root required except optionally
# installing missing distro packages):
#   1. Checks Python and its GUI dependencies.
#   2. Creates the data directory and initialises the SQLite database.
#   3. Installs a desktop launcher for the MATE menu.
#   4. Installs and starts the background tracker as a systemd *user* service.
#   5. Optionally (with --autostart) enables launch at login.
#
set -euo pipefail

APP_NAME="Parrot Uptime Dashboard"
APP_ID="parrot-uptime-dashboard"
SERVICE_NAME="${APP_ID}-tracker"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/${APP_ID}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

info() { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]   \033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[error]  \033[0m %s\n' "$*" >&2; }

AUTOSTART=0
for arg in "$@"; do
  case "$arg" in
    --autostart) AUTOSTART=1 ;;
    -h|--help)
      echo "Usage: $0 [--autostart]"
      echo "  --autostart   also launch the dashboard when you log in to MATE"
      exit 0 ;;
    *) err "Unknown argument: $arg"; exit 2 ;;
  esac
done

# --- 1. Python ------------------------------------------------------------
info "Checking Python..."
if ! command -v python3 >/dev/null 2>&1; then
  err "python3 was not found on PATH."
  exit 1
fi
PYTHON_BIN="$(command -v python3)"
info "Using Python: $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"

# --- 2. Dependencies ------------------------------------------------------
info "Checking Python dependencies..."
MISSING=""
if ! "$PYTHON_BIN" -c "import tkinter" 2>/dev/null; then MISSING="$MISSING python3-tk"; fi
if ! "$PYTHON_BIN" -c "import matplotlib" 2>/dev/null; then MISSING="$MISSING python3-matplotlib"; fi
if [ -n "$MISSING" ]; then
  warn "Missing packages:$MISSING"
  if command -v sudo >/dev/null 2>&1; then
    read -rp "  Install them now with sudo apt? [y/N] " ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
      sudo apt-get update && sudo apt-get install -y $MISSING
    else
      warn "Skipping package install; the GUI may not start until they are installed."
    fi
  else
    warn "Install manually with:  sudo apt install$MISSING"
  fi
else
  info "All Python dependencies present (tkinter + matplotlib)."
fi

# --- 3. Directories + database -------------------------------------------
info "Creating data directory: $DATA_DIR"
mkdir -p "$DATA_DIR" "$APPS_DIR" "$SYSTEMD_USER_DIR"

info "Initialising SQLite database..."
"$PYTHON_BIN" - "$SCRIPT_DIR" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[1])
import database
database.init_db()
print("  database ready (schema version", database.schema_version(), ")")
PYEOF

# --- 4. Desktop launcher --------------------------------------------------
info "Installing desktop launcher..."
DESKTOP_FILE="$APPS_DIR/$APP_ID.desktop"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=View system uptime history
Exec=$PYTHON_BIN $SCRIPT_DIR/app.py
Icon=$SCRIPT_DIR/assets/$APP_ID.svg
Terminal=false
Categories=System;Monitor;
Keywords=uptime;system;monitor;boot;
StartupNotify=false
EOF
chmod +x "$DESKTOP_FILE"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi
info "Launcher written: $DESKTOP_FILE"

# --- 5. systemd user service (background tracker) -------------------------
info "Installing background tracker as a systemd user service..."
UNIT_FILE="$SYSTEMD_USER_DIR/$SERVICE_NAME.service"
cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Parrot Uptime Dashboard background tracker
After=default.target

[Service]
Type=simple
ExecStart=$PYTHON_BIN $SCRIPT_DIR/tracker.py
Restart=on-failure
RestartSec=30
Nice=15

[Install]
WantedBy=default.target
EOF

if systemctl --user daemon-reload 2>/dev/null; then
  systemctl --user enable --now "$SERVICE_NAME.service" 2>/dev/null || \
    warn "Could not enable the tracker service (no systemd user session?)."
  info "Tracker service installed and started."
else
  warn "No systemd user session detected; the tracker service is written to:"
  warn "  $UNIT_FILE"
  warn "It will start automatically on your next login."
fi

# --- 6. Autostart (optional) ----------------------------------------------
if [ "$AUTOSTART" -eq 1 ]; then
  info "Enabling MATE autostart..."
  mkdir -p "$AUTOSTART_DIR"
  cp "$DESKTOP_FILE" "$AUTOSTART_DIR/$APP_ID.desktop"
  warn "Autostart enabled: the dashboard will open when you log in."
  warn "To disable it later, run:  rm -f $AUTOSTART_DIR/$APP_ID.desktop"
else
  info "Autostart NOT enabled (pass --autostart to enable it)."
fi

echo
info "Installation complete."
info "Launch the GUI:          $PYTHON_BIN $SCRIPT_DIR/app.py"
info "From the MATE menu:      System -> $APP_NAME"
info "Tracker service status:  systemctl --user status $SERVICE_NAME"
