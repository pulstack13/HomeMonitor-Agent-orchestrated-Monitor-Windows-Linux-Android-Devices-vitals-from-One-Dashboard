# Platform support and validation

HomeMonitor uses the same controller and protocol everywhere, but "the code runs" is not
the same as "this platform was tested". This page records both.

## Status legend

| Label | Meaning |
| --- | --- |
| **Validated** | Exercised on real hardware for the v1.0 feature set, including the listed install path |
| **Implemented** | Code and installer exist and pass automated checks, but real-hardware validation is incomplete |
| **Experimental** | Optional component; expect rough edges and verify before relying on it |
| **Not supported** | No official path; reports are welcome but no compatibility promise |

Automated checks do not prove that systemd, the Windows startup folder or an Android
vendor's battery manager behaves correctly. Reports from real machines are valuable.

## Matrix

| Platform / version | Controller | Desktop agent | Android agent | Notes |
| --- | --- | --- | --- | --- |
| Windows 11 | **Validated** | **Validated** | - | Original v1.0 deployment, physical hardware |
| Windows 10 22H2+ | Implemented | Implemented | - | Same Python/psutil code path; not independently validated |
| Ubuntu 22.04 / 24.04 / 24.10 / 25.04 | Implemented | Implemented | - | systemd installer + apt; not hardware-validated in this tree |
| Debian 12 / 13 | Implemented | Implemented | - | systemd installer + apt; not hardware-validated in this tree |
| Linux Mint 21.x / 22.x | Implemented | Implemented | - | Ubuntu derivative; not independently validated |
| Other systemd Debian/Ubuntu derivatives | Implemented (best effort) | Implemented (best effort) | - | Installer warns and continues; no support claim |
| Android 13 phone (Termux) | Implemented | - | **Validated** | v1.0 agent tested; Android restricts some `/proc` values |
| Android 7.1 phone/tablet (Termux) | **Validated** | - | **Validated** | Original low-power controller/agent hardware |
| Fire OS 5.1 TV device (Termux) | **Validated** | - | **Validated** | Original deployment; slow boot, allow up to 2 minutes |
| Android 5.0+ | - | - | Experimental | Termux Python availability and vendor limits vary |
| Android Lite viewer | - | - | - | Compiled; optional and experimental |
| macOS | Not supported | Not supported | - | No packaged installer or validation |
| WSL (without systemd) | Implemented manually | Implemented manually | - | Packaged systemd installers refuse to run |
| Containers without systemd | Manual only | Manual only | - | No boot integration |
| Routers / NAS appliances | Not supported | Not supported | - | No router firmware agent |

## What "implemented" means for Linux

The Linux agent is not a renamed Windows binary. It is the same Python package with
platform-specific collectors and a native service integration:

- `agent/collector.py` reads CPU, memory, disk, network, temperature and process data via
  `psutil` and `/proc`/`/sys`.
- `agent/platform_linux.py` parses `/etc/os-release`, detects systemd/OpenRC/SysV and the
  package manager, and reports whether the distribution/version is in the validated set.
- `agents/linux/install.sh` creates a dedicated system user, a virtual environment, the
  service unit, config/data directories and a pairing-only registration.
- `agents/linux/ubuntu/install.sh`, `debian/install.sh` and `linuxmint/install.sh` enforce
  the expected distribution family and add apt dependency handling.

The public tree's automated tests cover the parser, service layout, shell syntax and
protocol code. A real systemd boot test is still required before a Linux distribution is
marked **Validated**.

### Linux versions recognized by the detector

| Distribution | Recognized versions |
| --- | --- |
| Ubuntu | 22.04, 24.04, 24.10, 25.04 |
| Debian | 12, 13 |
| Linux Mint | 21, 21.1, 21.2, 21.3, 22, 22.1 |

These are detection hints, not a hard gate. Newer point releases normally report the same
major version. The installer checks the distribution family, while the agent reports
whether the exact version is in the validated set.

## What "implemented" means for Windows 10

The Windows installer and agent use documented Windows APIs through Python and `psutil`:

- Per-user install under `%LOCALAPPDATA%`.
- Per-user startup folder shortcut (sign-in, not pre-login service).
- `pythonw.exe` background process and rotating log.
- Windows network probes via `ipconfig`/`netsh`/`psutil`.

Windows 10 22H2 with current Python 3.10+ is expected to work, but this release was only
validated on Windows 11 hardware. If you test Windows 10, include the edition/build,
Python version and installer output in a report.

## Android agent scope

The Android agent is a single standard-library file (`agent/android_agent.py`) and uses:

- `/proc/stat`, `/proc/meminfo`, `/proc/net/dev`, `/sys/class/thermal`, `statvfs` and
  `getprop` where accessible.
- Termux:API commands for SSID/battery when installed.
- A wake lock and Termux:Boot supervisor for persistence.

Known Android restrictions:

- Android 13+ may hide `/proc/stat` and `/proc/net/dev` from normal apps, so CPU
  utilisation and network throughput can be unavailable.
- Some devices expose a dummy battery node (especially TV boxes); the agent suppresses
  obviously meaningless values.
- SSID requires location permission and a ROM that exposes it to Termux.
- Vendor battery managers can kill background apps regardless of wake locks. Disable
  optimisation for Termux and Termux:Boot.

The agent never claims a missing value is zero; it reports the field as unavailable.

## Installer footprints

| Component | Install location | Data/config | Service |
| --- | --- | --- | --- |
| Windows server | `%LOCALAPPDATA%\HomeMonitor\Server` | `%LOCALAPPDATA%\HomeMonitor\ServerData` | User sign-in shortcut |
| Windows agent | `%LOCALAPPDATA%\HomeMonitor\Agent` | `%APPDATA%\HomeMonitor` | User sign-in shortcut |
| Linux server | `/opt/homemonitor` | `/var/lib/homemonitor`, `/etc/homemonitor/server.env` | `homemonitor-controller.service` |
| Linux agent | `/opt/homemonitor-agent` | `/var/lib/homemonitor-agent` | `homemonitor-agent.service` |
| Termux server | Project folder | `~/.local/share/homemonitor` | Termux:Boot script |
| Android agent | Project folder | `~/.config/homemonitor` | Termux:Boot script |
| Android Lite | Installed APK | WebView cookie only | None |

## Ports and protocols

| Port | Protocol | Direction | Purpose |
| --- | --- | --- | --- |
| 8787 | TCP | Agent/browser -> controller | HTTP dashboard and API |
| 45892 | UDP | Agent -> controller broadcast | Optional discovery |
| Ephemeral | TCP | Agent -> controller | Outbound requests, no inbound agent port |

No UPnP, NAT traversal, cloud relay or inbound agent listener is used.

## Hardware guidance

| Role | Minimum | Recommended |
| --- | --- | --- |
| Controller on Windows/Linux | Dual-core 1 GHz, 512 MB RAM, 250 MB disk | Any always-on mini PC/NAS-class machine |
| Controller on Android/Termux | Android 5.0+, 1 GB RAM, 500 MB free, mains power | Android 7-13 phone/box with unrestricted Termux |
| Desktop agent | Python 3.10+, 100 MB disk, 30 MB RAM | Any supported desktop |
| Android agent | Termux Python 3.8+, 100 MB free | Device with Termux:Boot and battery exemption |

Database growth depends on `retention_days`, the number of devices and the metrics
interval. A few devices at the default five-second cadence are small (a few MB per week);
reduce retention or increase the interval for very low-storage devices.

## Reporting a platform result

Open an issue titled `Platform report: <OS> <version> <component>` with:

- Distribution/edition and version.
- Hardware model (remove serial numbers).
- Python version.
- Install method and exact command.
- Whether the service started at boot and survived a reboot.
- Relevant log lines with tokens, IPs, SSIDs and names redacted.
- Whether the packaged installer or a source checkout was used.

Please do not attach real databases, `agent.json`, `config.json`, keystores or screenshots
that show tokens or pairing codes.
