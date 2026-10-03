<#
.SYNOPSIS
    Clean reset of generated output and working data.

.DESCRIPTION
    Deletes everything the extractor generates, so the next run starts from
    scratch:

      output/            generated reports, review CSVs
      review/            review queue exports
      data/cache         pipeline caches
      data/extracted     per-page rendered text and images
      data/ocr           OCR text and hOCR sidecars
      data/raw_text      extracted raw text
      data/tmp           scratch space used by Tesseract
      database/*.db      processing database and its WAL/SHM sidecars
      logs/              log files

    Two things are never deleted, because losing them is expensive or
    unrecoverable:

      - The input directory (default ./XBRL). Your 546 downloaded filing
        folders stay untouched. A reset un-registers them from the database,
        and the next scan re-registers them from their file hashes.
      - data/tessdata. Those are the Indonesian/English language packs. Use
        -DeleteTessdata if you really want them gone.

    Running the dashboard while the database is deleted can corrupt the WAL, so
    any running dashboard, Vite or Cloudflare tunnel is stopped first.

.PARAMETER Force
    Skip the confirmation prompt.

.PARAMETER KeepDatabase
    Delete output and working data but keep the processing database, so already
    processed documents stay known and only the generated files are rebuilt.

.PARAMETER KeepLogs
    Keep logs/.

.PARAMETER DeleteTessdata
    Also delete the Tesseract language packs. They will need re-downloading.

.PARAMETER WhatIf
    Show what would be deleted without deleting anything.

.EXAMPLE
    ./reset.ps1 -WhatIf
    ./reset.ps1
    ./reset.ps1 -KeepDatabase
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [switch]$Force,
    [switch]$KeepDatabase,
    [switch]$KeepLogs,
    [switch]$DeleteTessdata
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Declaring our own -Force switch shadows the common parameter that would
# normally lower $ConfirmPreference, so ShouldProcess would still try to prompt
# for a High-impact action. Set it here so -Force really does mean "no
# questions". Without -Force both gates still apply and nothing changes.
if ($Force) { $ConfirmPreference = 'None' }

$RepoRoot = $PSScriptRoot
if (-not $RepoRoot) { $RepoRoot = (Get-Location).Path }

function Write-Step { param([string]$Message) Write-Host "==> $Message" }
function Write-Item { param([string]$Message) Write-Host "    $Message" -ForegroundColor DarkGray }
function Write-Keep { param([string]$Message) Write-Host "    keep  $Message" -ForegroundColor DarkYellow }

# Measure-Object returns $null (not an object with Sum=0) for an empty folder,
# and Set-StrictMode turns reading .Sum off that into a terminating error.
function Get-DirSize {
    param([string]$Path)
    $m = Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum
    if ($null -eq $m -or $null -eq $m.Sum) { return [double]0 }
    return [double]$m.Sum
}

function Get-DirCount {
    param([string]$Path)
    $m = Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
        Measure-Object
    if ($null -eq $m -or $null -eq $m.Count) { return 0 }
    return [int]$m.Count
}

function Resolve-InRepo {
    param([string]$RelativePath)
    $full = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $RelativePath))
    $root = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd('\') + '\'
    if (-not ($full + '\').StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to touch '$full' because it is outside $RepoRoot"
    }
    return $full
}

# --- stop anything that still holds the database or the ports ----------------

Write-Step 'Stopping running dashboard processes'
$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -like '*run-dashboard.ps1*' -or
        $_.CommandLine -like '*main.py*dashboard*' -or
        $_.CommandLine -like '*cloudflared*tunnel*' -or
        $_.CommandLine -like '*Fitri\frontend*'
    }
$stopped = 0
foreach ($proc in $procs) {
    # Never kill the shell that is running this script.
    if ($proc.ProcessId -eq $PID) { continue }
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        Write-Item ("stopped PID {0} ({1})" -f $proc.ProcessId, $proc.Name)
        $stopped++
    } catch {
        Write-Item ("could not stop PID {0}: {1}" -f $proc.ProcessId, $_.Exception.Message)
    }
}
if ($stopped -eq 0) { Write-Item 'nothing running' }

# --- build the list of things to delete --------------------------------------

$dirs = @('output', 'review', 'data\cache', 'data\extracted', 'data\ocr', 'data\raw_text', 'data\tmp')
if (-not $KeepLogs) { $dirs += 'logs' }

$files = @()
if (-not $KeepDatabase) {
    $files += @('database\processing.db', 'database\processing.db-wal', 'database\processing.db-shm')
}

# --- report, confirm, delete --------------------------------------------------

$targets = @()
foreach ($d in $dirs) {
    $p = Resolve-InRepo $d
    if (Test-Path -LiteralPath $p) {
        $targets += [pscustomobject]@{
            Kind = 'dir'
            Path = $p
            Label = $d
            Size = (Get-DirSize $p)
            Count = (Get-DirCount $p)
        }
    }
}
foreach ($f in $files) {
    $p = Resolve-InRepo $f
    if (Test-Path -LiteralPath $p) {
        $targets += [pscustomobject]@{
            Kind = 'file'
            Path = $p
            Label = $f
            Size = [double](Get-Item -LiteralPath $p).Length
            Count = 1
        }
    }
}
if ($DeleteTessdata) {
    $p = Resolve-InRepo 'data\tessdata'
    if (Test-Path -LiteralPath $p) {
        $targets += [pscustomobject]@{
            Kind = 'dir'
            Path = $p
            Label = 'data\tessdata'
            Size = (Get-DirSize $p)
            Count = (Get-DirCount $p)
        }
    }
}

Write-Host ''
if ($targets.Count -eq 0) {
    Write-Host 'Nothing to clean - already empty.' -ForegroundColor Green
    Write-Host ''
    return
}

Write-Step 'Will delete'
$total = 0
foreach ($t in $targets) {
    $mb = [math]::Round(($t.Size / 1MB), 2)
    $total += $t.Size
    $suffix = if ($t.Kind -eq 'dir') { "$($t.Count) files" } else { 'file' }
    Write-Host ("    {0,-26} {1,10} MB  {2}" -f $t.Label, $mb, $suffix)
}
Write-Host ("    {0,-26} {1,10} MB  total" -f '', [math]::Round(($total / 1MB), 2)) -ForegroundColor Gray
Write-Host ''

Write-Keep 'XBRL (input filings)'
if (-not $DeleteTessdata) { Write-Keep 'data\tessdata (OCR language packs)' }
if ($KeepDatabase) { Write-Keep 'database\processing.db (-KeepDatabase)' }
if ($KeepLogs) { Write-Keep 'logs\ (-KeepLogs)' }
Write-Host ''

# "-and", not "-": PowerShell reads "a - b" here as subtraction, so the old
# form evaluated to ($false - $true) = -1, which is truthy and prompted even
# when -Force was passed.
if (-not $Force -and -not $WhatIfPreference) {
    $answer = Read-Host 'Delete these? Type YES to continue'
    if ($answer -cne 'YES') {
        Write-Host 'Cancelled - nothing was deleted.' -ForegroundColor Yellow
        return
    }
}

foreach ($t in $targets) {
    if ($PSCmdlet.ShouldProcess($t.Label, 'Delete')) {
        Remove-Item -LiteralPath $t.Path -Recurse -Force -ErrorAction Stop
    }
}

# Recreate the empty folders the pipeline expects, so the next run does not
# have to care whether they exist.
foreach ($d in @('output', 'review', 'data\cache', 'data\extracted', 'data\ocr', 'data\raw_text', 'data\tmp')) {
    $p = Resolve-InRepo $d
    if (-not (Test-Path -LiteralPath $p)) {
        New-Item -ItemType Directory -Path $p -Force | Out-Null
    }
}
$logDir = Resolve-InRepo 'logs'
if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$dbDir = Resolve-InRepo 'database'
if (-not (Test-Path -LiteralPath $dbDir)) { New-Item -ItemType Directory -Path $dbDir -Force | Out-Null }

Write-Host ''
Write-Host 'Clean. Next run starts from an empty database - use Scan and process' -ForegroundColor Green
Write-Host 'on the dashboard to re-register the input PDFs.' -ForegroundColor Green
Write-Host ''