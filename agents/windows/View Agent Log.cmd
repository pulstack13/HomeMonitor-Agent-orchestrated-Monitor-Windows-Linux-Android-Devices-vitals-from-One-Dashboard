@echo off
setlocal
set "LOG=%APPDATA%\HomeMonitor\logs\agent.log"
if not exist "%LOG%" (
  echo No log file yet: %LOG%
  echo Start the agent once and try again.
  echo.
  pause
  exit /b 1
)
type "%LOG%"
echo.
pause
