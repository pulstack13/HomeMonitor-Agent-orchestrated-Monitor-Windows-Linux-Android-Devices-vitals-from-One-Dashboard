# Linux agent

The Linux agent is the same Python package as the Windows agent, with Linux collection
and a hardened systemd service. Package entry points exist for Ubuntu, Debian and Linux
Mint; other systemd Debian/Ubuntu derivatives can use the generic installer.

**Status:** implemented and covered by unit/shell checks. Real systemd installation was not
validated in the public build session. See [PLATFORMS.md](PLATFORMS.md).

## Requirements

- Ubuntu 22.04/24.04/24.10/25.04, Debian 12/13, Linux Mint 21.x/22.x, or a compatible
  systemd Debian/Ubuntu derivative.
- Python 3.10+ with `venv`.
- `systemd` as PID 1.
- `sudo` for installation.
- Outbound access to the controller. No inbound port.

Containers and WSL without systemd are not supported by the packaged service installer;
run the agent manually there.

## Install

From the extracted release folder:

**Ubuntu:**

```bash
sudo bash agents/linux/ubuntu/install.sh \
  --controller http://192.0.2.10:8787 \
  --pairing-code ABCD-1234 \
  --name "Living Room PC"
```

**Debian:**

```bash
sudo bash agents/linux/debian/install.sh \
  --controller http://192.0.2.10:8787 \
  --pairing-code ABCD-1234 \
  --name "Living Room PC"
```

**Linux Mint:**

```bash
sudo bash agents/linux/linuxmint/install.sh \
  --controller http://192.0.2.10:8787 \
  --pairing-code ABCD-1234 \
  --name "Living Room PC"
```

**Other systemd Debian/Ubuntu derivative:**

```bash
sudo bash agents/linux/install.sh \
  --controller http://192.0.2.10:8787 \
  --pairing-code ABCD-1234 \
  --name "Living Room PC"
```

The wrappers add `--require-distro <id> --install-deps`, so apt installs
`python3-venv`/`python3-psutil` when needed. The installer refuses to continue if the
detected distribution family does not match.

## Installer options

| Option | Default | Meaning |
| --- | --- | --- |
| `--controller URL` | env `HOMEMONITOR_CONTROLLER` | Controller base URL |
| `--pairing-code CODE` | env `HOMEMONITOR_PAIRING_CODE` | One-time pairing code |
| `--name NAME` | hostname | Friendly device name |
| `--source DIR` | installer's project root | Directory containing `agent/` and `common/` |
| `--install-dir DIR` | `/opt/homemonitor-agent` | Program files |
| `--data-dir DIR` | `/var/lib/homemonitor-agent` | Config, token, logs |
| `--service-user USER` | `homemonitor-agent` | Dedicated system user |
| `--require-distro ID` | none | Fail unless `/etc/os-release` ID/ID_LIKE matches |
| `--install-deps` | off | apt-get install `python3-venv`/`python3-psutil` |
| `--force-pair` | off | Pair again even if a token exists |
| `--no-start` | off | Install but do not enable/start the service |
| `--dry-run` | off | Validate and print planned actions |
| `--help` | - | Usage |

Use `--dry-run` first on an unfamiliar derivative:

```bash
sudo bash agents/linux/install.sh --dry-run \
  --controller http://192.0.2.10:8787 --name "Test"
```

## What the installer does

1. Requires root, systemd, a supported `/etc/os-release` and Python 3.10+.
2. Creates the system user/group `homemonitor-agent` (no login shell).
3. Copies `agent/` and `common/` to `/opt/homemonitor-agent`.
4. Creates `/opt/homemonitor-agent/.venv` and installs
   `requirements-agent.txt` (or the distro `python3-psutil` package when appropriate).
5. Creates `/var/lib/homemonitor-agent` with restrictive ownership.
6. Pairs with `python -m agent --pair-only` unless a token already exists or
   `--force-pair` is supplied. The pairing code is not written to the unit file.
7. Installs `/etc/systemd/system/homemonitor-agent.service`, enables it and starts it.

Representative output:

```text
HomeMonitor agent installer
  Distribution : Ubuntu 24.04.1 LTS (24.04)
  Source       : /home/you/HomeMonitor
  Install dir  : /opt/homemonitor-agent
  Data dir     : /var/lib/homemonitor-agent
  Service user : homemonitor-agent
  Device name  : Living Room PC
  Controller   : http://192.0.2.10:8787
  Pairing      : enabled (code is not written to the service file)
...
Pairing the device with the controller...
Approve 'Living Room PC' in the controller dashboard.
Enabling and starting homemonitor-agent...
```

Approve the device in the dashboard. Until then heartbeats are accepted and metrics are
rejected with `pending_approval`.

## Files and service

| Item | Location |
| --- | --- |
| Program files | `/opt/homemonitor-agent` |
| Virtual environment | `/opt/homemonitor-agent/.venv` |
| Config/token | `/var/lib/homemonitor-agent/agent.json` |
| Log | `/var/lib/homemonitor-agent/logs/agent.log` |
| Service unit | `/etc/systemd/system/homemonitor-agent.service` |
| Service user | `homemonitor-agent` |

The unit uses `Restart=always`, `RestartSec=10`, `NoNewPrivileges`, `ProtectSystem=strict`,
`ProtectHome=true`, `PrivateTmp=true`, kernel/control-group protections and
`RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`. The agent is outbound-only and does
not need inbound ports.

## Operations

```bash
sudo systemctl status homemonitor-agent --no-pager
sudo systemctl restart homemonitor-agent
sudo systemctl stop homemonitor-agent
sudo systemctl disable --now homemonitor-agent
sudo journalctl -u homemonitor-agent -f
sudo tail -f /var/lib/homemonitor-agent/logs/agent.log
```

Update: replace the project files and re-run the installer. It preserves the token and
database. Re-pair only when needed:

```bash
sudo bash agents/linux/install.sh --controller http://192.0.2.10:8787 \
  --pairing-code NEW-CODE --force-pair
```

Change the controller address: edit `/var/lib/homemonitor-agent/agent.json` while the
service is stopped, or re-run the installer with `--controller`. If the controller's data
directory was preserved, the token stays valid; otherwise re-pair.

## Manual run (no systemd)

```bash
python3 -m pip install --user -r requirements-agent.txt
python3 -m agent --controller http://192.0.2.10:8787 --pairing-code ABCD-1234
```

Config defaults to `~/.config/homemonitor/agent.json` when run manually. This mode does not
start at boot. Use your init system, a container supervisor, or a terminal multiplexer if
you need persistence.

## Distro detection

`agent/platform_linux.py` parses `/etc/os-release` and reports:

- distribution ID, ID_LIKE, version and pretty name;
- init system (`systemd`, `openrc`, `sysv`, `unknown`);
- package manager (`apt`, `dnf`, `pacman`, ...);
- whether the detected distribution/version is in the validated set.

The detector is informational for the agent and a gate (`--require-distro`) for the
wrapper installers. It is not a hard runtime dependency.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| "systemd is required" | Run on a systemd host/VM, or use manual mode |
| "Python 3.10+ required" | Install a newer Python; the installer will not replace system Python |
| "distribution is not supported" | Use the generic installer or run manually; report the OS |
| Service restarts every 10 s | `journalctl`; usually a wrong URL, missing token or ownership problem |
| Pending forever | Approve in the dashboard |
| No temperature | Linux sensors depend on kernel drivers/`psutil`; not all machines expose it |
| No GPU | Install `nvidia-ml-py` in the venv for NVIDIA telemetry |
| Permission denied on data dir | Keep ownership `homemonitor-agent:homemonitor-agent` |

More: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
