@echo off
chcp 65001 >nul
title IronTrader 3.0 启动器
cd /d "%~dp0"

REM ============================================================
REM  IronTrader 3.0 统一本地启动入口（仅本机访问，不对外暴露）
REM  双击运行；服务在本窗口前台运行，关闭窗口或按 Ctrl+C 即停止。
REM ============================================================

REM 优先使用项目虚拟环境的 Python
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

REM 本地运行配置：仅监听 127.0.0.1，调试模式关闭
set "FLASK_HOST=127.0.0.1"
set "FLASK_PORT=5002"
set "FLASK_DEBUG=False"

echo.
echo ===================================
echo   IronTrader 3.0  本地启动
echo ===================================
echo.

echo [1/3] 停止已在运行的旧实例（含遗留的后台进程）...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'run_background\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo [2/3] 打开浏览器 http://localhost:%FLASK_PORT% （服务启动需几秒，若提示无法连接请稍后按 Ctrl+F5 刷新）...
start "" "http://localhost:%FLASK_PORT%"

echo [3/3] 启动服务（关闭本窗口或按 Ctrl+C 即停止）...
echo.
"%PY%" run_background.py

echo.
echo 服务已停止。
pause
