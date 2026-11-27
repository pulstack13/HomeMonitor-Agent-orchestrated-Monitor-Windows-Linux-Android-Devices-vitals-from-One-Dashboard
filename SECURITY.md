# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.x | Yes, security fixes are applied to the latest 1.x release |
| Earlier / unreleased forks | No |

## Reporting a vulnerability

Please do **not** open a public issue for a vulnerability. Use GitHub's private
vulnerability reporting on the repository's **Security** tab, or contact the maintainers
through the private channel listed in the repository profile. If neither is available,
open a minimal public issue asking for a private contact path without disclosing details.

Include:

- HomeMonitor version and commit/archive name.
- Deployment platform and Python version.
- A clear description and impact.
- Reproduction steps or a proof of concept using placeholder credentials.
- Whether the issue requires LAN access, local access or a malicious agent.

Never include a real admin token, pairing code, device token, database or personal
network details. Replace them with obvious placeholders.

We aim to acknowledge reports within 7 days and provide a remediation plan for confirmed
issues. This is a volunteer project; no bug bounty is offered.

## Security model

HomeMonitor is designed for a **trusted private LAN** and a small number of personally
managed devices.

- The controller listens on TCP 8787. It serves plain HTTP by default and has no built-in
  TLS.
- The admin token is a bearer credential. The dashboard exchanges it for an HttpOnly,
  SameSite=Strict session cookie with a seven-day lifetime.
- Agents receive a random 256-bit device token. The controller stores only a SHA-256 hash
  and compares it in constant time. IP addresses are not device identity.
- Pairing requires a short code. Registration is rate-limited, and a new device remains
  pending until an administrator approves it.
- Metrics, history, events and alerts are stored in a local SQLite database. The data
  directory includes hashed device tokens and network metadata.
- Static files are served from a known dashboard directory with path traversal checks and
  a restrictive Content Security Policy.

### Explicit non-goals

- Exposing the controller directly to the public internet.
- Multi-user accounts, roles or per-user permissions.
- Built-in TLS certificate management or reverse-proxy configuration.
- Protection from a compromised administrator browser, compromised controller host or
  malicious agent running with the controller's OS privileges.
- Storing secrets in an OS keychain. Tokens are files with restrictive permissions.

## Deployment hardening

1. Keep the controller on a trusted LAN or VPN. Do not port-forward TCP 8787.
2. Use a firewall rule limited to your LAN/private network profile.
3. Protect the data directory (`/var/lib/homemonitor`, `%LOCALAPPDATA%\HomeMonitor\ServerData`
   or the Termux data directory). It contains the admin token, pairing code, hashed
   device tokens and monitoring history.
4. Use a long random admin token if you set one yourself. Do not reuse a password.
5. Regenerate the pairing code after onboarding devices and keep it out of screenshots,
   chat and issue reports.
6. Revoke a device immediately if it is lost or retired, then delete it if history is no
   longer needed. Revocation invalidates the stored token hash.
7. Back up the database and config only to encrypted, access-controlled storage.
8. Keep Python and the host OS patched. `psutil` is the only desktop-agent dependency.
9. For remote access, prefer a VPN (WireGuard, Tailscale or similar). If a reverse proxy
   is required, terminate TLS there, add authentication, restrict source addresses and
   keep HomeMonitor bound to loopback for that deployment. See
   [docs/REMOTE-ACCESS.md](docs/REMOTE-ACCESS.md).
10. Treat the optional Android Lite viewer carefully: its `--es token` launch path exposes
    the admin token to the host's `adb` process. Pasting the token into the app is safer.

## Known limitations

- No CSRF token is used. The session cookie is SameSite=Strict and the API is same-origin;
  do not weaken this by serving the dashboard and API from different sites.
- Session invalidation is not server-side. Rotating the admin token invalidates existing
  cookies only when they are next checked against the new token.
- The login rate limiter is per source IP and in memory; it resets on restart.
- Discovery is unauthenticated by design. It reveals the controller URL and hostname to
  the local network only.
- The Android agent cannot read some `/proc` values on newer Android releases. Missing
  metrics are reported as unavailable, not fabricated.
- A compromised local account that can read the agent config can impersonate that agent.
  OS file permissions are the boundary.

## Dependency and release hygiene

- The server and Android agent use the Python standard library only.
- The desktop agent depends on `psutil`.
- CI runs the test suite and scans the repository for personal data and accidental
  secrets before packaging.
- Release archives include SHA-256 checksums. Verify them before installation.
