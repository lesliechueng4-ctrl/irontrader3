# IronTrader 3.0 - 一键启动公网访问
# 自动启动应用和 Ngrok

Write-Host "`n=== IronTrader 3.0 公网启动 ===" -ForegroundColor Green
Write-Host "正在启动 IronTrader 和 Ngrok...`n" -ForegroundColor Cyan

# 检查 Ngrok 是否安装
$ngrokExists = Get-Command ngrok -ErrorAction SilentlyContinue
if (-not $ngrokExists) {
    Write-Host "❌ 未检测到 Ngrok，请先安装！" -ForegroundColor Red
    Write-Host "`n下载地址: https://ngrok.com/download" -ForegroundColor Yellow
    Write-Host "或使用 Chocolatey 安装: choco install ngrok`n" -ForegroundColor Yellow
    Read-Host "按回车键退出"
    exit
}

# 检查 Python 是否安装
$pythonExists = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonExists) {
    Write-Host "❌ 未检测到 Python！" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit
}

# 启动 IronTrader
Write-Host "✅ 启动 IronTrader 应用..." -ForegroundColor Green
$appProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; python app.py" -PassThru

# 等待应用启动
Write-Host "⏳ 等待应用启动 (5秒)..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# 启动 Ngrok
Write-Host "✅ 启动 Ngrok 隧道..." -ForegroundColor Green
$ngrokProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", "ngrok http 5002" -PassThru

# 等待 Ngrok 启动
Start-Sleep -Seconds 3

Write-Host "`n=== 启动完成！ ===" -ForegroundColor Green
Write-Host "`n📱 使用说明:" -ForegroundColor Cyan
Write-Host "1. 查看 Ngrok 窗口中的公网地址（Forwarding 行）"
Write-Host "2. 地址格式类似: https://xxxx-xx-xxx-xxx-xx.ngrok-free.app"
Write-Host "3. 用手机浏览器访问该地址即可！"
Write-Host "`n💡 提示:" -ForegroundColor Yellow
Write-Host "- 本地访问: http://localhost:5002"
Write-Host "- 查看日志: tail -f logs/irontrader_*.log"
Write-Host "- 停止服务: 关闭两个 PowerShell 窗口"
Write-Host "`n按 Ctrl+C 退出此窗口（不影响服务运行）`n"

# 保持脚本运行
try {
    while ($true) {
        Start-Sleep -Seconds 10

        # 检查进程是否还在运行
        if (-not (Get-Process -Id $appProcess.Id -ErrorAction SilentlyContinue)) {
            Write-Host "⚠️ IronTrader 已停止" -ForegroundColor Yellow
            break
        }
    }
}
finally {
    Write-Host "`n脚本已退出（服务仍在运行）" -ForegroundColor Cyan
}
