#!/usr/bin/env bash
# Remove the HomeMonitor central server installed by server/install-linux.sh.
#
#   sudo bash server/uninstall-linux.sh           # keep database and credentials
#   sudo bash server/uninstall-linux.sh --purge   # delete all server data
set -euo pipefail

INSTALL_DIR="/opt/homemonitor"
DATA_DIR="/var/lib/homemonitor"
SERVICE_NAME="homemonitor-controller"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_DIR="/etc/homemonitor"
SERVICE_USER="homemonitor"
PURGE=0

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

case "${1:-}" in
  --purge) PURGE=1 ;;
  -h|--help)
    echo "Usage: sudo bash server/uninstall-linux.sh [--purge]"
    exit 0
    ;;
  "") ;;
  *) die "Unknown option: $1" ;;
esac

[ "$(id -u)" -eq 0 ] || die "Run this uninstaller with sudo."

if command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
fi
rm -f "$SERVICE_FILE"
if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true
fi
rm -rf "$INSTALL_DIR"

if [ "$PURGE" -eq 1 ]; then
  rm -rf "$DATA_DIR" "$ENV_DIR"
  if id "$SERVICE_USER" >/dev/null 2>&1; then
    userdel "$SERVICE_USER" 2>/dev/null || true
  fi
  say "Removed the server, service, configuration, database and system user."
else
  say "Removed the server and service. Data remains in $DATA_DIR."
  say "Configuration remains in $ENV_DIR/server.env."
  say "Run with --purge to delete the database, admin token and pairing code."
fi
