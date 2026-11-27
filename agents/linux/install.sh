#!/usr/bin/env bash
# Install the HomeMonitor desktop agent as a systemd service on Ubuntu, Debian
# or Linux Mint. The same Python agent is used on all three distributions; this
# installer owns the distro-specific package manager and service integration.
#
# Usage (from a git clone or extracted release):
#   sudo bash agents/linux/install.sh \
#     --controller http://CONTROLLER_IP:8787 \
#     --pairing-code ABCD-1234 \
#     --name "Living Room PC"
#
# Re-run without --pairing-code after the first successful pairing to update
# files or repair the service. Use --no-start to install without enabling the
# service, and --install-deps to let apt install python3-venv/python3-psutil.
set -euo pipefail

INSTALL_DIR="/opt/homemonitor-agent"
DATA_DIR="/var/lib/homemonitor-agent"
SERVICE_USER="homemonitor-agent"
SERVICE_NAME="homemonitor-agent"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SOURCE_DIR="${HOMEMONITOR_SOURCE_DIR:-}"
CONTROLLER="${HOMEMONITOR_CONTROLLER:-}"
PAIRING_CODE="${HOMEMONITOR_PAIRING_CODE:-}"
DEVICE_NAME="${HOMEMONITOR_NAME:-}"
REQUIRED_DISTRO=""
INSTALL_DEPS=0
NO_START=0
DRY_RUN=0
FORCE_PAIR=0

usage() {
  cat <<'EOF'
Install the HomeMonitor agent on Ubuntu, Debian or Linux Mint.

Options:
  --controller URL       Controller base URL, e.g. http://192.0.2.10:8787
  --pairing-code CODE    One-time code shown by the controller
  --name NAME            Friendly device name (default: hostname)
  --source DIR           Directory containing agent/ and common/
  --install-dir DIR      Default: /opt/homemonitor-agent
  --data-dir DIR         Default: /var/lib/homemonitor-agent
  --service-user USER    Default: homemonitor-agent
  --require-distro ID    Fail unless /etc/os-release ID or ID_LIKE matches
  --install-deps         Use apt-get to install python3-venv and python3-psutil
  --force-pair           Re-pair even when the saved config already has a token
  --no-start             Install files but do not enable/start the service
  --dry-run              Validate inputs and print planned actions
  -h, --help             Show this help

Environment variables with the same purpose:
  HOMEMONITOR_CONTROLLER, HOMEMONITOR_PAIRING_CODE, HOMEMONITOR_NAME,
  HOMEMONITOR_SOURCE_DIR
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --controller) CONTROLLER="${2:-}"; shift 2 ;;
    --pairing-code) PAIRING_CODE="${2:-}"; shift 2 ;;
    --name) DEVICE_NAME="${2:-}"; shift 2 ;;
    --source) SOURCE_DIR="${2:-}"; shift 2 ;;
    --install-dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --data-dir) DATA_DIR="${2:-}"; shift 2 ;;
    --service-user) SERVICE_USER="${2:-}"; shift 2 ;;
    --require-distro) REQUIRED_DISTRO="${2:-}"; shift 2 ;;
    --install-deps) INSTALL_DEPS=1; shift ;;
    --force-pair) FORCE_PAIR=1; shift ;;
    --no-start) NO_START=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

[ "$(id -u)" -eq 0 ] || die "Run this installer with sudo."
[ -r /etc/os-release ] || die "Cannot read /etc/os-release; this is not a supported Linux host."
# shellcheck disable=SC1091
. /etc/os-release
DISTRO_ID="${ID:-unknown}"
DISTRO_LIKE="${ID_LIKE:-}"
DISTRO_VERSION="${VERSION_ID:-unknown}"
DISTRO_PRETTY="${PRETTY_NAME:-$DISTRO_ID}"

matches_distro() {
  local wanted="$1"
  [ "$DISTRO_ID" = "$wanted" ] && return 0
  case " $DISTRO_LIKE " in *" $wanted "*) return 0 ;; esac
  return 1
}

if [ -n "$REQUIRED_DISTRO" ] && ! matches_distro "$REQUIRED_DISTRO"; then
  die "This package targets $REQUIRED_DISTRO, but the host reports $DISTRO_PRETTY."
fi

case "$DISTRO_ID" in
  ubuntu|debian|linuxmint) ;;
  *)
    if ! matches_distro ubuntu && ! matches_distro debian; then
      die "Unsupported distribution '$DISTRO_PRETTY'. Supported: Ubuntu, Debian, Linux Mint."
    fi
    say "WARNING: '$DISTRO_PRETTY' is not an officially validated distribution; continuing as a derivative."
    ;;
esac

if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
  die "systemd is not running. This installer requires systemd for auto-start."
fi

if ! command -v python3 >/dev/null 2>&1; then
  die "python3 is missing. Install Python 3.10+ first (apt-get install python3)."
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  die "Python 3.10 or newer is required; found $(python3 --version 2>&1)."
fi

if [ -z "$SOURCE_DIR" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  for candidate in "$SCRIPT_DIR/../.." "$SCRIPT_DIR" "$PWD"; do
    if [ -f "$candidate/agent/__main__.py" ] && [ -f "$candidate/common/protocol.py" ]; then
      SOURCE_DIR="$(cd "$candidate" && pwd)"
      break
    fi
  done
fi
[ -n "$SOURCE_DIR" ] || die "Could not locate agent/ and common/. Pass --source DIR."
[ -f "$SOURCE_DIR/agent/__main__.py" ] || die "Missing $SOURCE_DIR/agent/__main__.py"
[ -f "$SOURCE_DIR/common/protocol.py" ] || die "Missing $SOURCE_DIR/common/protocol.py"
[ -f "$SOURCE_DIR/requirements-agent.txt" ] || die "Missing $SOURCE_DIR/requirements-agent.txt"

if [ -z "$CONTROLLER" ]; then
  if [ -s "$DATA_DIR/agent.json" ]; then
    say "Using the controller URL already saved in $DATA_DIR/agent.json"
  else
    die "Pass --controller http://CONTROLLER_IP:8787 (or set HOMEMONITOR_CONTROLLER)."
  fi
else
  case "$CONTROLLER" in
    http://*|https://*) ;;
    *) CONTROLLER="http://$CONTROLLER" ;;
  esac
fi

if [ -z "$DEVICE_NAME" ]; then
  DEVICE_NAME="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo 'Linux PC')"
fi

say "HomeMonitor agent installer"
say "  Distribution : $DISTRO_PRETTY ($DISTRO_VERSION)"
say "  Source       : $SOURCE_DIR"
say "  Install dir  : $INSTALL_DIR"
say "  Data dir     : $DATA_DIR"
say "  Service user : $SERVICE_USER"
say "  Device name  : $DEVICE_NAME"
[ -n "$CONTROLLER" ] && say "  Controller   : $CONTROLLER"
[ -n "$PAIRING_CODE" ] && say "  Pairing      : enabled (code is not written to the service file)"

if [ "$DRY_RUN" -eq 1 ]; then
  say "Dry run complete. No files were changed."
  exit 0
fi

if [ "$INSTALL_DEPS" -eq 1 ]; then
  say "Installing Python packaging dependencies with apt-get..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y python3-venv python3-psutil >/dev/null
else
  python3 -c 'import venv' >/dev/null 2>&1 || die "python3-venv is missing. Re-run with --install-deps or install it with apt."
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  say "Creating system user $SERVICE_USER..."
  useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -m 0755 "$INSTALL_DIR"
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR"
rm -rf "$INSTALL_DIR/agent" "$INSTALL_DIR/common"
cp -a "$SOURCE_DIR/agent" "$INSTALL_DIR/agent"
cp -a "$SOURCE_DIR/common" "$INSTALL_DIR/common"
cp -a "$SOURCE_DIR/requirements-agent.txt" "$INSTALL_DIR/requirements-agent.txt"
install -m 0644 "$SOURCE_DIR/agents/linux/homemonitor-agent.service" "$SERVICE_FILE"
chown -R root:root "$INSTALL_DIR"
chmod -R go-w "$INSTALL_DIR"

if [ ! -x "$INSTALL_DIR/.venv/bin/python" ]; then
  say "Creating the Python virtual environment..."
  python3 -m venv --system-site-packages "$INSTALL_DIR/.venv"
fi

if ! "$INSTALL_DIR/.venv/bin/python" -c 'import psutil; assert tuple(map(int, psutil.__version__.split(".")[:2])) >= (5, 9)' >/dev/null 2>&1; then
  say "Installing psutil into the virtual environment..."
  "$INSTALL_DIR/.venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir 'psutil>=5.9'
fi
(cd "$INSTALL_DIR" && "$INSTALL_DIR/.venv/bin/python" - <<'PY'
import psutil
from agent.platform_linux import distribution
info = distribution()
print(f"psutil {psutil.__version__} ready; detected {info['name']}")
PY
)

PAIR_COMMAND="$INSTALL_DIR/.venv/bin/python -m agent --config $DATA_DIR/agent.json --controller $CONTROLLER --name $(printf '%q' "$DEVICE_NAME")"
ALREADY_PAIRED=0
if [ -s "$DATA_DIR/agent.json" ] && python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); raise SystemExit(0 if isinstance(d.get("token"), str) and d["token"] else 1)' "$DATA_DIR/agent.json" 2>/dev/null; then
  ALREADY_PAIRED=1
fi

if [ -n "$PAIRING_CODE" ] && { [ "$ALREADY_PAIRED" -eq 0 ] || [ "$FORCE_PAIR" -eq 1 ]; }; then
  say "Pairing the device with the controller..."
  if ! run sudo -u "$SERVICE_USER" env HOME="$DATA_DIR" PYTHONPATH="$INSTALL_DIR" \
      "$INSTALL_DIR/.venv/bin/python" -m agent \
      --config "$DATA_DIR/agent.json" \
      --controller "$CONTROLLER" \
      --pairing-code "$PAIRING_CODE" \
      --name "$DEVICE_NAME" \
      --pair-only; then
    die "Pairing failed. Check the controller URL and pairing code, then re-run."
  fi
  say "Approve '$DEVICE_NAME' in the controller dashboard."
elif [ "$ALREADY_PAIRED" -eq 1 ]; then
  say "Existing paired configuration found; skipping pairing (use --force-pair to replace it)."
elif [ -n "$PAIRING_CODE" ]; then
  die "A pairing code was supplied but the existing config could not be read. Remove $DATA_DIR/agent.json or use --force-pair."
else
  say "No pairing code supplied. Files were installed, but the service was not started."
  say "Pair first, then enable the service:"
  say "  sudo -u $SERVICE_USER env HOME=$DATA_DIR $PAIR_COMMAND --pairing-code CODE --pair-only"
  say "  sudo systemctl enable --now $SERVICE_NAME"
  exit 0
fi

if [ "$NO_START" -eq 1 ]; then
  say "Service installed but not started (--no-start)."
  say "  sudo systemctl enable --now $SERVICE_NAME"
  exit 0
fi

say "Enabling and starting $SERVICE_NAME..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"
sleep 2
systemctl --no-pager --lines=8 status "$SERVICE_NAME" || true

cat <<EOF

Installation complete.

  Service : $SERVICE_NAME
  Config  : $DATA_DIR/agent.json
  Log     : $DATA_DIR/logs/agent.log
  Status  : sudo systemctl status $SERVICE_NAME
  Logs    : sudo journalctl -u $SERVICE_NAME -f

Approve the device in the dashboard if it is still pending. The agent retries
automatically and will start on every boot.
EOF
