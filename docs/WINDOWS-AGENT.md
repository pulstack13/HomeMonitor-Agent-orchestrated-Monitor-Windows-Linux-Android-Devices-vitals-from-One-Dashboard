# Windows agent

The Windows agent reports CPU, memory, disks, network, battery, uptime, top processes and,
where available, GPU/temperature data. It installs per user, needs no administrator
rights, and starts when the user signs in.

**Supported:** Windows 10/11 with Python 3.10-3.15 (validated on Windows 11 in the
original deployment; Windows 10 uses the same code path but was not independently tested
in this tree).

## Install

From the extracted release folder:

```powershell
.\agents\windows\Install HomeMonitor Agent.cmd
```

or unattended:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\agents\windows\install.ps1 `
  -Controller http://192.0.2.10:8787 `
  -PairingCode ABCD-1234 `
  -Name "Living Room PC"
```

The installer:

1. Finds Python (`py -3.10` through `py -3.15`, then `python`).
2. Copies `agent/` and `common/` to `%LOCALAPPDATA%\HomeMonitor\Agent`.
3. Creates a private virtual environment there.
4. Installs `psutil`, preferring `agents\windows\wheels` if present.
5. Pairs with `python -m agent --pair-only` unless a token already exists.
6. Creates a Startup shortcut and a Start menu shortcut.
7. Starts `pythonw.exe -m agent` in the background.

Pairing does not approve the device. Open the dashboard and approve it under
**Settings -> Device access**.

## Parameters

| Parameter | Default | Meaning |
| --- | --- | --- |
| `-Controller URL` | none | Controller base URL, e.g. `http://192.0.2.10:8787` |
| `-PairingCode CODE` | none | One-time pairing code |
| `-Name NAME` | computer name | Friendly name in the dashboard |
| `-InstallDir PATH` | `%LOCALAPPDATA%\HomeMonitor\Agent` | Per-user install location |
| `-NoStartup` | off | Do not create the sign-in startup shortcut |
| `-NoLaunch` | off | Do not start the agent after install |
| `-ForcePair` | off | Pair again even if a token exists (use a fresh code) |

Re-running the installer repairs/updates files and keeps the existing token unless
`-ForcePair` is supplied. Use a fresh pairing code with `-ForcePair`; an old code is not
accepted after regeneration.

## Files

| Item | Location |
| --- | --- |
| Install | `%LOCALAPPDATA%\HomeMonitor\Agent` |
| Python environment | `%LOCALAPPDATA%\HomeMonitor\Agent\.venv` |
| Config/token | `%APPDATA%\HomeMonitor\agent.json` |
| Log | `%APPDATA%\HomeMonitor\logs\agent.log` (1 MB × 3 rotations) |
| Startup shortcut | `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\HomeMonitor Agent.lnk` |
| Start menu | `HomeMonitor Agent Console` / `HomeMonitor Agent Log` shortcuts |

`agent.json` contains a device token. Treat it as a credential and do not copy it to
another machine.

## Auto-start behaviour

The agent starts at **user sign-in**, not at boot and not as a Windows service. It runs as
the signed-in user and stops if that user logs out or the machine shuts down. This is
deliberate: it avoids administrator rights and a system-wide service.

- To run before sign-in you would need a Windows service under a service account. That is
  not packaged or supported by v1.0.
- A locked screen does not stop the agent. Sleep/hibernate does; the device will appear
  offline until it resumes.
- If you use multiple Windows accounts, install per account or move the Startup shortcut
  to the all-users startup folder manually. The default is per user.

## Commands

```powershell
# Run in a visible console for diagnosis (Ctrl+C to stop)
.\agents\windows\Run Agent in Console.cmd

# Show the log
.\agents\windows\View Agent Log.cmd

# Pair again with a new code
powershell -ExecutionPolicy Bypass -File .\agents\windows\install.ps1 `
  -Controller http://192.0.2.10:8787 -PairingCode NEW-CODE -ForcePair

# Change the friendly name / repair
powershell -ExecutionPolicy Bypass -File .\agents\windows\install.ps1 `
  -Controller http://192.0.2.10:8787 -Name "Office PC"
```

Manual agent options (from the install directory):

```powershell
.\.venv\Scripts\python.exe -m agent --help
.\.venv\Scripts\python.exe -m agent --once
.\.venv\Scripts\python.exe -m agent --discover
```

## Uninstall

```powershell
.\agents\windows\Uninstall HomeMonitor Agent.cmd
```

This stops the agent, removes the Startup/Start menu shortcuts and deletes the install
directory. It keeps `%APPDATA%\HomeMonitor` so a reinstall can reuse the token. To delete
the config, token and logs too:

```powershell
powershell -ExecutionPolicy Bypass -File .\agents\windows\uninstall.ps1 -RemoveConfig
```

The device remains in the controller database. Revoke or delete it in the dashboard.

## Logs and health

Healthy log lines:

```text
INFO    homemonitor.agent: HomeMonitor agent 1.0.0 starting as 'Living Room PC'
INFO    homemonitor.agent: Controller: http://192.0.2.10:8787
INFO    homemonitor.agent: Device approved; starting metrics upload
```

If the controller is unreachable, the agent logs the failure with backoff and retries. It
does not need re-pairing after a controller restart or an address change (unless the
address in `agent.json` is stale).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Installer says Python missing | `py -3 --version` in a new PowerShell; install from python.org; avoid the Store alias |
| `pip`/psutil fails | Internet/proxy, antivirus lock, or build a wheel bundle for this Python |
| Agent starts then stops | `agent.json` missing token; re-run with a pairing code |
| Device pending | Approve in the dashboard |
| Device offline | PC asleep, user signed out, network change; check the log |
| No temperature | CPU temperature needs vendor support or LibreHardwareMonitor/WMI; not all PCs expose it |
| No GPU | Install `nvidia-ml-py` in the agent venv and use an NVIDIA GPU |
| Startup shortcut missing | Re-run without `-NoStartup`; check the Startup folder path |
| Uninstall leaves a process | Stop the `pythonw.exe` whose command line contains `HomeMonitor\Agent`, then retry |

More: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
