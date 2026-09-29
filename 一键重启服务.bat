@echo off
cd /d "%~dp0"
title IronTrader 3.0 Restart Tool

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart.ps1"
