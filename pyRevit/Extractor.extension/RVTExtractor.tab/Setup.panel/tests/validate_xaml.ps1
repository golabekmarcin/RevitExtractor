#requires -Version 5.1
<#
.SYNOPSIS
  Loads every *.xaml under the given roots in real WPF (Windows PowerShell 5.1, .NET Framework).
  Prints one PASS/FAIL line per file, rx_theme.xaml first. Exit code 1 if any file fails.
.DESCRIPTION
  rx_theme.xaml (the first one found, lib/ first) is parsed first and kept as a
  ResourceDictionary. Every other file is parsed with XamlReader; when its root is a
  FrameworkElement, the theme is merged into the root's resources. Read-only: writes nothing.
  Default roots: the extension lib folder and the new Export.pushbutton folder. A default root
  that does not exist yet is skipped (SKIP line); a root passed with -Root must exist.
  -Root takes several folders, as an array or one string separated by ';' (powershell -File
  passes a single string). Does not prove behaviour inside Revit.
#>
param(
    [string[]]$Root
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Xaml

$explicit = [bool]$Root
if (-not $explicit) {
    $Root = @((Join-Path $PSScriptRoot '..\..\..\lib'), (Join-Path $PSScriptRoot '..\Export.pushbutton'))
}
$roots = @($Root | ForEach-Object { $_ -split ';' } | Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.Trim().Trim('"') })

function Read-Xaml([string]$path) {
    # UTF8 explicitly: Windows PowerShell 5.1 would otherwise read a BOM-less file as ANSI.
    Get-Content -LiteralPath $path -Raw -Encoding UTF8
}

$failed = 0
$entries = @()
$order = 0
foreach ($folder in $roots) {
    if (-not (Test-Path -LiteralPath $folder -PathType Container)) {
        if ($explicit) {
            Write-Host "FAIL ${folder}: folder not found"
            $failed++
        }
        else {
            Write-Host "SKIP ${folder}: folder not found (not built yet)"
        }
        continue
    }
    $full = (Resolve-Path -LiteralPath $folder).Path.TrimEnd('\')
    $label = Split-Path -Leaf $full
    foreach ($file in @(Get-ChildItem -LiteralPath $full -Filter '*.xaml' -File -Recurse | Sort-Object FullName)) {
        $entries += [pscustomobject]@{
            File = $file; Root = $order
            Name = $label + '\' + $file.FullName.Substring($full.Length).TrimStart('\')
        }
    }
    $order++
}

if ($entries.Count -eq 0) {
    Write-Host "FAIL: no *.xaml files found under $($roots -join ', ')"
    exit 1
}

$entries = @($entries | Sort-Object @{ Expression = { if ($_.File.Name -eq 'rx_theme.xaml') { 0 } else { 1 } } }, Root, Name)
$theme = $null

foreach ($entry in $entries) {
    try {
        $parsed = [System.Windows.Markup.XamlReader]::Parse((Read-Xaml $entry.File.FullName))
        if ($entry.File.Name -eq 'rx_theme.xaml') {
            if ($parsed -isnot [System.Windows.ResourceDictionary]) {
                throw "root is $($parsed.GetType().Name), expected ResourceDictionary"
            }
            if ($null -eq $theme) { $theme = $parsed }
        }
        elseif ($parsed -is [System.Windows.FrameworkElement] -and $null -ne $theme) {
            $parsed.Resources.MergedDictionaries.Add($theme)
        }
        Write-Host "PASS $($entry.Name)"
    }
    catch {
        $failed++
        $message = $_.Exception.Message
        if ($_.Exception.InnerException) { $message = $_.Exception.InnerException.Message }
        Write-Host "FAIL $($entry.Name): $message"
    }
}

if ($failed -gt 0) { exit 1 }
exit 0
