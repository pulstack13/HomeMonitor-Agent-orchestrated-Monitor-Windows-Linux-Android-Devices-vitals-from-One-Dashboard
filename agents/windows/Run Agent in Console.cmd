@echo off
setlocal
title HomeMonitor Agent Console
set "AGENT_DIR=%LOCALAPPDATA%\HomeMonitor\Agent"
if not exist "%AGENT_DIR%\.venv\Scripts\python.exe" (
  echo The agent is not installed. Run Install HomeMonitor Agent.cmd first.
  echo.
  pause
  exit /b 2
)
cd /d "%AGENT_DIR%"
".venv\Scripts\python.exe" -m agent
echo.
echo The agent stopped. Press any key to close.
pause
