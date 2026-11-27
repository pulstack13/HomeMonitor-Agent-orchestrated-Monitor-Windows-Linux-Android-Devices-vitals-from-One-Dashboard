# HTTP API

Base URL: `http://CONTROLLER_IP:8787`

The API is intentionally small and uses JSON. There is no API version prefix for the
software version; the route prefix is `/api/v1/` and the wire schema is version 1.

All examples use placeholders:

- `CONTROLLER_IP` - for example `192.0.2.10`
- `ADMIN_TOKEN` - the dashboard admin token
- `DEVICE_ID` - a device UUID
- `DEVICE_TOKEN` - the token returned at registration

Never paste real tokens into a shell that records history on a shared machine. Prefer
environment variables and a private terminal.

## Authentication

### Dashboard session

`POST /api/v1/session`

```bash
curl -i -X POST http://CONTROLLER_IP:8787/api/v1/session \
  -H "Content-Type: application/json" \
  -d '{"token":"ADMIN_TOKEN"}'
```

Success `200`:

```text
Set-Cookie: hm_session=ADMIN_TOKEN; Path=/; HttpOnly; SameSite=Strict; Max-Age=604800
{"ok":true}
```

The cookie lifetime is seven days. `DELETE /api/v1/session` clears it.

For scripts, send the admin token as a Bearer token or `X-Admin-Token` instead of dealing
with cookies:

```bash
curl -H "Authorization: Bearer ADMIN_TOKEN" http://CONTROLLER_IP:8787/api/v1/overview
```

### Device token

Agent endpoints require:

```text
Authorization: Bearer DEVICE_TOKEN
```

The controller stores only the SHA-256 hash. A revoked or missing device token returns
`401`/`403`.

### SSE query token

`GET /api/v1/stream` additionally accepts `?token=ADMIN_TOKEN` for clients that cannot set
headers (for example an `EventSource` implementation). The dashboard itself uses the
session cookie. Query tokens can leak through proxy logs; avoid them unless necessary.

## Public endpoints

### `GET /healthz` and `GET /api/v1/ping`

No authentication.

```json
{
  "service": "homemonitor",
  "version": "1.0.0",
  "schema": 1,
  "time": 1795752390.0
}
```

Use `/healthz` for monitoring. It does not expose device data.

### `POST /api/v1/register`

No authentication, but the pairing code is required and attempts are rate-limited to 12
per 60 seconds per source IP. See [PROTOCOL.md](PROTOCOL.md#registration) for the full
schema.

```bash
curl -X POST http://CONTROLLER_IP:8787/api/v1/register \
  -H "Content-Type: application/json" \
  -d '{
    "pairing_code":"ABCD-1234",
    "device":{
      "id":"00000000-0000-4000-8000-000000000001",
      "name":"Test device",
      "hostname":"test",
      "os":"Linux",
      "os_version":"12",
      "arch":"x86_64",
      "model":"VM",
      "category":"linux",
      "agent_version":"1.0.0"
    }
  }'
```

Success `201`:

```json
{
  "device_id":"00000000-0000-4000-8000-000000000001",
  "token":"DEVICE_TOKEN",
  "approved":false,
  "heartbeat_interval":5,
  "metrics_interval":5,
  "offline_after":15,
  "server_time":1795752390.0
}
```

Re-registering an existing UUID replaces its token hash and resets it to pending. Device
history remains.

## Device endpoints

These require the **device** token.

### `POST /api/v1/devices/{DEVICE_ID}/heartbeat`

```bash
curl -X POST http://CONTROLLER_IP:8787/api/v1/devices/DEVICE_ID/heartbeat \
  -H "Authorization: Bearer DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"uptime_s":12345.6,"battery_pct":87,"network":{"ip":"192.0.2.50"}}'
```

Response `200`:

```json
{
  "ok":true,
  "approved":false,
  "server_time":1795752390.0,
  "heartbeat_interval":5,
  "metrics_interval":5,
  "offline_after":15
}
```

### `POST /api/v1/devices/{DEVICE_ID}/metrics`

Requires approval.

```bash
curl -X POST http://CONTROLLER_IP:8787/api/v1/devices/DEVICE_ID/metrics \
  -H "Authorization: Bearer DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_version":1,
    "ts":1795752390.0,
    "cpu":{"percent":12.5,"cores":8},
    "memory":{"percent":41.2,"used_mb":6200,"total_mb":15000},
    "system":{"uptime_s":12345.6}
  }'
```

Response `202`:

```json
{"ok":true,"ts":1795752390.0}
```

Unapproved device:

```json
{"error":"Device is awaiting approval","code":"pending_approval"}
```

## Admin endpoints

All require an admin session cookie, `Authorization: Bearer ADMIN_TOKEN`, or
`X-Admin-Token: ADMIN_TOKEN`.

### `GET /api/v1/overview`

The main dashboard payload.

```json
{
  "controller": {
    "service":"homemonitor",
    "version":"1.0.0",
    "schema":1,
    "hostname":"controller-host",
    "platform":"Linux-...",
    "started_at":1795752000.0,
    "uptime_s":390.0,
    "port":8787,
    "addresses":["192.0.2.10"],
    "network":{"ssid":"Home Wi-Fi","ip":"192.0.2.10","gateway":"192.0.2.1"},
    "data_dir":"/var/lib/homemonitor",
    "db_bytes":40960
  },
  "counts":{"total":1,"online":1,"offline":0,"pending":0,"revoked":0},
  "devices":[ /* device objects */ ],
  "events":[ /* latest 12 events */ ],
  "alerts":[ /* up to 8 unresolved alerts */ ],
  "alert_count":0,
  "network":{"internet":true,"checked_at":1795752389.0},
  "settings":{"heartbeat_interval":5,"metrics_interval":5,"offline_after":15,
              "retention_days":7,"events_retention_days":30},
  "pending":[ /* pending device objects */ ]
}
```

### `GET /api/v1/devices`

```json
{"devices":[ /* device objects */ ]}
```

Device object:

```json
{
  "id":"00000000-0000-4000-8000-000000000001",
  "name":"Test device",
  "hostname":"test",
  "os_name":"Linux",
  "os_version":"12",
  "arch":"x86_64",
  "model":"VM",
  "category":"linux",
  "agent_version":"1.0.0",
  "approved":true,
  "revoked":false,
  "ip":"192.0.2.50",
  "created_at":1795752000.0,
  "last_seen":1795752390.0,
  "last_heartbeat":1795752390.0,
  "status":"online",
  "latest":{ /* metric row, including processes and disks arrays */ },
  "network":{"ssid":"Home Wi-Fi","ip":"192.0.2.50","signal_pct":72}
}
```

`status` is one of `online`, `offline`, `pending`, `revoked`. `latest` is `null` until the
first approved metrics upload.

### `GET /api/v1/devices/{DEVICE_ID}?minutes=15`

Returns device, history, events and alerts. `minutes` is clamped to 1-10080 (7 days).

```json
{
  "device":{ /* device object */ },
  "history":[ /* points */ ],
  "events":[ /* up to 25 for this device */ ],
  "alerts":[ /* up to 20 for this device */ ]
}
```

### `GET /api/v1/devices/{DEVICE_ID}/history?minutes=15`

```json
{
  "device_id":"DEVICE_ID",
  "minutes":15,
  "points":[
    {"ts":1795752390.0,"cpu_pct":12.5,"ram_pct":41.2,"gpu_pct":null,
     "gpu_temp_c":null,"cpu_temp_c":48.0,"net_up_bps":12000.0,
     "net_down_bps":340000.0,"disk_pct":61.0,"battery_pct":87.0,
     "ram_used_mb":6200.0}
  ]
}
```

History is capped at 240 points; larger ranges are sampled evenly. Raw retention is
controlled by settings.

### `POST /api/v1/devices/{DEVICE_ID}/approve`

```json
{"ok":true,"device":{ /* updated device */ }}
```

### `POST /api/v1/devices/{DEVICE_ID}/revoke`

```json
{"ok":true,"device":{ /* updated device, status "revoked" */ }}
```

### `DELETE /api/v1/devices/{DEVICE_ID}`

Deletes the device and its history (foreign keys cascade). Returns `{"ok":true}`.

### `GET /api/v1/events?limit=50&device_id=DEVICE_ID`

`limit` is 1-500; `device_id` is optional and must match the UUID pattern.

```json
{
  "events":[
    {"id":42,"device_id":"DEVICE_ID","ts":1795752390.0,
     "kind":"online","detail":"Heartbeat restored","device_name":"Test device"}
  ]
}
```

### `GET /api/v1/alerts?limit=100`

`limit` is 1-500. `include_resolved` is not exposed by this route; it returns both resolved
and unresolved alerts ordered by unresolved first.

```json
{
  "alerts":[
    {"id":7,"device_id":"DEVICE_ID","ts":1795752390.0,"kind":"offline",
     "severity":"warning","title":"Test device is offline",
     "detail":"No heartbeat for more than 15s","acknowledged":0,
     "resolved_at":null,"device_name":"Test device"}
  ]
}
```

### `POST /api/v1/alerts/{ALERT_ID}/ack`

```json
{"ok":true}
```

### `GET /api/v1/settings`

```json
{
  "settings":{
    "heartbeat_interval":5,
    "metrics_interval":5,
    "offline_after":15,
    "retention_days":7,
    "events_retention_days":30
  },
  "pairing_code":"ABCD-1234",
  "controller":{ /* controller info, including addresses */ }
}
```

### `PUT /api/v1/settings`

Body may contain any subset of the five settings. Unknown keys are ignored; if no valid
key is present the request fails.

```bash
curl -X PUT http://CONTROLLER_IP:8787/api/v1/settings \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"heartbeat_interval":10,"metrics_interval":10,"offline_after":30}'
```

Bounds:

| Key | Min | Max |
| --- | --- | --- |
| `heartbeat_interval` | 2 | 60 |
| `metrics_interval` | 2 | 60 |
| `offline_after` | 10 | 300 |
| `retention_days` | 1 | 90 |
| `events_retention_days` | 1 | 180 |

Success returns `{"ok":true, ...settings payload}`.

### `POST /api/v1/pairing/regenerate`

```json
{"pairing_code":"NEW-CODE"}
```

Existing paired devices remain valid.

### `GET /api/v1/network`

Returns controller network information, internet probe state, device network summaries and
an explicit `router` placeholder with `"status":"not_configured"` (router integration is
not implemented).

```json
{
  "controller":{ /* controller info */ },
  "internet":{"internet":true,"checked_at":1795752389.0},
  "devices":[
    {"id":"DEVICE_ID","name":"Test device","category":"linux",
     "ip":"192.0.2.50","network":{ /* ... */ },"status":"online",
     "last_seen":1795752390.0}
  ],
  "router":{"status":"not_configured",
            "note":"Router and LAN latency integration is planned for Phase 8."}
}
```

### `GET /api/v1/stream` (SSE)

Requires admin auth. The server sends:

```text
retry: 3000

data: {"type":"ready","version":"1.0.0"}

data: {"type":"refresh","reason":"heartbeat","device_id":"DEVICE_ID"}

: keepalive
```

Reasons currently include `pairing`, `heartbeat`, `metrics`, `approved`, `revoked`,
`deleted`, `settings`, `status`, `alert`. Clients should treat the event as a hint to
refresh and not depend on every reason.

### Static routes

- `GET /` or `/index.html` - full dashboard
- `GET /lite`, `/lite/`, `/lite.html` - lite dashboard
- `GET /static/<file>` - flat assets only (`app.js`, `style.css`, `lite.js`,
  `lite.webmanifest`, `favicon.svg`)

Unknown static paths return JSON `404`. The dashboard is served with a restrictive
Content Security Policy; only same-origin scripts/resources are allowed.

## Status codes

| Status | Use |
| --- | --- |
| 200 | Successful GET/POST/PUT/DELETE with a JSON body |
| 201 | Device registration created/updated |
| 202 | Metrics accepted |
| 400 | Malformed JSON, invalid payload or missing body |
| 401 | Missing/invalid credential |
| 403 | Pending approval, revoked device or wrong pairing code |
| 404 | Unknown route/device/alert |
| 413 | Body larger than 512 KiB |
| 429 | Rate limited |
| 500 | Unexpected server error |

## PowerShell examples

```powershell
$base = "http://192.0.2.10:8787"
$token = "ADMIN_TOKEN"
$headers = @{ Authorization = "Bearer $token" }

Invoke-RestMethod "$base/healthz"
Invoke-RestMethod "$base/api/v1/overview" -Headers $headers

Invoke-RestMethod "$base/api/v1/devices/DEVICE_ID/approve" `
  -Method Post -Headers $headers

Invoke-RestMethod "$base/api/v1/settings" -Method Put -Headers $headers `
  -ContentType "application/json" `
  -Body '{"heartbeat_interval":10,"metrics_interval":10}'
```

## Bash examples

```bash
BASE="http://192.0.2.10:8787"
TOKEN="ADMIN_TOKEN"

curl -s "$BASE/healthz"
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/overview"
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/v1/devices/DEVICE_ID/approve"
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"heartbeat_interval":10,"metrics_interval":10}' \
  "$BASE/api/v1/settings"
```

## Security notes

- The API is plain HTTP unless you put a TLS proxy in front of it.
- Admin credentials grant full control, including approval, revocation and deletion.
- Device tokens are per-device and cannot call admin routes.
- Rate limits are in memory and per source IP; they are not a substitute for a firewall.
- Do not put tokens in URLs except where the SSE compatibility path requires it.
- CORS is not enabled. The dashboard and API are intended to be same-origin.
