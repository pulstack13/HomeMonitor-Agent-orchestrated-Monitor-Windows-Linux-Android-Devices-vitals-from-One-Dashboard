#!/usr/bin/env bash
# Install the HomeMonitor central server as a systemd service on Ubuntu,
# Debian or Linux Mint.
#
# Usage (from a git clone or extracted release):
#   sudo bash server/install-linux.sh
#   sudo bash server/install-linux.sh --port 8787 --bind 0.0.0.0
#
# The server has no third-party Python dependencies and stores its data in
# /var/lib/homemonitor. It listens on the LAN by default. Do not port-forward it.
set -euo pipefail

INSTALL_DIR="/opt/homemonitor"
DATA_DIR="/var/lib/homemonitor"
SERVICE_USER="homemonitor"
SERVICE_NAME="homemonitor-controller"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_DIR="/etc/homemonitor"
ENV_FILE="$ENV_DIR/server.env"
BIND_ADDRESS="0.0.0.0"
HTTP_PORT="8787"
NO_START=0
INSTALL_DEPS=0
SOURCE_DIR="${HOMEMONITOR_SOURCE_DIR:-}"

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

while [ "$#" -gt 0 ]; do
  case "$1" in
    --bind) BIND_ADDRESS="${2:-}"; shift 2 ;;
    --port) HTTP_PORT="${2:-}"; shift 2 ;;
    --source) SOURCE_DIR="${2:-}"; shift 2 ;;
    --install-deps) INSTALL_DEPS=1; shift ;;
    --no-start) NO_START=1; shift ;;
    -h|--help)
      cat <<'EOF'
Install the HomeMonitor central server.

  --bind ADDRESS      HTTP bind address (default: 0.0.0.0)
  --port PORT         HTTP port (default: 8787)
  --source DIR        Directory containing server/ and common/
  --install-deps      Use apt-get to install python3 if missing
  --no-start          Install but do not start the service
EOF
      exit 0
      ;;
    *) die "Unknown option: $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "Run this installer with sudo."
[ -r /etc/os-release ] || die "Cannot read /etc/os-release."
# shellcheck disable=SC1091
. /etc/os-release
DISTRO_PRETTY="${PRETTY_NAME:-${ID:-Linux}}"

if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
  die "systemd is not running. This installer requires systemd."
fi

if ! command -v python3 >/dev/null 2>&1; then
  if [ "$INSTALL_DEPS" -eq 1 ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y python3 >/dev/null
  else
    die "python3 is missing. Install it first or re-run with --install-deps."
  fi
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  die "Python 3.10 or newer is required; found $(python3 --version 2>&1)."
fi

if [ -z "$SOURCE_DIR" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  for candidate in "$SCRIPT_DIR/.." "$SCRIPT_DIR" "$PWD"; do
    if [ -f "$candidate/server/__main__.py" ] && [ -f "$candidate/common/protocol.py" ]; then
      SOURCE_DIR="$(cd "$candidate" && pwd)"
      break
    fi
  done
fi
[ -n "$SOURCE_DIR" ] || die "Could not locate server/ and common/. Pass --source DIR."
[ -f "$SOURCE_DIR/server/__main__.py" ] || die "Missing $SOURCE_DIR/server/__main__.py"
[ -f "$SOURCE_DIR/common/protocol.py" ] || die "Missing $SOURCE_DIR/common/protocol.py"
[ -d "$SOURCE_DIR/dashboard" ] || die "Missing $SOURCE_DIR/dashboard"

case "$HTTP_PORT" in
  ''|*[!0-9]*) die "Port must be a number." ;;
esac
[ "$HTTP_PORT" -ge 1 ] && [ "$HTTP_PORT" -le 65535 ] || die "Port must be 1-65535."

say "HomeMonitor server installer"
say "  Distribution : $DISTRO_PRETTY"
say "  Source       : $SOURCE_DIR"
say "  Install dir  : $INSTALL_DIR"
say "  Data dir     : $DATA_DIR"
say "  Listen       : $BIND_ADDRESS:$HTTP_PORT"

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  say "Creating system user $SERVICE_USER..."
  useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -m 0755 "$INSTALL_DIR"
install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR"
install -d -m 0755 "$INSTALL_DIR/server" "$INSTALL_DIR/common" "$INSTALL_DIR/dashboard"
rm -rf "$INSTALL_DIR/server/controller" "$INSTALL_DIR/common" "$INSTALL_DIR/dashboard"
cp -a "$SOURCE_DIR/server/." "$INSTALL_DIR/server/"
cp -a "$SOURCE_DIR/common/." "$INSTALL_DIR/common/"
cp -a "$SOURCE_DIR/dashboard/." "$INSTALL_DIR/dashboard/"
cp -a "$SOURCE_DIR/LICENSE" "$INSTALL_DIR/LICENSE" 2>/dev/null || true
cp -a "$SOURCE_DIR/README.md" "$INSTALL_DIR/README.md" 2>/dev/null || true
chown -R root:root "$INSTALL_DIR"
chmod -R go-w "$INSTALL_DIR"

install -d -m 0750 "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<EOF
# HomeMonitor central server configuration.
# Restart after editing: sudo systemctl restart $SERVICE_NAME
HOMEMONITOR_HOST=$BIND_ADDRESS
HOMEMONITOR_PORT=$HTTP_PORT
HOMEMONITOR_DISCOVERY=1
# Generate a token with: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# HOMEMONITOR_ADMIN_TOKEN=
EOF
  chmod 600 "$ENV_FILE"
else
  say "Keeping existing $ENV_FILE"
fi

install -m 0644 "$SOURCE_DIR/server/homemonitor-controller.service" "$SERVICE_FILE"
systemctl daemon-reload

if [ "$NO_START" -eq 1 ]; then
  say "Installed but not started (--no-start)."
  say "  sudo systemctl enable --now $SERVICE_NAME"
  exit 0
fi

systemctl enable "$SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"
sleep 2
systemctl --no-pager --lines=8 status "$SERVICE_NAME" || true

ADMIN_TOKEN=""
PAIRING_CODE=""
if [ -f "$DATA_DIR/config.json" ]; then
  ADMIN_TOKEN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("admin_token", ""))' "$DATA_DIR/config.json" 2>/dev/null || true)"
fi
if [ -f "$DATA_DIR/pairing_code.txt" ]; then
  PAIRING_CODE="$(tr -d '\r\n' < "$DATA_DIR/pairing_code.txt")"
fi

ADDRESSES="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' | grep -v '^127\.' || true)"
cat <<EOF

HomeMonitor server is running.

  Dashboard : http://${BIND_ADDRESS}:${HTTP_PORT}/
EOF
if [ -n "$ADDRESSES" ]; then
  for address in $ADDRESSES; do
    echo "              http://$address:$HTTP_PORT/"
  done
fi
cat <<EOF
  Admin token: ${ADMIN_TOKEN:-see $DATA_DIR/config.json}
  Pair code  : ${PAIRING_CODE:-see $DATA_DIR/pairing_code.txt}
  Data       : $DATA_DIR
  Config     : $ENV_FILE
  Logs       : sudo journalctl -u $SERVICE_NAME -f

Open the dashboard from a device on the same LAN. Keep this service on a
trusted network; do not expose it directly to the internet.
EOF
