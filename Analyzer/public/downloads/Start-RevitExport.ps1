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
    [switch]$NoPause
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$resultCode = 1

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
        if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw 'Anulowano wybor pliku.' }
        return $dialog.FileName
    } finally { $dialog.Dispose() }
}

function Read-InputFile {
    param([string]$Value, [string]$Label, [string]$Extension)
    while ($true) {
        if ([string]::IsNullOrWhiteSpace($Value)) {
            Write-Host "`n$Label"
            Write-Host 'Wklej pelna sciezke lub nacisnij Enter, aby wybrac plik w oknie.'
            $Value = Read-Host 'Sciezka (Q = anuluj)'
            if ($Value -eq 'Q') { throw 'Anulowano.' }
            if ([string]::IsNullOrWhiteSpace($Value)) {
                $Value = Select-InputFile $Label $Extension
            }
        }
        $Value = $Value.Trim().Trim('"')
        if ((Test-Path -LiteralPath $Value -PathType Leaf) -and [IO.Path]::GetExtension($Value) -ieq $Extension) {
            return (Resolve-Path -LiteralPath $Value).ProviderPath
        }
        if ($ValidateOnly) { throw "Nie znaleziono pliku $Extension : $Value" }
        Write-Host "Nie znaleziono pliku $Extension : $Value" -ForegroundColor Yellow
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
        throw 'ValidateOnly wymaga RevitVersion lub RevitDirectory, aby jednoznacznie wybrac instalacje.'
    }
    if ($Directory) {
        $installation = Get-RevitInstallation $Directory
        if ($null -eq $installation) { throw "Brak poprawnej instalacji Revita z RevitExtractor: $Directory" }
        if ($RequestedVersion -and $installation.Version -ne $RequestedVersion) {
            throw "Wybrano Revit $RequestedVersion, ale folder zawiera Revit $($installation.Version): $Directory"
        }
        return $installation
    }
    $installations = @(Get-RevitInstallations | Sort-Object @{Expression = { [int]$_.Version }; Descending = $true}, Directory)
    if ($RequestedVersion) {
        $installations = @($installations | Where-Object { $_.Version -eq $RequestedVersion })
        if ($installations.Count -eq 1) { return $installations[0] }
    }
    if ($ValidateOnly) {
        throw "Nie znaleziono jednej instalacji Revit $RequestedVersion z Extractorem. Podaj RevitDirectory."
    }
    while ($true) {
        Write-Host "`nWybierz wersje Revita do eksportu:" -ForegroundColor Cyan
        for ($i = 0; $i -lt $installations.Count; $i++) {
            Write-Host ('  {0}. Revit {1} - {2}' -f ($i + 1), $installations[$i].Version, $installations[$i].Directory)
        }
        if (!$installations.Count) { Write-Host 'Nie znaleziono instalacji z RevitExtractor. Mozesz wskazac folder recznie.' }
        Write-Host '  M. Wskaz inny folder instalacji'
        Write-Host '  Q. Anuluj'
        $choice = (Read-Host 'Numer pozycji, rok wersji, M lub Q').Trim()
        if ($choice -eq 'Q') { throw 'Anulowano wybor wersji Revita.' }
        if ($choice -eq 'M') {
            $folder = (Read-Host 'Folder instalacji Revita, zawierajacy Revit.exe (Q = anuluj)').Trim().Trim('"')
            if ($folder -eq 'Q') { throw 'Anulowano wybor wersji Revita.' }
            $installation = Get-RevitInstallation $folder
            if ($null -eq $installation) {
                Write-Host 'Brak poprawnej instalacji Revita z RevitExtractor w tym folderze.' -ForegroundColor Yellow
                continue
            }
            if ($RequestedVersion -and $installation.Version -ne $RequestedVersion) {
                Write-Host "Ten folder zawiera Revit $($installation.Version); wymagany Revit $RequestedVersion." -ForegroundColor Yellow
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
        Write-Host 'Wybierz pozycje z listy albo M, aby wskazac folder.' -ForegroundColor Yellow
    }
}

try {
    Write-Host "`nRevit Extractor - eksport lokalny" -ForegroundColor Cyan
    Write-Host 'Najpierw zapisz RVT, w tym zestawy Collaborate > Publish Settings, jesli ich uzywasz.'
    if ($UseDefaultIndex -and ![string]::IsNullOrWhiteSpace($IndexPath)) { throw 'Wybierz UseDefaultIndex albo IndexPath, nie oba naraz.' }
    if ($ValidateOnly -and (!$ModelPath -or !$OutputParent)) { throw 'ValidateOnly wymaga ModelPath i OutputParent.' }
    $installation = Select-RevitInstallation $RevitVersion $RevitDirectory
    $RevitVersion = $installation.Version
    $RevitDirectory = $installation.Directory
    $exe = $installation.Exe
    $version = $installation.ExtractorVersion
    Write-Host "Wybrano Revit $RevitVersion - $RevitDirectory" -ForegroundColor Green
    if (!$UseDefaultIndex -and [string]::IsNullOrWhiteSpace($IndexPath)) {
        if ($ValidateOnly) { $UseDefaultIndex = $true }
        else {
            Write-Host "`nKonfiguracja: Enter = wbudowana (2D + 3D + parametry)."
            Write-Host 'Nie wymusza listy widokow. Zakres wybiera Extractor; nie oznacza to wszystkich widokow.'
            $choice = (Read-Host 'Enter = domyslna, P = wybierz index.json, Q = anuluj, lub wklej sciezke').Trim()
            if ($choice -eq 'Q') { throw 'Anulowano.' }
            if (!$choice) { $UseDefaultIndex = $true }
            elseif ($choice -eq 'P') { $IndexPath = Select-InputFile 'Wskaz konfiguracje index.json' '.json' }
            else { $IndexPath = $choice }
        }
    }

    if ($UseDefaultIndex) { $config = $defaultIndexJson | ConvertFrom-Json }
    else {
        $IndexPath = Read-InputFile $IndexPath 'Wskaz konfiguracje index.json' '.json'
        $config = Get-Content -LiteralPath $IndexPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    if (!$config -or !$config.PSObject.Properties['metadata'] -or !$config.metadata -or
        !$config.metadata.PSObject.Properties['parameters'] -or !$config.metadata.parameters -or
        !$config.metadata.parameters.PSObject.Properties['derivative_type'] -or !$config.metadata.parameters.derivative_type) {
        throw 'Nieprawidlowa konfiguracja: wymagane metadata.parameters.derivative_type. Wygeneruj index.json w pyRevit.'
    }
    $ModelPath = Read-InputFile $ModelPath "Wskaz zapisany model dla Revit $RevitVersion (.rvt)" '.rvt'

    if ([string]::IsNullOrWhiteSpace($OutputParent)) {
        $defaultOutput = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'RevitExtractor'
        $OutputParent = Read-Host "Folder wynikow [Enter = $defaultOutput, Q = anuluj]"
        if ($OutputParent -eq 'Q') { throw 'Anulowano.' }
        if ([string]::IsNullOrWhiteSpace($OutputParent)) { $OutputParent = $defaultOutput }
    }
    $OutputParent = [IO.Path]::GetFullPath($OutputParent.Trim().Trim('"'))
    if ((Test-Path -LiteralPath $OutputParent) -and !(Test-Path -LiteralPath $OutputParent -PathType Container)) { throw 'Miejsce wynikow musi byc folderem.' }
    # Reject quotes/newlines before forming a Windows native-process argument string.
    foreach ($value in @($IndexPath, $ModelPath, $OutputParent, $RevitDirectory)) {
        if ($value -match '["\r\n]') { throw 'Sciezka zawiera niedozwolony znak.' }
    }

    if ($UseDefaultIndex) {
        Write-Host "`nKonfiguracja: wbudowana - 2D + 3D + parametry, domyslny zakres Extractora."
        Write-Host 'Indeks zostanie zapisany w nowym folderze eksportu jako index.json.'
    } else { Write-Host "`nKonfiguracja: $IndexPath" }
    Write-Host "Model RVT:   $ModelPath"
    Write-Host "Revit:       $RevitVersion ($RevitDirectory)"
    Write-Host "Extractor:   $version"
    Write-Host "Wyniki:      $OutputParent (nowy osobny folder dla kazdego uruchomienia)"
    if ($ValidateOnly) {
        Write-Host 'Walidacja OK. Nie uruchomiono eksportu i nie utworzono folderow.' -ForegroundColor Green
        $resultCode = 0
    } elseif ((Read-Host 'Uruchomic eksport? [T/N]') -notin @('T', 'TAK')) {
        Write-Host 'Anulowano. Nie uruchomiono eksportu.'
        $resultCode = 0
    } else {
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
        Write-Host "`nTrwa eksport. Moze to potrwac wiele minut. Poczekaj na zakonczenie."
        Write-Host "Logi: $runRoot"
        $process = Start-Process -FilePath $exe -ArgumentList $argumentLine -WorkingDirectory $RevitDirectory -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'console.log') -RedirectStandardError (Join-Path $runRoot 'stderr.log')
        $resultCode = $process.ExitCode
        Write-Host "Kod zakonczenia: $resultCode"
        if ($resultCode -ne 0) { throw "Extractor zakonczyl sie bledem. Sprawdz console.log, stderr.log, logs i journals w $runRoot" }
        $summary = Select-String -LiteralPath (Join-Path $runRoot 'console.log') -Pattern 'Success Jobs:\s*(\d+), Failed Jobs:\s*(\d+)' | Select-Object -Last 1
        if ($summary -and [int]$summary.Matches[0].Groups[2].Value -gt 0) {
            $resultCode = 1
            throw "Czesc zadan eksportu nie powiodla sie. Sprawdz console.log i logs w $runRoot"
        }
        if (!(Test-Path -LiteralPath (Join-Path $outputDir 'bubble.json') -PathType Leaf) -or !(Test-Path -LiteralPath (Join-Path $outputDir 'Resource') -PathType Container)) {
            $resultCode = 1
            throw "Brak kompletnej struktury eksportu. Sprawdz logi w $runRoot"
        }
        Write-Host "`nProces zakonczony. Sprawdz w logach statusy poszczegolnych zadan (IFC/PDF/3D)." -ForegroundColor Green
        Write-Host 'Otworz https://kopecp.github.io/RevitExtractor/ i wybierz Otworz folder:'
        Write-Host $outputDir -ForegroundColor Cyan
    }
} catch {
    if ($resultCode -eq 0) { $resultCode = 1 }
    Write-Host "`nBlad: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    if (!$NoPause -and !$ValidateOnly) { [void](Read-Host "`nNacisnij Enter, aby zamknac") }
}
exit $resultCode
