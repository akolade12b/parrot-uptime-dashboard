#!/usr/bin/env bash
#
# Uninstaller for Parrot Uptime Dashboard.
#
# Removes the desktop launcher, the background tracker service, and the
# autostart entry.  Historical uptime data is only deleted after asking.
# The application files themselves (this directory) are left in place so you
# can reinstall easily -- see the note at the end.
#
set -euo pipefail

APP_ID="parrot-uptime-dashboard"
SERVICE_NAME="${APP_ID}-tracker"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/${APP_ID}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

info() { printf '\033[1;34m[uninstall]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }

# --- 1. Stop and remove the tracker service ------------------------------
info "Stopping and removing the tracker service..."
systemctl --user disable --now "$SERVICE_NAME.service" 2>/dev/null || true
rm -f "$SYSTEMD_USER_DIR/$SERVICE_NAME.service"
systemctl --user daemon-reload 2>/dev/null || true
info "Tracker service removed."

# --- 2. Remove desktop launcher ------------------------------------------
info "Removing desktop launcher..."
rm -f "$APPS_DIR/$APP_ID.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi
info "Desktop launcher removed."

# --- 3. Remove autostart entry -------------------------------------------
if [ -e "$AUTOSTART_DIR/$APP_ID.desktop" ]; then
  info "Removing autostart entry..."
  rm -f "$AUTOSTART_DIR/$APP_ID.desktop"
fi

# --- 4. Historical data (ask first) --------------------------------------
if [ -d "$DATA_DIR" ]; then
  read -rp "Delete historical uptime data at $DATA_DIR? [y/N] " ans
  if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
    rm -rf "$DATA_DIR"
    info "Historical data deleted."
  else
    info "Historical data kept at: $DATA_DIR"
  fi
else
  info "No historical data directory present."
fi

echo
info "Uninstall complete."
info "The application files in $SCRIPT_DIR were left in place."
info "To remove them too:  rm -rf $SCRIPT_DIR"
