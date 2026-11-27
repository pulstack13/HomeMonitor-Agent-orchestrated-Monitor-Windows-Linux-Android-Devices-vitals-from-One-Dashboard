# Troubleshooting

Start with the symptom, then work through the matching section. Commands use
`CONTROLLER_IP` and `192.0.2.10` as placeholders.

## First checks

Run these on the controller and on the agent host before changing anything.

**Controller health:**

```bash
curl http://127.0.0.1:8787/healthz
```

Expected:

```json
{"service":"homemonitor","version":"1.0.0","schema":1,"time":1795752390.0}
```

**From the agent host:**

```bash
curl http://CONTROLLER_IP:8787/healthz
```

If the first works and the second does not, the problem is the network/firewall, not the
agent.

**Processes:**

```powershell
# Windows: show the command line so you can tell the server from the agent
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
  Select-Object ProcessId, CommandLine | Format-List
```

```bash
# Linux
systemctl status homemonitor-controller --no-pager
systemctl status homemonitor-agent --no-pager
```

**Logs:**

| Component | Log |
| --- | --- |
| Windows server | `%LOCALAPPDATA%\HomeMonitor\ServerData\controller.log` |
| Windows agent | `%APPDATA%\HomeMonitor\logs\agent.log` |
| Linux server | `journalctl -u homemonitor-controller` and `/var/lib/homemonitor/controller.log` |
| Linux agent | `journalctl -u homemonitor-agent` and `/var/lib/homemonitor-agent/logs/agent.log` |
| Termux server | `~/homemonitor-controller.log` |
| Android agent | `~/.config/homemonitor/android_agent.log` or `~/homemonitor-agent.log` |

When posting a log, remove tokens, pairing codes, real IP addresses, SSIDs and device
names.

---

## Dashboard and login

### The dashboard does not load from another device

1. Confirm the server process is running on the controller.
2. Test `curl http://CONTROLLER_IP:8787/healthz` from the same device as the browser.
3. Check the controller received a routable address. The startup banner prints the LAN
   URL; if it only shows `127.0.0.1`, the server bound to loopback or the machine has no
   LAN address.
4. Check the OS firewall. Windows must allow TCP 8787 on the **Private** profile. Linux
   must allow it from the LAN CIDR, not from the whole internet.
5. Check router "AP isolation", "client isolation" or a guest network; these block
   device-to-device traffic even when both devices have internet.
6. Confirm both devices are on the same VLAN/subnet. A wired PC on the main LAN and a
   phone on a guest Wi-Fi often cannot reach each other.

Windows rule:

```powershell
New-NetFirewallRule -DisplayName "HomeMonitor (Private)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8787 -Profile Private
```

UFW rule (replace `YOUR_LAN_CIDR` with your LAN prefix, for example the first three
octets of the controller address followed by `0/24`):

```bash
sudo ufw allow from YOUR_LAN_CIDR to any port 8787 proto tcp
sudo ufw status verbose
```

Do not use `ufw allow 8787` on an untrusted network.

### "Invalid admin token"

- Copy the token again from `config.json` (`admin_token`) or, on Linux,
  `/var/lib/homemonitor/config.json`.
- Remove leading/trailing spaces; some terminals copy a line break.
- Make sure you are talking to the intended controller. Two installs on the same LAN can
  both answer on port 8787 on different addresses.
- Login is rate-limited per source IP. After repeated failures, wait about a minute.
- Rotating the admin token invalidates old cookies on their next check. Clear the
  `hm_session` cookie or use a private window.

The admin token is not shown in the dashboard by design. It is stored in `config.json`
and printed once during installation/startup.

### Dashboard loads but is empty or stale

- Check `GET /api/v1/overview` with the admin token. If the API returns data, the browser
  session or SSE stream is the problem.
- Refresh the page. The dashboard reconnects SSE automatically, but a sleeping laptop may
  pause it.
- A reverse proxy must not buffer `text/event-stream`. If you use one, disable buffering
  for `/api/v1/stream`.
- Browser extensions that block scripts or cookies can break the dashboard. Test a private
  window.

### Dashboard shows the wrong controller address

The overview uses the request's `Host` header and local interface detection. If you use a
reverse proxy or a different hostname, set the proxy's forwarded headers correctly. The
dashboard does not send data to the address it displays; it is informational.

---

## Pairing and approval

### "No device token" / agent exits immediately

The first agent run needs a pairing code:

```bash
python -m agent --controller http://CONTROLLER_IP:8787 --pairing-code ABCD-1234
```

Installers pair with `--pair-only`. If you skipped the code, re-run the installer with
`--pairing-code` (Linux) or `-PairingCode` (Windows), or pair manually and then start the
agent with the saved config.

### "Pairing rejected" / 403 `pairing_denied`

- The code is wrong, expired after regeneration, or belongs to another controller.
- Read the current code from **Settings -> Pairing** or `pairing_code.txt` in the data
  directory.
- Codes are case-insensitive and ignore punctuation, but not extra characters.
- Registration is rate-limited (12 attempts per 60 seconds per source IP). Wait a minute
  after repeated failures.

### Device is stuck in "pending"

Pairing creates a pending device; it does not grant monitoring. Open the dashboard and
approve it under **Settings -> Device access** or the overview banner. Until then:

- heartbeats are accepted,
- metrics are rejected with `403 pending_approval`,
- the agent logs that it is waiting.

If the approve button fails, check that the dashboard is logged in as admin and that the
device ID in the URL matches an existing device.

### Device was revoked by mistake

Revocation invalidates the stored token. Re-pair the agent with a fresh code; the device
returns as pending and must be approved again. History may still exist unless you deleted
the device.

### Re-pairing creates a second device

Each device UUID is a separate identity. Reinstalling the agent with a new config file or
after deleting the config generates a new UUID. Remove the old entry in the dashboard. If
the controller's database was lost, old tokens no longer exist and every agent must pair
again.

---

## Agent connectivity

### Agent cannot connect to the controller

Test from the agent host:

```bash
curl -v http://CONTROLLER_IP:8787/healthz
```

Common causes:

- `127.0.0.1` used instead of the controller's LAN address.
- Controller is on a different network/VLAN or a guest Wi-Fi.
- Firewall blocks outbound or inbound TCP 8787.
- The controller URL has `https://` but the server speaks HTTP (or vice versa).
- A typo in the port. The default is `8787`, not `80` or `8080`.
- The controller was reinstalled on a new address and the agent config is stale.

Update the URL:

- Windows: re-run the installer with `-Controller` or edit
  `%APPDATA%\HomeMonitor\agent.json` while the agent is stopped.
- Linux: edit `/var/lib/homemonitor-agent/agent.json` and restart the service, or re-run
  the installer with `--controller`.
- Android: supply `--controller` on the next start, or edit
  `~/.config/homemonitor/android_agent.json`.

### Agent connects, then goes offline

- The controller marks a device offline after `offline_after` seconds without a
  heartbeat (default 15 s). Check the settings if you changed intervals.
- A sleeping laptop, Wi-Fi power saving, or a phone's battery manager can suspend the
  agent. Use wired Ethernet for the controller where possible.
- Windows: check **Settings -> System -> Power** and the network adapter's power
  management. The agent starts at sign-in, not before login, and stops if the user logs
  out or the machine sleeps.
- Linux: `systemctl status` and `journalctl` show restarts. A laptop lid close or suspend
  stops heartbeats.
- Android: disable battery optimisation for Termux and Termux:Boot; keep the device on
  mains power; use the wake lock.

### Agent works intermittently on Wi-Fi

- The controller may have multiple addresses (Ethernet, Wi-Fi, VPN). Bind it to the
  intended interface with `--host` / `HOMEMONITOR_HOST` if the wrong address is advertised.
- UDP discovery may return a VPN or virtual adapter. Use an explicit controller URL.
- Mesh Wi-Fi roaming and client isolation can drop connections. Test with a cable.

### Discovery does not find the controller

- Discovery uses UDP 45892 broadcast. Many networks block broadcast or isolate clients.
- The controller must have discovery enabled (`HOMEMONITOR_DISCOVERY=1`, no
  `--no-discovery`).
- Host firewalls must allow inbound UDP 45892.
- A VPN or multiple interfaces can confuse the reply address.
- Discovery is optional. Use an explicit `--controller` URL; it is more reliable.

---

## Installer problems

### Windows says Python is missing or too old

The installers accept Python 3.10 through 3.15.

1. Open a new PowerShell after installing Python.
2. Test:

   ```powershell
   py -3 --version
   ```

3. The Microsoft Store alias can shadow a real install. Use <https://www.python.org/> or
   the bundled `Install Python (winget).cmd`.
4. If `py` is missing, select **Add python.exe to PATH** in the installer, or install the
   Python Launcher for Windows.
5. Re-run the HomeMonitor installer.

### Windows install fails at "Installing psutil"

- The release package may not include wheels for your Python version. Connect to the
  internet and re-run, or build the package with wheels for that platform.
- A proxy can block `pip`. Configure `HTTPS_PROXY` for the current user or allow
  `pypi.org`/`files.pythonhosted.org`.
- Antivirus can lock DLLs in a new virtual environment. Retry after the scan finishes.
- `pip` needs a writable `%LOCALAPPDATA%`. Domain policies that redirect it can break the
  venv; use `-InstallDir` to a writable location.

### Windows uninstall says the process is still running

The uninstaller stops `pythonw.exe` only when its command line contains the HomeMonitor
install path. If it still fails:

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like "*HomeMonitor*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Then run the uninstaller again.

### Linux installer says systemd is missing

The packaged service installers require systemd. Containers and WSL without systemd are
not supported by the installer. Options:

- Use a normal VM or host with systemd.
- Run the agent manually for testing (no boot integration).
- For a server, run `python -m server` under your own supervisor.

### Linux installer says Python is too old

HomeMonitor requires Python 3.10+ for the server and desktop agent. Install a newer Python
from your distribution's backports or a supported source. The installer does not replace
the system Python.

### Linux installer says the distribution is unsupported

The distribution-specific wrappers use `--require-distro`. Use the generic
`agents/linux/install.sh` for a compatible derivative, or run manually. The installer
prints the detected `/etc/os-release` values so you can report them.

### Linux service starts then exits

```bash
sudo systemctl status homemonitor-agent --no-pager
sudo journalctl -u homemonitor-agent -n 100 --no-pager
```

Typical causes:

- The agent config has no token and no pairing code. Re-run with `--pairing-code`.
- The controller URL is wrong or unreachable.
- `/var/lib/homemonitor-agent` ownership is wrong. The installer sets it to the service
  user; manual changes can break it.
- The service unit's hardening blocks a path you added. Do not loosen
  `ProtectSystem`/`ProtectHome` unless you understand the impact.
- The controller revoked the device. Re-pair.

### `pip` install fails behind a proxy

Set `HTTPS_PROXY`/`HTTP_PROXY` before running the installer, and make sure the service
environment does not need the proxy at runtime. The agent only needs the controller URL.

### Port 8787 is already in use

Windows:

```powershell
netstat -ano | findstr :8787
Get-Process -Id PID
```

Linux:

```bash
ss -ltnp | grep 8787
```

Stop the conflicting process or install on another port. If you change the port, update
every agent's controller URL and the firewall rule.

---

## Data and database

### Database is growing quickly

- Lower `retention_days` (metrics) and `events_retention_days` in Settings.
- Increase `metrics_interval` from 5 s to 10-30 s.
- Each device stores a metrics row per interval plus network rows. A handful of devices
  at 5 s is still only a few MB per week, but a large process list or long retention adds
  up.
- SQLite WAL files (`*.db-wal`, `*.db-shm`) can be larger than the main file. They shrink
  after a checkpoint/restart.

### "Database is locked"

The controller uses WAL, a busy timeout and a process-wide write lock. Persistent
`database is locked` usually means:

- two controller processes are using the same data directory, or
- a backup tool holds an exclusive lock, or
- the disk is full/read-only.

Stop duplicate processes and check free space. Do not run two controllers against one
data directory.

### Restore failed or devices disappeared

The data directory contains the database, admin token and pairing code. Restoring an old
copy reverts device approvals and tokens to that point. Agents paired after the backup
must pair again. Keep file ownership correct:

```bash
sudo chown -R homemonitor:homemonitor /var/lib/homemonitor
```

### Time is wrong on the dashboard

The controller stores its own receive time. Fix the host clock/NTP. Agents' `ts` values
are diagnostic and can be skewed; history uses controller time.

---

## Android and Termux

### Termux commands are not found

Use Termux from F-Droid, not an old Play Store build. Run `pkg update` and install the
package again. Do not run HomeMonitor scripts from another terminal app.

### Agent does not start after reboot

1. Install **Termux:Boot** from F-Droid and open it once.
2. Disable battery optimisation for Termux and Termux:Boot.
3. Check that `~/.termux/boot/homemonitor-agent.sh` exists and is executable.
4. Test it manually:

   ```bash
   sh ~/.termux/boot/homemonitor-agent.sh &
   tail -f ~/homemonitor-agent.log
   ```

5. Some vendors kill background apps even with Termux:Boot. Lock Termux in the recent
   apps list and keep the device charging.
6. Android may delay boot scripts for a minute or two. Wait before concluding it failed.

### Android agent has no CPU or network values

Android 13+ restricts `/proc/stat` and `/proc/net/dev` for apps. The agent reports those
fields as unavailable instead of inventing values. RAM, storage, battery, temperature and
frequency may still work. This is a platform limitation, not a configuration error.

### SSID is unavailable

- Install Termux:API (app and `pkg install termux-api`).
- Grant location permission to Termux; Android requires it for Wi-Fi details.
- Some ROMs do not expose the SSID to apps at all.
- A missing SSID is shown as unavailable, not as an error.

### Battery shows 100% on a TV box

Some Android TV boxes expose a dummy battery node. The agent suppresses obviously
meaningless battery values. If yours still shows a constant value, report the device model
and `dumpsys battery` output with personal data removed.

### Termux server stops when the screen is off

- Acquire a wake lock (`termux-wake-lock`; the start script does this).
- Disable battery optimisation for Termux and Termux:Boot.
- Keep the device on mains power.
- Some vendors still kill background processes. A small always-on PC is more reliable for
  a controller.

### `pkg install python` fails

- Run `pkg update` first and accept repository changes.
- Check free storage; Termux needs room for packages.
- Use a stable network; Termux mirrors can be slow.
- Do not mix F-Droid and Play Store Termux builds.

---

## Security and remote access

### I exposed the controller to the internet by mistake

1. Remove the port-forward or public firewall rule immediately.
2. Rotate the admin token by stopping the service, editing `config.json`, and restarting
   (or restore from a known-good backup and set a new token).
3. Regenerate the pairing code.
4. Revoke devices you do not recognize.
5. Review controller logs for unexpected registrations or logins.
6. Treat the database and any screenshots/tokens as compromised.

HomeMonitor has no built-in TLS or public-internet hardening. Use a VPN or a properly
configured TLS reverse proxy with additional authentication.

### Login works over HTTP but not HTTPS through a proxy

The dashboard sets a SameSite=Strict cookie without `Secure`. If the proxy terminates TLS
and forwards HTTP, the cookie still works, but you must ensure the browser sees a single
origin and the proxy forwards the correct `Host`. Do not serve the dashboard and API from
different sites; SameSite=Strict will block the cookie.

### SSE does not work through a proxy

Disable response buffering, compression and short idle timeouts for
`/api/v1/stream`. The server sends keepalives, but some proxies still close idle
connections. The dashboard falls back to API refreshes, so data may be delayed rather than
lost.

---

## Collecting a useful bug report

Include:

- HomeMonitor version (`/healthz`).
- OS/distribution and version, Python version.
- Install method (release archive, source checkout, installer).
- Whether it is the controller, Windows agent, Linux agent or Android agent.
- Exact command and complete error output.
- Relevant log lines with tokens, pairing codes, IPs, SSIDs and device names redacted.
- Whether the device survived a reboot.

Do not attach:

- `config.json`, `agent.json`, `android_agent.json`
- `homemonitor.db` or WAL files
- keystores, `keystore.password`, APKs signed with a private key
- screenshots showing the admin token or pairing code
- real public IPs or router credentials

Use placeholders such as `192.0.2.10`, `ABCD-1234`, `DEVICE_TOKEN` and `TestNetwork`.
