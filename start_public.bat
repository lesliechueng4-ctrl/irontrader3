@echo off
chcp 65001 >nul
REM IronTrader 3.0 - Start Public Access

echo.
echo ===================================
echo   IronTrader 3.0 Public Access
echo ===================================
echo.

REM Check if Ngrok is installed
where ngrok >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Ngrok not found!
    echo.
    echo Please install Ngrok first:
    echo 1. Visit https://ngrok.com/download
    echo 2. Download and extract
    echo 3. Add ngrok.exe to system PATH
    echo.
    pause
    exit /b 1
)

REM Check if Python is installed
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found!
    pause
    exit /b 1
)

echo [1/3] Starting IronTrader App...
start "IronTrader-App" cmd /k "cd /d %~dp0 && python app.py"

echo [2/3] Waiting for app to start...
ping 127.0.0.1 -n 6 >nul

echo [3/3] Starting Ngrok Tunnel...
start "Ngrok-Tunnel" cmd /k "ngrok http 5002"

echo.
echo ===================================
echo   Startup Complete!
echo ===================================
echo.
echo How to use:
echo 1. Check "Ngrok-Tunnel" window for public URL
echo 2. URL format: https://xxxx.ngrok-free.app
echo 3. Open this URL on your phone!
echo.
echo Tips:
echo - Local access: http://localhost:5002
echo - Stop service: Run stop_public.bat
echo.
pause
