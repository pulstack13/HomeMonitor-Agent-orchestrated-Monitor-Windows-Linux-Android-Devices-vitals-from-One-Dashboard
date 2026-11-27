#!/data/data/com.termux/files/usr/bin/sh
# Stop and remove the HomeMonitor Android/Termux agent from this device.
# This does not delete the device from the controller database.
set -eu

export HOME="${HOME:-/data/data/com.termux/files/home}"
export PATH="/data/data/com.termux/files/usr/bin:/system/bin:/system/xbin"

BOOT_SCRIPT="$HOME/.termux/boot/homemonitor-agent.sh"
CONFIG_DIR="$HOME/.config/homemonitor"

pkill -f 'agent/android_agent.py' 2>/dev/null || true
rm -f "$BOOT_SCRIPT"
rm -f "$CONFIG_DIR/android_agent.json"

if command -v termux-wake-unlock >/dev/null 2>&1; then
  termux-wake-unlock >/dev/null 2>&1 || true
fi

echo "Removed the agent boot script, stopped the process and deleted the saved token."
echo "The project files and log remain. Delete $HOME/homemonitor-agent.log manually if desired."
