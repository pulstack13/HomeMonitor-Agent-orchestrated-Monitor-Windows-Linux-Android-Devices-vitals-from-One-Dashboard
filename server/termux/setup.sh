#!/data/data/com.termux/files/usr/bin/sh
# Prepare an Android/Termux device as the HomeMonitor central server.
#
# Usage:
#   pkg install -y python
#   bash server/termux/setup.sh
#   bash server/termux/start.sh
#
# For automatic start after reboot install Termux:Boot from F-Droid and open it once.
set -eu

export HOME="${HOME:-/data/data/com.termux/files/home}"
export LD_LIBRARY_PATH="/data/data/com.termux/files/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="/data/data/com.termux/files/usr/bin:/system/bin:/system/xbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_DIR="${HOMEMONITOR_DATA_DIR:-$HOME/.local/share/homemonitor}"
LAUNCHER="$PROJECT_DIR/server/termux/start.sh"
BOOT_DIR="$HOME/.termux/boot"
BOOT_SCRIPT="$BOOT_DIR/homemonitor-controller.sh"

if [ -z "${PREFIX:-}" ] || [ ! -d "$PREFIX" ]; then
  echo "This script must run inside Termux." >&2
  exit 1
fi
if [ ! -f "$PROJECT_DIR/server/__main__.py" ]; then
  echo "Missing server package. Extract the complete release first." >&2
  exit 1
fi
if ! command -v python >/dev/null 2>&1; then
  echo "Python is not installed. Run: pkg install -y python" >&2
  exit 1
fi
if ! python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)'; then
  echo "Python 3.8 or newer is required; found $(python --version 2>&1)." >&2
  exit 1
fi

mkdir -p "$BOOT_DIR" "$DATA_DIR"
chmod 700 "$LAUNCHER" 2>/dev/null || true

cat > "$BOOT_SCRIPT" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
export HOME="$HOME"
export PATH="/data/data/com.termux/files/usr/bin:/system/bin:/system/xbin"
export LD_LIBRARY_PATH="/data/data/com.termux/files/usr/lib"
export HOMEMONITOR_DATA_DIR="$DATA_DIR"
termux-wake-lock >/dev/null 2>&1 || true
while true; do
  "$LAUNCHER" >> "\$HOME/homemonitor-controller.log" 2>&1
  echo "[\$(date)] controller exited; restarting in 15s" >> "\$HOME/homemonitor-controller.log"
  sleep 15
done
EOF
chmod 700 "$BOOT_SCRIPT"

PACKAGES="$(pm list packages 2>/dev/null | tr -d '\r' || true)"
if [ -n "$PACKAGES" ] && ! printf '%s\n' "$PACKAGES" | grep -q 'com.termux.boot'; then
  echo "Warning: Termux:Boot is not installed; the controller will not start after reboot." >&2
fi

cat <<EOF

HomeMonitor controller is prepared.

  Project : $PROJECT_DIR
  Data    : $DATA_DIR
  Boot    : $BOOT_SCRIPT
  Log     : $HOME/homemonitor-controller.log

Start it now:

  bash "$LAUNCHER"

The first start prints the dashboard URL, admin token and pairing code. Keep the
device on mains power and disable battery optimisation for Termux/Termux:Boot.
EOF
