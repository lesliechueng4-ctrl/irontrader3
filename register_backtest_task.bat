@echo off
chcp 65001 >nul
REM 注册/更新"每周自动回测"的 Windows 计划任务（每周六 18:00）。双击即可。
schtasks /Create /SC WEEKLY /D SAT /ST 18:00 /F ^
 /TN "IronTrader\WeeklyBacktest" ^
 /TR "\"%~dp0run_backtest_weekly.bat\""
echo.
if %errorlevel%==0 (
    echo [OK] 已注册：每周六 18:00 自动回测，结果累积到 outputs\backtest_samples.csv
    echo 立即试跑一次： schtasks /Run /TN "IronTrader\WeeklyBacktest"
    echo 查看任务：     schtasks /Query /TN "IronTrader\WeeklyBacktest"
    echo 删除任务：     schtasks /Delete /TN "IronTrader\WeeklyBacktest" /F
) else (
    echo [FAIL] 注册失败。若提示权限不足，请右键“以管理员身份运行”本文件。
)
echo.
pause
