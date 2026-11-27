# Wire protocol (version 1)

HomeMonitor uses JSON over HTTP/1.1 on the LAN. The same validation code
(`common/protocol.py`) runs in the controller and the desktop agent so malformed or
out-of-range values are rejected consistently.

Constants:

| Constant | Value |
| --- | --- |
| Software version | `1.0.0` |
| Schema version | `1` |
| Default HTTP port | `8787` |
| Discovery UDP port | `45892` |
| Discovery magic | `HOMEMONITOR_DISCOVER_V1` |
| Maximum request body | 524288 bytes (512 KiB) |
| Default heartbeat / metrics interval | 5 s / 5 s |
| Default offline threshold | 15 s |

Timestamps are Unix epoch seconds (float). Throughput fields ending in `_bps` are
**bytes per second**, not bits. Sizes are MiB/GiB as documented per field.

## Transport and headers

Every API request except `GET /healthz`, `GET /api/v1/ping` and
`POST /api/v1/register` requires authentication.

| Header | Used by | Meaning |
| --- | --- | --- |
| `Authorization: Bearer <device-token>` | Agent | Per-device credential |
| `Authorization: Bearer <admin-token>` | Admin/API | Dashboard admin credential |
| `Cookie: hm_session=<admin-token>` | Browser | HttpOnly SameSite=Strict session |
| `X-Admin-Token: <admin-token>` | Admin/API | Alternate admin header |
| `X-Agent-Version: 1.0.0` | Agent | Stored on heartbeat when supplied |
| `Content-Type: application/json` | POST/PUT | Required for JSON bodies |

The controller responds with `Content-Type: application/json; charset=utf-8`,
`Cache-Control: no-store` and `X-Content-Type-Options: nosniff` on API routes.

The agent does not follow redirects to arbitrary hosts, uses a 10-second timeout, and maps
HTTP errors to structured exceptions. It never sends credentials over HTTPS unless the
configured controller URL uses `https://`.

## Discovery (optional)

The agent broadcasts the magic bytes to UDP 45892. A controller replies to the source
address with:

```json
{
  "service": "homemonitor",
  "version": "1.0.0",
  "schema": 1,
  "base_url": "http://192.0.2.10:8787",
  "hostname": "controller-host"
}
```

Discovery is unauthenticated and reveals only the controller URL/version/hostname to the
local broadcast domain. Agents can disable it with `auto_discover: false` or by using an
explicit controller URL. The controller can disable the responder with
`--no-discovery` / `HOMEMONITOR_DISCOVERY=0`.

## Registration

`POST /api/v1/register` (no authentication; rate-limited to 12 attempts per 60 seconds per
source IP).

Request:

```json
{
  "pairing_code": "ABCD-1234",
  "device": {
    "id": "6f1c2f7e-1a2b-4c3d-8e9f-0123456789ab",
    "name": "Living Room PC",
    "hostname": "living-room",
    "os": "Windows",
    "os_version": "11",
    "arch": "AMD64",
    "model": "Desktop",
    "category": "windows",
    "agent_version": "1.0.0"
  }
}
```

Validation:

- `pairing_code`: 1-32 characters after normalization; compared case-insensitively after
  removing non-alphanumeric characters.
- `device.id`: 8-64 characters, letters/digits/`-`/`_`, must start with a letter/digit.
- `device.name`: required, 1-80 characters after control-character removal.
- `category`: one of `windows`, `linux`, `android`, `router`, `other`; unknown values
  become `other`.
- Text limits: hostname 80, OS 80, OS version 120, architecture 40, model 120, agent
  version 40.

Success `201`:

```json
{
  "device_id": "6f1c2f7e-1a2b-4c3d-8e9f-0123456789ab",
  "token": "generated-device-token",
  "approved": false,
  "heartbeat_interval": 5,
  "metrics_interval": 5,
  "offline_after": 15,
  "server_time": 1795752390.0
}
```

The token is returned **once**. The agent must save it with restrictive permissions. The
controller stores only its SHA-256 hash. A registration with an existing UUID replaces the
stored token hash and returns the same device ID; pending/approved state follows the
database rules.

Errors:

| Status | Code | Meaning |
| --- | --- | --- |
| 400 | `invalid_payload` / `invalid_json` | Malformed JSON or missing fields |
| 403 | `pairing_denied` | Wrong pairing code |
| 429 | `rate_limited` | Too many registration attempts |

## Heartbeat

`POST /api/v1/devices/<device_id>/heartbeat`, authenticated with the device token.

Request (all fields optional except the body object; send `{}` if nothing is available):

```json
{
  "uptime_s": 12345.6,
  "battery_pct": 87.0,
  "status": "ok",
  "network": {
    "ssid": "Home Wi-Fi",
    "ip": "192.0.2.50",
    "gateway": "192.0.2.1",
    "dns": "192.0.2.1",
    "interface": "wlan0",
    "signal_pct": 72,
    "link_mbps": 866
  }
}
```

Field notes:

- `uptime_s`: 0 to 1e10.
- `battery_pct`: 0-100.
- `status`: up to 32 characters, default `ok`.
- `network`: optional object; empty/unknown SSIDs (`<unknown ssid>`, `unknown`, `0x`,
  `-`, etc.) are dropped. `signal_pct` is 0-100. `link_mbps` is 0-100000.
- The controller records `last_heartbeat` from its own clock and updates the device IP from
  the TCP peer address.

Success `200`:

```json
{
  "ok": true,
  "approved": true,
  "server_time": 1795752390.0,
  "heartbeat_interval": 5,
  "metrics_interval": 5,
  "offline_after": 15
}
```

`approved` tells the agent whether to upload metrics. Heartbeats are accepted for a valid
token even while pending, so the dashboard can show the device and push interval changes.

Errors: `401 auth_required` / `auth_failed`, `403 revoked`, `404 not_found`,
`429 rate_limited` (registration/login endpoints only).

## Metrics

`POST /api/v1/devices/<device_id>/metrics`, authenticated with the device token. The device
must be approved; otherwise the response is `403 {"error":"Device is awaiting approval",
"code":"pending_approval"}`.

Request:

```json
{
  "schema_version": 1,
  "ts": 1795752390.0,
  "cpu": {
    "percent": 12.5,
    "cores": 8,
    "freq_mhz": 3200.0,
    "temp_c": 48.0,
    "load": [0.4, 0.5, 0.6]
  },
  "memory": {
    "percent": 41.2,
    "used_mb": 6200.0,
    "total_mb": 15000.0,
    "swap_percent": 1.0
  },
  "gpu": {
    "name": "GPU name",
    "percent": 22.0,
    "temp_c": 55.0,
    "mem_used_mb": 1024.0,
    "mem_total_mb": 8192.0
  },
  "disks": [
    {"mount": "C:\\", "percent": 61.0, "used_gb": 300.0, "total_gb": 500.0}
  ],
  "disk_pct": 61.0,
  "disk_io": {"read_bps": 1024.0, "write_bps": 2048.0},
  "network": {
    "up_bps": 12000.0,
    "down_bps": 340000.0,
    "rx_bytes": 123456789.0,
    "tx_bytes": 98765432.0
  },
  "battery": {"percent": 87.0, "plugged": true},
  "system": {"uptime_s": 12345.6},
  "processes": [
    {"pid": 1234, "name": "browser", "cpu": 4.2, "mem_mb": 512.0}
  ]
}
```

Required structure:

- `body.cpu` and `body.memory` must be objects.
- `memory.percent` is required, 0-100.
- Everything else is optional. Missing values are stored as SQL `NULL` and displayed as
  unavailable; the protocol does not invent zeros.
- `processes` is capped at 15 entries; `disks` at 16. The reference collector sends at most
  10 processes and 8 disks.
- `schema_version`: 0-1000 (current 1). The controller does not reject a future schema
  outright, but a future shape may omit fields.
- `ts`: non-negative epoch seconds. The controller stores its own receive time for history
  and uses `ts` for diagnostics.

Numeric ranges include CPU/GPU/RAM/disk/battery percentages 0-100, temperatures -50 to
250 °C, frequencies 0-100000 MHz, byte counters 0-1e18 and throughput 0-1e15 B/s.

Success `202`:

```json
{"ok": true, "ts": 1795752390.0}
```

## Error envelope

All API errors use:

```json
{"error": "Human-readable message", "code": "machine_code"}
```

Common codes:

| Code | Typical status | Meaning |
| --- | --- | --- |
| `auth_required` | 401 | Missing admin/device credential |
| `auth_failed` | 401 | Invalid admin/device credential |
| `pending_approval` | 403 | Device exists but is not approved |
| `revoked` | 403 | Device access was revoked |
| `pairing_denied` | 403 | Wrong pairing code |
| `rate_limited` | 429 | Per-IP rate limit |
| `invalid_json` | 400 | Body is not valid JSON |
| `invalid_payload` | 400 | Protocol validation failed |
| `invalid_request` | 400 | Missing/empty body, bad Content-Length |
| `too_large` | 413 | Body exceeds 512 KiB |
| `not_found` | 404 | Unknown route or device |
| `internal` | 500 | Unexpected server error (details only in logs) |

## Compatibility policy

- A change that removes/renames a field or changes its meaning requires a schema version
  bump and a migration note.
- Adding an optional field is backward compatible; old agents omit it.
- The current controller accepts unknown JSON fields and ignores them. This is not a
  promise that every future version will.
- The software version and schema version are exposed by `/healthz`, the dashboard and
  discovery.
- Protocol version 1 is the only public wire protocol. There is no legacy endpoint.

## Security notes

- Pairing codes and tokens are never written to logs by the controller. Failed logins are
  logged with the source IP only.
- All comparisons of secrets use `hmac.compare_digest`.
- Device tokens are 256-bit URL-safe random strings; SHA-256 is sufficient because they
  are not user-chosen passwords.
- Registration and login are rate-limited in memory per source IP.
- The controller trusts the TCP peer address for the displayed IP; proxies must set
  appropriate forwarding if that matters to you.
- The protocol is plain HTTP. Use a VPN/TLS proxy if traffic crosses an untrusted link.
