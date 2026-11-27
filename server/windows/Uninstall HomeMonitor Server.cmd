@echo off
setlocal
title HomeMonitor Server Uninstall
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall-server.ps1" %*
echo.
pause
