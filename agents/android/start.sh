#!/data/data/com.termux/files/usr/bin/sh
# Start the HomeMonitor Android/Termux agent.
#
# First run:
#   bash agents/android/start.sh --controller http://CONTROLLER_IP:8787 \
#       --pairing-code ABCD-1234 --name "Android phone"
#
# Later runs only need:
#   bash agents/android/start.sh
set -u

export HOME="${HOME:-/data/data/com.termux/files/home}"
export LD_LIBRARY_PATH="/data/data/com.termux/files/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="/data/data/com.termux/files/usr/bin:/system/bin:/system/xbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${HOMEMONITOR_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
AGENT="$PROJECT_DIR/agent/android_agent.py"

if [ ! -f "$AGENT" ]; then
  echo "android_agent.py not found at $AGENT" >&2
  echo "Extract the complete release or set HOMEMONITOR_DIR." >&2
  exit 2
fi
if ! command -v python >/dev/null 2>&1; then
  echo "Python is not installed. Inside Termux run: pkg install -y python" >&2
  exit 2
fi

cd "$PROJECT_DIR" || exit 1
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock >/dev/null 2>&1 || true
fi

exec python "$AGENT" "$@"
