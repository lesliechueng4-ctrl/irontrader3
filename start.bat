@echo off
chcp 65001 >nul
cd /d "%~dp0" || (
  echo Failed to enter project directory: %~dp0
  pause
  exit /b 1
)
title IronTrader 3.0 Launcher

REM ============================================================
REM  IronTrader 3.0 local launcher.
REM  Keep this file ASCII-only so Windows cmd can parse it safely.
REM  Close this window or press Ctrl+C to stop the service.
REM ============================================================

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "FLASK_HOST=0.0.0.0"
set "FLASK_PORT=5002"
set "FLASK_DEBUG=False"

echo.
echo ===================================
echo   IronTrader 3.0 local startup
echo ===================================
echo.

echo [1/3] Stopping old background instance if one is still running...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'run_background\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo [2/3] Opening browser: http://localhost:%FLASK_PORT%
start "" "http://localhost:%FLASK_PORT%"

echo [3/3] Starting service. Close this window or press Ctrl+C to stop.
echo.
"%PY%" run_background.py

echo.
echo Service stopped.
pause
