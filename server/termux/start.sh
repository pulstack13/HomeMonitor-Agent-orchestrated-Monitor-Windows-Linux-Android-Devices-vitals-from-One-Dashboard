#!/data/data/com.termux/files/usr/bin/sh
# Run the HomeMonitor controller in the foreground inside Termux.
set -eu

export HOME="${HOME:-/data/data/com.termux/files/home}"
export LD_LIBRARY_PATH="/data/data/com.termux/files/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="/data/data/com.termux/files/usr/bin:/system/bin:/system/xbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${HOMEMONITOR_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
DATA_DIR="${HOMEMONITOR_DATA_DIR:-$HOME/.local/share/homemonitor}"

if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock >/dev/null 2>&1 || true
  trap 'termux-wake-unlock >/dev/null 2>&1 || true' EXIT INT TERM
fi

cd "$PROJECT_DIR" || exit 1
exec python -m server --data-dir "$DATA_DIR" "$@"
