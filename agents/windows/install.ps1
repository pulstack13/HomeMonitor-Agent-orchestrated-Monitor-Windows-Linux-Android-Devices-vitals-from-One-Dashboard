<#
.SYNOPSIS
  Install and pair the HomeMonitor Windows agent.

.DESCRIPTION
  Copies the agent to %LOCALAPPDATA%\HomeMonitor\Agent, creates a local Python
  environment, installs psutil (offline from .\wheels when present), pairs the
  device and adds a per-user startup shortcut. No administrator rights are needed.
  Run again to repair the installation or update files.

.PARAMETER Controller
  Controller base URL, for example http://192.0.2.10:8787

.PARAMETER PairingCode
  One-time pairing code displayed by the controller.

.PARAMETER Name
  Device name shown in the dashboard. Defaults to the computer name.

.PARAMETER InstallDir
  Default: %LOCALAPPDATA%\HomeMonitor\Agent

.PARAMETER NoStartup
  Do not create the current-user startup shortcut.

.PARAMETER NoLaunch
  Do not start the agent after a successful installation.

.PARAMETER ForcePair
  Pair again even if the saved configuration already contains a token.
#>
[CmdletBinding()]
param(
    [string]$Controller = "",
    [string]$PairingCode = "",
    [string]$Name = "",
    [string]$InstallDir = "",
    [switch]$NoStartup,
    [switch]$NoLaunch,
    [switch]$ForcePair
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

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Fail "This installer only supports Windows."
}

$packageRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
foreach ($required in @("agent\__main__.py", "common\protocol.py", "requirements-agent.txt")) {
    if (-not (Test-Path (Join-Path $packageRoot $required))) {
        Fail "Missing $required. Extract the complete Windows agent package and run the installer again."
    }
}

if (-not $InstallDir) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "HomeMonitor\Agent"
}
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)
$configDir = Join-Path $env:APPDATA "HomeMonitor"
$configPath = Join-Path $configDir "agent.json"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Startup")) "HomeMonitor Agent.lnk"
$startMenuPath = Join-Path ([Environment]::GetFolderPath("Programs")) "HomeMonitor Agent.lnk"

if (-not $Controller) {
    $Controller = Read-Host "Controller URL (for example http://192.0.2.10:8787)"
}
$Controller = $Controller.Trim().TrimEnd("/")
if (-not $Controller) { Fail "A controller URL is required." }
if ($Controller -notmatch '^https?://') { $Controller = "http://$Controller" }
try {
    $uri = [Uri]$Controller
    if (-not $uri.Host) { throw "missing host" }
} catch {
    Fail "Invalid controller URL: $Controller"
}

if (-not $Name) { $Name = $env:COMPUTERNAME }
if (-not $Name) { Fail "Could not determine the computer name; pass -Name." }

$existingToken = $false
if (Test-Path $configPath) {
    try {
        $existing = Get-Content $configPath -Raw | ConvertFrom-Json
        if ($existing.token -is [string] -and $existing.token.Length -gt 0) {
            $existingToken = $true
        }
    } catch {
        $existingToken = $false
    }
}

if (-not $PairingCode -and (-not $existingToken -or $ForcePair)) {
    $PairingCode = Read-Host "Pairing code shown by the controller (for example ABCD-1234)"
    $PairingCode = $PairingCode.Trim()
    if (-not $PairingCode) { Fail "A pairing code is required for the first installation." }
}

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
        if ($LASTEXITCODE -eq 0) {
            $python = (& python -c "import sys; print(sys.executable)").Trim()
        }
    }
}
if (-not $python) {
    Fail "Python 3.10+ was not found. Run 'Install Python (winget).cmd' or install it from python.org and tick 'Add python.exe to PATH'."
}
$version = (& $python -c "import platform; print(platform.python_version())").Trim()
Write-Host "Using Python $version at $python"

Write-Step "Installing files to $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
foreach ($dir in @("agent", "common")) {
    $target = Join-Path $InstallDir $dir
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    Copy-Item (Join-Path $packageRoot $dir) $target -Recurse -Force
}
Copy-Item (Join-Path $packageRoot "requirements-agent.txt") $InstallDir -Force
$license = Join-Path $packageRoot "LICENSE"
if (Test-Path $license) { Copy-Item $license $InstallDir -Force }
$readme = Join-Path $packageRoot "docs\WINDOWS-AGENT.md"
if (Test-Path $readme) { Copy-Item $readme $InstallDir -Force }
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

& $venvPython -c "import psutil; assert tuple(map(int, psutil.__version__.split('.')[:2])) >= (5, 9)" *> $null
if ($LASTEXITCODE -ne 0) {
    $wheels = Join-Path $packageRoot "wheels"
    if (-not (Test-Path $wheels)) {
        $wheels = Join-Path $packageRoot "agents\windows\wheels"
    }
    if (Test-Path $wheels) {
        Write-Step "Installing psutil from bundled wheels"
        & $venvPython -m pip install --disable-pip-version-check -q --no-index --find-links $wheels -r (Join-Path $InstallDir "requirements-agent.txt")
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Step "Installing psutil from the internet"
        & $venvPython -m pip install --disable-pip-version-check -q -r (Join-Path $InstallDir "requirements-agent.txt")
    }
    if ($LASTEXITCODE -ne 0) { Fail "psutil installation failed. Check the network or include the wheels directory in the package." }
}

if ($PairingCode) {
    if ($existingToken -and -not $ForcePair) {
        Write-Step "Existing paired configuration found; skipping pairing"
    } else {
        Write-Step "Pairing '$Name' with $Controller"
        Push-Location $InstallDir
        try {
            & $venvPython -m agent --config $configPath --controller $Controller --pairing-code $PairingCode --name $Name --pair-only
            if ($LASTEXITCODE -ne 0) {
                Fail "Pairing failed. Check the controller URL and pairing code, then run the installer again."
            }
        } finally {
            Pop-Location
        }
        Write-Host "Pairing saved. Approve '$Name' in the dashboard." -ForegroundColor Yellow
    }
} elseif ($existingToken) {
    Write-Step "Existing paired configuration found; keeping it"
} else {
    Fail "No pairing code was supplied."
}

if (-not $NoStartup) {
    Write-Step "Installing the current-user startup shortcut"
    $shell = New-Object -ComObject WScript.Shell
    foreach ($path in @($shortcutPath, $startMenuPath)) {
        $shortcut = $shell.CreateShortcut($path)
        $shortcut.TargetPath = $venvPythonw
        $shortcut.Arguments = "-m agent --config `"$configPath`""
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.WindowStyle = 7
        $shortcut.Description = "HomeMonitor device agent"
        $shortcut.Save()
    }
}

if (-not $NoLaunch) {
    Write-Step "Starting the agent in the background"
    $running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$InstallDir*" -and $_.CommandLine -like "*-m agent*" }
    if (-not $running) {
        Start-Process -FilePath $venvPythonw -ArgumentList @("-m", "agent", "--config", $configPath) -WorkingDirectory $InstallDir -WindowStyle Hidden
    }
}

Write-Host ""
Write-Host "HomeMonitor Windows agent installed." -ForegroundColor Green
Write-Host "  Device   : $Name"
Write-Host "  Server   : $Controller"
Write-Host "  Agent    : $InstallDir"
Write-Host "  Config   : $configPath"
Write-Host "  Log      : $(Join-Path $configDir 'logs\agent.log')"
Write-Host "  Startup  : $(if ($NoStartup) { 'not installed' } else { $shortcutPath })"
Write-Host ""
Write-Host "Open the dashboard and approve the device if it is still pending."
Write-Host "To remove it later, run 'Uninstall HomeMonitor Agent.cmd'."
