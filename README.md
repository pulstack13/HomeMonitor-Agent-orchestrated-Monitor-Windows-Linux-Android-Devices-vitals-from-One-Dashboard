# HomeMonitor

HomeMonitor is a self-hosted, LAN-only monitor for a small home network. Lightweight
agents report CPU, memory, disk, network, battery and temperature data to a central
controller. The controller stores history in SQLite and serves a live dashboard with no
cloud account, external CDN, telemetry or public port.

**Version:** 1.0.0  
**License:** [MIT](LICENSE)  
**Default ports:** TCP 8787 (HTTP dashboard/API), UDP 45892 (optional discovery)

> HomeMonitor is designed for a trusted home LAN. It serves plain HTTP by default and has
> no built-in TLS or internet-facing authentication. Read [Security](#security) before
> exposing anything outside your network.

## What you get

- A central controller built on the Python standard library, with SQLite history,
  retention, events and alerts.
- A responsive dashboard and a minimal `/lite` view for phones.
- A Windows agent with a one-click installer and per-user auto-start.
- Ubuntu, Debian and Linux Mint agents installed as hardened systemd services.
- An Android/Termux agent that runs on old and new Android devices without psutil.
- A Termux server install path for an always-on Android phone or TV box.
- UDP discovery, pairing-code registration, dashboard approval, per-device bearer
  tokens, revoke and delete.
- An optional Android Lite WebView viewer for a controller running on the same phone.

## Architecture

```text
+--------------------------+          HTTP (trusted LAN)          +---------------------------+
| Windows / Linux agent    |  register, heartbeat, metrics, ACK   | Controller                |
| Python + psutil          | -----------------------------------> | ThreadingHTTPServer       |
| systemd / Startup folder | <----------------------------------- | SQLite (WAL) + SSE broker |
+--------------------------+       intervals, approval state      +-------------+-------------+
                                                                                 |
+--------------------------+          same HTTP API                             |
| Android/Termux agent     | ------------------------------------+              |
| Python standard library  |                                     |              |
+--------------------------+                                     |              |
                                                                 v              v
                                                    +------------------+  +------------------+
                                                    | Browser dashboard|  | /lite phone view |
                                                    | HTML/CSS/JS      |  | HTML/CSS/JS      |
                                                    +------------------+  +------------------+
```

The server has no third-party runtime dependencies. The Windows/Linux agent needs
`psutil`; the Android agent is a single standard-library file.

## Validation status

This repository distinguishes code that has been exercised on real hardware from code
that is implemented but not yet validated on a particular distribution. Please read
[docs/PLATFORMS.md](docs/PLATFORMS.md) for the full matrix.

| Target | Component | Status |
| --- | --- | --- |
| Windows 11 | Server + desktop agent | Validated on physical hardware in the v1.0 deployment |
| Windows 10 (22H2+) | Server + desktop agent | Implemented; same code path as Windows 11, not independently validated |
| Ubuntu 24.04 | Desktop agent + systemd installer | Implemented; unit/shell validation only in this tree |
| Debian 12/13 | Desktop agent + systemd installer | Implemented; unit/shell validation only in this tree |
| Linux Mint 22 | Desktop agent + systemd installer | Implemented as an Ubuntu derivative; not independent hardware validation |
| Android 13 / Termux | Android agent | Validated on Android 13 hardware with the v1.0 agent |
| Android 7.1 / Fire OS 5.1 | Android agent + Termux server | Validated on the original low-power deployment hardware |
| Android 5.0+ | Optional Lite viewer | Compiled; previously used on an older Android device; optional |

Linux installation has not been claimed as hardware-validated just because the shared
Python code is tested. Run [docs/TESTING.md](docs/TESTING.md) on your distribution and
open an issue with the result.

## Requirements

### Controller

- Python **3.10+** (standard library only).
- Any always-on Windows PC, Linux machine, Android phone/tablet or TV box running Termux.
- Suggested minimum: dual-core 1 GHz, 512 MB RAM, 250 MB free disk for the application
  and the default retention window. A small network uses a few MB of database per week.
- TCP 8787 reachable from the LAN. UDP 45892 is optional and used only for discovery.
- A trusted private network and a way to back up the data directory.

### Desktop agent

- Windows 10/11 or Ubuntu/Debian/Linux Mint with systemd.
- Python **3.10+**.
- `psutil` 5.9 or newer.
- Optional: `nvidia-ml-py` for NVIDIA telemetry, `WMI` plus LibreHardwareMonitor for
  Windows CPU temperature.
- Outbound access to the controller only. No inbound ports.

### Android agent

- Android 5.0+ with [Termux](https://f-droid.org/packages/com.termux/) from F-Droid.
- Python 3.8+ (`pkg install python`).
- Termux:Boot for automatic start after reboot; Termux:API is optional for SSID/battery
  details on devices that expose them.
- Battery optimisation disabled for Termux and Termux:Boot.

## Quick start

The complete beginner walkthrough, including expected output, is
**[docs/COMPLETE_SETUP_GUIDE.md](docs/COMPLETE_SETUP_GUIDE.md)**. The short version:

### 1. Start the controller

**Windows** (current user, starts at sign-in):

```powershell
.\server\windows\Install HomeMonitor Server.cmd
```

**Ubuntu / Debian / Linux Mint** (systemd, starts at boot):

```bash
sudo bash server/install-linux.sh
```

**Android / Termux** (starts after reboot with Termux:Boot):

```bash
pkg install -y python
bash server/termux/setup.sh
bash server/termux/start.sh
```

The first start prints the dashboard URL, an admin token and a pairing code. Keep the
token private. It is also stored in the server data directory:

- Windows: `%LOCALAPPDATA%\HomeMonitor\ServerData\config.json`
- Linux: `/var/lib/homemonitor/config.json`
- Termux: `~/.local/share/homemonitor/config.json`

Verify the server:

```text
GET http://CONTROLLER_IP:8787/healthz
{"service":"homemonitor","version":"1.0.0","schema":1,...}
```

### 2. Open the dashboard

Browse to `http://CONTROLLER_IP:8787/`, paste the admin token and approve new devices
from the overview banner or **Settings -> Device access**.

### 3. Install an agent

Replace the example address (`192.0.2.10`) and code with the values printed by your
controller.

**Windows** (no administrator rights):

```powershell
.\agents\windows\Install HomeMonitor Agent.cmd
```

or unattended:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\agents\windows\install.ps1 `
  -Controller http://192.0.2.10:8787 -PairingCode ABCD-1234 -Name "Living Room PC"
```

**Ubuntu / Debian / Linux Mint** (systemd):

```bash
sudo bash agents/linux/ubuntu/install.sh \
  --controller http://192.0.2.10:8787 \
  --pairing-code ABCD-1234 \
  --name "Living Room PC"
```

Use `agents/linux/debian/install.sh` or `agents/linux/linuxmint/install.sh` for those
distributions, or `agents/linux/install.sh` on a compatible derivative.

**Android / Termux**:

```bash
pkg install -y python termux-api
bash agents/android/setup.sh
bash agents/android/start.sh \
  --controller http://192.0.2.10:8787 \
  --pairing-code ABCD-1234 \
  --name "Android phone"
```

Approve the device in the dashboard. Metrics begin after approval; heartbeats and
approval checks continue automatically.

## Repository layout

```text
HomeMonitor/
|-- agent/                    Desktop agent, Android agent and Linux detection
|-- agents/
|   |-- windows/              Windows installer, uninstaller and helper launchers
|   |-- linux/                Shared Linux installer + Ubuntu/Debian/Mint entry points
|   `-- android/              Termux setup, start and uninstall scripts
|-- common/                   Wire protocol and network probes shared by agents/server
|-- dashboard/                Full dashboard and /lite static assets
|-- android-lite/             Optional signed WebView viewer (source only)
|-- server/                   Controller package, systemd unit, Windows and Termux installers
|-- docs/                     Setup, architecture, protocol, API, testing and release docs
|-- examples/                 Safe configuration and API examples
|-- scripts/                  Packaging, validation and secret-scanning tools
|-- tests/                    unittest suite
|-- .github/workflows/        CI, shell/PowerShell checks, packaging validation
|-- .env.example              Documented environment variables
|-- requirements-agent.txt    psutil for the desktop agent
`-- LICENSE
```

## Configuration

### Server

Environment variables and command-line flags are equivalent; flags win when both are
present. See [.env.example](.env.example).

| Setting | Default | Purpose |
| --- | --- | --- |
| `HOMEMONITOR_DATA_DIR` / `--data-dir` | `./data` | SQLite, tokens, pairing code and logs |
| `HOMEMONITOR_HOST` / `--host` | `0.0.0.0` | HTTP bind address |
| `HOMEMONITOR_PORT` / `--port` | `8787` | HTTP port |
| `HOMEMONITOR_DISCOVERY` / `--no-discovery` | enabled | UDP discovery on 45892 |
| `HOMEMONITOR_ADMIN_TOKEN` | generated | Override the dashboard token |
| `HOMEMONITOR_PAIRING_CODE` | generated | Override the persisted pairing code |
| `HOMEMONITOR_DASHBOARD_DIR` | `./dashboard` | Static dashboard location for packaging |

The pairing code can be regenerated from the dashboard. The admin token is not shown in
the dashboard; read it from `config.json` or set it before first start.

Dashboard settings (Settings page or `PUT /api/v1/settings`):

| Setting | Default | Bounds |
| --- | --- | --- |
| `heartbeat_interval` | 5 s | 2-60 s |
| `metrics_interval` | 5 s | 2-60 s |
| `offline_after` | 15 s | 10-300 s |
| `retention_days` | 7 | 1-90 days |
| `events_retention_days` | 30 | 1-180 days |

### Agent

The agent stores `controller_url`, `device_id`, `token`, `name`, `heartbeat_interval`,
`metrics_interval` and `auto_discover` in `agent.json`. Command-line and environment
variables override the URL, name and pairing code for that run.

- Windows config: `%APPDATA%\HomeMonitor\agent.json`
- Linux config: `/var/lib/homemonitor-agent/agent.json` when installed with the
  systemd installer, or `~/.config/homemonitor/agent.json` when run manually
- Android config: `~/.config/homemonitor/android_agent.json` inside Termux
- Logs: a rotated `logs/agent.log` next to the desktop config, or
  `android_agent.log` next to the Android config

If the controller address changes, update the config (or re-run the installer with the
new `--controller` value and `--force-pair`) and approve the device again.

## Documentation

- **[Complete setup guide](docs/COMPLETE_SETUP_GUIDE.md)** - beginner walkthrough from a
  blank PC/phone to a working dashboard, with expected output and uninstall steps.
- [Platform support and validation](docs/PLATFORMS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Wire protocol](docs/PROTOCOL.md)
- [HTTP API](docs/API.md)
- [Windows agent](docs/WINDOWS-AGENT.md)
- [Linux agent](docs/LINUX-AGENT.md)
- [Android agent](docs/ANDROID-AGENT.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Remote access guidance](docs/REMOTE-ACCESS.md)
- [Testing and validation](docs/TESTING.md)
- [Release preparation](docs/RELEASE.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## Security

- LAN-only by default. Do not port-forward the controller to the internet.
- The dashboard token is exchanged for an HttpOnly, SameSite=Strict cookie. The cookie
  has no `Secure` flag because the default transport is plain HTTP on a trusted LAN.
- Device tokens are random 256-bit values; the controller stores only SHA-256 hashes.
- Pairing codes are short-lived secrets. Regenerate one after onboarding and do not post
  screenshots that include it.
- Every static asset is served locally. The dashboard has a restrictive Content Security
  Policy and no external scripts, fonts or images.
- There is no built-in TLS, user account system or multi-user role model. For remote
  access, use a VPN or a TLS reverse proxy with additional authentication; see
  [docs/REMOTE-ACCESS.md](docs/REMOTE-ACCESS.md).

Report vulnerabilities as described in [SECURITY.md](SECURITY.md). Never include real
tokens, pairing codes, keystores, database files or personal IP addresses in an issue.

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m compileall -q agent common server tests
python -m server --data-dir ./data-dev --port 8788 --no-discovery
```

The test suite uses `unittest`, needs no network, and covers the protocol, database,
HTTP API, agents, Linux detection, installers and dashboard path handling. See
[docs/TESTING.md](docs/TESTING.md) for the validation commands used for this release.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first, keep real
credentials out of commits, and include the output of the relevant tests. Platform
reports are especially useful: state the distribution/version, Python version and
whether the packaged installer or a source checkout was used.

## License

MIT. See [LICENSE](LICENSE).

HomeMonitor is an independent project. Android, Windows, Ubuntu, Debian, Linux Mint,
Termux and other names are trademarks of their respective owners.
