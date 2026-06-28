@echo off
chcp 65001 >nul
REM 放行 5002 端口（手机/局域网访问 IronTrader 所需）。双击运行，弹出 UAC 时点“是”。
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 需要管理员权限，正在请求提权...
    powershell -NoProfile -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)
echo 正在添加防火墙入站规则: IronTrader 5002 (TCP)...
netsh advfirewall firewall delete rule name="IronTrader 5002" >nul 2>&1
netsh advfirewall firewall add rule name="IronTrader 5002" dir=in action=allow protocol=TCP localport=5002 profile=any
echo.
echo 完成！现在手机连上 Tailscale 后访问: http://100.87.47.42:5002
echo.
pause
