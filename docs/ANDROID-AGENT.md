# Android agent

The Android agent is a single-file, standard-library Python program for Termux. It does
not use `psutil`, root or a native Android app. It reads what Android exposes through
`/proc`, `/sys`, `getprop`, `df` and optional Termux:API commands.

**Supported:** Android 5.0+ with Termux from F-Droid and Python 3.8+. Validated on
Android 13 and older Android/Fire OS hardware with the v1.0 agent. Android
13+ hides some `/proc` values; missing values are reported as unavailable.

## Prepare the device

1. Install **Termux** and **Termux:Boot** from F-Droid:
   - <https://f-droid.org/packages/com.termux/>
   - <https://f-droid.org/packages/com.termux.boot/>
   Do not use an old Play Store build.
2. Open Termux:Boot once, then close it.
3. Disable battery optimisation for Termux and Termux:Boot:
   **Settings -> Apps -> Termux -> Battery -> Unrestricted** (wording varies).
   If your vendor has "put unused apps to sleep", exclude Termux.
4. Optional but recommended for SSID/battery details: install **Termux:API** from F-Droid
   and grant location permission.

## Install

Copy or download the HomeMonitor release to the phone. In Termux:

```bash
termux-setup-storage
cd ~
tar -xzf ~/storage/downloads/HomeMonitor-1.0.0.tar.gz
cd HomeMonitor-1.0.0
pkg update -y
pkg install -y python termux-api
bash agents/android/setup.sh
```

The setup script:

- checks that it is running inside Termux and that Python 3.8+ is available;
- creates `~/.termux/boot/homemonitor-agent.sh`, which acquires a wake lock and restarts
  the agent if it exits;
- warns if Termux:Boot or Termux:API is missing;
- prints the exact next command.

Pair and start:

```bash
bash agents/android/start.sh \
  --controller http://192.0.2.10:8787 \
  --pairing-code ABCD-1234 \
  --name "Android phone"
```

Approve the device in the dashboard. The agent saves its token to
`~/.config/homemonitor/android_agent.json` and keeps this foreground process running.
The boot script handles the next reboot.

## Commands

```bash
# Start with saved config (after pairing)
bash agents/android/start.sh

# Find controllers on the LAN
python agent/android_agent.py --discover

# Print one metrics sample without networking
python agent/android_agent.py --once

# Run in the foreground with verbose logging
python agent/android_agent.py --controller http://192.0.2.10:8787 --verbose

# Test the boot script without rebooting
sh ~/.termux/boot/homemonitor-agent.sh &
```

Agent options: `--config`, `--controller`, `--pairing-code`, `--name`, `--discover`,
`--once`, `--verbose`.

Environment variables: `HOMEMONITOR_PAIRING_CODE` is read by the agent; `HOMEMONITOR_DIR`
overrides the project directory for `start.sh`.

## Files

| Item | Location |
| --- | --- |
| Project | The extracted release folder |
| Agent | `agent/android_agent.py` |
| Config/token | `~/.config/homemonitor/android_agent.json` |
| Agent log | `~/.config/homemonitor/android_agent.log` |
| Boot supervisor log | `~/homemonitor-agent.log` |
| Boot script | `~/.termux/boot/homemonitor-agent.sh` |

`android_agent.json` contains a device token. Do not copy it to another phone.

## What is collected

- CPU utilisation (from `/proc/stat` when readable), cores and frequency.
- Memory used/total from `/proc/meminfo`.
- Storage for the data partition via `statvfs`/`df`.
- Network counters from `/proc/net/dev` when readable; SSID/signal via Termux:API when
  available.
- Battery percentage/status, temperature and voltage from `/sys/class/power_supply`
  where exposed; obviously fake TV-box battery nodes are suppressed.
- Uptime, load average, Android version/model via `getprop`.
- Top processes if `/proc` allows it.

Fields Android hides are omitted or `null`. The agent never invents zero values.

## Auto-start and battery behaviour

The boot script is started by Termux:Boot after reboot. It acquires a wake lock and
restarts the agent every 15 seconds if it exits. This is best effort: Android vendors can
still kill background processes.

- Keep the device on mains power for an always-on agent.
- Disable battery optimisation for Termux and Termux:Boot.
- Lock Termux in the recent-apps list if your vendor supports it.
- After a reboot, allow up to two minutes before assuming failure.
- A missing Termux:Boot install is the most common reason the agent does not return.

## Limitations

- Android 13+ may hide `/proc/stat` and `/proc/net/dev`; CPU/network can be unavailable.
- SSID requires location permission, Termux:API and a ROM that exposes it.
- Some devices report dummy battery/temperature values; the agent filters obvious cases.
- Doze mode and vendor battery managers can delay or stop heartbeats.
- There is no native Android app; Termux must remain installed.
- The optional Android Lite viewer is separate and read-only; see
  [android-lite/README.md](../android-lite/README.md).

## Uninstall

From the project folder in Termux:

```bash
bash agents/android/uninstall.sh
```

This stops the agent, removes the boot script and deletes the saved token, and releases
the wake lock. It leaves the project files and `~/homemonitor-agent.log`. Delete them
manually if desired:

```bash
rm -rf ~/HomeMonitor-1.0.0 ~/homemonitor-agent.log
```

The device remains in the controller database; revoke or delete it in the dashboard.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| "must run inside Termux" | Use the Termux app from F-Droid; do not run from adb shell |
| `python: not found` | `pkg install -y python` |
| "not paired yet" | Pass `--pairing-code` on the first run |
| Pending | Approve in the dashboard |
| No CPU/network | Android 13+ `/proc` restriction; check the log |
| SSID unavailable | Termux:API + location permission; not all ROMs expose it |
| Stops after reboot | Termux:Boot installed/opened, battery unrestricted, boot script exists |
| Stops when screen off | Wake lock, battery optimisation, vendor app killer |

More: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
