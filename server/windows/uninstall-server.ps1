[CmdletBinding()]
param(
    [switch]$Purge
)

$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "HomeMonitor\Server"
$DataDir = Join-Path $env:LOCALAPPDATA "HomeMonitor\ServerData"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Startup")) "HomeMonitor Server.lnk"
$consoleShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "HomeMonitor Server Console.lnk"
$dashboardShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "HomeMonitor Dashboard.lnk"

Write-Host "Stopping the HomeMonitor server..."
$processes = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$InstallDir*" -and $_.CommandLine -like "*-m server*" }
foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 800

foreach ($path in @($shortcutPath, $consoleShortcut, $dashboardShortcut)) {
    if (Test-Path $path) {
        Remove-Item $path -Force
        Write-Host "Removed $path"
    }
}
if (Test-Path $InstallDir) {
    Remove-Item $InstallDir -Recurse -Force
    Write-Host "Removed $InstallDir"
}

if ($Purge) {
    if (Test-Path $DataDir) {
        Remove-Item $DataDir -Recurse -Force
        Write-Host "Removed database, admin token and pairing code ($DataDir)"
    }
} else {
    Write-Host "Kept database and credentials in $DataDir"
    Write-Host "Run again with -Purge to delete them."
}

Write-Host ""
Write-Host "Uninstall complete."
