#!/usr/bin/env bash
# Remove the HomeMonitor agent installed by agents/linux/install.sh.
#
#   sudo bash agents/linux/uninstall.sh           # keep config and logs
#   sudo bash agents/linux/uninstall.sh --purge   # delete config and history
set -euo pipefail

INSTALL_DIR="/opt/homemonitor-agent"
DATA_DIR="/var/lib/homemonitor-agent"
SERVICE_NAME="homemonitor-agent"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SERVICE_USER="homemonitor-agent"
PURGE=0

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

case "${1:-}" in
  --purge) PURGE=1 ;;
  -h|--help)
    echo "Usage: sudo bash agents/linux/uninstall.sh [--purge]"
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
  rm -rf "$DATA_DIR"
  if id "$SERVICE_USER" >/dev/null 2>&1; then
    userdel "$SERVICE_USER" 2>/dev/null || true
  fi
  say "Removed the agent, service, config, logs and system user."
else
  say "Removed the agent and service. Config/logs remain in $DATA_DIR."
  say "Run with --purge to remove them (this also deletes the saved device token)."
fi
