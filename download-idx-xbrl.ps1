<#
.SYNOPSIS
    Downloads IDX inline-XBRL filings for the companies listed in download.csv.

.DESCRIPTION
    For every company in the CSV, and for every year in the requested range,
    asks idx.co.id which attachments exist for that filing, picks inlineXBRL.zip,
    downloads it and unpacks it:

        XBRL\<KODE> <Company Name>\<year>\<files from the zip>

    The zip is flat -- entries sit at the root and are named after IDX's own
    statement codes, e.g. 1000000.html -- so extraction needs no nesting logic.

    Two things about idx.co.id are worth knowing before changing this:

    * The listing pages sit behind Cloudflare, but the read APIs and the file
      paths themselves are reachable from a plain HTTP client as long as a
      browser cookie jar is seeded first. Invoke-WebRequest gets a flat 403;
      curl.exe with a jar from a first hit on the landing page does not. The
      jar's __cf_bm cookie is short-lived, so it is re-seeded periodically and
      whenever a request comes back 403.

    * Attachment paths contain literal spaces ("Laporan Keuangan Tahun 2024").
      They must be percent-encoded before they are requested or curl rejects the
      URL outright.

.PARAMETER Csv
    Company list. Needs a Kode column and a company-name column.

.PARAMETER OutRoot
    Root folder created for the tree. Default 'XBRL', beside this script.

.PARAMETER Period
    IDX filing period: audit (annual), TW1, TW2 or TW3. Default audit, because
    the target tree has one folder per year and two periods would overwrite
    each other in it.

.PARAMETER Codes
    Comma-separated ticker subset, for testing without doing the whole list.

.PARAMETER Force
    Re-download and overwrite years that already have files.

.EXAMPLE
    .\download-idx-xbrl.ps1 -Codes AALI,ADES -StartYear 2024 -EndYear 2024

.EXAMPLE
    .\download-idx-xbrl.ps1
    Downloads 2020-2024 for every company in download.csv.

.NOTES
    Output tree is resumable: a year folder that already holds files is skipped
    unless -Force is given, so an interrupted run can simply be repeated.

    Every company-year ends up in the report CSV with a status, including the
    ones with nothing to download. A ticker with no filing for a year is normal
    -- issuers file on their own schedule -- and is recorded as NoFiling rather
    than being passed over in silence.

    WHAT IS IN THE FOLDER, BY YEAR

    The five primary statements keep the same code in every year from 2020 to
    2024, so a parser can rely on these:

        1000000  cover / general information
        1210000  statement of financial position
        1321000  statement of profit or loss and other comprehensive income
        1410000  statement of changes in equity
        1510000  statement of cash flows

    Filing size varies sharply with the year, and it is worth knowing why before
    concluding that an older year downloaded badly:

        2020-2021  about 6 files -- the five statements above, no notes
        2022+      20-32 files -- the same five, plus notes to the statements
                   (1610000 accounting policies, 1611000 property plant and
                   equipment, 1630000 inventories, 1640100 trade payables,
                   1670000 cost of goods sold, 1691000a bank loans, ...)

    Older filings are therefore smaller because IDX only began publishing the
    notes section as inline XBRL in 2022, not because data is missing. The
    primary statements are fully populated in 2020 -- AALI's 2020 income
    statement reports sales of 18,807,043. If notes-level detail is needed for
    2020-2021, it has to come from the disclosure-information page rather than
    from this API.

    Two naming changes also matter to anything that walks the extracted folder:
    the changes-in-equity file is 1410000_1_CurrentYear.html and
    1410000_2_PriorYear.html up to 2022, and becomes 1410000.html plus
    1410000PY.html from 2023.
#>
[CmdletBinding()]
param(
    [string]   $Csv       = 'download.csv',
    [string]   $OutRoot   = 'XBRL',
    [int]      $StartYear = 2020,
    [int]      $EndYear   = 2024,
    [ValidateSet('audit', 'TW1', 'TW2', 'TW3')]
    [string]   $Period    = 'audit',
    [string[]] $Codes,
    [int]      $DelayMs       = 900,
    [int]      $MaxRetries    = 3,
    [int]      $ThrottleLimit = 8,
    [switch]   $Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ZipFile is used rather than Expand-Archive so that a truncated archive can be
# detected by counting its entries, instead of being discovered halfway through
# extraction.
Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue

# curl exits non-zero on ordinary, recoverable conditions here (a 403, a
# malformed URL, a timeout). Under PowerShell 7.3+ a native command's exit code
# becomes a terminating error when ErrorActionPreference is Stop, which would
# turn one refused request into the end of the whole run.
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$script:Root      = $PSScriptRoot
$script:Referer   = 'https://www.idx.co.id/en/listed-companies/financial-statements-and-annual-report'
$script:Landing   = 'https://www.idx.co.id/'
$script:ApiBase   = 'https://www.idx.co.id/primary/ListedCompany/GetFinancialReport'
$script:UserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
$script:CookieJar = Join-Path ([IO.Path]::GetTempPath()) 'idx-xbrl-cookies.txt'

# Re-seeded on this interval as well as on failure: __cf_bm is good for roughly
# half an hour, and a full run is long enough to outlive it.
$script:RequestsSinceSeed = 0
$script:SeedEvery        = 20

# --------------------------------------------------------------------------
# output helpers
# --------------------------------------------------------------------------

function Write-Step { param([string]$m) Write-Host $m -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "  $m" -ForegroundColor Green }
function Write-Info { param([string]$m) Write-Host "  $m" -ForegroundColor DarkGray }
function Write-Fail { param([string]$m) Write-Host "  $m" -ForegroundColor Red }
function Write-Warn { param([string]$m) Write-Host "  $m" -ForegroundColor Yellow }

# --------------------------------------------------------------------------
# paths and names
# --------------------------------------------------------------------------

$script:Reserved = @(
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
)

function ConvertTo-SafeFolderName {
    <#
      Folder names come from a spreadsheet, so they can hold anything. Windows
      silently drops trailing dots and spaces, which would quietly merge two
      companies whose names differ only there, so they are stripped explicitly
      rather than left to the filesystem.
    #>
    param([string]$Name)

    $safe = $Name -replace '[<>:"/\\|?*]', ' '
    $safe = ($safe -replace '\s+', ' ').Trim()
    $safe = $safe -replace '[. ]+$', ''
    if ([string]::IsNullOrWhiteSpace($safe)) { return 'UNNAMED' }
    if ($script:Reserved -contains $safe.ToUpperInvariant()) { return "_$safe" }
    return $safe
}

# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

function Initialize-CookieJar {
    # Seeds _cfuvid and __cf_bm. The landing page itself answers 403 to a
    # non-browser client; the cookies it sets on the way through are what the
    # API and file requests actually need.
    & curl.exe -sS -o NUL -A $script:UserAgent -c $script:CookieJar `
        --max-time 45 $script:Landing 2>$null | Out-Null
    $script:RequestsSinceSeed = 0
}

function Invoke-IdxRequest {
    <#
      Runs one curl request and returns @{ Status = <int>; Body = <string> }.
      Status is taken from curl's -w so that a Cloudflare 403, which arrives
      with a 200-looking HTML challenge body, cannot be mistaken for success.

      curl.exe is used rather than Invoke-WebRequest because the latter is
      fingerprint-blocked by Cloudflare on this host.
    #>
    param(
        [Parameter(Mandatory)][string]$Url,
        [string]$OutFile,
        [switch]$AsJson
    )

    $curlArgs = @(
        '-sS', '-A', $script:UserAgent,
        '-b', $script:CookieJar, '-c', $script:CookieJar,
        '--max-time', '120'
    )
    if ($AsJson) {
        $curlArgs += @(
            '-H', "Referer: $script:Referer",
            '-H', 'Accept: application/json, text/plain, */*',
            '-H', 'X-Requested-With: XMLHttpRequest'
        )
    } else {
        $curlArgs += @(
            '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            '-H', 'Accept-Language: en-US,en;q=0.9',
            '-H', 'Sec-Fetch-Dest: document',
            '-H', 'Sec-Fetch-Mode: navigate',
            '-H', 'Sec-Fetch-Site: same-origin',
            '-e', $script:Referer
        )
    }
    if ($OutFile) { $curlArgs += @('-o', $OutFile) }
    $curlArgs += @('-w', '%{http_code}', $Url)

    $raw = (& curl.exe @curlArgs 2>$null) -join ''
    $code = 0
    if ($raw -match '(\d{3})\s*$') { $code = [int]$Matches[1] }

    $script:RequestsSinceSeed++
    if ($script:RequestsSinceSeed -ge $script:SeedEvery) { Initialize-CookieJar }

    $body = ''
    if (-not $OutFile -and $code -eq 200 -and $raw.Length -ge 3) {
        $body = $raw.Substring(0, $raw.Length - 3)
    }
    return @{ Status = $code; Body = $body }
}

function Get-AttachmentPath {
    <#
      Returns the File_Path of the named attachment for one company-year, or
      $null when IDX has no filing, has a filing without that attachment, or
      answers with something unexpected. Never throws: a single unreachable
      company must not end the run.
    #>
    param(
        [Parameter(Mandatory)][string]$Code,
        [Parameter(Mandatory)][int]$Year,
        [Parameter(Mandatory)][string]$AttachmentName
    )

    $url = '{0}?indexFrom=0&pageSize=10&year={1}&reportType=rdf&periode={2}&kodeEmiten={3}' -f `
        $script:ApiBase, $Year, $Period, [uri]::EscapeDataString($Code)

    $res = Invoke-IdxRequest -Url $url -AsJson
    if ($res.Status -ne 200 -or [string]::IsNullOrWhiteSpace($res.Body)) {
        if ($res.Status -eq 403) { Initialize-CookieJar }
        return [pscustomobject]@{ Path = $null; Reason = "ApiStatus$($res.Status)" }
    }

    try { $json = $res.Body | ConvertFrom-Json } catch {
        return [pscustomobject]@{ Path = $null; Reason = 'ApiUnparseable' }
    }

    if (-not $json -or $json.ResultCount -eq 0) {
        return [pscustomobject]@{ Path = $null; Reason = 'NoFiling' }
    }

    $hit = $json.Results[0].Attachments |
        Where-Object { $_.File_Name -eq $AttachmentName } |
        Select-Object -First 1

    if (-not $hit) { return [pscustomobject]@{ Path = $null; Reason = 'NoInlineXBRL' } }
    if ([string]::IsNullOrWhiteSpace($hit.File_Path)) {
        return [pscustomobject]@{ Path = $null; Reason = 'EmptyFilePath' }
    }
    return [pscustomobject]@{ Path = $hit.File_Path; Reason = '' }
}

function Save-Attachment {
    <#
      Downloads one attachment to $Destination and unpacks it into $ExtractTo.
      Returns $true on success. A partial download is deleted rather than left
      behind, because a truncated zip that looks present would make the resume
      check skip that year forever.
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$ExtractTo
    )

    # IDX serves these paths with literal spaces in them.
    $url = 'https://www.idx.co.id' + ($FilePath -replace ' ', '%20')

    for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
        $res = Invoke-IdxRequest -Url $url -OutFile $Destination

        if ($res.Status -eq 200) {
            # A 200 is not proof of a usable file. The transfer can be cut short
            # and the result still begins with a valid PK signature while having
            # no central directory at all, so the archive is opened and counted
            # before anything is written to the year folder.
            $entries = 0
            try {
                $zip = [IO.Compression.ZipFile]::OpenRead($Destination)
                try { $entries = $zip.Entries.Count } finally { $zip.Dispose() }
            } catch {
                $entries = 0   # truncated, or an HTML error page served with a 200
            }

            if ($entries -gt 0) {
                try {
                    # Always start from an empty folder: ExtractToDirectory will
                    # not overwrite, and a half-extracted folder from an earlier
                    # attempt would otherwise poison every retry.
                    Remove-Item -LiteralPath $ExtractTo -Recurse -Force -ErrorAction SilentlyContinue
                    [IO.Compression.ZipFile]::ExtractToDirectory($Destination, $ExtractTo)
                    Remove-Item -LiteralPath $Destination -Force

                    $written = @(Get-ChildItem -LiteralPath $ExtractTo -Recurse -File).Count
                    if ($written -gt 0) { return $true }

                    # Nothing landed on disk after all; clear the empty folder so
                    # the resume check does not treat it as already done.
                    Remove-Item -LiteralPath $ExtractTo -Recurse -Force -ErrorAction SilentlyContinue
                } catch {
                    Remove-Item -LiteralPath $ExtractTo -Recurse -Force -ErrorAction SilentlyContinue
                }
            }
        }

        # Whatever went wrong, the downloaded bytes are not trustworthy.
        Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue

        if ($res.Status -eq 403) {
            Initialize-CookieJar
            Start-Sleep -Seconds ([Math]::Min(60, 10 * $attempt))
        } else {
            Start-Sleep -Seconds ([Math]::Min(8, 2 * $attempt))
        }
    }
    return $false
}

# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

Write-Host ''
Write-Host 'IDX inline XBRL downloader' -ForegroundColor White
Write-Host '---------------------------' -ForegroundColor DarkGray

$csvPath = if ([IO.Path]::IsPathRooted($Csv)) { $Csv } else { Join-Path $script:Root $Csv }
$outPath = if ([IO.Path]::IsPathRooted($OutRoot)) { $OutRoot } else { Join-Path $script:Root $OutRoot }

if (-not (Test-Path -LiteralPath $csvPath)) { throw "Company list not found: $csvPath" }
if ($EndYear -lt $StartYear) { throw "EndYear ($EndYear) is before StartYear ($StartYear)." }
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    throw 'curl.exe not found. It ships with Windows 10 1803 and later.'
}

$rows = Import-Csv -LiteralPath $csvPath -Encoding UTF8 |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_.Kode) }
if (-not $rows) { throw "No rows with a Kode column in $csvPath" }

if ($Codes) {
    $wanted = $Codes |
        ForEach-Object { $_.Split(',') } |
        ForEach-Object { $_.Trim().ToUpperInvariant() } |
        Where-Object { $_ }
    $rows = $rows | Where-Object { $wanted -contains $_.Kode.Trim().ToUpperInvariant() }
    if (-not $rows) { throw "None of the codes in -Codes matched $csvPath" }
}

$years = $StartYear..$EndYear
$reportPath = Join-Path $script:Root ("idx-xbrl-report-{0}-{1}.csv" -f $StartYear, $EndYear)

# Tried in order. The second is the fallback described in Save-CompanyYear.
$AttachmentOrder = @('inlineXBRL.zip', 'instance.zip')

Write-Info "companies : $($rows.Count)"
Write-Info "years     : $($years -join ', ')  (period: $Period)"
Write-Info "output    : $outPath"
Write-Info "report    : $reportPath"
$total = $rows.Count * $years.Count
$mins = [Math]::Ceiling($total * ($DelayMs / 1000) / 60)
Write-Info "requests  : ~$total company-years, expect at least $mins min plus download time"
Write-Host ''

if (-not (Test-Path -LiteralPath $outPath)) {
    New-Item -ItemType Directory -Path $outPath -Force | Out-Null
}

$report    = [System.Collections.Generic.List[object]]::new()
$done      = 0
$ok        = 0
$fallback  = 0
$skipped   = 0
$failed    = 0
$throttled = $false
# Cloudflare starts refusing the whole run once the request rate is too high.
# Stopping outright is better than pushing through: the tree is resumable, so
# the same command later picks up exactly where this left off.
$consecutiveFailures = 0
$startedAt = Get-Date

Initialize-CookieJar

foreach ($row in $rows) {
    $code = $row.Kode.Trim()
    # Header lookup tolerates the column being spelled differently in a
    # hand-edited sheet.
    $nameCol = @('Nama Perusahaan', 'NamaPerusahaan', 'Company', 'CompanyName') |
        Where-Object { $row.PSObject.Properties.Name -contains $_ } |
        Select-Object -First 1
    $company = if ($nameCol) { $row.$nameCol } else { $code }

    $folder = ConvertTo-SafeFolderName "$code $company"
    $companyDir = Join-Path $outPath $folder

    Write-Step "[$code] $company"

    foreach ($year in $years) {
        $done++
        $yearDir = Join-Path $companyDir $year

        if (-not $Force -and (Test-Path -LiteralPath $yearDir) -and
            (Get-ChildItem -LiteralPath $yearDir -File -ErrorAction SilentlyContinue)) {
            $report.Add([pscustomobject]@{
                Kode = $code; Company = $company; Year = $year
                Status = 'AlreadyPresent'; Source = ''; Files = ''
            })
            $skipped++
            Write-Info ("  {0}  already downloaded" -f $year)
            continue
        }

        # inlineXBRL.zip is the preferred form because it arrives already split
        # into one file per statement. It is not always intact, though: some
        # filings serve a truncated archive that still carries a valid PK
        # signature, byte-for-byte identically on every attempt, which means the
        # copy on IDX's side is damaged. instance.zip is the same filing in its
        # raw form -- a single instance.xbrl plus Taxonomy.xsd -- so it is used
        # as the fallback rather than leaving the year empty.
        $saved = $false
        $usedSource = ''
        $lastReason = ''

        foreach ($candidate in $AttachmentOrder) {
            $found = Get-AttachmentPath -Code $code -Year $year -AttachmentName $candidate
            $lastReason = $found.Reason

            if (-not $found.Path) { continue }

            if (-not (Test-Path -LiteralPath $companyDir)) {
                New-Item -ItemType Directory -Path $companyDir -Force | Out-Null
            }

            $zipPath = Join-Path ([IO.Path]::GetTempPath()) ("idx-{0}-{1}-{2}.zip" -f $code, $year, $candidate)
            if (Save-Attachment -FilePath $found.Path -Destination $zipPath -ExtractTo $yearDir) {
                $saved = $true
                $usedSource = $candidate
                break
            }
            $lastReason = "CorruptOrUnreachable:$candidate"
            Start-Sleep -Milliseconds $DelayMs
        }

        if ($saved) {
            $count = @(Get-ChildItem -LiteralPath $yearDir -Recurse -File -ErrorAction SilentlyContinue).Count
            $report.Add([pscustomobject]@{
                Kode = $code; Company = $company; Year = $year
                Status = 'Downloaded'; Source = $usedSource; Files = $count
            })
            $ok++
            if ($usedSource -eq 'inlineXBRL.zip') {
                Write-Ok ("  {0}  {1} files" -f $year, $count)
            } else {
                $fallback++
                Write-Warn ("  {0}  {1} files from {2} (inlineXBRL.zip was unusable)" -f $year, $count, $usedSource)
            }
            $consecutiveFailures = 0
        } else {
            $reason = if ($lastReason) { $lastReason } else { 'DownloadFailed' }
            $report.Add([pscustomobject]@{
                Kode = $code; Company = $company; Year = $year
                Status = $reason; Source = ''; Files = ''
            })
            $failed++
            Write-Fail ("  {0}  {1}" -f $year, $reason)

            # Only transport-level trouble counts towards the breaker. A genuine
            # "this issuer filed nothing that year" is a real answer from a
            # working API, and a list that happens to contain eight such issuers
            # in a row is not evidence of being throttled.
            if ($reason -match '^(ApiStatus(403|429|5\d\d)|ApiUnparseable|CorruptOrUnreachable|DownloadFailed|EmptyFilePath)') {
                if (++$consecutiveFailures -ge $ThrottleLimit) {
                    $throttled = $true
                    Write-Fail "  $consecutiveFailures transport failures in a row -- giving up for now."
                    break
                }
            } else {
                $consecutiveFailures = 0
            }
        }

        Start-Sleep -Milliseconds $DelayMs
    }

    if ($throttled) { break }
}

$report | Export-Csv -LiteralPath $reportPath -NoTypeInformation -Encoding UTF8

$elapsed = (Get-Date) - $startedAt
Write-Host ''
Write-Host '===============================================' -ForegroundColor Green
Write-Host ("  downloaded : {0}" -f $ok) -ForegroundColor Green
Write-Host ("  of which   : {0} came from instance.zip (inlineXBRL.zip unusable)" -f $fallback) -ForegroundColor $(if ($fallback) { 'Yellow' } else { 'DarkGray' })
Write-Host ("  skipped    : {0}  (already on disk)" -f $skipped) -ForegroundColor DarkGray
Write-Host ("  not ok     : {0}  (no filing, no inlineXBRL, or failed)" -f $failed) -ForegroundColor $(if ($failed) { 'Yellow' } else { 'DarkGray' })
Write-Host ("  elapsed    : {0:hh\:mm\:ss}" -f $elapsed) -ForegroundColor DarkGray
Write-Host ("  output     : {0}" -f $outPath) -ForegroundColor DarkGray
Write-Host ("  report     : {0}" -f $reportPath) -ForegroundColor DarkGray
Write-Host '===============================================' -ForegroundColor Green
if ($throttled) {
    Write-Host ''
    Write-Warning 'idx.co.id started refusing requests, so the run stopped early.'
    Write-Warning 'Wait a few minutes, then run the identical command again --'
    Write-Warning 'finished years are detected and skipped, so it resumes where it stopped.'
}
Write-Host ''
