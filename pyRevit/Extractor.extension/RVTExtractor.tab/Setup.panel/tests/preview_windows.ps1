#requires -Version 5.1
<#
.SYNOPSIS
  Renders the new windows with sample rows to PNG files, in English and Polish.
.DESCRIPTION
  For each window (today: lib\rx_status.xaml), loads the XAML in real WPF with rx_theme.xaml
  merged, fills the {DynamicResource} text and sample rows from runner_cli.py status-sample
  (rx_status.resources() and job_view() of made-up jobs), shows it off-screen without focus,
  renders it, and writes <OutputDir>\<window>-<lang>.png. Default OutputDir:
  %TEMP%\rx-window-preview. Nothing is written into the repo.
  Needs CPython 3 on PATH (or -Python). Proves layout and text only: no IronPython, no pyRevit,
  no Revit.
#>
param(
    [string]$OutputDir = (Join-Path $env:TEMP 'rx-window-preview'),
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Xaml

$testsDir = $PSScriptRoot
$lib = (Resolve-Path -LiteralPath (Join-Path $testsDir '..\..\..\lib')).Path
$repo = (Resolve-Path -LiteralPath (Join-Path $testsDir '..\..\..\..\..')).Path.TrimEnd('\')
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (($OutputDir + '\').StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must be outside the repo: $OutputDir"
}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$env:PYTHONDONTWRITEBYTECODE = '1'

function Read-Xaml([string]$Path) { Get-Content -LiteralPath $Path -Raw -Encoding UTF8 }

function Get-Sample([string]$Lang) {
    $text = (& $Python -B (Join-Path $testsDir 'runner_cli.py') status-sample --lang $Lang | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "runner_cli.py status-sample failed: $text" }
    return $text | ConvertFrom-Json
}

function Invoke-Idle {
    $frame = New-Object System.Windows.Threading.DispatcherFrame
    $callback = [System.Windows.Threading.DispatcherOperationCallback] { param($f) $f.Continue = $false; $null }
    [void][System.Windows.Threading.Dispatcher]::CurrentDispatcher.BeginInvoke(
        [System.Windows.Threading.DispatcherPriority]::ApplicationIdle, $callback, $frame)
    [System.Windows.Threading.Dispatcher]::PushFrame($frame)
}

function Save-Png($Element, [string]$Path) {
    $width = [int][math]::Ceiling($Element.ActualWidth)
    $height = [int][math]::Ceiling($Element.ActualHeight)
    $bitmap = New-Object System.Windows.Media.Imaging.RenderTargetBitmap($width, $height, 96, 96,
        [System.Windows.Media.PixelFormats]::Pbgra32)
    $bitmap.Render($Element)
    $encoder = New-Object System.Windows.Media.Imaging.PngBitmapEncoder
    $encoder.Frames.Add([System.Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
    $stream = [IO.File]::Create($Path)
    try { $encoder.Save($stream) } finally { $stream.Dispose() }
}

$theme = [System.Windows.Markup.XamlReader]::Parse((Read-Xaml (Join-Path $lib 'rx_theme.xaml')))
$written = @()

foreach ($lang in @('en', 'pl')) {
    $sample = Get-Sample $lang
    $window = [System.Windows.Markup.XamlReader]::Parse((Read-Xaml (Join-Path $lib 'rx_status.xaml')))
    foreach ($property in $sample.resources.PSObject.Properties) {
        $window.Resources[[string]$property.Name] = [string]$property.Value
    }
    $window.Resources.MergedDictionaries.Add($theme)
    try { $window.Style = $window.FindResource('RxWindow') } catch { }

    $rows = New-Object System.Collections.ObjectModel.ObservableCollection[object]
    foreach ($view in $sample.views) {
        $rows.Add([pscustomobject]@{
            Model = [string]$view.model; ModelPath = [string]$view.model_path
            State = [string]$view.state_text; Progress = [string]$view.progress
            Started = [string]$view.started; Time = [string]$view.time })
    }
    $list = $window.FindName('jobs_lv')
    $list.ItemsSource = $rows
    $list.SelectedIndex = [int]$sample.selected
    $selected = $sample.views[[int]$sample.selected]
    $window.FindName('cancel_btn').IsEnabled = [bool]$selected.can_cancel
    $window.FindName('open_folder_btn').IsEnabled = [bool]$selected.can_open_folder
    $window.FindName('open_analyzer_btn').IsEnabled = [bool]$selected.can_open_analyzer
    $window.FindName('summary_text').Text = [string]$sample.summary
    $window.FindName('hint_text').Text = [string]$sample.hint
    $window.FindName('error_text').Text = [string]$sample.error

    # Off-screen, no focus, no taskbar button: nothing appears on the desktop.
    $window.WindowStartupLocation = [System.Windows.WindowStartupLocation]::Manual
    $window.Left = -20000
    $window.Top = -20000
    $window.ShowActivated = $false
    $window.ShowInTaskbar = $false
    $window.Show()
    try {
        Invoke-Idle
        $path = Join-Path $OutputDir "status-window-$lang.png"
        Save-Png $window $path
        $written += $path
        Write-Host ("PASS status-window {0}: {1} ({2}x{3})" -f $lang, $path, [int]$window.ActualWidth, [int]$window.ActualHeight)
    }
    finally { $window.Close() }
}

Write-Host "Written: $($written.Count) PNG file(s) under $OutputDir"
exit 0
