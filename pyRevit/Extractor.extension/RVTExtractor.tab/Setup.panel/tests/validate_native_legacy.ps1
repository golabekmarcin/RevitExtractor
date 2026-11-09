# Checks the ExportSetupLegacy (Revit 2022-2025) index profiles with the native Autodesk parser.
# Supports both parser shapes:
#   Extractor 2025.3+  : static IndexJson.Parse(json), PropertyDbStorageType
#   Extractor 2024.0.x : new IndexJson(path), GeneratePropertyDB from 3dviewing.db_export
# Without -ExtractorDirectory, it uses the first Revit 2022-2025 install that has RevitExtractor.
param(
    [string]$ExtractorDirectory,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
if (-not $ExtractorDirectory) {
    $ExtractorDirectory = 2022..2025 |
        ForEach-Object { Join-Path $env:ProgramFiles "Autodesk\Revit $_\RevitExtractor" } |
        Where-Object { Test-Path (Join-Path $_ 'ExtractorUtility.dll') } | Select-Object -First 1
    if (-not $ExtractorDirectory) { throw 'No Revit 2022-2025 RevitExtractor found; pass -ExtractorDirectory.' }
}
$bundle = Join-Path (Split-Path $PSScriptRoot -Parent) 'ExportSetupLegacy.pushbutton'
# 'database' is the expected property DB state; each parser shape reports it differently.
$fixtureSource = @'
import json
import sys
sys.path.insert(0, sys.argv[1])
from extractor_config import build_index
profiles = [
    ('defaults', {}, [], [], dict(Has2DViewing=True, Has3DViewing=True, database=True,
        GenerateAECModelData=True, GenerateDesignDescription=True, GenerateMaster3DViews=False,
        GenerateTopologyMetadata=False, F2D=False)),
    ('selected-2d', dict(enable_3d=False, scope_2d='selected'), [14325], [],
        dict(Has2DViewing=True, Has3DViewing=False, database=True)),
    ('selected-3d', dict(enable_2d=False, scope_3d='selected'), [], [14720],
        dict(Has2DViewing=False, Has3DViewing=True)),
    ('separate-selections', dict(scope_2d='selected', scope_3d='selected'), [14325, 22118], [14720],
        dict(Has2DViewing=True, Has3DViewing=True)),
    ('no-database', dict(pdb=False), [], [], dict(database=False)),
    ('database-only', dict(enable_2d=False, enable_3d=False), [], [],
        dict(Has2DViewing=False, Has3DViewing=False, database=True)),
    ('advanced', dict(aec_model_data=False, design_description=False, generate_master_views=True,
        f2d=True), [], [],
        dict(GenerateAECModelData=False, GenerateDesignDescription=False, GenerateMaster3DViews=True,
        GenerateTopologyMetadata=False, GenerateExtendedPropertyDB=False, F2D=True)),
    ('int32-limit', dict(scope_3d='selected'), [], [2147483647], dict(Has3DViewing=True)),
    # Known limit of Extractor 2024.0.x: without 3D the DB cannot be switched off (see README).
    ('2d-only-no-database', dict(enable_3d=False, pdb=False), [], [],
        dict(Has2DViewing=True, Has3DViewing=False, database=False, database_2024=True)),
]
print(json.dumps([dict(name=name, payload=build_index(options, two, three), expected=expected,
    selected2=two, selected3=three) for name, options, two, three, expected in profiles]))
'@
$fixtureJson = $fixtureSource | & $Python -B - $bundle
if ($LASTEXITCODE -ne 0) { throw 'Could not generate index fixtures.' }
$fixtures = $fixtureJson | ConvertFrom-Json
foreach ($file in @('Newtonsoft.Json.dll', 'log4net.dll', 'ExtractorUtility.dll')) {
    $assembly = [Reflection.Assembly]::LoadFrom((Join-Path $ExtractorDirectory $file))
}
$indexType = $assembly.GetType('Autodesk.ExtractorUtility.IndexJson', $true)
$parse = $indexType.GetMethod('Parse')
$constructor = $indexType.GetConstructor([type[]]@([string]))
if (-not $parse -and -not $constructor) {
    throw 'Unknown IndexJson shape: neither static Parse nor a (String path) constructor.'
}
$shape = if ($parse) { 'Parse (2025.3+)' } else { 'constructor (2024.0.x)' }
Write-Output ('Parser: {0}; file version {1}; shape {2}' -f $assembly.Location,
    [Diagnostics.FileVersionInfo]::GetVersionInfo($assembly.Location).FileVersion, $shape)
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('extractor-index-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    foreach ($fixture in $fixtures) {
        [string]$payloadJson = ConvertTo-Json $fixture.payload -Depth 20
        if ($parse) {
            $native = $parse.Invoke($null, [object[]]@($payloadJson))
        } else {
            [IO.File]::WriteAllText($temporary, $payloadJson, (New-Object Text.UTF8Encoding $false))
            # Keep the [string] casts: cmdlet output (Join-Path, ConvertTo-Json) is PSObject-wrapped,
            # and reflection then looks for a PSObject parameter ("Constructor ... not found").
            $native = $constructor.Invoke([object[]]@([string]$temporary))
        }
        foreach ($property in $fixture.expected.PSObject.Properties) {
            if ($property.Name -eq 'database_2024') { continue }
            if ($property.Name -eq 'database') {
                if ($parse) {
                    $name = 'PropertyDbStorageType'
                    $expected = if ($property.Value) { 'Sqlite' } else { 'None' }
                } else {
                    $name = 'GeneratePropertyDB'
                    $override = $fixture.expected.PSObject.Properties['database_2024']
                    $expected = if ($override) { $override.Value } else { $property.Value }
                }
            } else {
                $name = $property.Name
                $expected = $property.Value
            }
            $actual = $indexType.GetProperty($name).GetValue($native)
            if ("$actual" -ne "$expected") {
                throw "$($fixture.name): $name expected $expected, got $actual"
            }
        }
        foreach ($dimension in @('2', '3')) {
            $selection = $indexType.GetProperty("Selected${dimension}DViewIdsToExport").GetValue($native)
            # Older parsers return integer IDs directly; newer ones wrap them in Id.
            $actual = @($selection | ForEach-Object {
                if ($null -ne $_) {
                    if ($null -ne $_.PSObject.Properties['Id']) { $_.Id } else { $_ }
                }
            })
            $expected = @($fixture."selected$dimension")
            if (($actual -join ',') -ne ($expected -join ',')) {
                throw "$($fixture.name): selected $dimension IDs mismatch: $actual"
            }
            foreach ($id in $actual) {
                if ($id -isnot [int] -and $id -isnot [long]) { throw 'Selected ID is not numeric.' }
            }
        }
        foreach ($format in @('dwg', 'ifc')) {
            if ($indexType.GetMethod('IsExportFormatEnabled').Invoke($native, @($format))) {
                throw "$($fixture.name): unsupported $format export enabled"
            }
        }
        Write-Output "PASS native parser: $($fixture.name)"
    }
} finally {
    if (Test-Path $temporary) { Remove-Item $temporary }
}
