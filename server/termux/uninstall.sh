#!/data/data/com.termux/files/usr/bin/sh
# Remove the HomeMonitor controller start script from Termux.
# --purge also deletes the database, admin token and pairing code.
set -eu

export HOME="${HOME:-/data/data/com.termux/files/home}"
export PATH="/data/data/com.termux/files/usr/bin:/system/bin:/system/xbin"

DATA_DIR="${HOMEMONITOR_DATA_DIR:-$HOME/.local/share/homemonitor}"
BOOT_SCRIPT="$HOME/.termux/boot/homemonitor-controller.sh"

pkill -f 'python -m server' 2>/dev/null || true
pkill -f 'python -m controller' 2>/dev/null || true
rm -f "$BOOT_SCRIPT"

case "${1:-}" in
  --purge)
    rm -rf "$DATA_DIR"
    echo "Removed the controller boot script and data directory ($DATA_DIR)."
    ;;
  -h|--help)
    echo "Usage: bash server/termux/uninstall.sh [--purge]"
    ;;
  "")
    echo "Removed the controller boot script. Data remains in $DATA_DIR."
    echo "Run with --purge to delete the database and credentials."
    ;;
  *)
    echo "Unknown option: $1" >&2
    exit 2
    ;;
esac
