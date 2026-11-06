param(
    [string]$ExtractorDirectory = 'C:\Program Files\Autodesk\Revit 2022\RevitExtractor',
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$bundle = Join-Path (Split-Path $PSScriptRoot -Parent) 'ExportSetup22.pushbutton'
$fixtureSource = @'
import json
import sys
sys.path.insert(0, sys.argv[1])
from extractor_config import build_index
profiles = [
    ('defaults', {}, [], [], dict(Has2DViewing=True, Has3DViewing=True, PropertyDbStorageType='Sqlite',
        GenerateAECModelData=True, GenerateDesignDescription=True, GenerateMaster3DViews=False,
        GenerateTopologyMetadata=False, F2D=False)),
    ('selected-2d', dict(enable_3d=False, scope_2d='selected'), [14325], [],
        dict(Has2DViewing=True, Has3DViewing=False, PropertyDbStorageType='Sqlite')),
    ('selected-3d', dict(enable_2d=False, scope_3d='selected'), [], [14720],
        dict(Has2DViewing=False, Has3DViewing=True)),
    ('separate-selections', dict(scope_2d='selected', scope_3d='selected'), [14325, 22118], [14720],
        dict(Has2DViewing=True, Has3DViewing=True)),
    ('no-database', dict(pdb=False), [], [], dict(PropertyDbStorageType='None')),
    ('database-only', dict(enable_2d=False, enable_3d=False), [], [],
        dict(Has2DViewing=False, Has3DViewing=False, PropertyDbStorageType='Sqlite')),
    ('advanced', dict(aec_model_data=False, design_description=False, generate_master_views=True,
        f2d=True), [], [],
        dict(GenerateAECModelData=False, GenerateDesignDescription=False, GenerateMaster3DViews=True,
        GenerateTopologyMetadata=False, GenerateExtendedPropertyDB=False, F2D=True)),
    ('int32-limit', dict(scope_3d='selected'), [], [2147483647], dict(Has3DViewing=True)),
]
print(json.dumps([dict(name=name, payload=build_index(options, two, three), expected=expected,
    selected2=two, selected3=three) for name, options, two, three, expected in profiles]))
'@
$fixtureJson = $fixtureSource | & $Python -B - $bundle
if ($LASTEXITCODE -ne 0) { throw 'Could not generate Revit 2022 index fixtures.' }
$fixtures = $fixtureJson | ConvertFrom-Json
foreach ($file in @('Newtonsoft.Json.dll', 'log4net.dll', 'ExtractorUtility.dll')) {
    $assembly = [Reflection.Assembly]::LoadFrom((Join-Path $ExtractorDirectory $file))
}
$indexType = $assembly.GetType('Autodesk.ExtractorUtility.IndexJson', $true)
Write-Output ('Parser: {0}; file version {1}' -f $assembly.Location,
    [Diagnostics.FileVersionInfo]::GetVersionInfo($assembly.Location).FileVersion)
foreach ($fixture in $fixtures) {
    [string]$payloadJson = ConvertTo-Json $fixture.payload -Depth 20
    $native = $indexType.GetMethod('Parse').Invoke($null, [object[]]@($payloadJson))
    foreach ($property in $fixture.expected.PSObject.Properties) {
        $actual = $indexType.GetProperty($property.Name).GetValue($native)
        if ($actual -ne $property.Value) {
            throw "$($fixture.name): $($property.Name) expected $($property.Value), got $actual"
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
