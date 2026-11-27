# HomeMonitor admin API examples for PowerShell. Uses placeholders only.
# Usage:
#   $env:BASE = "http://192.0.2.10:8787"
#   $env:TOKEN = "ADMIN_TOKEN"
#   .\examples\api.ps1

$ErrorActionPreference = "Stop"

$base = if ($env:BASE) { $env:BASE } else { "http://192.0.2.10:8787" }
$token = if ($env:TOKEN) { $env:TOKEN } else { "ADMIN_TOKEN" }
$deviceId = if ($env:DEVICE_ID) { $env:DEVICE_ID } else { "00000000-0000-4000-8000-000000000001" }
$headers = @{ Authorization = "Bearer $token" }

Write-Host "== Health =="
Invoke-RestMethod "$base/healthz"

Write-Host "== Overview =="
Invoke-RestMethod "$base/api/v1/overview" -Headers $headers

Write-Host "== Devices =="
Invoke-RestMethod "$base/api/v1/devices" -Headers $headers

Write-Host "== Approve device =="
Invoke-RestMethod "$base/api/v1/devices/$deviceId/approve" -Method Post -Headers $headers

Write-Host "== Settings =="
Invoke-RestMethod "$base/api/v1/settings" -Headers $headers

Write-Host "== Tighten intervals =="
Invoke-RestMethod "$base/api/v1/settings" -Method Put -Headers $headers `
  -ContentType "application/json" `
  -Body '{"heartbeat_interval":5,"metrics_interval":5,"offline_after":15}'
