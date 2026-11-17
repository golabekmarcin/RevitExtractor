<#
Experiment: can the Extractor export a cloud model from NTFS hard links (no copy)?
Windows PowerShell 5.1. Prints counts only (no model name, path or GUID). Never writes to the cache.

Step 1  -Stage -CacheHost <cache host file> [-HostName Real.rvt] -Link 'RealName.rvt=<cache file>', ... [-Root <folder>]
        Makes <Root>\run1 with hard links under the real names (host + links), and a snapshot
        (size and write time of every cache file involved, plus the file count of their folders).
        Root defaults to a folder in %TEMP% (must be on the same drive as the cache).
Step 2  In the Export window add <Root>\run1 as a normal local folder and export the host.
Step 3  -Verify [-Root <folder>]
        Compares the snapshot: sizes and times of the cache files, new files beside them,
        and what the export left in <Root>\run1 (names only counted).
Step 4  -Remove [-Root <folder>] deletes only the links in <Root>\run1 (never a cache file).
#>
param(
    [switch]$Stage, [switch]$Verify, [switch]$Remove,
    [string]$CacheHost, [string]$HostName = 'Host.rvt', [string[]]$Link = @(),
    [string]$Root = (Join-Path $env:TEMP 'RX-hardlink')
)
$ErrorActionPreference = 'Stop'
$run = Join-Path $Root 'run1'
$snap = Join-Path $Root 'snapshot.json'

function Get-Snapshot($files) {
    $dirs = $files | ForEach-Object { Split-Path -Parent $_ } | Sort-Object -Unique
    [pscustomobject]@{
        files = @($files | ForEach-Object { $i = Get-Item -LiteralPath $_; [pscustomobject]@{ p = $i.FullName; len = $i.Length; t = $i.LastWriteTimeUtc.Ticks } })
        dirs  = @($dirs | ForEach-Object { [pscustomobject]@{ p = $_; n = @(Get-ChildItem -LiteralPath $_ -Force).Count } })
    }
}

if ($Stage) {
    if (-not $CacheHost) { throw 'Pass -CacheHost <cache host file>' }
    $pairs = @(@{ n = $HostName; p = $CacheHost })
    foreach ($l in $Link) { $k = $l.IndexOf('='); $pairs += @{ n = $l.Substring(0, $k); p = $l.Substring($k + 1) } }
    $files = $pairs | ForEach-Object { $_.p }
    if ((Split-Path -Qualifier $CacheHost) -ne (Split-Path -Qualifier $Root)) { throw 'Root must be on the same drive as the cache (hard links).' }
    if (Test-Path -LiteralPath $run) { throw 'run1 exists; run -Remove first.' }
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    Get-Snapshot $files | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $snap -Encoding UTF8
    New-Item -ItemType Directory -Path $run | Out-Null
    foreach ($x in $pairs) { New-Item -ItemType HardLink -Path (Join-Path $run $x.n) -Target $x.p | Out-Null }
    Write-Host ('Staged {0} hard link(s) in {1}.' -f $pairs.Count, $run)
}
elseif ($Verify) {
    $s = Get-Content -LiteralPath $snap -Raw -Encoding UTF8 | ConvertFrom-Json
    $changed = 0
    foreach ($f in $s.files) { $i = Get-Item -LiteralPath $f.p; if ($i.Length -ne $f.len -or $i.LastWriteTimeUtc.Ticks -ne $f.t) { $changed++ } }
    $newFiles = 0
    foreach ($d in $s.dirs) { $newFiles += [math]::Max(0, @(Get-ChildItem -LiteralPath $d.p -Force).Count - $d.n) }
    $left = @(Get-ChildItem -LiteralPath $run -Force -Recurse -ErrorAction SilentlyContinue).Count
    Write-Host ('cache files checked: {0}; changed (size/time): {1}; new entries beside them: {2}; entries in run1: {3}' -f $s.files.Count, $changed, $newFiles, $left)
    if ($changed -eq 0 -and $newFiles -eq 0) { Write-Host 'RESULT: cache untouched' } else { Write-Host 'RESULT: CACHE CHANGED - do not use hard links' }
}
elseif ($Remove) {
    if (Test-Path -LiteralPath $run) {
        Get-ChildItem -LiteralPath $run -File -Force | ForEach-Object { $_.Delete() }   # deletes the link only
        Get-ChildItem -LiteralPath $run -Directory -Force | Remove-Item -Recurse -Force
        Remove-Item -LiteralPath $run -Force
        Write-Host 'run1 removed (links only).'
    }
}
else { Get-Help $MyInvocation.MyCommand.Path | Out-Null; Write-Host 'Use -Stage, -Verify or -Remove (see the header).' }
