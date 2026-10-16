# Supervises operator-owned Gateway (uvicorn on EVOFLOW_GATEWAY_PORT, default 8070).
# Root-cause aid for「连接极不稳定」: every exit is logged with exit code + timestamp,
# then the process is restarted. Pair with desktop EVOFLOW_GATEWAY_URL.
#
# Grep: ``[gateway-supervisor]``
# Log:  ``%USERPROFILE%\.evoflow-dev\logs\gateway-supervisor.log``
#       plus backend ``evoflow-gateway-*.log`` / ``[GATEWAY-EXIT]`` lines.
#
# Usage:
#   .\scripts\windows\watch-external-gateway.ps1
#   .\scripts\windows\watch-external-gateway.ps1 -Port 8070 -RestartDelaySec 3
#   # Then launch desktop with:
#   #   $env:EVOFLOW_GATEWAY_URL='http://127.0.0.1:8070'

param(
    [int] $Port = 0,
    [int] $RestartDelaySec = 3,
    [switch] $NoRestart
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
. (Join-Path $PSScriptRoot "backend-common.ps1")
Initialize-EvoFlowBackendPaths -RepoRoot $RepoRoot

if ($Port -le 0) {
    if ($env:EVOFLOW_GATEWAY_PORT -and $env:EVOFLOW_GATEWAY_PORT.Trim()) {
        [void][int]::TryParse($env:EVOFLOW_GATEWAY_PORT.Trim(), [ref]$Port)
    }
}
if ($Port -le 0) { $Port = 8070 }

$logDir = Join-Path $env:USERPROFILE ".evoflow-dev\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$supervisorLog = Join-Path $logDir "gateway-supervisor.log"
$pidFile = Join-Path $logDir "gateway-8070.pid"
if ($Port -ne 8070) {
    $pidFile = Join-Path $logDir ("gateway-{0}.pid" -f $Port)
}

function Write-SupervisorLog {
    param([string] $Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    $line = "[$ts] [gateway-supervisor] $Message"
    Add-Content -LiteralPath $supervisorLog -Value $line -Encoding UTF8
    Write-Host $line
}

$pyExe = Join-Path $script:DFBackendDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pyExe)) {
    throw "Python venv not found: $pyExe"
}

Write-SupervisorLog "begin port=$Port repo=$RepoRoot py=$pyExe restart=$(-not $NoRestart)"
Write-Host ""
Write-Host "Gateway supervisor watching :$Port" -ForegroundColor Cyan
Write-Host "  Log: $supervisorLog" -ForegroundColor DarkGray
Write-Host "  Set desktop: EVOFLOW_GATEWAY_URL=http://127.0.0.1:$Port" -ForegroundColor DarkYellow
Write-Host "  Ctrl+C to stop supervisor (and current uvicorn)." -ForegroundColor DarkGray
Write-Host ""

$generation = 0
while ($true) {
    $generation += 1
    # Free port if a zombie holds it
    try {
        $listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
        foreach ($c in @($listeners)) {
            $opid = [int]$c.OwningProcess
            if ($opid -gt 0) {
                Write-SupervisorLog "killing stale listener pid=$opid on port=$Port"
                Stop-Process -Id $opid -Force -ErrorAction SilentlyContinue
            }
        }
    } catch { }

    $env:EVOFLOW_GATEWAY_URL = "http://127.0.0.1:$Port"
    $env:EVOFLOW_GATEWAY_PORT = [string]$Port
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUNBUFFERED = "1"
    $env:PYTHONPATH = "$($script:DFBackendDir);$($script:DFBackendDir)\packages\harness"

    $day = Get-Date -Format "yyyyMMdd"
    $outLog = Join-Path $logDir ("gateway-supervisor-uvicorn-{0}.out.log" -f $day)
    $errLog = Join-Path $logDir ("gateway-supervisor-uvicorn-{0}.err.log" -f $day)
    Write-SupervisorLog "spawn gen=$generation uvicorn port=$Port out=$outLog err=$errLog"

    $p = Start-Process -FilePath $pyExe `
        -ArgumentList @("-u", "-m", "uvicorn", "app.gateway.app:app", "--host", "0.0.0.0", "--port", "$Port") `
        -WorkingDirectory $script:DFBackendDir `
        -PassThru `
        -NoNewWindow `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog

    Set-Content -LiteralPath $pidFile -Value "$($p.Id)" -Encoding ASCII
    Write-SupervisorLog "running gen=$generation pid=$($p.Id)"

    # Wait until process exits
    Wait-Process -Id $p.Id
    $code = $p.ExitCode
    if ($null -eq $code) { $code = -1 }
    Write-SupervisorLog "exit gen=$generation pid=$($p.Id) exitCode=$code — check evoflow-gateway-*.log for [GATEWAY-EXIT]"

    if ($NoRestart) {
        Write-SupervisorLog "NoRestart set; supervisor exiting"
        break
    }
    Write-SupervisorLog "restart in ${RestartDelaySec}s"
    Start-Sleep -Seconds $RestartDelaySec
}
