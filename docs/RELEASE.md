# Release preparation

This page is for maintainers preparing a public release. It assumes the repository is
already sanitized and tested.

## Versioning

HomeMonitor uses semantic versioning for the software and a separate wire schema version.

- `VERSION` / `AGENT_VERSION` in `common/protocol.py` and `agent/android_agent.py`.
- `SCHEMA_VERSION` in `common/protocol.py`. Bump it only for an incompatible wire change.
- `CHANGELOG.md` gets a dated section for every public release.
- Release tag: `vMAJOR.MINOR.PATCH` (for example `v1.0.0`).

Update all version strings together:

```bash
grep -R "1\.0\.0" --include="*.py" --include="*.md" --include="*.ps1" --include="*.sh" .
```

Do not bump the schema version for documentation or installer-only changes.

## Pre-release checklist

1. **Personal data scan**

   ```bash
   python scripts/scan_personal_data.py
   ```

   Fix every finding. Common regressions: a real IP in an example, a personal path in a
   log excerpt, an old SSID, a device serial, a keystore or a filled-in config.

2. **Repository validation**

   ```bash
   python scripts/validate_repo.py
   ```

3. **Tests and compile**

   ```bash
   python -m unittest discover -s tests -v
   python -m compileall -q agent common server tests
   ```

4. **Script syntax**

   ```bash
   for f in $(find agents server scripts -name '*.sh' | sort); do bash -n "$f" || exit 1; done
   ```

   Parse every `.ps1` with the PowerShell parser (see [TESTING.md](TESTING.md)).

5. **Line endings**

   `.gitattributes` normalizes text to LF and Windows launchers to CRLF. Verify:

   ```bash
   file agents/linux/install.sh server/install-linux.sh
   git ls-files --eol | grep -E '\.(sh|service)' | grep -v 'i/lf'
   ```

   `.sh`, `.service` and `.md` must be LF. `.cmd`/`.bat`/`.ps1` may be CRLF.

6. **Documentation links**

   Check that every relative link resolves. The validator covers the main ones; also open
   `README.md`, `docs/COMPLETE_SETUP_GUIDE.md` and `docs/PLATFORMS.md` in a Markdown
   preview.

7. **Android artifacts**

   The optional viewer must not ship a signing key, password, APK or build directory:

   ```bash
   test ! -e android-lite/keystore.jks
   test ! -e android-lite/keystore.password
   test ! -d android-lite/build
   ```

   If you built the APK locally, keep it outside the repository or delete it before
   packaging.

8. **License and metadata**

   Confirm `LICENSE`, `README.md` links, repository description and topics. Ensure any
   repository-specific links point to the actual GitHub project before publishing.

## Build the release archives

```bash
python scripts/package_release.py --output dist
```

The script creates, in a temporary staging directory:

| Archive | Contents |
| --- | --- |
| `HomeMonitor-1.0.0.tar.gz` / `.zip` | Full project: server, agents, dashboard, docs, examples, scripts, tests |
| `HomeMonitor-Server-1.0.0.tar.gz` | Server, common, dashboard, server installers, required docs |
| `HomeMonitor-Agent-Windows-1.0.0.zip` | Windows agent, installers, common, requirements, bundled wheels if present |
| `HomeMonitor-Agent-Linux-1.0.0.tar.gz` | Linux agent, installers, systemd unit, common, requirements |
| `HomeMonitor-Agent-Android-1.0.0.tar.gz` | Android agent and Termux scripts |

Every generated archive gets a `.sha256` file and the output directory gets a
`SHA256SUMS` file. The script refuses to run if the working tree contains obvious
personal data or generated secrets; run the scanner first.

Inspect before publishing:

```bash
tar -tzf dist/HomeMonitor-1.0.0.tar.gz | head -50
unzip -l dist/HomeMonitor-Agent-Windows-1.0.0.zip
python scripts/validate_repo.py --archives dist
```

Verify checksums on a clean machine:

```bash
sha256sum -c SHA256SUMS        # Linux
Get-FileHash ... -Algorithm SHA256   # Windows PowerShell
```

## Windows package wheels

The Windows agent needs `psutil`. If the release machine can download wheels, include
them for each supported Python version/architecture:

```powershell
python -m pip download psutil==6.1.1 --dest agents/windows/wheels `
  --only-binary=:all: --platform win_amd64 --python-version 3.12
```

The installer prefers `agents\windows\wheels` when present and falls back to the internet.
Do not commit wheels to the repository; the packaging script can copy a locally built
`agents/windows/wheels` directory into the Windows archive. Test the archive on a machine
without internet before claiming offline installation.

## Publish

1. Create the Git tag and release notes from `CHANGELOG.md`.
2. Upload the archives and `SHA256SUMS`.
3. Verify the downloaded archives match the checksums.
4. Install from the downloaded archive on a clean machine (Windows + one Linux VM if
   possible).
5. Announce the validation status honestly. Do not upgrade an "implemented" platform to
   "validated" without a real-hardware report.

## After publish

- Keep `CHANGELOG.md` current.
- Triage platform reports and update `docs/PLATFORMS.md` with evidence.
- Never commit a real token, config, database, keystore or personal network value in a
  follow-up fix. Run the scanner before every release.
- If a credential is accidentally published, treat it as compromised: rotate the admin
  token, regenerate the pairing code, revoke affected devices and publish a security
  note. Removing the commit is not enough.

## Rolling back a release

- Revert the tag/release notes and publish a patch version; do not silently replace an
  archive with different contents.
- Keep data-directory compatibility in mind. A schema bump may require a migration; the
  current v1 schema has no automatic downgrade path.
- Tell users to back up before upgrading to a version with a schema change.
