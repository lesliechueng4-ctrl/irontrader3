[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not $Python) {
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $Python = if (Test-Path $venvPython) { $venvPython } else { "python" }
}

& $Python -m pip install -r requirements-build.txt

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --specpath build `
    --onedir `
    --console `
    --name IronTrader `
    --add-data "templates;templates" `
    --add-data "static;static" `
    --hidden-import wash_pattern_scanner `
    --hidden-import stock_screener_2 `
    --collect-all akshare `
    --collect-all ta `
    --collect-all flask `
    --collect-all flask_cors `
    --collect-all flask_compress `
    --collect-all waitress `
    desktop_launcher.py

$distDir = Join-Path $projectRoot "dist\IronTrader"
Copy-Item (Join-Path $projectRoot "PACKAGING.md") (Join-Path $distDir "README.txt") -Force
Compress-Archive -Path $distDir -DestinationPath (Join-Path $projectRoot "dist\IronTrader-Windows.zip") -Force

Write-Host "Build complete: $distDir"
Write-Host "Portable archive: $projectRoot\dist\IronTrader-Windows.zip"
