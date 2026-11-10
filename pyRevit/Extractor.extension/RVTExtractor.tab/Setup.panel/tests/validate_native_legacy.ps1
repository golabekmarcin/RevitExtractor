# Checks the index profiles with the native Autodesk parser. Every profile is generated twice, by the
# old button's builder (ExportSetupLegacy / ExportSetup bundle) and by lib/rx_index.py. The script
# fails if the two differ, then parses the lib result natively.
#   - nine legacy profiles (Revit 2022-2025 row): every one must PASS;
#   - newest-row profiles (DWG, IFC, IFC setup name, extended properties, topology, UniqueIds):
#     only what the installed parser has is asserted; the rest prints SKIP with its reason.
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
$panel = Split-Path $PSScriptRoot -Parent
$bundle = Join-Path $panel 'ExportSetupLegacy.pushbutton'
$bundleNewest = Join-Path $panel 'ExportSetup.pushbutton'
$lib = [string](Resolve-Path (Join-Path $panel '..\..\lib'))
# 'database' is the expected property DB state; each parser shape reports it differently.
$fixtureSource = @'
import importlib.util
import json
import sys

bundle_dir, newest_dir, lib_dir = sys.argv[1:4]
sys.path.insert(0, bundle_dir)  # the legacy builder imports extractor_i18n by bare name
sys.path.append(lib_dir)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


legacy = load('legacy_config_for_native_check', bundle_dir + '/extractor_config.py')
newest = load('newest_config_for_native_check', newest_dir + '/extractor_config.py')
import rx_capabilities
import rx_index
legacy_caps = rx_capabilities.for_revit(2022)
newest_caps = rx_capabilities.for_revit(2026)
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
# Newest row: checks are (kind, name, value). Whether the installed parser has the property is
# decided on the PowerShell side; a missing one is a SKIP, never a silent pass.
newest_profiles = [
    ('newest-all-options', dict(scope_2d='selected', scope_3d='selected', dwg=True, ifc=True,
        ifc_setup_name='Setup A', extended_properties=True, topology_metadata=True),
        ['uid-2d-b', 'uid-2d-a'], ['uid-3d'],
        [('property', 'Has2DViewing', True), ('property', 'Has3DViewing', True),
         ('property', 'GenerateTopologyMetadata', True),
         ('property', 'GenerateExtendedPropertyDB', True),
         ('format', 'dwg', True), ('format', 'ifc', True),
         ('option', 'IFCExportOption', 'Setup A'),
         ('unique_ids', '2', ['uid-2d-a', 'uid-2d-b']), ('unique_ids', '3', ['uid-3d'])]),
    ('newest-ifc-only', dict(enable_2d=False, enable_3d=False, pdb=False, ifc=True,
        ifc_setup_name='Setup B'), [], [],
        [('property', 'Has2DViewing', False), ('property', 'Has3DViewing', False),
         ('format', 'dwg', False), ('format', 'ifc', True),
         ('option', 'IFCExportOption', 'Setup B')]),
    ('newest-no-extended-without-database', dict(pdb=False, extended_properties=True,
        topology_metadata=True), [], [],
        [('property', 'GenerateExtendedPropertyDB', False),
         ('property', 'GenerateTopologyMetadata', True)]),
]


def same(a, b, text_a, text_b):
    return (json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)) and text_a == text_b


def fixture(name, bundle_builder, bundle_json, lib_caps, options, two, three, **extra):
    old = bundle_builder(options, two, three)
    new = rx_index.build_index(lib_caps, options, two, three)
    row = dict(name=name, payload_json=rx_index.to_json(new), same=same(
        old, new, bundle_json(old), rx_index.to_json(new)),
        selected2=two, selected3=three)
    row.update(extra)
    return row


print(json.dumps(dict(
    legacy=[fixture(name, legacy.build_index, legacy.to_json, legacy_caps, options, two, three,
                    expected=expected)
            for name, options, two, three, expected in profiles],
    newest=[fixture(name, newest.build_index, newest.to_json, newest_caps, options, two, three,
                    checks=[dict(kind=k, name=n, value=v) for k, n, v in checks])
            for name, options, two, three, checks in newest_profiles])))
'@
$fixtureJson = $fixtureSource | & $Python -B - $bundle $bundleNewest $lib
if ($LASTEXITCODE -ne 0) { throw 'Could not generate index fixtures.' }
$fixtureSet = $fixtureJson | ConvertFrom-Json
$fixtures = @($fixtureSet.legacy)
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
        if (-not $fixture.same) { throw "$($fixture.name): lib/rx_index.py result differs from the legacy bundle" }
        Write-Output "PASS bundle == lib: $($fixture.name)"
        [string]$payloadJson = [string]$fixture.payload_json
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
    # Newest row (Revit 2026 and later): no installed Extractor is guaranteed to know these keys.
    # Assert only what the installed parser has; print SKIP with the reason for everything else.
    $unproven = 0
    foreach ($fixture in @($fixtureSet.newest)) {
        if (-not $fixture.same) { throw "$($fixture.name): lib/rx_index.py result differs from the 2026 bundle" }
        Write-Output "PASS bundle == lib: $($fixture.name)"
        [string]$payloadJson = [string]$fixture.payload_json
        if ($parse) {
            $native = $parse.Invoke($null, [object[]]@($payloadJson))
        } else {
            [IO.File]::WriteAllText($temporary, $payloadJson, (New-Object Text.UTF8Encoding $false))
            $native = $constructor.Invoke([object[]]@([string]$temporary))
        }
        foreach ($check in @($fixture.checks)) {
            $label = "$($fixture.name) $($check.kind) $($check.name)"
            $skip = $false
            $actual = $null
            $expected = $check.value
            switch ($check.kind) {
                'property' {
                    $info = $indexType.GetProperty([string]$check.name)
                    if ($info) { $actual = $info.GetValue($native) } else { $skip = $true }
                }
                'format' {
                    $method = $indexType.GetMethod('IsExportFormatEnabled')
                    if ($method) { $actual = $method.Invoke($native, [object[]]@([string]$check.name)) } else { $skip = $true }
                }
                'option' {
                    $method = $indexType.GetMethod('ExportOption')
                    if ($method) { $actual = $method.Invoke($native, [object[]]@([string]$check.name)) } else { $skip = $true }
                }
                'unique_ids' {
                    $info = $indexType.GetProperty("Selected$($check.name)DViewUniqueIdsToExport")
                    if ($info) {
                        $actual = (@($info.GetValue($native)) | ForEach-Object { "$_" }) -join ','
                        $expected = (@($check.value) -join ',')
                    } else { $skip = $true }
                }
                default { throw "Unknown check kind: $($check.kind)" }
            }
            # (continue inside switch would only leave the switch, so the flag is checked here)
            if ($skip) { Write-Output "SKIP ${label}: needs a newer Extractor"; $unproven++; continue }
            if ("$actual" -ne "$expected") {
                throw "${label}: expected $expected, got $actual"
            }
            Write-Output "PASS native parser: $label"
        }
    }
    Write-Output "Newest row: $unproven check(s) not provable with this Extractor (see SKIP lines)."
} finally {
    if (Test-Path $temporary) { Remove-Item $temporary }
}
