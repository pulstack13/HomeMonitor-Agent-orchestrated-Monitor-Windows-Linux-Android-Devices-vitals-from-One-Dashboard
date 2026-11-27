#!/usr/bin/env bash
# Linux Mint entry point. The shared Linux installer performs the actual work.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="$HERE/../install.sh"
[ -f "$INSTALLER" ] || { echo "Missing shared installer: $INSTALLER" >&2; exit 1; }

if [ "$(id -u)" -ne 0 ]; then
  exec sudo -- bash "$INSTALLER" --require-distro linuxmint --install-deps "$@"
fi
exec bash "$INSTALLER" --require-distro linuxmint --install-deps "$@"
