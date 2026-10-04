<#
.SYNOPSIS
    Run the web dashboard and expose it through a random Cloudflare tunnel.

.DESCRIPTION
    Two modes:

      Hot reload (default) - two processes on the same public port you already
      use. Vite owns -Port and serves the SPA with HMR, proxying /api to FastAPI
      on an internal port that runs with uvicorn's reloader. Editing anything
      under app/ or frontend/src/ takes effect immediately, with no restart and
      therefore no new tunnel URL. The URL is only ever changed by restarting
      the script, so a bookmark or shared link keeps working.

      -Production - one process. FastAPI serves the prebuilt bundle from
      frontend/dist and the JSON API from the same origin. Use this to check the
      real build, or on a machine with no Node toolchain. Edits need a rebuild
      (and -ForceRebuild, since an existing dist is otherwise reused).

    In both modes a Cloudflare quick tunnel is started and the random
    https://<random>.trycloudflare.com URL is printed and saved.

    Press Ctrl+C to stop everything.

.PARAMETER Port
    The public port: the one you open in the browser and the one the tunnel
    points at. Unchanged by the mode, so the URL does not move.

.PARAMETER Production
    Serve the built bundle from FastAPI instead of running the dev server. No
    hot reload.

.PARAMETER Dev
    Deprecated and ignored. Hot reload is now the default; -Production is the
    opposite of what -Dev used to mean, so pass that instead.

.PARAMETER ForceRebuild
    Run `npm run build` even if frontend/dist already exists.

.PARAMETER NoTunnel
    Start the app locally only. Useful when you do not want it on the internet.

.PARAMETER NoBrowser
    Do not open the tunnel URL in the default browser.

.EXAMPLE
    ./run-dashboard.ps1
    ./run-dashboard.ps1 -Production
    ./run-dashboard.ps1 -NoTunnel
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,

    [switch]$Production,
    [switch]$Dev,
    [switch]$ForceRebuild,
    [switch]$NoTunnel,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

# Hot reload unless the caller explicitly asked for the built bundle. -Dev used
# to select this and is kept only so an old command line does not silently do
# the opposite of what it says.
$HotReload = -not $Production
if ($Dev -and $Production) {
    throw '-Dev and -Production ask for opposite things. -Dev is now the default, so drop it.'
}

$RepoRoot    = Split-Path -Parent $PSCommandPath
$FrontendDir = Join-Path $RepoRoot 'frontend'
$DistIndex   = Join-Path $FrontendDir 'dist\index.html'
$LogDir      = Join-Path $RepoRoot 'logs'

# The port the browser and the tunnel use, in both modes.
$PublicPort  = $Port
# Where FastAPI listens. In production that is the public port; with hot reload
# Vite has to own it, so the API moves behind the proxy and takes a free port of
# its own, resolved once the helpers below are defined.
$ApiPort     = $Port

$children = @()   # every process started here, torn down on exit

function Write-Step { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "    $m" -ForegroundColor Green }
function Write-Warn { param([string]$m) Write-Host "    $m" -ForegroundColor Yellow }
function Write-Fail { param([string]$m) Write-Host "    $m" -ForegroundColor Red }

# An unused TCP port on the loopback interface. The API port is internal and
# never typed by hand, so letting the OS pick it removes any chance of
# colliding with something already listening on the usual +1 guess.
function Get-FreePort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try { return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port }
    finally { $listener.Stop() }
}

# True when something is already listening. Vite runs with --strictPort so it
# fails loudly rather than quietly sliding to another port and breaking the one
# URL that is meant to stay put.
function Test-PortBusy {
    param([int]$CheckPort)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync('127.0.0.1', $CheckPort)
        return $task.Wait(500) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

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

if ($HotReload) {
    # Nothing to build: the dev server compiles on demand and pushes updates
    # over HMR, which is the whole reason this mode needs no restart.
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

# Preflight, deliberately outside the try: if the public port is taken we must
# bail out without reaching the teardown below, which would otherwise sweep up
# the very process we just complained about. Refusing to start must never be the
# thing that stops what is already running.
if (Test-PortBusy -CheckPort $PublicPort) {
    throw "Port $PublicPort is already in use. Stop whatever is listening there, or pass -Port <n>."
}

if ($HotReload) {
    # Picked up front rather than passed as --port 0: the port has to be known to
    # configure the dev server's proxy and to tell the reader where the API is,
    # and a port the OS chose at bind time is announced too late for either.
    $ApiPort = Get-FreePort
    Write-Ok "api port: $ApiPort (internal, proxied by Vite on :$PublicPort)"
}

try {
    $apiArgs = @('main.py', 'dashboard', '--host', '127.0.0.1', '--port', "$ApiPort")
    if ($HotReload) {
        # The reloader is what makes a backend edit take effect on its own.
        $apiArgs += '--reload'
    }

    $apiProc = Start-Child -FilePath $python -ArgumentList $apiArgs `
        -WorkingDirectory $RepoRoot -Name "FastAPI on :$ApiPort" `
        -StdOutLog "$apiLog" -StdErrLog "$apiLog.err"

    Wait-HttpOk -Url "http://127.0.0.1:$ApiPort/api/health" -Label 'FastAPI' -Process $apiProc
    Write-Ok "API healthy at http://127.0.0.1:$ApiPort/api/health"

    # The public port is the same number in both modes, so a bookmarked URL and
    # a shared tunnel link keep working when the mode changes.
    $targetPort = $PublicPort

    if ($HotReload) {
        $npm = Get-NpmCmd
        # Bind IPv4 explicitly. Vite's default is localhost, which on Windows can
        # resolve to ::1 only, and then 127.0.0.1 (the tunnel target) is refused.
        # FITRI_API_PORT tells the dev server where the API actually ended up,
        # since it is no longer the obvious :8000.
        $env:FITRI_API_PORT = "$ApiPort"
        $env:FITRI_UI_PORT  = "$PublicPort"
        # --strictPort so a busy port is an error rather than a silent move to a
        # different port, which would change the URL out from under the reader.
        $viteProc = Start-Child -FilePath $npm `
            -ArgumentList @('run', 'dev', '--', '--port', "$PublicPort", '--strictPort',
                            '--host', '127.0.0.1') `
            -WorkingDirectory $FrontendDir -Name "Vite on :$PublicPort" `
            -StdOutLog "$viteLog" -StdErrLog "$viteLog.err"

        Wait-HttpOk -Url "http://127.0.0.1:$PublicPort/" -Label 'Vite dev server' -Process $viteProc
        Write-Ok "Vite ready at http://127.0.0.1:$PublicPort (proxying /api to :$ApiPort)"

        # Prove the proxy works rather than reporting the dev server up and
        # leaving the reader to find out that the API is unreachable.
        Wait-HttpOk -Url "http://127.0.0.1:$PublicPort/api/health" -Label 'API through the Vite proxy' -Process $viteProc
        Write-Ok 'API reachable through the same origin as the page'
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
    if ($HotReload) {
        Write-Host "  API:     http://127.0.0.1:$ApiPort/api/health  (via $localUrl/api)" -ForegroundColor Green
    } else {
        Write-Host "  API:     http://127.0.0.1:$ApiPort/api/health" -ForegroundColor Green
    }
    Write-Host "  Logs:    $LogDir" -ForegroundColor Green
    if ($HotReload) {
        Write-Host '===============================================' -ForegroundColor Green
        Write-Host '  Hot reload is on. Edit app/ or frontend/src/ and save -- no' -ForegroundColor Green
        Write-Host '  restart, and the URL above stays the same. Ctrl+C to stop.' -ForegroundColor Green
    }
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

    # uvicorn's reloader runs the app in a *child* process whose command line is
    # a multiprocessing bootstrap and never mentions main.py, and npm.cmd spawns
    # node the same way. Killing only the parent would leave those children
    # holding the ports, so the next start would fail on a port that looks free.
    # /T takes each started process's own tree down, and only that tree: nothing
    # here can reach a server this run did not start.
    foreach ($p in $children) {
        if (-not $p) { continue }
        try {
            if (-not $p.HasExited) {
                & taskkill /PID $p.Id /T /F 2>&1 | Out-Null
            }
        } catch { }
    }

    # Orphan sweep from an earlier run of this script: anything still running out
    # of this repo that we did not start ourselves.
    foreach ($proc in (Get-Process python, node, cloudflared -ErrorAction SilentlyContinue)) {
        if ($proc.Id -eq $PID) { continue }
        try {
            $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)").CommandLine
            if (-not $cmdline) { continue }
            $ours = $cmdline -like "*$RepoRoot*main.py*dashboard*" -or
                    $cmdline -like "*$FrontendDir*" -or
                    $cmdline -like '*cloudflared*tunnel*'
            if ($ours) { & taskkill /PID $proc.Id /T /F 2>&1 | Out-Null }
        } catch { }
    }

    Remove-Item $urlFile -ErrorAction SilentlyContinue
    Write-Ok 'stopped'
}