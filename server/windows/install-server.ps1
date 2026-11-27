<#
.SYNOPSIS
  Install the HomeMonitor central server on Windows for the current user.

.DESCRIPTION
  Copies the server into %LOCALAPPDATA%\HomeMonitor\Server, creates a local
  Python environment, starts it hidden, and adds a startup shortcut. No
  administrator rights are required. The service starts when this user signs in.

.PARAMETER Port
  HTTP port. Default 8787.

.PARAMETER Bind
  Bind address. Default 0.0.0.0 (dashboard reachable on the LAN).

.PARAMETER NoStartup
  Do not create the sign-in startup shortcut.

.PARAMETER NoLaunch
  Do not start the server after installation.
#>
[CmdletBinding()]
param(
    [int]$Port = 8787,
    [string]$Bind = "0.0.0.0",
    [switch]$NoStartup,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}
function Fail([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { Fail "Windows only." }
if ($Port -lt 1 -or $Port -gt 65535) { Fail "Port must be 1-65535." }

$packageRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
foreach ($required in @("server\__main__.py", "common\protocol.py", "dashboard\index.html")) {
    if (-not (Test-Path (Join-Path $packageRoot $required))) {
        Fail "Missing $required. Extract the complete server package first."
    }
}
if (-not $Bind) { $Bind = "0.0.0.0" }

$InstallDir = Join-Path $env:LOCALAPPDATA "HomeMonitor\Server"
$DataDir = Join-Path $env:LOCALAPPDATA "HomeMonitor\ServerData"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Startup")) "HomeMonitor Server.lnk"
$consoleShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "HomeMonitor Server Console.lnk"
$dashboardShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "HomeMonitor Dashboard.lnk"

Write-Step "Checking Python"
$python = $null
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    foreach ($candidate in @("3.15", "3.14", "3.13", "3.12", "3.11", "3.10")) {
        & py "-$candidate" -c "import sys; print(sys.executable)" *> $null
        if ($LASTEXITCODE -eq 0) {
            $python = (& py "-$candidate" -c "import sys; print(sys.executable)").Trim()
            break
        }
    }
}
if (-not $python) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) { $python = (& python -c "import sys; print(sys.executable)").Trim() }
    }
}
if (-not $python) {
    Fail "Python 3.10+ was not found. Install Python from python.org (tick 'Add python.exe to PATH')."
}

Write-Step "Installing server files"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
foreach ($dir in @("server", "common", "dashboard")) {
    $target = Join-Path $InstallDir $dir
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    Copy-Item (Join-Path $packageRoot $dir) $target -Recurse -Force
}
foreach ($file in @("LICENSE", "README.md")) {
    $sourceFile = Join-Path $packageRoot $file
    if (Test-Path $sourceFile) { Copy-Item $sourceFile $InstallDir -Force }
}
Get-ChildItem $InstallDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$venv = Join-Path $InstallDir ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
$venvPythonw = Join-Path $venv "Scripts\pythonw.exe"
if (-not (Test-Path $venvPython)) {
    Write-Step "Creating the local Python environment"
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the virtual environment." }
}

$runScript = Join-Path $InstallDir "Run Server Console.cmd"
@"
@echo off
setlocal
title HomeMonitor Server
cd /d "%~dp0"
".venv\Scripts\python.exe" -m server --data-dir "$DataDir" --host $Bind --port $Port
echo.
echo Server stopped. Press any key to close.
pause
"@ | Set-Content -Path $runScript -Encoding ASCII

$serverArgs = "-m server --data-dir `"$DataDir`" --host $Bind --port $Port"

Write-Step "Stopping an older installed HomeMonitor server"
$old = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$InstallDir*" -and $_.CommandLine -like "*-m server*" }
foreach ($process in $old) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 500

if (-not $NoStartup) {
    Write-Step "Installing the sign-in startup shortcut"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $venvPythonw
    $shortcut.Arguments = $serverArgs
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.WindowStyle = 7
    $shortcut.Description = "HomeMonitor central server"
    $shortcut.Save()

    $console = $shell.CreateShortcut($consoleShortcut)
    $console.TargetPath = $runScript
    $console.WorkingDirectory = $InstallDir
    $console.Description = "Show the HomeMonitor server console"
    $console.Save()

    $dashboard = $shell.CreateShortcut($dashboardShortcut)
    $dashboard.TargetPath = "http://127.0.0.1:$Port/"
    $dashboard.Description = "Open the HomeMonitor dashboard"
    $dashboard.Save()
}

if (-not $NoLaunch) {
    Write-Step "Starting the server in the background"
    Start-Process -FilePath $venvPythonw -ArgumentList $serverArgs -WorkingDirectory $InstallDir -WindowStyle Hidden
    for ($i = 0; $i -lt 20; $i++) {
        if (Test-Path (Join-Path $DataDir "config.json")) { break }
        Start-Sleep -Milliseconds 500
    }
}

$configPath = Join-Path $DataDir "config.json"
$pairPath = Join-Path $DataDir "pairing_code.txt"
$adminToken = ""
$pairCode = ""
if (Test-Path $configPath) {
    try { $adminToken = (Get-Content $configPath -Raw | ConvertFrom-Json).admin_token } catch {}
}
if (Test-Path $pairPath) { $pairCode = (Get-Content $pairPath -Raw).Trim() }

Write-Host ""
Write-Host "HomeMonitor server installed." -ForegroundColor Green
Write-Host "  Install   : $InstallDir"
Write-Host "  Data      : $DataDir"
Write-Host "  Dashboard : http://127.0.0.1:$Port/"
Write-Host "  LAN URL   : http://<this-pc-lan-ip>:$Port/"
Write-Host "  Admin     : $adminToken"
Write-Host "  Pair code : $pairCode"
Write-Host "  Log       : $(Join-Path $DataDir 'controller.log')"
Write-Host "  Startup   : $(if ($NoStartup) { 'not installed' } else { $shortcutPath })"
Write-Host ""
Write-Host "If Windows Firewall asks, allow Python on Private networks only."
Write-Host "Do not port-forward this server; use a VPN plus a TLS reverse proxy for remote access."
