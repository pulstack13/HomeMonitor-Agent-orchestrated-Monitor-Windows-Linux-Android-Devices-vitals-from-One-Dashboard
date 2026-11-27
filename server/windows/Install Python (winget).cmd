@echo off
setlocal
title Install Python for HomeMonitor
where py >nul 2>&1
if not errorlevel 1 (
  echo Python is already installed:
  py -3 --version
  echo.
  pause
  exit /b 0
)
where winget >nul 2>&1
if errorlevel 1 (
  echo winget is not available.
  echo Install Python 3.12 from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
echo.
echo Close this window and run Install HomeMonitor Server.cmd.
pause
