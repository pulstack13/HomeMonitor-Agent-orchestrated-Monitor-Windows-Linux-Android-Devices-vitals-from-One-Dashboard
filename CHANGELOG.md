# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses semantic
versioning for the public release.

## [1.0.0] - 2026-11-27

### Added

- Public, sanitized repository layout with no personal network values, tokens, device
  identifiers, keystores or local paths.
- Cross-platform server packaging:
  - Windows per-user installer and uninstaller.
  - Ubuntu/Debian/Linux Mint systemd installer and uninstaller.
  - Android/Termux setup, start and uninstall scripts with Termux:Boot integration.
- Cross-platform agent packaging:
  - Windows one-click installer, per-user startup, repair and uninstall.
  - Shared Linux installer with Ubuntu, Debian and Linux Mint entry points, a hardened
    systemd unit, virtual environment and pairing-only setup.
  - Android/Termux setup, boot supervisor and uninstall scripts.
- Pair-only agent mode so installers can register a device without starting telemetry.
- Environment-based server configuration (`HOMEMONITOR_*`) and an override for the
  dashboard directory.
- Linux distribution detection with explicit validation states for Ubuntu, Debian and
  Linux Mint.
- Optional Android Lite WebView viewer with a locally generated signing key; no embedded
  admin token.
- Documentation set: complete setup guide, architecture, protocol, HTTP API, platform
  matrix, troubleshooting, remote access, testing and release preparation.
- GitHub Actions for Python tests, installer syntax, PowerShell parsing and secret scans.
- Packaging and validation scripts with SHA-256 checksums.
- Unit tests for server configuration, pairing-only mode, Linux detection and installer
  layout, in addition to the existing protocol/database/API/agent tests.

### Changed

- Server package path is now `server.controller` and the dashboard lives beside the
  server package instead of inside it.
- Windows installers support Python 3.10 through 3.15 and no longer assume one specific
  minor version.
- Linux installers require Python 3.10+ and systemd; Debian/Ubuntu families are detected
  from `/etc/os-release`.
- All example addresses use documentation ranges (`192.0.2.0/24`) instead of a real LAN.
- The controller's pairing code can be supplied through `HOMEMONITOR_PAIRING_CODE` or
  `--pairing-code` for automated setup.

### Security

- Removed a previously exposed example admin token, a personal ADB serial, a reusable
  signing keystore and personal SSIDs/IP addresses from the public tree.
- API documentation calls out the LAN-only plain-HTTP default and the lack of built-in
  TLS.
- Added a repository scanner for personal data and common secret patterns.

### Known limitations

- Ubuntu, Debian and Linux Mint installer execution was not hardware-validated for this
  public tree. The shared agent code is tested, but systemd installation remains a
  "report your result" path.
- Windows 10 is supported by the same code path as Windows 11 but was not independently
  validated on a Windows 10 machine.
- The Android Lite viewer is optional and compiled for an older Android target; it was
  not re-tested on every Android version.
- No built-in TLS, public-internet exposure, multi-user roles, router integration or
  remote device control.

[1.0.0]: https://github.com/YOUR-USERNAME/HomeMonitor/releases/tag/v1.0.0
