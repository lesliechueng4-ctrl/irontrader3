@echo off
REM Quick Start - IronTrader 3.0 Public Access
REM Simple version without complex checks

title IronTrader Public Starter

echo Starting IronTrader...
start "IronTrader" cmd /k "python app.py"

timeout /t 5

echo Starting Ngrok...
start "Ngrok" cmd /k "ngrok http 5002"

echo.
echo Done! Check Ngrok window for public URL
echo.
pause
