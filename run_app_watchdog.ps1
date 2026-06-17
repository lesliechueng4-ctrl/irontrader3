$ErrorActionPreference = "Continue"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Runner = Join-Path $ProjectRoot "run_background.py"
$LogPath = Join-Path $ProjectRoot "app.background.log"
$PidPath = Join-Path $ProjectRoot "app.background.pid"

Set-Location $ProjectRoot

while ($true) {
    $startedAt = Get-Date -Format o
    "[$startedAt] starting IronTrader3 background app" | Out-File -LiteralPath $LogPath -Append -Encoding utf8

    try {
        $process = Start-Process -FilePath $Python `
            -ArgumentList @("-u", $Runner) `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -PassThru

        Set-Content -LiteralPath $PidPath -Value $process.Id -Encoding ascii
        Wait-Process -Id $process.Id

        $exitAt = Get-Date -Format o
        "[$exitAt] app process exited; restarting in 5 seconds" | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    }
    catch {
        $errorAt = Get-Date -Format o
        "[$errorAt] watchdog error: $($_.Exception.Message)" | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    }

    Start-Sleep -Seconds 5
}
