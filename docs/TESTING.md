# Testing and validation

This page records what is tested automatically, what was validated on real hardware for
the v1.0 feature set, and what still needs a human on the target platform.

## Automated test suite

Requirements: Python 3.10+ and `psutil` for the desktop-agent tests.

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The suite uses `unittest`, needs no network and creates temporary data directories. It
covers:

| Area | Examples |
| --- | --- |
| Protocol | Registration, heartbeat and metrics validation, normalization, error shapes |
| Database | Schema, devices, tokens, metrics, history, events, alerts, retention |
| HTTP API | Session auth, overview, devices, approve/revoke/delete, settings, SSE setup |
| Agent runner | Pairing, pending approval, backoff, interval updates, shutdown |
| Collector | Platform detection helpers and metric shaping without requiring real GPUs |
| Linux platform | `/etc/os-release` parsing, distro families, init/package-manager detection |
| Installer layout | Required files, Linux wrappers, service unit contents, Windows scripts |
| Server configuration | Environment variables, CLI overrides, dashboard directory override |

Expected result:

```text
Ran 56 tests in ...s

OK
```

The exact count can grow; treat the run as a regression gate, not a fixed number.

Compile check:

```bash
python -m compileall -q agent common server tests
```

## Installer syntax checks

Bash files must be LF-only and parse without executing:

```bash
for f in $(find agents server -name '*.sh' | sort); do
  bash -n "$f" || exit 1
done
```

Optional, if `shellcheck` is installed:

```bash
shellcheck -x agents/linux/*.sh agents/linux/*/*.sh \
  server/*.sh agents/android/*.sh server/termux/*.sh
```

PowerShell files are parsed without running them:

```powershell
$errors = @()
Get-ChildItem -Recurse -Filter *.ps1 | ForEach-Object {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $_.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    foreach ($e in $parseErrors) { $errors += "$($_.FullName): $($e.Message)" }
}
if ($errors) { $errors; exit 1 }
```

## Repository validation

```bash
python scripts/validate_repo.py
python scripts/scan_personal_data.py
```

`validate_repo.py` checks required files, LF line endings for shell scripts, generated or
secret artifacts, and relative Markdown links. `scan_personal_data.py` looks for private
IPv4 addresses, personal home-directory paths, common credential patterns, and signing
artifacts. Both are CI gates.

## Manual smoke test (any desktop OS)

1. Start a controller on a free port with a temporary data directory:

   ```bash
   python -m server --data-dir ./data-test --port 8788 --no-discovery
   ```

2. Check health and dashboard:

   ```bash
   curl http://127.0.0.1:8788/healthz
   curl -I http://127.0.0.1:8788/
   ```

3. Pair a second process as an agent:

   ```bash
   python -m agent --controller http://127.0.0.1:8788 \
     --pairing-code CODE --config ./data-test/agent.json --pair-only
   ```

4. Approve the device with the admin token:

   ```bash
   curl -X POST -H "Authorization: Bearer ADMIN_TOKEN" \
     http://127.0.0.1:8788/api/v1/devices/DEVICE_ID/approve
   ```

5. Start the agent and confirm metrics appear:

   ```bash
   python -m agent --config ./data-test/agent.json
   curl -H "Authorization: Bearer ADMIN_TOKEN" \
     http://127.0.0.1:8788/api/v1/devices
   ```

6. Stop the agent, wait longer than `offline_after`, and confirm the device goes offline
   and an alert is created.
7. Restart the controller and confirm the device tokens and history survive.
8. Uninstall/clean up: stop both processes and delete `./data-test`.

## Platform validation checklist

Run this on real hardware (or a full VM) before reporting a platform as working.

### Controller

- [ ] Installed with the packaged installer, not only from source.
- [ ] Survives a reboot and starts automatically.
- [ ] `/healthz` works locally and from another LAN device.
- [ ] Dashboard login works from another LAN device.
- [ ] Pairing, approval and metrics work end to end.
- [ ] Firewall limited to the LAN/private profile.
- [ ] Logs show no traceback or repeated connection errors after 24 hours.
- [ ] Backup and restore of the data directory works.

### Desktop agent

- [ ] Installed with the packaged installer.
- [ ] Survives a reboot/sign-in and reconnects.
- [ ] CPU, RAM, disk, network and uptime appear (temperature/GPU optional).
- [ ] Pending approval is enforced before metrics are accepted.
- [ ] Controller restart does not require re-pairing.
- [ ] Uninstall removes the service/startup entry and leaves no running process.
- [ ] Log is readable and contains no token.

### Android agent

- [ ] Termux and Termux:Boot from F-Droid.
- [ ] Battery optimisation disabled, wake lock acquired.
- [ ] Pairing and approval work.
- [ ] Metrics update while the screen is off.
- [ ] Survives a reboot and returns within two minutes.
- [ ] Missing `/proc` values are shown as unavailable, not zero.
- [ ] Uninstall removes the boot script and token.

## Results for this release

| Check | Result |
| --- | --- |
| Unit test suite | 56 tests pass (`Ran 56 tests ... OK`) on Windows with Python 3.15 in this validation run |
| Python compile check | Passes for `agent`, `common`, `server`, `tests` and `scripts` in this validation run |
| Repository validator | Passes in this validation run |
| Personal-data scanner | Passes after removing local signing/build artifacts |
| Release packages | Six archives built and inspected for forbidden artifacts; SHA-256 manifests generated |
| Bash syntax (`bash -n`) | Passes in the automated installer syntax test; the direct PowerShell Bash shim check requires WSL, and Ubuntu CI repeats it |
| PowerShell parse | Passes for all current `.ps1` files in this validation run |
| Dashboard health + root smoke test | Passed in this validation run on Windows with a temporary data directory |
| Android Lite APK build | Optional source only; no APK or signing key is included |
| Windows 11 server + agent | Validated on real hardware in the original v1.0 deployment |
| Windows 10 | Implemented; not independently validated here |
| Ubuntu/Debian/Mint packages | Implemented; no real systemd host available in this session |
| Docker/Linux containers | Not validated; Docker daemon unavailable in this session |
| Android agent on real hardware | v1.0 agent validated earlier; public packaging not re-run here |

"Not validated" means no claim is made. The shared Python code is tested, but installer
behaviour, boot integration and OS-specific collectors can still fail on a target we did
not run.

## CI

`.github/workflows/tests.yml` runs the unit suite on Windows and Ubuntu with supported
Python versions, checks shell syntax on Ubuntu, parses PowerShell on Windows, and runs the
repository validator and scanner. Packaging validation is a separate job that builds the
release archives and checks their contents/checksums.

CI cannot prove real boot behaviour, Android vendor battery policy or installer
interaction with a desktop session. Those remain manual checks.

## Reporting a result

Open an issue titled `Platform report: <OS> <version> <component>` and include:

- Distribution/edition/build and architecture.
- Python version.
- Installer command and whether it was a release archive or source checkout.
- Hardware model (no serial number).
- Boot/sign-in behaviour and reboot result.
- Relevant logs with tokens, IPs, SSIDs and names removed.
- Any deviation from the checklist above.

Do not attach databases, configs, keystores or screenshots containing credentials.
