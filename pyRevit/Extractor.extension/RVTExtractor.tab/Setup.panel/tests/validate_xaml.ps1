#requires -Version 5.1
<#
.SYNOPSIS
  Loads every *.xaml under -Root in real WPF (Windows PowerShell 5.1, .NET Framework).
  Prints one PASS/FAIL line per file, rx_theme.xaml first. Exit code 1 if any file fails.
.DESCRIPTION
  rx_theme.xaml is parsed first and kept as a ResourceDictionary. Every other file is parsed
  with XamlReader; when its root is a FrameworkElement, the theme is merged into the root's
  resources. Read-only: writes nothing.
  Default -Root is the extension lib folder. Later modules pass their button folder too.
  Does not prove behaviour inside Revit.
#>
param(
    [string]$Root = (Join-Path $PSScriptRoot '..\..\..\lib')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Xaml

if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    Write-Host "FAIL ${Root}: folder not found"
    exit 1
}
$rootFull = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')

function Read-Xaml([string]$path) {
    # UTF8 explicitly: Windows PowerShell 5.1 would otherwise read a BOM-less file as ANSI.
    Get-Content -LiteralPath $path -Raw -Encoding UTF8
}

$files = @(Get-ChildItem -LiteralPath $rootFull -Filter '*.xaml' -File -Recurse |
    Sort-Object @{ Expression = { if ($_.Name -eq 'rx_theme.xaml') { 0 } else { 1 } } }, FullName)

$failed = 0
$theme = $null

if ($files.Count -eq 0) {
    Write-Host "FAIL ${rootFull}: no *.xaml files found"
    exit 1
}

foreach ($file in $files) {
    $relative = $file.FullName.Substring($rootFull.Length).TrimStart('\')
    try {
        $parsed = [System.Windows.Markup.XamlReader]::Parse((Read-Xaml $file.FullName))
        if ($file.Name -eq 'rx_theme.xaml') {
            if ($parsed -isnot [System.Windows.ResourceDictionary]) {
                throw "root is $($parsed.GetType().Name), expected ResourceDictionary"
            }
            $theme = $parsed
        }
        elseif ($parsed -is [System.Windows.FrameworkElement] -and $null -ne $theme) {
            $parsed.Resources.MergedDictionaries.Add($theme)
        }
        Write-Host "PASS $relative"
    }
    catch {
        $failed++
        $message = $_.Exception.Message
        if ($_.Exception.InnerException) { $message = $_.Exception.InnerException.Message }
        Write-Host "FAIL ${relative}: $message"
    }
}

if ($failed -gt 0) { exit 1 }
exit 0
