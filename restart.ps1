# ============================================================
# IronTrader 3.0 & Cloudflare Tunnel 一键重启与诊断工具
# ============================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 1. 检查管理员权限，若无则自动请求 UAC 提权
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[提示] 正在请求管理员权限以重启系统穿透服务..." -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

Clear-Host
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "      IronTrader 3.0 & Tunnel 一键重启与自检工具        " -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 2. 重启 Cloudflare Tunnel 服务
Write-Host "[步骤 1/3] 正在重启 Cloudflare Tunnel 穿透服务..." -ForegroundColor White
try {
    # 强制终止可能卡死的残留进程
    Stop-Process -Name "cloudflared" -Force -ErrorAction SilentlyContinue
    Restart-Service -Name "Cloudflared" -Force -ErrorAction Stop
    Write-Host "  [OK] Cloudflared Windows 系统服务已成功重启。" -ForegroundColor Green
} catch {
    Write-Host "  [!] 重启服务提示: $($_.Exception.Message)" -ForegroundColor Yellow
    Start-Service -Name "Cloudflared" -ErrorAction SilentlyContinue
}

# 3. 检查 IronTrader 本地后端 (端口 5002)
Write-Host ""
Write-Host "[步骤 2/3] 正在重启 IronTrader 本地后端服务 (端口 5002)..." -ForegroundColor White

$scriptDir = Split-Path -Parent $PSCommandPath
Set-Location $scriptDir

$pyPath = ".venv\Scripts\python.exe"
if (-not (Test-Path $pyPath)) { $pyPath = "python.exe" }
$pywPath = ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pywPath)) { $pywPath = "pythonw.exe" }

$consoleLog = Join-Path $scriptDir "logs\server_console.log"

function Test-Backend {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:5002" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

# 结束 IronTrader 后端进程：命令行含 run_background.py 的 python，以及占着 5002 端口的 python
# （之前用别的方式启动、或已卡死不响应的旧进程也会被清掉）
function Stop-Backend {
    $ids = @()
    Get-CimInstance Win32_Process | Where-Object { $_.Name -like "python*" -and $_.CommandLine -match "run_background\.py" } | ForEach-Object { $ids += $_.ProcessId }
    Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
        if ($p -and $p.ProcessName -like "python*") { $ids += $p.Id }
        elseif ($p) { Write-Host "  [!] 端口 5002 被非 Python 进程占用：$($p.ProcessName) (PID $($p.Id))，请手动处理。" -ForegroundColor Red }
    }
    $ids | Sort-Object -Unique | ForEach-Object {
        Write-Host "  - 结束旧进程 PID $_" -ForegroundColor DarkGray
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

# 后台启动并等待真正可访问（最多约 60 秒）；失败时打印 logs\server_console.log 末尾的报错
function Start-Backend {
    $env:FLASK_HOST = "0.0.0.0"
    $env:FLASK_PORT = "5002"
    $env:FLASK_DEBUG = "False"
    Start-Process -FilePath $pywPath -ArgumentList "run_background.py" -WorkingDirectory $scriptDir
    Write-Host "  正在等待服务就绪" -NoNewline
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        Write-Host "." -NoNewline
        if (Test-Backend) {
            Write-Host ""
            Write-Host "  [OK] IronTrader 后端已启动 (http://127.0.0.1:5002)。" -ForegroundColor Green
            return $true
        }
    }
    Write-Host ""
    Write-Host "  [×] 60 秒内后端没有响应，启动失败。最近的启动记录：" -ForegroundColor Red
    if (Test-Path $consoleLog) {
        Get-Content $consoleLog -Tail 25 -Encoding UTF8 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkYellow }
    } else {
        Write-Host "    （没有找到 $consoleLog）" -ForegroundColor DarkYellow
    }
    Write-Host "  也可以双击 start.bat 用前台窗口启动，直接看到报错。" -ForegroundColor Yellow
    return $false
}

# "一键重启"就是真的重启：无论旧进程是否还在响应，都结束后重新拉起，
# 这样更新代码后双击一次即可生效（旧版本在后端健康时会跳过重启，需要手动输入 R）。
if (Test-Backend) {
    Write-Host "  检测到后端正在运行，正在结束旧进程以加载最新代码..." -ForegroundColor Yellow
} else {
    Write-Host "  [!] IronTrader 本地后端没有响应，正在清理旧进程并重新拉起..." -ForegroundColor Yellow
}
Stop-Backend
if (Test-Backend) {
    Write-Host "  [×] 旧进程没能结束（端口 5002 仍在响应），新代码不会生效。请在任务管理器里结束 python/pythonw 后重试。" -ForegroundColor Red
    $backendOk = $false
} else {
    $backendOk = Start-Backend
}

# 4. 等待 Tunnel 连接注册并检测连通性
Write-Host ""
Write-Host "[步骤 3/3] 正在等待 Cloudflare 边缘节点握手建联 (约 3~5 秒)..." -ForegroundColor White
Start-Sleep -Seconds 4

# 检测本地 ready 接口
$readyConnCount = 0
try {
    $readyRaw = (Invoke-WebRequest -Uri "http://127.0.0.1:20241/ready" -TimeoutSec 3 -UseBasicParsing -ErrorAction SilentlyContinue).Content
    if ($readyRaw -match '"readyConnections":\s*(\d+)') {
        $readyConnCount = [int]$matches[1]
    }
} catch {
    $readyConnCount = 0
}

# 检测公网访问
$publicStatus = 0
try {
    $curlOut = & curl.exe -m 5 -s -o nul -w "%{http_code}" "https://irontrader.asia"
    if ($curlOut) { $publicStatus = [int]$curlOut }
} catch {
    $publicStatus = 0
}

Write-Host ""
Write-Host "======================= 诊断结果报告 =======================" -ForegroundColor Cyan

if ($readyConnCount -gt 0) {
    Write-Host " [√] Cloudflare 穿透通道 : 正常 (活跃连接数: $readyConnCount)" -ForegroundColor Green
} else {
    Write-Host " [×] Cloudflare 穿透通道 : 握手中或未建立 (请确认网络/Clash规则未阻断)" -ForegroundColor Red
}

if ($backendOk) {
    Write-Host " [√] IronTrader 本地服务 : 正常 (端口 5002 正常监听)" -ForegroundColor Green
} else {
    Write-Host " [×] IronTrader 本地服务 : 未运行（原因见上方启动记录）" -ForegroundColor Red
}

if ($publicStatus -eq 200 -or $publicStatus -eq 401) {
    Write-Host " [√] 公网域名访问测试   : 成功 (https://irontrader.asia -> HTTP $publicStatus，401 表示需要访问密钥，属正常)" -ForegroundColor Green
    Write-Host ""
    Write-Host " 恭喜！现在您可以直接访问使用: https://irontrader.asia" -ForegroundColor Yellow
} elseif ($publicStatus -eq 530) {
    Write-Host " [!] 公网域名访问测试   : HTTP 530 (穿透通道刚建立，通常再等 5~10 秒刷新即可)" -ForegroundColor Yellow
} else {
    Write-Host " [!] 公网域名访问测试   : HTTP $publicStatus (请检查外网连接)" -ForegroundColor Yellow
}
Write-Host "============================================================" -ForegroundColor Cyan

Write-Host ""
Read-Host "按 Enter 退出"
