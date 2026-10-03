<#
.SYNOPSIS
    Run the web dashboard and expose it through a random Cloudflare tunnel.

.DESCRIPTION
    Two modes:

      Production (default) - one process. FastAPI serves the built SPA from
      frontend/dist and the JSON API from the same origin, so the whole app
      lives on a single port.

      -Dev - two processes. Vite serves the SPA on one port with HMR and proxies
      /api to FastAPI on 8000.

    In both modes a Cloudflare quick tunnel is started and the random
    https://<random>.trycloudflare.com URL is printed and saved.

    Press Ctrl+C to stop everything.

.PARAMETER Port
    Port for the FastAPI server. Also the tunnel target in production mode.

.PARAMETER Dev
    Use the Vite dev server instead of the built bundle. The tunnel then points
    at the Vite port instead.

.PARAMETER ForceRebuild
    Run `npm run build` even if frontend/dist already exists.

.PARAMETER NoTunnel
    Start the app locally only. Useful when you do not want it on the internet.

.PARAMETER NoBrowser
    Do not open the tunnel URL in the default browser.

.EXAMPLE
    ./run-dashboard.ps1
    ./run-dashboard.ps1 -Dev
    ./run-dashboard.ps1 -NoTunnel
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,

    [switch]$Dev,
    [switch]$ForceRebuild,
    [switch]$NoTunnel,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$RepoRoot    = Split-Path -Parent $PSCommandPath
$FrontendDir = Join-Path $RepoRoot 'frontend'
$DistIndex   = Join-Path $FrontendDir 'dist\index.html'
$LogDir      = Join-Path $RepoRoot 'logs'
$VitePort    = 5173

$children = @()   # every process started here, torn down on exit

function Write-Step { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "    $m" -ForegroundColor Green }
function Write-Warn { param([string]$m) Write-Host "    $m" -ForegroundColor Yellow }
function Write-Fail { param([string]$m) Write-Host "    $m" -ForegroundColor Red }

# Poll an HTTP endpoint until it answers 200. Starting a server and immediately
# curling it is a race; this removes the race instead of guessing a sleep.
function Wait-HttpOk {
    param(
        [string]$Url,
        [string]$Label,
        [int]$TimeoutSec = 60,
        [System.Diagnostics.Process]$Process
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { return }
        } catch {
            # not up yet
        }
        # Fail fast instead of burning the whole timeout on a process that
        # already died on startup.
        if ($Process -and $Process.HasExited) {
            throw "$Label exited immediately with code $($Process.ExitCode)."
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$Label did not answer at $Url within $TimeoutSec seconds."
}

function Get-PythonExe {
    $venv = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw 'python not found on PATH.'
}

function Get-NpmCmd {
    $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $shim = Get-Command npm -ErrorAction SilentlyContinue
    if ($shim) { return $shim.Source }
    throw 'npm not found on PATH. Install Node.js 20 or newer.'
}

function Get-Cloudflared {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        (Join-Path $RepoRoot 'tools\cloudflared.exe'),
        "$env:ProgramFiles\cloudflared\cloudflared.exe"
    )
    if (${env:ProgramFiles(x86)}) {
        $candidates += "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe"
    }
    foreach ($p in $candidates) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    return $null
}

# cloudflared prints the assigned hostname on stderr, so the error log is what
# has to be read.
function Wait-TunnelUrl {
    param(
        [string]$ErrLog,
        [int]$TimeoutSec = 45,
        [System.Diagnostics.Process]$Process
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $ErrLog) {
            $content = Get-Content -LiteralPath $ErrLog -Raw -ErrorAction SilentlyContinue
            if ($content) {
                $m = [regex]::Match($content, 'https://[a-zA-Z0-9-]+\.trycloudflare\.com')
                if ($m.Success) { return $m.Value }
            }
        }
        # cloudflared can exit immediately (bad args, no network). Surface that
        # in seconds rather than waiting out the full timeout.
        if ($Process -and $Process.HasExited) {
            $tail = ''
            if (Test-Path $ErrLog) {
                $tail = (Get-Content -LiteralPath $ErrLog -Tail 8) -join [Environment]::NewLine
            }
            throw "cloudflared exited immediately with code $($Process.ExitCode).`n$tail"
        }
        Start-Sleep -Milliseconds 400
    }
    throw "cloudflared did not report a tunnel URL within $TimeoutSec seconds. See $ErrLog"
}

# Starts a hidden child process and remembers it for teardown. Redirects are
# opt-in per call; when set, the caller tail-polls the error log for readiness.
# The argument parameter is named ArgumentList (not Arguments) to match
# Start-Process itself, so the value passed here is unambiguously the one that
# reaches the child process.
function Start-Child {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$Name,
        [string]$StdOutLog,
        [string]$StdErrLog
    )
    $startParams = @{
        FilePath         = $FilePath
        ArgumentList     = $ArgumentList
        WorkingDirectory = $WorkingDirectory
        WindowStyle      = 'Hidden'
        PassThru         = $true
    }
    if ($StdOutLog) { $startParams['RedirectStandardOutput'] = $StdOutLog }
    if ($StdErrLog) { $startParams['RedirectStandardError'] = $StdErrLog }

    Write-Ok "starting $Name"
    $p = Start-Process @startParams
    $script:children += $p
    return $p
}

# ---------------------------------------------------------------- preflight

Write-Host ''
Write-Host 'Finance Report Extractor - dashboard' -ForegroundColor White
Write-Host '--------------------------------------' -ForegroundColor DarkGray

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$python = Get-PythonExe
Write-Ok "python: $python"

# ------------------------------------------------------------------ frontend

if ($Dev) {
    if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
        Write-Step 'Installing npm dependencies'
        $npm = Get-NpmCmd
        & $npm install --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
    }
} elseif ($ForceRebuild -or -not (Test-Path $DistIndex)) {
    Write-Step 'Building frontend'
    $npm = Get-NpmCmd
    if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
        Write-Ok 'installing npm dependencies'
        & $npm install --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
    }
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw 'npm run build failed.' }
    Write-Ok "build complete -> $DistIndex"
} else {
    Write-Ok "using existing build: $DistIndex"
}

# -------------------------------------------------------------------- server

Write-Step 'Starting application'

$apiLog   = Join-Path $LogDir 'dashboard-api.log'
$viteLog  = Join-Path $LogDir 'dashboard-vite.log'
$tunOut   = Join-Path $LogDir 'tunnel.out.log'
$tunErr   = Join-Path $LogDir 'tunnel.err.log'
$urlFile  = Join-Path $LogDir 'dashboard-url.txt'

Remove-Item $tunOut, $tunErr, $urlFile -ErrorAction SilentlyContinue

try {
    $apiArgs = @('main.py', 'dashboard', '--host', '127.0.0.1', '--port', "$Port")
    $apiProc = Start-Child -FilePath $python -ArgumentList $apiArgs `
        -WorkingDirectory $RepoRoot -Name "FastAPI on :$Port" `
        -StdOutLog "$apiLog" -StdErrLog "$apiLog.err"

    Wait-HttpOk -Url "http://127.0.0.1:$Port/api/health" -Label 'FastAPI' -Process $apiProc
    Write-Ok "API healthy at http://127.0.0.1:$Port/api/health"

    # In -Dev mode FastAPI is still needed: Vite proxies /api to it.
    $targetPort = $Port
    if ($Dev) {
        $npm = Get-NpmCmd
        # Bind IPv4 explicitly. Vite's default is localhost, which on Windows can
        # resolve to ::1 only, and then 127.0.0.1 (the tunnel target) is refused.
        $viteProc = Start-Child -FilePath $npm `
            -ArgumentList @('run', 'dev', '--', '--port', "$VitePort", '--host', '127.0.0.1') `
            -WorkingDirectory $FrontendDir -Name "Vite on :$VitePort" `
            -StdOutLog "$viteLog" -StdErrLog "$viteLog.err"

        Wait-HttpOk -Url "http://127.0.0.1:$VitePort/" -Label 'Vite dev server' -Process $viteProc
        Write-Ok "Vite ready at http://127.0.0.1:$VitePort"
        $targetPort = $VitePort
    }

    # ------------------------------------------------------------------ tunnel

    $tunnelUrl = $null
    if (-not $NoTunnel) {
        $cf = Get-Cloudflared
        if (-not $cf) {
            Write-Fail 'cloudflared not found. Install it with: winget install Cloudflare.cloudflared'
            Write-Fail 'Re-run with -NoTunnel to start the app locally only.'
        } else {
            Write-Step 'Starting Cloudflare quick tunnel'
            Write-Ok "cloudflared: $cf"
            $tunProc = Start-Child -FilePath $cf `
                -ArgumentList @('tunnel', '--no-autoupdate', '--url', "http://127.0.0.1:$targetPort") `
                -WorkingDirectory $RepoRoot -Name 'quick tunnel' `
                -StdOutLog $tunOut -StdErrLog $tunErr
            $tunnelUrl = Wait-TunnelUrl -ErrLog $tunErr -Process $tunProc
        }
    }

    $localUrl = "http://127.0.0.1:$targetPort"

    Write-Host ''
    Write-Host '===============================================' -ForegroundColor Green
    if ($tunnelUrl) {
        Write-Host "  Public:  $tunnelUrl" -ForegroundColor Green
    } else {
        Write-Host '  Public:  (disabled)' -ForegroundColor DarkGray
    }
    Write-Host "  Local:   $localUrl" -ForegroundColor Green
    Write-Host "  API:     http://127.0.0.1:$Port/api/health" -ForegroundColor Green
    Write-Host "  Logs:    $LogDir" -ForegroundColor Green
    Write-Host '===============================================' -ForegroundColor Green
    Write-Host ''

    if ($tunnelUrl) {
        Write-Warn 'Anyone with this URL can read your dashboard.'
        Write-Warn 'Quick tunnels are rate-limited and meant for temporary use.'
        Set-Content -LiteralPath $urlFile -Value $tunnelUrl -Encoding utf8
        if (-not $NoBrowser) { Start-Process $tunnelUrl | Out-Null }
    }
    Write-Host 'Press Ctrl+C to stop.' -ForegroundColor DarkGray

    # Block until Ctrl+C, then fall into finally.
    while ($true) { Start-Sleep -Seconds 1 }

} finally {
    Write-Host ''
    Write-Step 'Stopping'

    foreach ($p in $children) {
        if ($p) {
            try {
                if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
            } catch { }
        }
    }

    # npm.cmd spawns node as a child, so killing npm alone can leave the Vite
    # server running. Sweep up anything still bound to this repo.
    foreach ($proc in (Get-Process python, node, cloudflared -ErrorAction SilentlyContinue)) {
        try {
            $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)").CommandLine
            if (-not $cmdline) { continue }
            $ours = $cmdline -like "*$RepoRoot*main.py*dashboard*" -or
                    $cmdline -like "*$FrontendDir*" -or
                    $cmdline -like '*cloudflared*tunnel*'
            if ($ours) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
        } catch { }
    }

    Remove-Item $urlFile -ErrorAction SilentlyContinue
    Write-Ok 'stopped'
}