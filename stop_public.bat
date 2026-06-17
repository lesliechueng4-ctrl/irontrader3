@echo off
chcp 65001 >nul
REM IronTrader 3.0 - Stop All Services

echo.
echo ===================================
echo   Stop IronTrader Services
echo ===================================
echo.

echo Stopping Python processes...
taskkill /F /IM python.exe >nul 2>&1

echo Stopping Ngrok processes...
taskkill /F /IM ngrok.exe >nul 2>&1

echo.
echo Services stopped successfully!
echo.
timeout /t 2 >nul
