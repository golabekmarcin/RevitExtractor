#Requires -Version 5.1
<#
Helper for the owner's one Revit session (specs/v1-revit-test.md). Windows PowerShell 5.1.
Pomocnik do jednej sesji testowej wlasciciela (specs/v1-revit-test.md).

  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\v1_test_kit.ps1 -Setup [-Root C:\RX-test]
                 [-SampleA a.rvt] [-SampleB b.rvt] [-Newer n.rvt] [-Older o.rvt] [-Force]
      Builds the test folder. Without -SampleA/-SampleB it takes the two smallest different
      sample models it finds under C:\ProgramData\Autodesk\RVT <year>\ (Dynamo samples).
      Creates: both samples; a copy in a folder with spaces, Polish letters, & and %; a
      Backup folder with a copy; a .0001.rvt backup next to a model; a model named like
      Tower.2024.rvt; a text file renamed to .rvt; optional Newer and Older models.
      Only copies files. Never opens, changes or deletes a source model. An existing -Root is
      refused, unless it holds this kit's marker file and -Force is given.

  ... -Check [<run folder, or a folder that holds run folders>]   (the folder is the first argument)
      Prints the lines the owner sends back. Never prints a path, a file or model name, or
      anything read from a model: only counts, sizes, times, state words and the
      'Success Jobs' / exit-code lines of console.log. Without a folder it prints only the
      machine lines (Print Spooler, leftover processes, Extractor builds).

  ... -Stamp <file>
      Prints the size and last-write time of one file (no name, no path), to compare before
      and after a step.

All user-facing text is English and Polish. The script is ASCII only, so Windows PowerShell
5.1 reads it correctly; Polish letters are built from character codes.
Exit code: 0 = done (and every run OK for -Check), 1 = a run failed or an error.
#>
[CmdletBinding(DefaultParameterSetName = 'Check')]
param(
    [Parameter(ParameterSetName = 'Setup', Mandatory)][switch]$Setup,
    [Parameter(ParameterSetName = 'Setup')][string]$Root = 'C:\RX-test',
    [Parameter(ParameterSetName = 'Setup')][string]$SampleA,
    [Parameter(ParameterSetName = 'Setup')][string]$SampleB,
    [Parameter(ParameterSetName = 'Setup')][string]$Newer,
    [Parameter(ParameterSetName = 'Setup')][string]$Older,
    [Parameter(ParameterSetName = 'Setup')][switch]$Force,
    [Parameter(ParameterSetName = 'Check', Mandatory)][switch]$Check,
    [Parameter(ParameterSetName = 'Check', Position = 0)][string]$Folder,
    [Parameter(ParameterSetName = 'Stamp', Mandatory)][string]$Stamp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$markerName = 'rx-test-kit.marker'

function Get-Spooler {
    # Same line as run_extractor_integration.ps1.
    $service = Get-Service -Name Spooler -ErrorAction SilentlyContinue
    if ($null -eq $service) { return 'not found / nie znaleziono' }
    return "StartType=$($service.StartType), Status=$($service.Status)"
}

function Get-RevitYear([string]$Directory) {
    # Same rule as run_extractor_integration.ps1.
    $revitExe = Join-Path $Directory 'Revit.exe'
    if (!(Test-Path -LiteralPath $revitExe -PathType Leaf)) { return 0 }
    $major = (Get-Item -LiteralPath $revitExe).VersionInfo.FileMajorPart
    if ($major -gt 0 -and $major -lt 100) { return 2000 + $major }
    if ($major -ge 2000 -and $major -le 9999) { return $major }
    return 0
}

function Get-ExtractorBuilds {
    $builds = @()
    $autodesk = Join-Path $env:ProgramFiles 'Autodesk'
    if (Test-Path -LiteralPath $autodesk -PathType Container) {
        foreach ($folder in Get-ChildItem -LiteralPath $autodesk -Directory -Filter 'Revit *') {
            $dll = Join-Path $folder.FullName 'RevitExtractor\ExtractorUtility.dll'
            if (Test-Path -LiteralPath $dll -PathType Leaf) {
                $builds += ('Revit {0}: Extractor {1}' -f (Get-RevitYear $folder.FullName), (Get-Item -LiteralPath $dll).VersionInfo.FileVersion)
            }
        }
    }
    return $builds
}

function Test-InsideRepo([string]$Path) {
    $repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..\..\..')).ProviderPath.TrimEnd('\')
    return ([IO.Path]::GetFullPath($Path).TrimEnd('\') + '\').StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase)
}

# ---------------------------------------------------------------- -Setup
function Find-Samples {
    $found = @(Get-ChildItem -LiteralPath 'C:\ProgramData\Autodesk' -Directory -Filter 'RVT *' -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -Filter '*.rvt' -Recurse -File -ErrorAction SilentlyContinue } |
        Where-Object { $_.Name -notmatch '\.\d{4}\.rvt$' } | Sort-Object Length)
    $picked = @()
    $names = @{}
    foreach ($file in $found) {
        if (!$names.ContainsKey($file.Name.ToLowerInvariant())) {
            $names[$file.Name.ToLowerInvariant()] = $true
            $picked += $file.FullName
        }
        if ($picked.Count -eq 2) { break }
    }
    return $picked
}

function Copy-Model([string]$Source, [string]$Folder, [string]$Name) {
    New-Item -ItemType Directory -Path $Folder -Force | Out-Null
    Copy-Item -LiteralPath $Source -Destination (Join-Path $Folder $Name)
}

function Invoke-Setup {
    $Root = [IO.Path]::GetFullPath($Root.Trim('"')).TrimEnd('\')
    if (Test-InsideRepo $Root) { throw 'The test folder must be outside the repo. / Folder testowy musi byc poza repozytorium.' }
    if ($Root -match '(^|\\)test-[^\\]*(\\|$)') { throw 'The test folder must not be a test-* folder. / Folder testowy nie moze byc folderem test-*.' }
    if (Test-Path -LiteralPath $Root) {
        $marker = Join-Path $Root $markerName
        if ($Force -and (Test-Path -LiteralPath $marker -PathType Leaf)) {
            Remove-Item -LiteralPath $Root -Recurse -Force
        } else {
            throw 'The test folder already exists. Delete it yourself, or pass -Force (only works on a folder this kit made). / Folder testowy juz istnieje. Usun go lub uzyj -Force (dziala tylko na folderze utworzonym przez ten skrypt).'
        }
    }
    if (!$SampleA -or !$SampleB) {
        $auto = @(Find-Samples)
        if ($auto.Count -lt 2) { throw 'Could not find two sample .rvt files under C:\ProgramData\Autodesk\RVT *. Pass -SampleA and -SampleB. / Nie znaleziono dwoch przykladowych plikow .rvt. Podaj -SampleA i -SampleB.' }
        if (!$SampleA) { $SampleA = $auto[0] }
        if (!$SampleB) { $SampleB = $auto[1] }
    }
    foreach ($item in @($SampleA, $SampleB, $Newer, $Older) | Where-Object { $_ }) {
        if (!(Test-Path -LiteralPath $item.Trim('"') -PathType Leaf)) { throw 'A model file was not found. / Nie znaleziono pliku modelu.' }
    }
    $a = (Resolve-Path -LiteralPath $SampleA.Trim('"')).ProviderPath
    $b = (Resolve-Path -LiteralPath $SampleB.Trim('"')).ProviderPath
    $nameA = [IO.Path]::GetFileName($a)
    $nameB = [IO.Path]::GetFileName($b)
    if ($nameA -ieq $nameB) { throw 'The two samples have the same file name. Pick different ones. / Oba modele maja te sama nazwe pliku.' }

    # Polish letters from character codes, so this file stays ASCII.
    $polish = 'Projekt za' + [char]0x17C + [char]0xF3 + [char]0x142 + [char]0x107 + ' g' + [char]0x119 + [char]0x15B + 'l' + [char]0x105 + ' ja' + [char]0x17A + [char]0x144 + ' & 100%'

    New-Item -ItemType Directory -Path $Root | Out-Null
    Set-Content -LiteralPath (Join-Path $Root $markerName) -Value 'made by v1_test_kit.ps1' -Encoding UTF8
    $made = New-Object System.Collections.Generic.List[string]
    Copy-Model $a (Join-Path $Root 'Samples') $nameA;                      $made.Add('Samples\A')
    Copy-Model $b (Join-Path $Root 'Samples') $nameB;                      $made.Add('Samples\B')
    Copy-Model $a (Join-Path $Root 'Folder with spaces') 'Model with spaces.rvt'
    $made.Add('Folder with spaces\ (a copy of A)')
    Copy-Model $b (Join-Path $Root $polish) 'Model PL & 100%.rvt'
    $made.Add('<Polish letters, & and %>\ (a copy of B) - used in item C6')
    Copy-Model $a (Join-Path $Root 'Backup') 'Model in Backup folder.rvt'; $made.Add('Backup\ (must NOT be listed)')
    $base = [IO.Path]::GetFileNameWithoutExtension($nameA)
    Copy-Item -LiteralPath $a -Destination (Join-Path $Root ('Samples\' + $base + '.0001.rvt')); $made.Add('Samples\ .0001.rvt backup (must NOT be listed)')
    Copy-Model $a $Root 'Tower.2024.rvt';                                  $made.Add('Tower.2024.rvt (must be listed)')
    Set-Content -LiteralPath (Join-Path $Root 'Not a model.rvt') -Value 'This is plain text, not a Revit file.' -Encoding UTF8
    $made.Add('Not a model.rvt (a text file; greyed as unreadable)')
    if ($Newer) { Copy-Model (Resolve-Path -LiteralPath $Newer.Trim('"')).ProviderPath (Join-Path $Root 'Newer') 'Newer model.rvt'; $made.Add('Newer\ (greyed)') }
    if ($Older) { Copy-Model (Resolve-Path -LiteralPath $Older.Trim('"')).ProviderPath (Join-Path $Root 'Older') 'Older model.rvt'; $made.Add('Older\ (upgrade note)') }

    Write-Host 'Test folder built / Folder testowy zbudowany:' -ForegroundColor Green
    Write-Host "  $Root"
    foreach ($line in $made) { Write-Host "  - $line" }
    Write-Host 'Expected in the Export window: the Samples models, Tower.2024, the spaces and Polish-letter models are listed; Backup and .0001 are skipped; Not a model is greyed.'
    Write-Host 'Oczekiwane w oknie Eksport: modele z Samples, Tower.2024 oraz z folderow ze spacjami i polskimi literami sa na liscie; Backup i .0001 pominiete; Not a model wyszarzony.'
}

# ---------------------------------------------------------------- -Check
function Get-RunFacts([IO.DirectoryInfo]$Dir) {
    $r = [ordered]@{}
    $console = Join-Path $Dir.FullName 'console.log'
    $output = Join-Path $Dir.FullName 'output'
    $hasConsole = Test-Path -LiteralPath $console -PathType Leaf
    $files = @(Get-ChildItem -LiteralPath $output -Recurse -File -ErrorAction SilentlyContinue)
    $r.Folders = ('index={0} output={1} logs={2} journals={3} console={4}' -f
        [int](Test-Path -LiteralPath (Join-Path $Dir.FullName 'index.json') -PathType Leaf),
        [int](Test-Path -LiteralPath $output -PathType Container),
        [int](Test-Path -LiteralPath (Join-Path $Dir.FullName 'logs') -PathType Container),
        [int](Test-Path -LiteralPath (Join-Path $Dir.FullName 'journals') -PathType Container),
        [int]$hasConsole)
    $bubble = Test-Path -LiteralPath (Join-Path $output 'bubble.json') -PathType Leaf
    $resource = Test-Path -LiteralPath (Join-Path $output 'Resource') -PathType Container
    $r.OutputFiles = $files.Count
    $r.OutputMB = [math]::Round((($files | Measure-Object Length -Sum).Sum) / 1MB, 1)
    $r.Bubble = $bubble
    $r.Resource = $resource
    $exit = $null; $summary = '(none)'; $failedJobs = $null; $errors = 0; $warns = 0
    if ($hasConsole) {
        $lines = @(Get-Content -LiteralPath $console -Encoding UTF8)
        $s = $lines | Select-String -Pattern 'Success Jobs:\s*(\d+), Failed Jobs:\s*(\d+)' | Select-Object -Last 1
        if ($s) { $summary = ($s.Matches[0].Value); $failedJobs = [int]$s.Matches[0].Groups[2].Value }
        $e = $lines | Select-String -Pattern 'exit with code \w+\((\d+)\)' | Select-Object -Last 1
        if ($e) { $exit = [int]$e.Matches[0].Groups[1].Value }
        $errors = @($lines | Where-Object { $_ -match '\sERROR\s' -and $_ -notmatch 'mesh number larger than 64k|DSM_InternalErrorMessage' }).Count
        $warns = @($lines | Where-Object { $_ -match '\sWARN\s' -and $_ -notmatch 'mesh number larger than 64k' }).Count
        $r.Seconds = [math]::Round(((Get-Item -LiteralPath $console).LastWriteTime - $Dir.CreationTime).TotalSeconds, 0)
    } else { $r.Seconds = 0 }
    $stderr = Join-Path $Dir.FullName 'stderr.log'
    $r.StderrBytes = if (Test-Path -LiteralPath $stderr -PathType Leaf) { (Get-Item -LiteralPath $stderr).Length } else { -1 }
    $r.Exit = $exit; $r.Summary = $summary; $r.Errors = $errors; $r.Warns = $warns
    if (!$hasConsole -and $files.Count -eq 0) { $r.State = 'NOT STARTED' }
    elseif ($null -eq $exit) { $r.State = 'INCOMPLETE (no exit line: cancelled, still running, or killed)' }
    elseif ($exit -ne 0) { $r.State = 'FAIL (exit code)' }
    elseif ($failedJobs) { $r.State = 'FAIL (failed jobs)' }
    elseif (!$bubble -or !$resource) { $r.State = 'FAIL (output incomplete)' }
    else { $r.State = 'OK' }
    return [pscustomobject]$r
}

function Invoke-Check {
    Write-Host '== Machine / Komputer'
    Write-Host "Print Spooler: $(Get-Spooler)"
    $extractors = @(Get-Process -Name 'RevitExtractor*' -ErrorAction SilentlyContinue)
    $revits = @(Get-Process -Name 'Revit' -ErrorAction SilentlyContinue)
    Write-Host "RevitExtractor processes left / procesy RevitExtractor: $($extractors.Count)"
    Write-Host "Revit.exe processes / procesy Revit.exe: $($revits.Count)"
    foreach ($line in Get-ExtractorBuilds) { Write-Host $line }
    $bad = 0
    if ($Folder) {
        $path = $Folder.Trim('"')
        if (!(Test-Path -LiteralPath $path -PathType Container)) { throw 'The folder was not found. / Nie znaleziono folderu.' }
        $dir = Get-Item -LiteralPath $path
        $runs = @()
        if (Test-Path -LiteralPath (Join-Path $dir.FullName 'index.json') -PathType Leaf) { $runs = @($dir) }
        else {
            $runs = @(Get-ChildItem -LiteralPath $dir.FullName -Directory |
                Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'index.json') -PathType Leaf } |
                Sort-Object CreationTime)
        }
        Write-Host "`n== Runs / Eksporty: $($runs.Count)"
        if (!$runs) { Write-Host 'No run folder (a folder with index.json) found. / Nie znaleziono folderu eksportu (z index.json).' }
        $n = 0
        foreach ($run in $runs) {
            $n++
            $f = Get-RunFacts $run
            Write-Host ("run {0}: {1}" -f $n, $f.State)
            Write-Host ("  exit code: {0}; {1}" -f $(if ($null -eq $f.Exit) { '(none)' } else { $f.Exit }), $f.Summary)
            Write-Host ("  output: {0} files, {1} MB; bubble.json {2}; Resource {3}" -f $f.OutputFiles, $f.OutputMB, $(if ($f.Bubble) { 'yes' } else { 'no' }), $(if ($f.Resource) { 'yes' } else { 'no' }))
            Write-Host ("  folders (1 = present): {0}" -f $f.Folders)
            Write-Host ("  console.log: {0} ERROR line(s), {1} WARN line(s); stderr.log {2} bytes (-1 = missing); about {3} s" -f $f.Errors, $f.Warns, $f.StderrBytes, $f.Seconds)
            if ($f.State -like 'FAIL*') { $bad++ }
        }
    }
    Write-Host "`nSend this output as it is. It holds no paths or model names. / Wyslij ten wynik bez zmian. Nie zawiera sciezek ani nazw modeli."
    return $bad
}

# ---------------------------------------------------------------- main
if ($PSCmdlet.ParameterSetName -eq 'Setup') { Invoke-Setup; exit 0 }
if ($PSCmdlet.ParameterSetName -eq 'Stamp') {
    $p = $Stamp.Trim('"')
    if (!(Test-Path -LiteralPath $p -PathType Leaf)) { throw 'The file was not found. / Nie znaleziono pliku.' }
    $item = Get-Item -LiteralPath $p
    Write-Host ('size {0} bytes; modified {1}' -f $item.Length, $item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))
    exit 0
}
$failed = Invoke-Check
if ($failed) { exit 1 }
exit 0
