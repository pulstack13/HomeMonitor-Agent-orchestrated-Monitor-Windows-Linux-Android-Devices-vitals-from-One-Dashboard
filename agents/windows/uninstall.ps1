[CmdletBinding()]
param(
    [switch]$RemoveConfig
)

$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "HomeMonitor\Agent"
$configDir = Join-Path $env:APPDATA "HomeMonitor"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Startup")) "HomeMonitor Agent.lnk"
$startMenuPath = Join-Path ([Environment]::GetFolderPath("Programs")) "HomeMonitor Agent.lnk"

Write-Host "Stopping the HomeMonitor agent..."
$processes = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$InstallDir*" -and $_.CommandLine -like "*-m agent*" }
foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 500

foreach ($path in @($shortcutPath, $startMenuPath)) {
    if (Test-Path $path) {
        Remove-Item $path -Force
        Write-Host "Removed $path"
    }
}

if (Test-Path $InstallDir) {
    Remove-Item $InstallDir -Recurse -Force
    Write-Host "Removed $InstallDir"
}

if ($RemoveConfig) {
    if (Test-Path $configDir) {
        Remove-Item $configDir -Recurse -Force
        Write-Host "Removed agent configuration, logs and token ($configDir)"
    }
} else {
    Write-Host "Kept configuration and logs in $configDir"
    Write-Host "Run again with -RemoveConfig to delete the saved token and logs."
}

Write-Host ""
Write-Host "Uninstall complete. The device may remain in the controller database;"
Write-Host "delete or revoke it from the dashboard's device access page."
