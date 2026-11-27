#!/data/data/com.termux/files/usr/bin/sh
# Prepare an Android/Termux device as a HomeMonitor agent.
#
# Usage inside Termux:
#   pkg install -y python termux-api
#   bash agents/android/setup.sh
#   bash agents/android/start.sh --controller http://CONTROLLER_IP:8787 \
#       --pairing-code ABCD-1234 --name "Android phone"
#
# Install Termux:Boot from F-Droid and open it once for automatic start after reboot.
set -eu

export HOME="${HOME:-/data/data/com.termux/files/home}"
export LD_LIBRARY_PATH="/data/data/com.termux/files/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="/data/data/com.termux/files/usr/bin:/system/bin:/system/xbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
AGENT="$PROJECT_DIR/agent/android_agent.py"
LAUNCHER="$PROJECT_DIR/agents/android/start.sh"
BOOT_DIR="$HOME/.termux/boot"
BOOT_SCRIPT="$BOOT_DIR/homemonitor-agent.sh"

if [ -z "${PREFIX:-}" ] || [ ! -d "$PREFIX" ]; then
  echo "This script must run inside Termux." >&2
  exit 1
fi
if [ ! -f "$AGENT" ]; then
  echo "Missing $AGENT. Extract the complete release first." >&2
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

chmod 700 "$LAUNCHER" 2>/dev/null || true
mkdir -p "$BOOT_DIR"

cat > "$BOOT_SCRIPT" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
export HOME="$HOME"
export PATH="/data/data/com.termux/files/usr/bin:/system/bin:/system/xbin"
export LD_LIBRARY_PATH="/data/data/com.termux/files/usr/lib"
termux-wake-lock >/dev/null 2>&1 || true
while true; do
  "$LAUNCHER" >> "\$HOME/homemonitor-agent.log" 2>&1
  echo "[\$(date)] agent exited; restarting in 15s" >> "\$HOME/homemonitor-agent.log"
  sleep 15
done
EOF
chmod 700 "$BOOT_SCRIPT"

PACKAGES="$(pm list packages 2>/dev/null | tr -d '\r' || true)"
if [ -n "$PACKAGES" ] && ! printf '%s\n' "$PACKAGES" | grep -q 'com.termux.boot'; then
  echo "Warning: Termux:Boot is not installed; the agent will not start after reboot." >&2
fi
if ! command -v termux-wifi-connectioninfo >/dev/null 2>&1; then
  echo "Optional: install Termux:API (app + 'pkg install -y termux-api') for SSID and battery."
fi

cat <<EOF

HomeMonitor Android agent is prepared.

  Project : $PROJECT_DIR
  Python  : $(python --version 2>&1)
  Boot    : $BOOT_SCRIPT
  Log     : $HOME/homemonitor-agent.log
  Config  : $HOME/.config/homemonitor/android_agent.json

Pair this device once:

  cd "$PROJECT_DIR"
  bash agents/android/start.sh --controller http://CONTROLLER_IP:8787 \\
      --pairing-code CODE --name "Android phone"

Approve it in the dashboard. After that the boot script starts it automatically.
Test the boot script without rebooting:

  sh "$BOOT_SCRIPT" &
EOF
