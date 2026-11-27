@echo off
setlocal
title HomeMonitor Server Setup
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-server.ps1" %*
echo.
pause
