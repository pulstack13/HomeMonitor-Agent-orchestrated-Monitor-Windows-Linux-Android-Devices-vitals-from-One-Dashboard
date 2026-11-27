# Contributing to HomeMonitor

Thanks for helping improve HomeMonitor. This project is intentionally small and
dependency-light. Please keep changes focused, testable and safe for a trusted home LAN.

## Before you start

- Read [README.md](README.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- Never commit real tokens, pairing codes, database files, logs, keystores, private IP
  addresses, device serial numbers, SSIDs or personal paths.
- Report security issues privately as described in [SECURITY.md](SECURITY.md), not in a
  public issue.
- For a platform report, include the OS version, Python version, install method and the
  exact command/output. Mark clearly whether it ran on real hardware, a VM or a container.

## Development setup

Requirements: Python 3.10+ and `psutil` for the desktop agent.

```bash
git clone https://github.com/YOUR-USERNAME/HomeMonitor.git
cd HomeMonitor
python -m venv .venv
# Windows: .venv\Scripts\python -m pip install -r requirements-dev.txt
# Linux:   .venv/bin/python -m pip install -r requirements-dev.txt
```

Run the server from the repository root:

```bash
python -m server --data-dir ./data-dev --port 8788 --no-discovery
```

Run an agent against it:

```bash
python -m agent --controller http://127.0.0.1:8788 --pairing-code CODE --pair-only
python -m agent --controller http://127.0.0.1:8788 --config ./data-dev/agent.json
```

Approve the device in the dashboard. Use a disposable data directory; never point tests
at a real deployment's data.

## Tests and checks

```bash
python -m unittest discover -s tests -v
python -m compileall -q agent common server tests
```

Installer checks:

```bash
# Bash syntax (Linux, macOS or Git Bash on Windows)
for f in $(find agents server -name '*.sh'); do bash -n "$f"; done

# Optional shell linter
shellcheck -x agents/linux/*.sh agents/linux/*/*.sh server/*.sh agents/android/*.sh server/termux/*.sh
```

On Windows, parse every PowerShell file before opening a pull request:

```powershell
$errors = @()
Get-ChildItem -Recurse -Filter *.ps1 | ForEach-Object {
    $tokens = $null; $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $_.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    foreach ($e in $parseErrors) { $errors += "$($_.FullName): $($e.Message)" }
}
if ($errors) { $errors; exit 1 }
```

Run the repository scanner before committing:

```bash
python scripts/scan_personal_data.py
```

## Code guidelines

- Target Python 3.10+ for the server and desktop agent. The Android agent must remain
  compatible with Python 3.8 and the standard library only.
- Do not add a runtime dependency to the server without a strong reason. Keep it usable
  in Termux on an old phone.
- Validate all input at the protocol boundary. Do not log tokens, pairing codes or
  authorization headers.
- Keep device identity UUID-based and IP addresses informational only.
- Preserve LAN-only defaults. New remote-access features need a threat model and an
  explicit opt-in; do not silently bind to a public interface with weaker auth.
- Follow the existing style: type hints, `logging`, small functions, no shelling out in
  the collectors when a standard-library path is available.
- Update documentation and `CHANGELOG.md` for user-visible changes.
- Do not claim an OS or device is validated unless you ran it on that target. Use
  "implemented, not yet validated" in the PR and update `docs/PLATFORMS.md` with evidence.

## Installer changes

Installers are part of the product, not an afterthought.

- Keep Linux scripts `set -euo pipefail` and safe with spaces in paths.
- Keep `.sh` files LF-only. GitHub Actions checks this.
- Windows scripts must not require administrator rights for the per-user agent install.
- Never write a pairing code or admin token into a service file, shortcut or log.
- Test `--help`, `--dry-run` where available, install, re-run/repair and uninstall.
- Document the exact commands in the relevant `docs/` page.

## Pull requests

1. Fork the repository and create a topic branch.
2. Make one logical change with tests and docs.
3. Describe the problem, the change and the validation you ran.
4. Include platform details and any remaining risk or unsupported path.
5. Confirm that no secrets or personal data are included.

Maintainers may ask for a real-hardware report before changing a support claim in the
README or platform matrix.

## License

By contributing, you agree that your contribution is licensed under the project's MIT
license.
