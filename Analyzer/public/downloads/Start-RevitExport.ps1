#Requires -Version 5.1
<#
One-file interactive launcher for installed Autodesk Revit Extractor versions.
Run: powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-RevitExport.ps1
The execution-policy override applies only to that process.
#>
[CmdletBinding()]
param(
    [string]$IndexPath,
    [string]$ModelPath,
    [string]$OutputParent,
    [ValidatePattern('^\d{4}$')]
    [string]$RevitVersion,
    [string]$RevitDirectory,
    [switch]$UseDefaultIndex,
    [switch]$ValidateOnly,
    [switch]$NoPause,
    [ValidateSet('en','pl')]
    [string]$Language = 'en'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$resultCode = 1
$lock = $null
$lockTaken = $false

function T { param([string]$English, [string]$Polish) if ($Language -eq 'pl') { $Polish } else { $English } }

# No view IDs or model-specific IFC setup: leave view selection to the Extractor.
$defaultIndexJson = @'
{
  "metadata": {
    "parameters": {
      "derivative_type": {
        "2dviewing": {},
        "3dviewing": {},
        "properties_data": { "pdb": true }
      }
    }
  }
}
'@

function Select-InputFile {
    param([string]$Label, [string]$Extension)
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    try {
        $dialog.Title = $Label
        $dialog.Filter = "$Extension (*$Extension)|*$Extension"
        $dialog.CheckFileExists = $true
        if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw (T 'File selection cancelled.' 'Anulowano wybor pliku.') }
        return $dialog.FileName
    } finally { $dialog.Dispose() }
}

function Read-InputFile {
    param([string]$Value, [string]$Label, [string]$Extension)
    while ($true) {
        if ([string]::IsNullOrWhiteSpace($Value)) {
            Write-Host "`n$Label"
            Write-Host (T 'Paste the full path or press Enter to pick a file in a dialog.' 'Wklej pelna sciezke lub nacisnij Enter, aby wybrac plik w oknie.')
            $Value = Read-Host (T 'Path (Q = cancel)' 'Sciezka (Q = anuluj)')
            if ($Value -eq 'Q') { throw (T 'Cancelled.' 'Anulowano.') }
            if ([string]::IsNullOrWhiteSpace($Value)) {
                $Value = Select-InputFile $Label $Extension
            }
        }
        $Value = $Value.Trim().Trim('"')
        if ((Test-Path -LiteralPath $Value -PathType Leaf) -and [IO.Path]::GetExtension($Value) -ieq $Extension) {
            return (Resolve-Path -LiteralPath $Value).ProviderPath
        }
        if ($ValidateOnly) { throw ((T 'File not found {0} : {1}' 'Nie znaleziono pliku {0} : {1}') -f $Extension, $Value) }
        Write-Host ((T 'File not found {0} : {1}' 'Nie znaleziono pliku {0} : {1}') -f $Extension, $Value) -ForegroundColor Yellow
        $Value = ''
    }
}

function Get-RevitInstallation {
    param([string]$Directory)
    if ([string]::IsNullOrWhiteSpace($Directory)) { return }
    $Directory = $Directory.Trim().Trim('"')
    $revitExe = Join-Path $Directory 'Revit.exe'
    $extractorExe = Join-Path $Directory 'RevitExtractor\RevitExtractor.exe'
    if (!(Test-Path -LiteralPath $revitExe -PathType Leaf) -or
        !(Test-Path -LiteralPath $extractorExe -PathType Leaf)) { return }
    $Directory = (Resolve-Path -LiteralPath $Directory).ProviderPath
    # Registry locations often end with a slash; discovery must list them only once.
    if ($Directory.Length -gt ([IO.Path]::GetPathRoot($Directory)).Length) {
        $Directory = $Directory.TrimEnd('\', '/')
    }
    # Revit.exe has a major file version such as 22; ProductVersion is a build date.
    # The Extractor's own version can differ from the Revit release hosting it.
    $major = (Get-Item -LiteralPath $revitExe).VersionInfo.FileMajorPart
    $release = if ($major -gt 0 -and $major -lt 100) { [string](2000 + $major) }
               elseif ($major -ge 2000 -and $major -le 9999) { [string]$major }
               else { '' }
    if (!$release) { return }
    [pscustomobject]@{
        Version = $release
        Directory = $Directory
        Exe = Join-Path $Directory 'RevitExtractor\RevitExtractor.exe'
        ExtractorVersion = (Get-Item -LiteralPath $extractorExe).VersionInfo.ProductVersion
    }
}

function Get-RevitInstallations {
    $directories = @()
    if ($env:ProgramFiles) {
        $autodesk = Join-Path $env:ProgramFiles 'Autodesk'
        if (Test-Path -LiteralPath $autodesk -PathType Container) {
            $directories += Get-ChildItem -LiteralPath $autodesk -Directory -Filter 'Revit *' |
                Select-Object -ExpandProperty FullName
        }
    }
    # Registered locations also cover installations outside Program Files.
    $registryRoot = 'HKLM:\SOFTWARE\Autodesk\Revit'
    if (Test-Path -LiteralPath $registryRoot -ErrorAction SilentlyContinue) {
        foreach ($key in Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue) {
            if ($key.PSChildName -notmatch '^(Autodesk Revit )?\d{4}$') { continue }
            $keys = @($key) + @(Get-ChildItem -LiteralPath $key.PSPath -ErrorAction SilentlyContinue)
            foreach ($installKey in $keys) {
                $values = Get-ItemProperty -LiteralPath $installKey.PSPath -ErrorAction SilentlyContinue
                if ($null -eq $values) { continue }
                foreach ($name in @('InstallationLocation', 'InstallLocation', 'InstallPath', 'InstallDir')) {
                    $property = $values.PSObject.Properties[$name]
                    if ($null -ne $property -and $property.Value) { $directories += [string]$property.Value }
                }
            }
        }
    }
    $seen = @{}
    foreach ($directory in $directories) {
        $installation = Get-RevitInstallation $directory
        if ($null -ne $installation -and !$seen.ContainsKey($installation.Directory)) {
            $seen[$installation.Directory] = $true
            $installation
        }
    }
}

function Select-RevitInstallation {
    param([string]$RequestedVersion, [string]$Directory)
    if ($ValidateOnly -and !$RequestedVersion -and !$Directory) {
        throw (T 'ValidateOnly requires RevitVersion or RevitDirectory to pick one installation unambiguously.' 'ValidateOnly wymaga RevitVersion lub RevitDirectory, aby jednoznacznie wybrac instalacje.')
    }
    if ($Directory) {
        $installation = Get-RevitInstallation $Directory
        if ($null -eq $installation) { throw ((T 'No valid Revit installation with RevitExtractor: {0}' 'Brak poprawnej instalacji Revita z RevitExtractor: {0}') -f $Directory) }
        if ($RequestedVersion -and $installation.Version -ne $RequestedVersion) {
            throw ((T 'Revit {0} was requested, but the folder contains Revit {1}: {2}' 'Wybrano Revit {0}, ale folder zawiera Revit {1}: {2}') -f $RequestedVersion, $installation.Version, $Directory)
        }
        return $installation
    }
    $installations = @(Get-RevitInstallations | Sort-Object @{Expression = { [int]$_.Version }; Descending = $true}, Directory)
    if ($RequestedVersion) {
        $installations = @($installations | Where-Object { $_.Version -eq $RequestedVersion })
        if ($installations.Count -eq 1) { return $installations[0] }
    }
    if ($ValidateOnly) {
        throw ((T 'Did not find exactly one Revit {0} installation with the Extractor. Provide RevitDirectory.' 'Nie znaleziono jednej instalacji Revit {0} z Extractorem. Podaj RevitDirectory.') -f $RequestedVersion)
    }
    while ($true) {
        Write-Host ("`n" + (T 'Choose the Revit version to export with:' 'Wybierz wersje Revita do eksportu:')) -ForegroundColor Cyan
        for ($i = 0; $i -lt $installations.Count; $i++) {
            Write-Host ('  {0}. Revit {1} - {2}' -f ($i + 1), $installations[$i].Version, $installations[$i].Directory)
        }
        if (!$installations.Count) { Write-Host (T 'No installation with RevitExtractor found. You can point to a folder manually.' 'Nie znaleziono instalacji z RevitExtractor. Mozesz wskazac folder recznie.') }
        Write-Host (T '  M. Pick another installation folder' '  M. Wskaz inny folder instalacji')
        Write-Host (T '  Q. Cancel' '  Q. Anuluj')
        $choice = (Read-Host (T 'Item number, version year, M or Q' 'Numer pozycji, rok wersji, M lub Q')).Trim()
        if ($choice -eq 'Q') { throw (T 'Revit version selection cancelled.' 'Anulowano wybor wersji Revita.') }
        if ($choice -eq 'M') {
            $folder = (Read-Host (T 'Revit installation folder containing Revit.exe (Q = cancel)' 'Folder instalacji Revita, zawierajacy Revit.exe (Q = anuluj)')).Trim().Trim('"')
            if ($folder -eq 'Q') { throw (T 'Revit version selection cancelled.' 'Anulowano wybor wersji Revita.') }
            $installation = Get-RevitInstallation $folder
            if ($null -eq $installation) {
                Write-Host (T 'No valid Revit installation with RevitExtractor in this folder.' 'Brak poprawnej instalacji Revita z RevitExtractor w tym folderze.') -ForegroundColor Yellow
                continue
            }
            if ($RequestedVersion -and $installation.Version -ne $RequestedVersion) {
                Write-Host ((T 'This folder contains Revit {0}; Revit {1} is required.' 'Ten folder zawiera Revit {0}; wymagany Revit {1}.') -f $installation.Version, $RequestedVersion) -ForegroundColor Yellow
                continue
            }
            return $installation
        }
        if ($choice -match '^\d{4}$') {
            $matching = @($installations | Where-Object { $_.Version -eq $choice })
            if ($matching.Count -eq 1) { return $matching[0] }
        } else {
            $number = 0
            if ([int]::TryParse($choice, [ref]$number) -and $number -ge 1 -and $number -le $installations.Count) {
                return $installations[$number - 1]
            }
        }
        Write-Host (T 'Pick an item from the list, or M to point to a folder.' 'Wybierz pozycje z listy albo M, aby wskazac folder.') -ForegroundColor Yellow
    }
}

try {
    Write-Host ("`n" + (T 'Revit Extractor - local export' 'Revit Extractor - eksport lokalny')) -ForegroundColor Cyan
    Write-Host (T 'Save the RVT first, including Collaborate > Publish Settings sets if you use them.' 'Najpierw zapisz RVT, w tym zestawy Collaborate > Publish Settings, jesli ich uzywasz.')
    if ($UseDefaultIndex -and ![string]::IsNullOrWhiteSpace($IndexPath)) { throw (T 'Choose UseDefaultIndex or IndexPath, not both.' 'Wybierz UseDefaultIndex albo IndexPath, nie oba naraz.') }
    if ($ValidateOnly -and (!$ModelPath -or !$OutputParent)) { throw (T 'ValidateOnly requires ModelPath and OutputParent.' 'ValidateOnly wymaga ModelPath i OutputParent.') }
    $installation = Select-RevitInstallation $RevitVersion $RevitDirectory
    $RevitVersion = $installation.Version
    $RevitDirectory = $installation.Directory
    $exe = $installation.Exe
    $version = $installation.ExtractorVersion
    Write-Host ((T 'Selected Revit {0} - {1}' 'Wybrano Revit {0} - {1}') -f $RevitVersion, $RevitDirectory) -ForegroundColor Green
    if (!$UseDefaultIndex -and [string]::IsNullOrWhiteSpace($IndexPath)) {
        if ($ValidateOnly) { $UseDefaultIndex = $true }
        else {
            Write-Host ("`n" + (T 'Configuration: Enter = built-in (2D + 3D + parameters).' 'Konfiguracja: Enter = wbudowana (2D + 3D + parametry).'))
            Write-Host (T 'Does not force a view list. The Extractor chooses the scope; this does not mean all views.' 'Nie wymusza listy widokow. Zakres wybiera Extractor; nie oznacza to wszystkich widokow.')
            $choice = (Read-Host (T 'Enter = default, P = pick index.json, Q = cancel, or paste a path' 'Enter = domyslna, P = wybierz index.json, Q = anuluj, lub wklej sciezke')).Trim()
            if ($choice -eq 'Q') { throw (T 'Cancelled.' 'Anulowano.') }
            if (!$choice) { $UseDefaultIndex = $true }
            elseif ($choice -eq 'P') { $IndexPath = Select-InputFile (T 'Pick the index.json configuration' 'Wskaz konfiguracje index.json') '.json' }
            else { $IndexPath = $choice }
        }
    }

    if ($UseDefaultIndex) { $config = $defaultIndexJson | ConvertFrom-Json }
    else {
        $IndexPath = Read-InputFile $IndexPath (T 'Pick the index.json configuration' 'Wskaz konfiguracje index.json') '.json'
        $config = Get-Content -LiteralPath $IndexPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    if (!$config -or !$config.PSObject.Properties['metadata'] -or !$config.metadata -or
        !$config.metadata.PSObject.Properties['parameters'] -or !$config.metadata.parameters -or
        !$config.metadata.parameters.PSObject.Properties['derivative_type'] -or !$config.metadata.parameters.derivative_type) {
        throw (T 'Invalid configuration: metadata.parameters.derivative_type is required. Generate index.json in pyRevit.' 'Nieprawidlowa konfiguracja: wymagane metadata.parameters.derivative_type. Wygeneruj index.json w pyRevit.')
    }
    $ModelPath = Read-InputFile $ModelPath ((T 'Pick the saved model for Revit {0} (.rvt)' 'Wskaz zapisany model dla Revit {0} (.rvt)') -f $RevitVersion) '.rvt'

    if ([string]::IsNullOrWhiteSpace($OutputParent)) {
        $defaultOutput = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'RevitExtractor'
        $OutputParent = Read-Host ((T 'Output folder [Enter = {0}, Q = cancel]' 'Folder wynikow [Enter = {0}, Q = anuluj]') -f $defaultOutput)
        if ($OutputParent -eq 'Q') { throw (T 'Cancelled.' 'Anulowano.') }
        if ([string]::IsNullOrWhiteSpace($OutputParent)) { $OutputParent = $defaultOutput }
    }
    $OutputParent = [IO.Path]::GetFullPath($OutputParent.Trim().Trim('"'))
    if ((Test-Path -LiteralPath $OutputParent) -and !(Test-Path -LiteralPath $OutputParent -PathType Container)) { throw (T 'The output location must be a folder.' 'Miejsce wynikow musi byc folderem.') }
    # Reject quotes/newlines before forming a Windows native-process argument string.
    foreach ($value in @($IndexPath, $ModelPath, $OutputParent, $RevitDirectory)) {
        if ($value -match '["\r\n]') { throw (T 'The path contains a forbidden character.' 'Sciezka zawiera niedozwolony znak.') }
    }

    if ($UseDefaultIndex) {
        Write-Host ("`n" + (T 'Configuration: built-in - 2D + 3D + parameters, default Extractor scope.' 'Konfiguracja: wbudowana - 2D + 3D + parametry, domyslny zakres Extractora.'))
        Write-Host (T 'The index will be saved in the new export folder as index.json.' 'Indeks zostanie zapisany w nowym folderze eksportu jako index.json.')
    } else { Write-Host ("`n" + ((T 'Configuration: {0}' 'Konfiguracja: {0}') -f $IndexPath)) }
    Write-Host ((T 'RVT model:   {0}' 'Model RVT:   {0}') -f $ModelPath)
    Write-Host ('Revit:       {0} ({1})' -f $RevitVersion, $RevitDirectory)
    Write-Host "Extractor:   $version"
    Write-Host ((T 'Results:     {0} (a new separate folder for every run)' 'Wyniki:      {0} (nowy osobny folder dla kazdego uruchomienia)') -f $OutputParent)
    if ($ValidateOnly) {
        Write-Host (T 'Validation OK. The export was not started and no folders were created.' 'Walidacja OK. Nie uruchomiono eksportu i nie utworzono folderow.') -ForegroundColor Green
        $resultCode = 0
    } elseif ((Read-Host (T 'Run the export? [Y/N]' 'Uruchomic eksport? [T/N]')) -notin $(if ($Language -eq 'pl') { @('T', 'TAK') } else { @('Y', 'YES') })) {
        Write-Host (T 'Cancelled. The export was not started.' 'Anulowano. Nie uruchomiono eksportu.')
        $resultCode = 0
    } else {
        # The Extractor uses a fixed IPC pipe; the pyRevit Export button takes the same mutex.
        if (Get-Process -Name RevitExtractor,RevitExtractor_Client -ErrorAction SilentlyContinue) {
            throw (T 'Another Revit Extractor is already running. Wait for it to finish.' 'Inny Revit Extractor jest juz uruchomiony. Poczekaj, az sie zakonczy.')
        }
        $busy = (T 'Another export is already running. Wait for it to finish.' 'Inny eksport jest juz uruchomiony. Poczekaj, az sie zakonczy.')
        $lock = New-Object System.Threading.Mutex($false, 'Global\RevitExtractor.ExtractorRun')
        try { $lockTaken = $lock.WaitOne(0) }
        catch [System.Threading.AbandonedMutexException] { $lockTaken = $true }
        catch [System.UnauthorizedAccessException] { throw $busy }
        if (!$lockTaken) { throw $busy }
        $runName = 'export-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
        $runRoot = Join-Path $OutputParent $runName
        $outputDir = Join-Path $runRoot 'output'
        $logDir = Join-Path $runRoot 'logs'
        $journalDir = Join-Path $runRoot 'journals'
        $runIndex = Join-Path $runRoot 'index.json'
        New-Item -ItemType Directory -Path $outputDir,$logDir,$journalDir -Force | Out-Null
        if ($UseDefaultIndex) {
            [IO.File]::WriteAllText($runIndex, $defaultIndexJson + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
        } else { Copy-Item -LiteralPath $IndexPath -Destination $runIndex }
        $arguments = @($runIndex, $ModelPath, '-RCEPath', $RevitDirectory, '-LogPath', $logDir, '-journalPath', $journalDir)
        $argumentLine = ($arguments | ForEach-Object { '"' + $_.TrimEnd('\') + '"' }) -join ' '
        Write-Host ("`n" + (T 'Export in progress. This can take many minutes. Wait for it to finish.' 'Trwa eksport. Moze to potrwac wiele minut. Poczekaj na zakonczenie.'))
        Write-Host ((T 'Logs: {0}' 'Logi: {0}') -f $runRoot)
        $process = Start-Process -FilePath $exe -ArgumentList $argumentLine -WorkingDirectory $RevitDirectory -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'console.log') -RedirectStandardError (Join-Path $runRoot 'stderr.log')
        $resultCode = $process.ExitCode
        Write-Host ((T 'Exit code: {0}' 'Kod zakonczenia: {0}') -f $resultCode)
        if ($resultCode -ne 0) { throw ((T 'The Extractor failed. Check console.log, stderr.log, logs and journals in {0}' 'Extractor zakonczyl sie bledem. Sprawdz console.log, stderr.log, logs i journals w {0}') -f $runRoot) }
        $summary = Select-String -LiteralPath (Join-Path $runRoot 'console.log') -Pattern 'Success Jobs:\s*(\d+), Failed Jobs:\s*(\d+)' | Select-Object -Last 1
        if ($summary -and [int]$summary.Matches[0].Groups[2].Value -gt 0) {
            $resultCode = 1
            throw ((T 'Some export jobs failed. Check console.log and logs in {0}' 'Czesc zadan eksportu nie powiodla sie. Sprawdz console.log i logs w {0}') -f $runRoot)
        }
        if (!(Test-Path -LiteralPath (Join-Path $outputDir 'bubble.json') -PathType Leaf) -or !(Test-Path -LiteralPath (Join-Path $outputDir 'Resource') -PathType Container)) {
            $resultCode = 1
            throw ((T 'The export structure is incomplete. Check the logs in {0}' 'Brak kompletnej struktury eksportu. Sprawdz logi w {0}') -f $runRoot)
        }
        Write-Host ("`n" + (T 'Process finished. Check the logs for the status of each job (IFC/PDF/3D).' 'Proces zakonczony. Sprawdz w logach statusy poszczegolnych zadan (IFC/PDF/3D).')) -ForegroundColor Green
        Write-Host (T 'Open https://kopecp.github.io/RevitExtractor/ and choose Open folder:' 'Otworz https://kopecp.github.io/RevitExtractor/ i wybierz Otworz folder:')
        Write-Host $outputDir -ForegroundColor Cyan
    }
} catch {
    if ($resultCode -eq 0) { $resultCode = 1 }
    Write-Host ("`n" + (T 'Error: ' 'Blad: ') + $_.Exception.Message) -ForegroundColor Red
} finally {
    if ($lock) {
        if ($lockTaken) { $lock.ReleaseMutex() }
        $lock.Dispose()
    }
    if (!$NoPause -and !$ValidateOnly) { [void](Read-Host ("`n" + (T 'Press Enter to close' 'Nacisnij Enter, aby zamknac'))) }
}
exit $resultCode
