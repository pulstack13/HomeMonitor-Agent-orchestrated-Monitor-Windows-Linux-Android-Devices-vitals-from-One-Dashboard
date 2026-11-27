#!/usr/bin/env bash
# HomeMonitor admin API examples. Uses placeholders only.
# Usage: BASE=http://192.0.2.10:8787 TOKEN=... DEVICE_ID=... bash examples/api.sh
set -euo pipefail

BASE="${BASE:-http://192.0.2.10:8787}"
TOKEN="${TOKEN:-ADMIN_TOKEN}"
DEVICE_ID="${DEVICE_ID:-00000000-0000-4000-8000-000000000001}"
AUTH=(-H "Authorization: Bearer $TOKEN")

echo "== Health =="
curl -sS "$BASE/healthz"

echo
echo "== Overview =="
curl -sS "${AUTH[@]}" "$BASE/api/v1/overview"

echo
echo "== Devices =="
curl -sS "${AUTH[@]}" "$BASE/api/v1/devices"

echo
echo "== Approve device =="
curl -sS -X POST "${AUTH[@]}" "$BASE/api/v1/devices/$DEVICE_ID/approve"

echo
echo "== Settings =="
curl -sS "${AUTH[@]}" "$BASE/api/v1/settings"

echo
echo "== Tighten intervals =="
curl -sS -X PUT "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"heartbeat_interval":5,"metrics_interval":5,"offline_after":15}' \
  "$BASE/api/v1/settings"

echo
echo "== Revoke device (uncomment deliberately) =="
# curl -sS -X POST "${AUTH[@]}" "$BASE/api/v1/devices/$DEVICE_ID/revoke"
