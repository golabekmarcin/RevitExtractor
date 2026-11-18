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

Cloud-tab route (the real feature; needs "cloud_hardlinks": true in the preferences file
%APPDATA%\RevitExtractor\preferences.json):
  -Snapshot -CacheHost <file> [-Link 'Name.rvt=<cache file>', ...] [-Root <folder>]
        Same snapshot as -Stage but makes no links. Also prints how many of the files have the
        read-only attribute (a link to such a file cannot be deleted afterwards).
  -Probe -OutputParent <the Export output folder>
        While the export runs: counts the files in the newest run's model folder that have two
        or more names (hard links) and those that are plain copies. Counts only.
  then -Verify as before (it now compares attributes too).
#>
param(
    [switch]$Stage, [switch]$Snapshot, [switch]$Probe, [switch]$Verify, [switch]$Remove,
    [string]$OutputParent, [string]$CacheHost, [string]$HostName = 'Host.rvt', [string[]]$Link = @(),
    [string]$Root = (Join-Path $env:TEMP 'RX-hardlink')
)
$ErrorActionPreference = 'Stop'
$run = Join-Path $Root 'run1'
$snap = Join-Path $Root 'snapshot.json'

function Get-Snapshot($files) {
    $dirs = $files | ForEach-Object { Split-Path -Parent $_ } | Sort-Object -Unique
    [pscustomobject]@{
        files = @($files | ForEach-Object { $i = Get-Item -LiteralPath $_; [pscustomobject]@{ p = $i.FullName; len = $i.Length; t = $i.LastWriteTimeUtc.Ticks; a = [int]$i.Attributes } })
        dirs  = @($dirs | ForEach-Object { [pscustomobject]@{ p = $_; n = @(Get-ChildItem -LiteralPath $_ -Force).Count } })
    }
}

if ($Stage -or $Snapshot) {
    if (-not $CacheHost) { throw 'Pass -CacheHost <cache host file>' }
    # Resolve to full paths first: relative paths have no drive qualifier.
    $CacheHost = [IO.Path]::GetFullPath($CacheHost)
    $Root = [IO.Path]::GetFullPath($Root)
    $run = Join-Path $Root 'run1'
    $snap = Join-Path $Root 'snapshot.json'
    $pairs = @(@{ n = $HostName; p = $CacheHost })
    foreach ($l in $Link) {
        $k = $l.IndexOf('=')
        if ($k -lt 1) { throw "Bad -Link value (expected 'RealName.rvt=<cache file>')." }
        $pairs += @{ n = $l.Substring(0, $k); p = [IO.Path]::GetFullPath($l.Substring($k + 1)) }
    }
    foreach ($x in $pairs) { if (-not (Test-Path -LiteralPath $x.p -PathType Leaf)) { throw ('Cache file not found for {0}. Pass the full path to an existing file.' -f $x.n) } }
    $files = $pairs | ForEach-Object { $_.p }
    $rootDrive = [IO.Path]::GetPathRoot($Root)
    foreach ($x in $pairs) {
        if ([IO.Path]::GetPathRoot($x.p) -ne $rootDrive) { throw ('Root ({0}) must be on the same drive as the cache files (hard links).' -f $rootDrive) }
    }
    if ($Stage -and (Test-Path -LiteralPath $run)) { throw 'run1 exists; run -Remove first.' }
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    $snapshotData = Get-Snapshot $files
    $snapshotData | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $snap -Encoding UTF8
    if ($Stage) {
        New-Item -ItemType Directory -Path $run | Out-Null
        foreach ($x in $pairs) { New-Item -ItemType HardLink -Path (Join-Path $run $x.n) -Target $x.p | Out-Null }
        Write-Host ('Staged {0} hard link(s) in {1}.' -f $pairs.Count, $run)
    } else {
        $ro = @($snapshotData.files | Where-Object { ($_.a -band 1) -ne 0 }).Count
        Write-Host ('Snapshot of {0} cache file(s) saved. Read-only attribute set on: {1} of {0}.' -f $files.Count, $ro)
    }
}
elseif ($Probe) {
    if (-not $OutputParent) { throw 'Pass -OutputParent <the Export output folder>' }
    $OutputParent = [IO.Path]::GetFullPath($OutputParent)
    $model = Get-ChildItem -LiteralPath $OutputParent -Directory -Force |
        ForEach-Object { Join-Path $_.FullName 'model' } | Where-Object { Test-Path -LiteralPath $_ } |
        Sort-Object { (Get-Item -LiteralPath $_).CreationTime } -Descending | Select-Object -First 1
    if (-not $model) { throw 'No run folder with a model folder found. Probe while the export runs.' }
    $linked = 0; $plain = 0
    foreach ($f in Get-ChildItem -LiteralPath $model -File -Force | Where-Object { $_.Extension -eq '.rvt' }) {
        $names = @(& fsutil hardlink list $f.FullName 2>$null | Where-Object { $_ }).Count
        if ($names -ge 2) { $linked++ } else { $plain++ }
    }
    Write-Host ('files in the newest run model folder: {0}; hard-linked (2+ names): {1}; plain copies: {2}' -f ($linked + $plain), $linked, $plain)
}
elseif ($Verify) {
    $s = Get-Content -LiteralPath $snap -Raw -Encoding UTF8 | ConvertFrom-Json
    $changed = 0
    foreach ($f in $s.files) { $i = Get-Item -LiteralPath $f.p; if ($i.Length -ne $f.len -or $i.LastWriteTimeUtc.Ticks -ne $f.t -or [int]$i.Attributes -ne $f.a) { $changed++ } }
    $newFiles = 0
    foreach ($d in $s.dirs) { $newFiles += [math]::Max(0, @(Get-ChildItem -LiteralPath $d.p -Force).Count - $d.n) }
    $left = @(Get-ChildItem -LiteralPath $run -Force -Recurse -ErrorAction SilentlyContinue).Count
    Write-Host ('cache files checked: {0}; changed (size/time/attributes): {1}; new entries beside them: {2}; entries in run1: {3}' -f $s.files.Count, $changed, $newFiles, $left)
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
else { Get-Help $MyInvocation.MyCommand.Path | Out-Null; Write-Host 'Use -Stage, -Snapshot, -Probe, -Verify or -Remove (see the header).' }
