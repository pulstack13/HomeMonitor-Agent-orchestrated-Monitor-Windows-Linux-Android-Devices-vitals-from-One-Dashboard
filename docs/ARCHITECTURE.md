# Architecture

HomeMonitor is a small three-part system: agents, a controller, and a browser dashboard.
It deliberately avoids a web framework, message broker, external database and cloud
services so that it can run on a low-power Android device.

## Components

```text
+-----------------------------+       +-------------------------------+
| Agent process               |       | Controller process            |
|                             |       |                               |
| Collector (psutil / /proc)  |       | ThreadingHTTPServer           |
| AgentRunner loop            | HTTP  | API handlers + static files   |
| ControllerClient (urllib)   | ----> | SQLite (WAL)                  |
| Config file (0600)          |       | SSE Broker                    |
| Rotating log                |       | Status/Retention/Internet     |
+-----------------------------+       | UDP discovery responder       |
                                      +---------------+---------------+
                                                      |
                                      +---------------v---------------+
                                      | Browser: dashboard /lite      |
                                      | vanilla HTML/CSS/JS           |
                                      +-------------------------------+
```

### Agent

- `agent/collector.py` - Windows/Linux metrics via `psutil`, `/proc`, `/sys` and OS
  commands. Optional NVIDIA (`pynvml`) and Windows WMI support.
- `agent/android_agent.py` - standalone standard-library agent for Android/Termux.
- `agent/runner.py` - registration, heartbeat, approval polling, metrics cadence,
  exponential backoff, discovery fallback and clean shutdown.
- `agent/transport.py` - `urllib` HTTP client with timeout, JSON handling and error
  mapping.
- `agent/config.py` - JSON configuration with restrictive permissions.
- `agent/platform_linux.py` - `/etc/os-release` parsing, init/package-manager detection
  and support reporting.

The agent is outbound-only. It never opens a listening socket, so it needs no inbound
firewall rule.

### Controller

- `server/controller/server.py` - HTTP routing, authentication, static files, SSE,
  discovery and background loops.
- `server/controller/db.py` - schema, registration, heartbeats, metrics, history, events,
  alerts, settings and retention.
- `server/controller/security.py` - token generation, hashing and constant-time comparison.
- `common/protocol.py` - shared validation for registration, heartbeats and metrics.
- `common/netinfo.py` - network probes shared by the controller and desktop agent.
- `dashboard/` - static HTML/CSS/JS served by the controller.

### Background threads

| Thread | Purpose |
| --- | --- |
| HTTP server thread | Accepts requests from agents and browsers |
| `StatusMonitor` | Detects online/offline transitions every few seconds |
| `RetentionWorker` | Deletes expired metrics/events and checkpoints WAL |
| `InternetMonitor` | Probes public DNS over TCP to show internet reachability |
| SSE broker | Fan-out queue per connected dashboard; no polling required |

The controller is a `ThreadingHTTPServer`. SQLite uses one connection per operation, WAL
mode and a process-wide write lock to avoid lock contention. This is appropriate for a
small home network, not for thousands of agents.

## Data flow

### Registration

```text
Agent                              Controller                         Dashboard
  |                                    |                                  |
  | POST /api/v1/register              |                                  |
  | pairing_code + device info         |                                  |
  |----------------------------------->| validate code + rate limit       |
  |                                    | create pending device            |
  |                                    | store SHA-256(token)             |
  |<-----------------------------------| 201 {token, device_id, intervals}|
  | save agent.json (0600)             |                                  |
  |                                    |  publish "pairing" refresh ----->|
  |                                    |                                  | admin approves
  |                                    |<---------------------------------| POST /approve
  |                                    | set approved=1, event            |
  |                                    |  publish "approved" ------------->|
```

### Heartbeat and metrics

```text
Every 5 s (configurable):
  Agent -> POST /devices/<uuid>/heartbeat  Authorization: Bearer <device token>
        <- 200 {approved, intervals, offline_after}

If approved, every 5 s:
  Agent -> POST /devices/<uuid>/metrics    Authorization: Bearer <device token>
        <- 202 {ok, ts}

Controller:
  validate -> SQLite insert -> SSE broker -> dashboard refresh
```

Metrics are rejected with `403 pending_approval` until an administrator approves the
device. Heartbeats are accepted for valid tokens even while pending so the dashboard can
show the device and interval changes can propagate.

### Offline detection

A device is:

- `revoked` if its token was revoked;
- `pending` if not approved;
- `online` if the last heartbeat is within `offline_after`;
- `offline` otherwise.

`StatusMonitor` records an event and an alert on online -> offline, and resolves the alert
on offline -> online. This avoids generating an alert on every status poll.

## Storage schema

SQLite tables:

| Table | Contents |
| --- | --- |
| `devices` | Identity, labels, OS, approval/revocation, IP, timestamps |
| `agents` | Device token hash, registration and last heartbeat |
| `device_network` | Latest SSID, signal, IP, gateway, DNS, interface, link speed |
| `metrics` | Raw CPU/RAM/GPU/disk/network/battery/uptime samples |
| `network_stats` | Time series for throughput/counters |
| `events` | Pairing, approval, revocation, online/offline and other audit events |
| `alerts` | Offline alerts and acknowledgement/resolution state |
| `settings` | Runtime intervals and retention |

Indexes cover `(device_id, ts)` for history and events. A retention worker prunes metrics
and network stats at `retention_days`, and events/resolved alerts at
`events_retention_days`.

The database contains hashed device tokens and network metadata. It does **not** contain
admin or device tokens in plaintext.

## Security boundaries

1. **Network:** controller on a trusted LAN; no public listener by default beyond
   `0.0.0.0:8787`.
2. **Dashboard auth:** admin token -> HttpOnly SameSite=Strict cookie (or Bearer header).
3. **Device auth:** per-device random token -> SHA-256 hash on the controller.
4. **Pairing:** short code + rate limit + manual approval.
5. **Static files:** fixed flat-file set, path traversal rejection, restrictive CSP.
6. **Host:** agent runs as the current user (Windows) or a dedicated system user (Linux);
   data directories are protected by OS permissions.

There is no TLS, role-based access control or CSRF token. Those are deliberate scope
decisions for a LAN-only v1.0 and are documented in [SECURITY.md](../SECURITY.md).

## Failure behaviour

| Failure | Behaviour |
| --- | --- |
| Controller unreachable | Agent retries with exponential backoff; optionally discovers controllers |
| Controller restarts | Agents reconnect; SQLite state and tokens persist |
| Browser SSE disconnects | `EventSource` reconnects; dashboard still works via explicit API calls |
| Agent crash | Windows startup shortcut starts at next sign-in; systemd restarts; Termux boot supervisor restarts |
| Database locked | Short busy timeout + write lock; unlikely at home scale |
| Disk full | SQLite write fails and is logged; metrics are not silently fabricated |
| Clock skew | Controller stores receive time; agent `ts` remains for diagnostics |
| Invalid payload | Rejected with a JSON error; agent logs and retries where appropriate |

## Design decisions

- **Standard library first.** The controller must run in Termux on old Android; a web
  framework and ORM would add size and failure modes without helping at this scale.
- **SQLite.** One file, transactional, easy to back up, adequate for a handful of devices.
- **SSE instead of WebSockets.** One-way refresh events are enough, and SSE works with a
  simple HTTP server.
- **UUID identity.** IPs change; a stable device UUID keeps history across address changes.
- **Manual approval.** Pairing alone does not grant monitoring access. This limits the
  impact of a leaked pairing code.
- **No external assets.** The dashboard works offline and cannot leak data to a CDN.
- **Explicit platform status.** Packaging is tested separately from the shared core; see
  [PLATFORMS.md](PLATFORMS.md).

## Extension points

- Add a collector field in `common/protocol.py`, the database schema and the dashboard.
  Bump `SCHEMA_VERSION` if the wire shape changes incompatibly.
- Add a platform agent under `agents/` and document its install/uninstall path. Do not
  rename the Windows installer and claim support.
- Add a reverse proxy in front of the existing HTTP server for TLS; do not embed
  certificates in the repository.
- Add an alert rule in `db.py` plus a dashboard label. Keep it opt-in and rate-limited.
