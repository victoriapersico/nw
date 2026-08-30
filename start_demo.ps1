<#
Starts the complete local NextWave demo without requiring manual activation of
the virtual environment. Telegram remains opt-in through the local .env file.

Examples:
  .\start_demo.ps1
  .\start_demo.ps1 -ApiPort 8003 -DashboardPort 8503
  .\start_demo.ps1 -ApiPort 8004 -DashboardPort 8504 -YunoDashboardPort 8505
  powershell -ExecutionPolicy Bypass -File .\start_demo.ps1
#>

[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8000,

    [ValidateRange(1, 65535)]
    [int]$DashboardPort = 8501,

    [ValidateRange(1, 65535)]
    [int]$YunoDashboardPort = 8502,

    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ApiUrl = "http://127.0.0.1:$ApiPort"
$DashboardUrl = "http://127.0.0.1:$DashboardPort"
$YunoDashboardUrl = "http://127.0.0.1:$YunoDashboardPort"
$LogDirectory = Join-Path ([System.IO.Path]::GetTempPath()) "nextwave-control-tower"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Virtual environment not found at $PythonExe. Create it first with: python -m venv .venv"
}

if ($DashboardPort -eq $YunoDashboardPort) {
    throw "DashboardPort and YunoDashboardPort must be different."
}

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null

# python-dotenv does not override process variables, so both child processes
# receive one shared API URL even if .env contains a different local port.
$env:CONTROL_TOWER_API_URL = $ApiUrl

function Test-LocalPortListening {
    param([int]$Port)

    return $null -ne (
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
    )
}

function Wait-ForApiHealth {
    param([string]$Url)

    foreach ($attempt in 1..30) {
        try {
            $health = Invoke-RestMethod -Uri "$Url/health" -TimeoutSec 2
            if ($null -ne $health) {
                return $true
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

if (Test-LocalPortListening -Port $ApiPort) {
    Write-Host "API port $ApiPort is already listening; reusing the existing process."
}
else {
    $backendLog = Join-Path $LogDirectory "backend-$ApiPort.log"
    $backendErrorLog = Join-Path $LogDirectory "backend-$ApiPort.error.log"
    Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @("-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendLog `
        -RedirectStandardError $backendErrorLog
    Write-Host "Starting FastAPI on $ApiUrl ..."
}

if (-not (Wait-ForApiHealth -Url $ApiUrl)) {
    throw "FastAPI did not become healthy. Check $LogDirectory for backend logs."
}

if (Test-LocalPortListening -Port $DashboardPort) {
    Write-Host "Dashboard port $DashboardPort is already listening; reusing the existing process."
}
else {
    $frontendLog = Join-Path $LogDirectory "frontend-$DashboardPort.log"
    $frontendErrorLog = Join-Path $LogDirectory "frontend-$DashboardPort.error.log"
    Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @("-m", "streamlit", "run", "frontend/app.py", "--server.address", "127.0.0.1", "--server.port", "$DashboardPort", "--server.headless", "true") `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendLog `
        -RedirectStandardError $frontendErrorLog
    Write-Host "Starting Streamlit on $DashboardUrl ..."
}

if (Test-LocalPortListening -Port $YunoDashboardPort) {
    Write-Host "Yuno API Manager port $YunoDashboardPort is already listening; reusing the existing process."
}
else {
    $yunoLog = Join-Path $LogDirectory "yuno-dashboard-$YunoDashboardPort.log"
    $yunoErrorLog = Join-Path $LogDirectory "yuno-dashboard-$YunoDashboardPort.error.log"
    Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @("-m", "streamlit", "run", "frontend/yuno_demo.py", "--server.address", "127.0.0.1", "--server.port", "$YunoDashboardPort", "--server.headless", "true") `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $yunoLog `
        -RedirectStandardError $yunoErrorLog
    Write-Host "Starting Yuno API Manager on $YunoDashboardUrl ..."
}

Write-Host ""
Write-Host "NextWave is ready:"
Write-Host "  Dashboard: $DashboardUrl"
Write-Host "  Yuno API Manager: $YunoDashboardUrl"
Write-Host "  API docs:  $ApiUrl/docs"
Write-Host "  Logs:      $LogDirectory"
Write-Host ""
Write-Host "Telegram is enabled only when its four TELEGRAM_* values are set in .env."

if (-not $NoBrowser) {
    Start-Process $DashboardUrl
}
