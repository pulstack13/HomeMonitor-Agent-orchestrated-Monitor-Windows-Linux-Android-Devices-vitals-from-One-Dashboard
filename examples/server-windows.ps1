# Start a controller from a source checkout on Windows.
# Run from the repository root in PowerShell. This does not install a service.
$env:HOMEMONITOR_DATA_DIR = "$PWD\data-dev"
$env:HOMEMONITOR_HOST = "0.0.0.0"
$env:HOMEMONITOR_PORT = "8788"
$env:HOMEMONITOR_DISCOVERY = "0"

# Use the virtual environment if one exists, otherwise python on PATH.
$python = if (Test-Path ".\.venv\Scripts\python.exe") {
    ".\.venv\Scripts\python.exe"
} else {
    "python"
}

& $python -m server --data-dir $env:HOMEMONITOR_DATA_DIR --port 8788 --no-discovery
