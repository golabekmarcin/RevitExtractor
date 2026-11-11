#Requires -Version 5.1
<#
Real Extractor run, started from rx_runner's launch spec (specs/SPEC-export-runner.md, Testing).

  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_extractor_integration.ps1
    (no switch)   one run on the sample model; PASS = result ok, sample hash and git status unchanged
    -Cancel       start, wait for RevitExtractor_Client.exe (or 30 s), run the kill spec, check that
                  no process of the tree is left and the run folder still exists
    -Parallel 2   Q28: two models alone (baseline), then both at once; compares results, output
                  file counts, Success Jobs and cross-model names in console.log / journals
    -Analyzer     after the normal run: rx_status.analyzer_plan for its output folder; a "local"
                  plan is started (as the status window starts it, minus --open so no browser
                  tab opens), GET /api/session must list exactly this one export, then the
                  script ends the Node process it started. SKIP (not FAIL) when Node.js 24+ or
                  the Analyzer packages are missing; npm is never run.
    -RevitDirectory, -ModelPath, -ModelPath2, -OutputParent   override the defaults

The process is started with System.Diagnostics.Process from exactly the spec's file, arguments,
working directory and environment, the fields rx_runner.DotNetStarter sets. Everything is written
under -OutputParent (default %TEMP%\rx-integration-<id>); never into the repo or a test-* folder.
Needs CPython 3 on PATH (or -Python). Exit code 0 = PASS, 1 = FAIL.
#>
[CmdletBinding()]
param(
    [string]$RevitDirectory,
    [string]$ModelPath,
    [string]$ModelPath2,
    [string]$OutputParent,
    [switch]$Cancel,
    [switch]$Analyzer,
    [ValidateSet(0, 2)]
    [int]$Parallel = 0,
    [ValidateRange(1, 240)]
    [int]$TimeoutMinutes = 30,
    [string]$Python = 'python'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($Cancel -and $Parallel) { throw 'Use -Cancel or -Parallel, not both.' }
if ($Analyzer -and ($Cancel -or $Parallel)) { throw '-Analyzer goes with the normal run only.' }

$testsDir = $PSScriptRoot
$cli = Join-Path $testsDir 'runner_cli.py'
$repo = (Resolve-Path -LiteralPath (Join-Path $testsDir '..\..\..\..\..')).ProviderPath.TrimEnd('\')
$env:PYTHONDONTWRITEBYTECODE = '1'
$failures = New-Object System.Collections.Generic.List[string]

function Write-Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }
function Add-Failure([string]$Text) { $failures.Add($Text); Write-Host "FAIL: $Text" -ForegroundColor Red }

function Invoke-Cli {
    param([string[]]$CliArgs)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $text = (& $Python -B $cli @CliArgs | Out-String) } finally { $ErrorActionPreference = $previous }
    $code = $LASTEXITCODE
    if (!$text.Trim()) { throw "runner_cli.py $($CliArgs[0]) printed nothing (exit $code)" }
    $data = $text | ConvertFrom-Json
    if ($code -ne 0 -or $data.PSObject.Properties['error']) {
        throw "runner_cli.py $($CliArgs[0]) failed (exit $code): $($data.error)"
    }
    return $data
}

function Get-Spooler {
    $service = Get-Service -Name Spooler -ErrorAction SilentlyContinue
    if ($null -eq $service) { return 'not found' }
    return "StartType=$($service.StartType), Status=$($service.Status)"
}

function Get-RepoState {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $lines = @(& git -C $repo status --porcelain=v1 --untracked-files=all --ignored 2>$null) }
    finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) { return $null }
    return ,$lines
}

function Get-RevitYear([string]$Directory) {
    $revitExe = Join-Path $Directory 'Revit.exe'
    if (!(Test-Path -LiteralPath $revitExe -PathType Leaf)) { return 0 }
    $major = (Get-Item -LiteralPath $revitExe).VersionInfo.FileMajorPart
    if ($major -gt 0 -and $major -lt 100) { return 2000 + $major }
    if ($major -ge 2000 -and $major -le 9999) { return $major }
    return 0
}

function Find-Revit {
    if ($RevitDirectory) {
        $dir = (Resolve-Path -LiteralPath $RevitDirectory.Trim('"')).ProviderPath.TrimEnd('\')
        if (!(Test-Path -LiteralPath (Join-Path $dir 'RevitExtractor\RevitExtractor.exe') -PathType Leaf)) {
            throw "No RevitExtractor\RevitExtractor.exe under $dir"
        }
        return [pscustomobject]@{ Directory = $dir; Year = (Get-RevitYear $dir) }
    }
    $found = @()
    $autodesk = Join-Path $env:ProgramFiles 'Autodesk'
    if (Test-Path -LiteralPath $autodesk -PathType Container) {
        foreach ($folder in Get-ChildItem -LiteralPath $autodesk -Directory -Filter 'Revit *') {
            $year = Get-RevitYear $folder.FullName
            if ($year -and (Test-Path -LiteralPath (Join-Path $folder.FullName 'RevitExtractor\RevitExtractor.exe') -PathType Leaf)) {
                $found += [pscustomobject]@{ Directory = $folder.FullName.TrimEnd('\'); Year = $year }
            }
        }
    }
    if (!$found) { throw 'No Revit folder with RevitExtractor found. Pass -RevitDirectory.' }
    return ($found | Sort-Object Year -Descending | Select-Object -First 1)
}

function Find-Sample([int]$Year) {
    if ($ModelPath) { return (Resolve-Path -LiteralPath $ModelPath.Trim('"')).ProviderPath }
    $candidates = @(Get-ChildItem -Path "C:\ProgramData\Autodesk\RVT $Year\Dynamo\samples\Data\*.rvt" -ErrorAction SilentlyContinue)
    if (!$candidates) { $candidates = @(Get-ChildItem -Path 'C:\ProgramData\Autodesk\RVT *\Dynamo\samples\Data\*.rvt' -ErrorAction SilentlyContinue) }
    if (!$candidates) { throw 'No sample RVT under C:\ProgramData\Autodesk\RVT *\Dynamo\samples\Data. Pass -ModelPath.' }
    return $candidates[0].FullName
}

function Find-SecondSample([int]$Year, [string]$First) {
    if ($ModelPath2) { return (Resolve-Path -LiteralPath $ModelPath2.Trim('"')).ProviderPath }
    $other = @(Get-ChildItem -Path "C:\ProgramData\Autodesk\RVT $Year\Dynamo\samples" -Filter '*.rvt' -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -ne $First } | Sort-Object Length | Select-Object -First 1)
    if ($other) { return $other[0].FullName }
    return $First
}

function Get-Hash([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash }

function Get-Tree([int]$RootPid) {
    $all = @(Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId, Name, CreationDate)
    $tree = @()
    $queue = New-Object System.Collections.Generic.Queue[int]
    $queue.Enqueue($RootPid)
    $seen = @{}
    while ($queue.Count) {
        $current = $queue.Dequeue()
        foreach ($p in $all) {
            if ($p.ProcessId -eq $current -and !$seen.ContainsKey("self$current")) {
                $seen["self$current"] = $true
                $tree += $p
            }
            if ($p.ParentProcessId -eq $current -and $p.ProcessId -ne $current -and !$seen.ContainsKey([string]$p.ProcessId)) {
                $seen[[string]$p.ProcessId] = $true
                $queue.Enqueue([int]$p.ProcessId)
            }
        }
    }
    return $tree
}

function Start-Spec($Spec, [switch]$ShowWindow) {
    # The same fields as rx_runner.DotNetStarter.start(spec, show_window).
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = [string]$Spec.file
    $info.Arguments = [string]$Spec.arguments
    $info.WorkingDirectory = [string]$Spec.working_dir
    $info.UseShellExecute = $false
    $info.CreateNoWindow = -not $ShowWindow
    $info.RedirectStandardInput = $false
    $info.RedirectStandardOutput = $false
    $info.RedirectStandardError = $false
    foreach ($property in @($Spec.env.PSObject.Properties | Sort-Object Name)) {
        $info.EnvironmentVariables[[string]$property.Name] = [string]$property.Value
    }
    $process = [System.Diagnostics.Process]::Start($info)
    if ($null -eq $process) { throw "Process did not start: $($Spec.file)" }
    return $process
}

function New-Run([string]$Model, [string]$Label) {
    $plan = Invoke-Cli @('plan', '--output-parent', $OutputParent, '--revit-dir', $revit.Directory,
                        '--model', $Model, '--year', [string]$revit.Year)
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $process = Start-Spec $plan.spec
    Write-Host ("[{0}] started pid {1}; run folder {2}" -f $Label, $process.Id, $plan.paths.root)
    return [pscustomobject]@{ Label = $Label; Model = $Model; Plan = $plan; Process = $process; Watch = $watch
                              Progress = New-Object System.Collections.Generic.List[string]; TimedOut = $false }
}

function Update-Progress($Run) {
    $line = (Invoke-Cli @('progress', '--root', $Run.Plan.paths.root)).progress
    if ($line -and ($Run.Progress.Count -eq 0 -or $Run.Progress[$Run.Progress.Count - 1] -ne $line)) {
        $Run.Progress.Add($line)
        Write-Host ("[{0}] {1:mm\:ss} {2}" -f $Run.Label, $Run.Watch.Elapsed, $line)
    }
}

function Wait-Runs($Runs) {
    $deadline = [DateTime]::UtcNow.AddMinutes($TimeoutMinutes)
    while ($true) {
        $pending = @($Runs | Where-Object { !$_.Process.HasExited })
        foreach ($run in $Runs) {
            if ($run.Process.HasExited -and $run.Watch.IsRunning) { $run.Watch.Stop() }
        }
        if (!$pending) { break }
        if ([DateTime]::UtcNow -gt $deadline) {
            foreach ($run in $pending) {
                $run.TimedOut = $true
                Write-Host "[$($run.Label)] timed out after $TimeoutMinutes min; killing the tree" -ForegroundColor Yellow
                $kill = Start-Spec (Invoke-Cli @('kill-spec', '--pid', [string]$run.Process.Id))
                [void]$kill.WaitForExit(60000)
            }
            [void]$pending[0].Process.WaitForExit(30000)
            continue
        }
        foreach ($run in $pending) { Update-Progress $run }
        [void]$pending[0].Process.WaitForExit(10000)
    }
    foreach ($run in $Runs) { Update-Progress $run }
}

function Complete-Run($Run) {
    $paths = $Run.Plan.paths
    $exitCode = $Run.Process.ExitCode
    $check = Invoke-Cli @('check', '--root', $paths.root, '--exit-code', [string]$exitCode)
    $files = @(Get-ChildItem -LiteralPath $paths.output -Recurse -File -ErrorAction SilentlyContinue)
    $summary = $null
    if (Test-Path -LiteralPath $paths.console -PathType Leaf) {
        $summary = Select-String -LiteralPath $paths.console -Pattern 'Success Jobs:\s*(\d+), Failed Jobs:\s*(\d+)' |
            Select-Object -Last 1
    }
    $result = [pscustomobject]@{
        Label = $Run.Label; Model = $Run.Model; Root = $paths.root; ExitCode = $exitCode
        State = $check.state; Message = $check.message; SuccessJobs = $check.success_jobs
        FailedJobs = $check.failed_jobs; SummaryLine = $(if ($summary) { $summary.Line.Trim() } else { '(none)' })
        OutputFiles = $files.Count; OutputBytes = [long](($files | Measure-Object Length -Sum).Sum)
        Seconds = [math]::Round($Run.Watch.Elapsed.TotalSeconds, 1); TimedOut = $Run.TimedOut
        LastProgress = $check.progress
    }
    Write-Host ("[{0}] exit {1}, state {2}, {3} s, {4} output files" -f $result.Label, $result.ExitCode,
        $result.State, $result.Seconds, $result.OutputFiles)
    Write-Host ("[{0}] Success Jobs line: {1}" -f $result.Label, $result.SummaryLine)
    Write-Host ("[{0}] message: {1}" -f $result.Label, $result.Message)
    if ($result.State -ne 'ok') { Show-RunLogs $Run }
    return $result
}

function Show-RunLogs($Run) {
    $paths = $Run.Plan.paths
    foreach ($file in @($paths.console, $paths.stderr)) {
        if (Test-Path -LiteralPath $file -PathType Leaf) {
            $lines = @(Get-Content -LiteralPath $file -Encoding UTF8 |
                Where-Object { $_.Trim() -and $_ -notmatch 'mesh number larger than 64k|DSM_InternalErrorMessage' })
            Write-Host "--- last lines of $(Split-Path -Leaf $file) ($($lines.Count) meaningful lines)"
            $lines | Select-Object -Last 25 | ForEach-Object { Write-Host "    $_" }
        } else { Write-Host "--- $(Split-Path -Leaf $file) is missing" }
    }
}

function Test-NamesOther($Run, [string]$OtherName) {
    $paths = $Run.Plan.paths
    $files = @()
    if (Test-Path -LiteralPath $paths.console -PathType Leaf) { $files += $paths.console }
    $files += @(Get-ChildItem -LiteralPath $paths.journals -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    $hits = @($files | Where-Object { Select-String -LiteralPath $_ -SimpleMatch -Pattern $OtherName -Quiet })
    return $hits
}

function Get-LeftOver {
    return @(Get-Process -Name 'RevitExtractor*' -ErrorAction SilentlyContinue)
}

function Test-AnalyzerPlan($Run) {
    # status-window criterion 13. Returns $true for PASS or SKIP; failures go to Add-Failure.
    $output = [string]$Run.Plan.paths.output
    $plan = Invoke-Cli @('analyzer-plan', '--output', $output)
    $found = $plan.found
    Write-Host "Node.js: $(if ($found.node) { "$($found.node) (major $($found.node_major))" } else { 'not found' })"
    Write-Host "Analyzer: $($found.analyzer); server.mjs $($found.server); packages installed $($found.packages)"
    if ($plan.kind -ne 'local') {
        $missing = (!$found.node) -or ($null -eq $found.node_major) -or ([int]$found.node_major -lt 24) -or (!$found.server) -or (!$found.packages)
        if ($missing) {
            Write-Host "SKIP Analyzer: $($plan.reason)" -ForegroundColor Yellow
            Write-Host '     (npm is never run here; install Node.js 24+ / run npm ci in Analyzer, then rerun -Analyzer)'
            return $true
        }
        Add-Failure "analyzer_plan is web although Node.js and the Analyzer are present: $($plan.reason)"
        return $false
    }
    Write-Host "Plan: $($plan.spec.file) $($plan.spec.arguments)"
    Write-Host "      working dir $($plan.spec.working_dir); url $($plan.url)"
    if (!([string]$plan.spec.arguments).EndsWith(' --open')) { Add-Failure 'the local plan does not end with --open' }
    if (!([string]$plan.spec.arguments).Contains('--output "' + $output + '"')) { Add-Failure 'the local plan does not pass the output folder' }
    $spec = [pscustomobject]@{ file = $plan.spec.file; working_dir = $plan.spec.working_dir; env = $plan.spec.env
                               arguments = ([string]$plan.spec.arguments).Substring(0, ([string]$plan.spec.arguments).Length - ' --open'.Length) }
    Write-Host "Started without --open (no browser tab during the test): $($spec.file) $($spec.arguments)"
    $node = Start-Spec $spec -ShowWindow
    Write-Host "Node pid $($node.Id)"
    try {
        $session = $null
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        while ([DateTime]::UtcNow -lt $deadline -and !$node.HasExited) {
            try { $session = Invoke-RestMethod -Uri ($plan.url + 'api/session') -UseBasicParsing -TimeoutSec 5; break }
            catch { [void]$node.WaitForExit(500) }
        }
        if ($null -eq $session) {
            Add-Failure "GET $($plan.url)api/session gave no answer (node exited: $($node.HasExited))"
            return $false
        }
        $exports = @($session.exports)
        Write-Host "/api/session: $($exports.Count) export(s)"
        foreach ($item in $exports) {
            Write-Host "    $($item.name) | root $($item.root) | files $($item.fileCount) | views $(@($item.views).Count) | sqlite $($item.hasSqlite)"
        }
        if ($exports.Count -ne 1) { Add-Failure "/api/session lists $($exports.Count) exports, expected 1"; return $false }
        if ([string]$exports[0].root -ne $output) { Add-Failure "/api/session root is $($exports[0].root), expected $output"; return $false }
        Write-Host 'PASS Analyzer: the local plan started and lists exactly this export' -ForegroundColor Green
        return $true
    }
    finally {
        # End only the Node process this script started; it has no children without --open.
        if (!$node.HasExited) { $node.Kill(); [void]$node.WaitForExit(10000) }
        Write-Host "Node pid $($node.Id) ended by the script: $($node.HasExited)"
        if (!$node.HasExited) { Add-Failure "Node pid $($node.Id) still running" }
        $node.Dispose()
    }
}

# ------------------------------------------------------------------------------------------------
$revit = Find-Revit
$exe = Join-Path $revit.Directory 'RevitExtractor\RevitExtractor.exe'
$utility = Join-Path $revit.Directory 'RevitExtractor\ExtractorUtility.dll'
$sample = Find-Sample $revit.Year

if (!$OutputParent) {
    $OutputParent = Join-Path $env:TEMP ('rx-integration-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
}
$OutputParent = [IO.Path]::GetFullPath($OutputParent.Trim('"')).TrimEnd('\')
if (($OutputParent + '\').StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputParent must be outside the repo: $OutputParent"
}
if ($OutputParent -match '(^|\\)test-[^\\]*(\\|$)') { throw "OutputParent must not be a test-* folder: $OutputParent" }
foreach ($path in @($sample, $ModelPath2) | Where-Object { $_ }) {
    if (([IO.Path]::GetFullPath($path) + '\').StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase) -and $path -match '\\test-') {
        throw "Refusing to read a private test-* export as a model: $path"
    }
}

$mode = if ($Cancel) { 'cancel' } elseif ($Parallel) { "parallel $Parallel" } elseif ($Analyzer) { 'normal + Analyzer' } else { 'normal' }
Write-Step "export-runner integration ($mode)"
Write-Host "Revit:            $($revit.Year) - $($revit.Directory)"
Write-Host "Extractor:        $exe"
Write-Host "  ExtractorUtility.dll FileVersion: $((Get-Item -LiteralPath $utility -ErrorAction SilentlyContinue).VersionInfo.FileVersion)"
Write-Host "  RevitExtractor.exe ProductVersion: $((Get-Item -LiteralPath $exe).VersionInfo.ProductVersion)"
Write-Host "Sample:           $sample"
Write-Host "Output parent:    $OutputParent"
Write-Host "Print Spooler (before): $(Get-Spooler)"
$leftBefore = Get-LeftOver
if ($leftBefore) {
    throw "RevitExtractor processes are already running ($(($leftBefore | ForEach-Object { "$($_.Name):$($_.Id)" }) -join ', ')). Stop them first."
}

$hashes = @{}
$hashes[$sample] = Get-Hash $sample
$repoBefore = Get-RepoState
if ($null -eq $repoBefore) { Write-Host 'git status: unavailable (repo check skipped)' -ForegroundColor Yellow }
New-Item -ItemType Directory -Path $OutputParent -Force | Out-Null
$total = [System.Diagnostics.Stopwatch]::StartNew()

try {
    if (!$Cancel -and !$Parallel) {
        Write-Step 'Run on the sample (in place; the Extractor copies it)'
        $run = New-Run $sample 'run'
        Wait-Runs @($run)
        $result = Complete-Run $run
        if ($result.State -ne 'ok') { Add-Failure "result $($result.State): $($result.Message)" }
        if ($result.TimedOut) { Add-Failure 'timed out' }
        Write-Host "Progress lines seen: $($run.Progress.Count)"
        $run.Progress | Select-Object -First 8 | ForEach-Object { Write-Host "    $_" }
        if ($run.Progress.Count -gt 8) { Write-Host '    ...'; Write-Host "    $($run.Progress[$run.Progress.Count - 1])" }
        Write-Host "stderr.log bytes: $((Get-Item -LiteralPath $run.Plan.paths.stderr -ErrorAction SilentlyContinue).Length)"
        if ($Analyzer) {
            Write-Step 'Analyzer (status-window, Open in Analyzer)'
            if ($result.State -eq 'ok') { [void](Test-AnalyzerPlan $run) }
            else { Add-Failure 'Analyzer check needs a successful run' }
        }
    }

    if ($Cancel) {
        Write-Step 'Cancel: start, wait for RevitExtractor_Client.exe, kill the tree'
        $run = New-Run $sample 'cancel'
        $clientSeen = $false
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        while ([DateTime]::UtcNow -lt $deadline -and !$run.Process.HasExited) {
            if (@(Get-Tree $run.Process.Id | Where-Object { $_.Name -like 'RevitExtractor_Client*' }).Count) { $clientSeen = $true; break }
            [void]$run.Process.WaitForExit(500)
        }
        $tree = @(Get-Tree $run.Process.Id)
        Write-Host ("Client seen: {0} after {1:N1} s" -f $clientSeen, $run.Watch.Elapsed.TotalSeconds)
        Write-Host "Tree before kill: $(($tree | ForEach-Object { "$($_.Name):$($_.ProcessId)" }) -join ' -> ')"
        if ($run.Process.HasExited) { Add-Failure 'the run ended before it could be cancelled' }
        $killSpec = Invoke-Cli @('kill-spec', '--pid', [string]$run.Process.Id)
        Write-Host "Kill spec: $($killSpec.file) $($killSpec.arguments)"
        $kill = Start-Spec $killSpec
        if (!$kill.WaitForExit(60000)) { Add-Failure 'taskkill did not finish in 60 s' }
        Write-Host "taskkill exit code: $($kill.ExitCode)"
        if ($kill.ExitCode -ne 0) { Add-Failure "taskkill exit code $($kill.ExitCode)" }
        if (!$run.Process.WaitForExit(30000)) { Add-Failure 'cmd.exe still running 30 s after the kill' }
        $run.Watch.Stop()
        $left = @()
        for ($i = 0; $i -lt 20; $i++) {
            $now = @(Get-CimInstance Win32_Process -Property ProcessId, Name, CreationDate)
            $left = @($tree | Where-Object { $member = $_; $now | Where-Object { $_.ProcessId -eq $member.ProcessId -and $_.CreationDate -eq $member.CreationDate } })
            if (!$left) { break }
            Start-Sleep -Milliseconds 500
        }
        if ($left) { Add-Failure "left running: $(($left | ForEach-Object { "$($_.Name):$($_.ProcessId)" }) -join ', ')" }
        else { Write-Host "No process of the tree is left ($($tree.Count) checked)." }
        if (Test-Path -LiteralPath $run.Plan.paths.root -PathType Container) {
            Write-Host "Run folder still exists: $($run.Plan.paths.root)"
            Write-Host "  contents: $((Get-ChildItem -LiteralPath $run.Plan.paths.root | ForEach-Object { $_.Name }) -join ', ')"
        } else { Add-Failure 'the run folder is gone' }
        Write-Host "cmd.exe exit code after the kill: $($run.Process.ExitCode)"
        $check = Invoke-Cli @('check', '--root', $run.Plan.paths.root, '--exit-code', [string]$run.Process.ExitCode)
        Write-Host "check_result: $($check.state) - $($check.message)"
    }

    if ($Parallel) {
        Write-Step 'Parallel (Q28): copies under different names, baselines, then both at once'
        $second = Find-SecondSample $revit.Year $sample
        if (!$hashes.ContainsKey($second)) { $hashes[$second] = Get-Hash $second }
        $modelsDir = Join-Path $OutputParent 'models'
        New-Item -ItemType Directory -Path $modelsDir -Force | Out-Null
        $copyA = Join-Path $modelsDir ('rxA-' + [IO.Path]::GetFileName($sample))
        $copyB = Join-Path $modelsDir ('rxB-' + [IO.Path]::GetFileName($second))
        Copy-Item -LiteralPath $sample -Destination $copyA
        Copy-Item -LiteralPath $second -Destination $copyB
        $nameA = [IO.Path]::GetFileNameWithoutExtension($copyA)
        $nameB = [IO.Path]::GetFileNameWithoutExtension($copyB)
        Write-Host "Model A: $sample -> $copyA"
        Write-Host "Model B: $second -> $copyB"

        $baseA = New-Run $copyA 'A alone'; Wait-Runs @($baseA); $resA = Complete-Run $baseA
        $baseB = New-Run $copyB 'B alone'; Wait-Runs @($baseB); $resB = Complete-Run $baseB
        $runA = New-Run $copyA 'A parallel'
        $runB = New-Run $copyB 'B parallel'
        $parallelWatch = [System.Diagnostics.Stopwatch]::StartNew()
        Wait-Runs @($runA, $runB)
        $parallelWatch.Stop()
        $parA = Complete-Run $runA
        $parB = Complete-Run $runB

        Write-Step 'Parallel comparison'
        $rows = @($resA, $resB, $parA, $parB)
        $rows | Format-Table Label, State, ExitCode, Seconds, OutputFiles, OutputBytes, SuccessJobs, FailedJobs -AutoSize | Out-String | Write-Host
        Write-Host ("Wall time: baselines {0:N1} s + {1:N1} s = {2:N1} s sequential; parallel {3:N1} s" -f
            $resA.Seconds, $resB.Seconds, ($resA.Seconds + $resB.Seconds), $parallelWatch.Elapsed.TotalSeconds)
        foreach ($row in $rows) { if ($row.State -ne 'ok') { Add-Failure "$($row.Label): $($row.State) - $($row.Message)" } }
        foreach ($pair in @(@($resA, $parA), @($resB, $parB))) {
            if ($pair[0].OutputFiles -ne $pair[1].OutputFiles) {
                Add-Failure "$($pair[1].Label): $($pair[1].OutputFiles) output files, baseline $($pair[0].OutputFiles)"
            }
            if ([string]$pair[0].SuccessJobs -ne [string]$pair[1].SuccessJobs) {
                Add-Failure "$($pair[1].Label): Success Jobs $($pair[1].SuccessJobs), baseline $($pair[0].SuccessJobs)"
            }
        }
        foreach ($check in @(@($runA, $nameB), @($runB, $nameA), @($baseA, $nameB), @($baseB, $nameA))) {
            $hits = Test-NamesOther $check[0] $check[1]
            if ($hits) { Add-Failure "$($check[0].Label) names $($check[1]) in: $($hits -join ', ')" }
            else { Write-Host "$($check[0].Label): console.log and journals do not name $($check[1])" }
        }
        Write-Host "Model copies after the runs: A $(if ((Get-Hash $copyA) -eq $hashes[$sample]) { 'unchanged' } else { 'CHANGED' }), B $(if ((Get-Hash $copyB) -eq $hashes[$second]) { 'unchanged' } else { 'CHANGED' })"
    }
} finally {
    $total.Stop()
    Write-Step 'Checks after the run'
    foreach ($path in $hashes.Keys) {
        $after = Get-Hash $path
        if ($after -eq $hashes[$path]) { Write-Host "SHA-256 unchanged: $path ($after)" }
        else { Add-Failure "SHA-256 changed: $path" }
    }
    $repoAfter = Get-RepoState
    if ($null -ne $repoBefore -and $null -ne $repoAfter) {
        if ((@($repoBefore) -join "`n") -ne (@($repoAfter) -join "`n")) {
            Add-Failure 'git status changed during the run'
            $before = @($repoBefore) + @('')
            $after = @($repoAfter) + @('')
            Compare-Object -ReferenceObject $before -DifferenceObject $after |
                ForEach-Object { Write-Host ("    {0} {1}" -f $_.SideIndicator, $_.InputObject) }
        } else { Write-Host "git status (incl. ignored) unchanged: $(@($repoAfter).Count) entries" }
    }
    $left = Get-LeftOver
    if ($left) { Add-Failure "RevitExtractor processes still running: $(($left | ForEach-Object { "$($_.Name):$($_.Id)" }) -join ', ')" }
    else { Write-Host 'No RevitExtractor*.exe process is running.' }
    Write-Host "Print Spooler (after):  $(Get-Spooler)"
    Write-Host ("Total time: {0:N1} s" -f $total.Elapsed.TotalSeconds)
    Write-Host "Run folders kept under: $OutputParent"
}

if ($failures.Count) {
    Write-Host "`nRESULT: FAIL ($($failures.Count))" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host "`nRESULT: PASS ($mode)" -ForegroundColor Green
exit 0
