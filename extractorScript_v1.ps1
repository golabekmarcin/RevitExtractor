#Requires -Version 5.1
# Compatibility entry point: use the shared launcher and choose a Revit version.
$launcher = Join-Path $PSScriptRoot 'Analyzer/public/downloads/Start-RevitExport.ps1'
if (!(Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Brak launchera: $launcher. Pobierz Start-RevitExport.ps1 lub pelne repozytorium."
}
& $launcher @args
exit $LASTEXITCODE
