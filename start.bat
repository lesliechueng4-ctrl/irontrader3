@echo off
chcp 65001 >nul
title IronTrader 3.0 启动器
cd /d "%~dp0"

REM ============================================================
REM  IronTrader 3.0 统一本地启动入口（仅本机访问，不对外暴露）
REM  双击本文件即可启动；关闭弹出的 "IronTrader-Server" 窗口即停止。
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

echo [1/3] 释放 %FLASK_PORT% 端口上的旧实例（确保加载最新代码/页面）...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%FLASK_PORT%" ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

echo [2/3] 启动服务...
start "IronTrader-Server" cmd /k ""%PY%" run_background.py"

echo [3/3] 等待服务就绪并打开浏览器...
ping 127.0.0.1 -n 5 >nul
start "" "http://localhost:%FLASK_PORT%"

echo.
echo 启动完成！
echo   - 本地地址: http://localhost:%FLASK_PORT%
echo   - 停止服务: 关闭标题为 "IronTrader-Server" 的窗口
echo   - 若页面未更新，请在浏览器按 Ctrl+F5 强制刷新
echo.
timeout /t 4 >nul
