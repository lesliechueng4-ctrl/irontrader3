@echo off
chcp 65001 >nul
REM ============================================================
REM  每周自动回测：把新一周的样本并入样本库 outputs\backtest_samples.csv
REM  由 Windows 任务计划程序每周调用一次（见 register_backtest_task.bat）。
REM ============================================================
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "outputs" mkdir "outputs"

REM days=10：覆盖最近约两周(与上轮重叠)，按 (date,code) 去重，确保不漏不重
"%PY%" backtest_study.py --days 10 --horizons 1,3,5 --accumulate "outputs\backtest_samples.csv" >> "outputs\backtest_weekly.out.log" 2>&1
