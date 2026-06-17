# IronTrader 3.0 - 停止所有服务

Write-Host "`n=== 停止 IronTrader 服务 ===" -ForegroundColor Yellow

# 停止 Python 进程
Write-Host "正在停止 IronTrader..." -ForegroundColor Cyan
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*$PSScriptRoot*" } | Stop-Process -Force

# 停止 Ngrok 进程
Write-Host "正在停止 Ngrok..." -ForegroundColor Cyan
Get-Process -Name ngrok -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "`n✅ 所有服务已停止！" -ForegroundColor Green
Start-Sleep -Seconds 2
