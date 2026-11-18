# v1 Revit test: the owner's one session

One session, about two hours (Part H, the Cloud source, adds 30 minutes and needs your ACC model; Part I, file names, adds 25 minutes), on the Revit 2022 + pyRevit machine. Part F (10 minutes) is on the machine with Revit 2025. Answer with the item number and PASS, FAIL or a note, for example `C6 FAIL: second window appeared`. Results come back privately, never through git.

**Everything below is unverified inside Revit.** The unit tests and the real Extractor runs on the agent's machine never ran IronPython, pyRevit or Revit's API. This session is the first time the code runs there, so a first-click failure (Part A) is possible and cheap to find: Part A comes first and takes minutes.

## Before you start (10 minutes, Revit closed)

**Every command block below is complete.** Each one sets the variables it needs (`$repo`, `$kit`, `$out`, `$res`), so you can paste any block into a fresh PowerShell window. `$repo` comes from the variable `RX_REPO` (step 0 below, once per machine), so the blocks hold no personal paths. `$out` is read from the output folder that the Export window uses. `$res` is `C:\RX-test\results`, where the blocks that must be sent back save their output as a text file (with `Tee-Object`), so you can attach the file instead of copying from the window. These files hold no model names or paths, except G2, which names your Windows user folder: private. Never commit them. (`-Setup -Force` would delete `C:\RX-test`, results included, so copy the results out first.)

**Execution policy.** The blocks do not change it. If a script is refused with "not digitally signed" (a file marked as downloaded from the Internet), run `Get-ChildItem -Recurse "$repo\pyRevit" -Filter *.ps1 | Unblock-File` once. A machine policy such as RemoteSigned is fine: it runs local scripts, and `Set-ExecutionPolicy` would only fail against it.

0. Tell the blocks where your clone is, once per machine. Use the folder that contains `pyRevit` and `specs`, and put your real path in place of the example:

```powershell
[Environment]::SetEnvironmentVariable('RX_REPO', 'C:\Users\m.golabek\OneDrive - Cundall\_Working Locally\0000000 - BIM\01_Revit\01_Scripts\00_RevitExtractor\RevitExtractor', 'User')   # edit this path
$env:RX_REPO = [Environment]::GetEnvironmentVariable('RX_REPO', 'User')                       # also for this window
$env:RX_REPO                                                                                  # prints your path
Test-Path $env:RX_REPO                                                                        # must print True
```

   New PowerShell windows get the variable by themselves. Windows that were already open need the second line. Do not commit your path anywhere: this file is in a public repository.
1. Git, on each machine (never `git pull`; `HANDOVER.md` §1):

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Set-Location $repo
git fetch origin
git reset --keep origin/mgo-changes
git log --oneline -1   # note this line: it says which version you are testing
```

   Then **Reload pyRevit** (or restart Revit).
2. Optional, for the local Analyzer (item C3). It needs Node.js 24 or later, installed by you or from the Company Portal; restart Revit after installing it. Without it, C3 tests the website fallback; say which one you tested. Check Node and install the packages once:

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
node --version        # must print v24 or higher
Set-Location (Join-Path $repo 'Analyzer')
.\Start-Analyzer.cmd  # first run installs the packages (Internet needed), then starts the server; close its window to stop it
```

   If `npm ci` reports a certificate error, `Start-Analyzer.cmd` already trusts the Windows certificate store; if it still fails, ask IT for the company root certificate and run `npm config set cafile "C:\path\to\root.pem"`. Do not turn off `strict-ssl`.
3. Build the sample folder with the test kit:

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Set-Location $repo
$kit = Join-Path $repo 'pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\v1_test_kit.ps1'
if (-not (Test-Path $kit)) { throw 'Wrong $repo: v1_test_kit.ps1 not found. Set $repo to the folder that holds pyRevit and specs.' }
& $kit -Setup
# With a newer and an older model for items B6 and D6, use this line instead:
# & $kit -Setup -Newer 'D:\path\newer-model.rvt' -Older 'D:\path\older-model.rvt'
# To build it again later: add -Force (it removes only a folder this kit made).
```

   It takes the two smallest different sample models under `C:\ProgramData\Autodesk\RVT <year>\` and builds `C:\RX-test` (change it with `-Root`). Only copies are made; your models are never opened or changed. `-Setup` refuses an existing folder (`-Force` removes one this kit made). It creates:
   - `Samples\` with both samples (A and B), plus a `.0001.rvt` backup of A next to them;
   - `Folder with spaces\` and a folder with Polish letters, `&` and `%` in its name, each with a copy;
   - `Backup\` with a copy;
   - `Tower.2024.rvt` (a model whose name looks like a version);
   - `Not a model.rvt`, a text file;
   - optional `Newer\` and `Older\`: add `-Newer '<model saved in a newer Revit>'` and `-Older '<model saved in an older Revit>'`. A Revit 2025 sample is a good "newer" one. Without them, items B6 and D6 are skipped.
4. **S1** The "before" check. Note the Print Spooler start type and that no `RevitExtractor` process is running:

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Set-Location $repo
$kit = Join-Path $repo 'pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\v1_test_kit.ps1'
if (-not (Test-Path $kit)) { throw 'Wrong $repo: v1_test_kit.ps1 not found. Set $repo to the folder that holds pyRevit and specs.' }
$res = 'C:\RX-test\results'; New-Item -ItemType Directory -Force $res | Out-Null
& $kit -Check *>&1 | Tee-Object (Join-Path $res 'S1.txt')
```

The kit has three commands. Its output holds no paths or model names, so it is safe to send:
- `-Setup`: as above.
- `-Check`: machine lines (Print Spooler, leftover `RevitExtractor*` and `Revit.exe` processes, Extractor builds). With a folder (`-Check $out`) it also reports each run in it: state OK / FAIL / INCOMPLETE / NOT STARTED, exit code, the `Success Jobs` line, output file counts, which folders exist, error counts and the duration. The folder is one run folder, or the output folder that holds several (runs are numbered in the order they were created).
- `-Stamp '<file>'`: the file's size and last-write time, for before and after comparisons.

The output folder is by default `Documents\RevitExtractor`. In the blocks `$out` is that folder.

## Part A: the first click (5 minutes; stop here if it fails)

Start Revit with no model open.

- [Works] **A1** The **Export** button is on the ribbon (RevitExtractor tab, Setup panel) and enabled. Open any model: it is greyed. Close the model: enabled again.
- [Works] **A2** Click Export. The window opens, and pyRevit's output window shows no error. **If it does not open, send the text of the output window and stop here.** (An import error under IronPython would show up exactly here.)
- [Works] **A3** The old "Export setup" button still opens and searches as before. Close it.

## Part B: model window, no export yet (10 minutes)

- [Works] **B1** Add folder… `C:\RX-test`. Rows appear. Not listed: the file in `Backup` and the `.0001.rvt` file. Listed: `Tower.2024`, and the model in the folder with Polish letters, `&` and `%`.
- [Works] **B2** While rows appear, the window stays responsive (it can be moved, and the search box takes text).
- [Works] **B3** `Not a model.rvt` is greyed as unreadable, cannot be ticked, and has a tooltip.
- [Works] **B4** Search, the ▾ filters, Select all shown and Space behave as in the old window. Select all shown does not tick greyed rows.
- [Works] **B5** Close and reopen: the folder and the output folder are remembered, and the list fills faster (the cache file `catalog-cache.json` exists in `%APPDATA%\RevitExtractor`; check with `Test-Path "$env:APPDATA\RevitExtractor\catalog-cache.json"`, which prints `True`).
- [Works] **B6** Only if you built `Newer\` and `Older\`: the newer model is greyed, cannot be ticked, and has a tooltip (note whether it shows a year or "could not be read"). The older model can be ticked and shows the upgrade note.
- [No, it doesn not] **B7** Note whether the model list scan caused any dialog, or Revit refusing the read (`BasicFileInfo.Extract` runs from the window's timer).

## Part C: exports with the sample models (25 minutes)

**The model window stays open after Export** so you can queue more (it is modal, on purpose: the background reads need the command's Revit API context). While it is open the status window still shows progress, but WPF does not pass clicks to it. Click **Close** on the model window before you use Cancel export, Clear finished, Open output folder, Open in Analyzer or the row menu, or before you open a model in Revit.

- [Works] **C1** Tick sample A, default scope, Export. The model window stays open (a short line says how many exports were queued, and the ticks are cleared) and the status window shows the row, the time running and the finished steps.
- [Works] **C2** Result is Done. Open output folder opens `…\export-<date>-<id>\output`. The run folder has `index.json`, `output\`, `logs\`, `journals\`, `console.log`.
- [Works, I got problem with npm ci so it returned the error with instruction how to do it manually. After resolving it opened local server] **C3** Open in Analyzer: the model shows in the browser (local Analyzer), or the folder and the website open (fallback). Say which. With the local Analyzer: a console window appeared, and closing it stops the server.
- [Works] **C4** Tick sample A, Choose views…: views are listed. Tick two 2D views and one 3D view, Export. Only those three are in the result.
- [Works] **C5** In the view window, Save index.json… writes a file. Back returns to the model list with its ticks.
- [Works] **C6** Tick three models (include the one in the folder with Polish letters, `&` and `%`), Export. They run one after another. **While they run** (click Close on the model window first):
  - open a model in Revit: the Export button is greyed, the status window still updates;
  - click X on the status window: it minimises and can be restored from the taskbar;
  - click the old "Export setup" button and close it: the status window still updates.
- [works] **C7** Still during C6: close the model, run pyRevit **Reload**, then click Export. The **same** status window with the same rows is shown, not a second one. Add one more export: it waits behind the others.
- [works] **C8** Cancel export on a waiting row: it never starts and no folder is created for it.
- [works] **C9** Cancel export on the running row. Then run the check: no `RevitExtractor` process is left, and the cancelled run is listed as INCOMPLETE, or as NOT STARTED when it was cancelled before the Extractor created its folders (its run folder still exists).

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Set-Location $repo
$kit = Join-Path $repo 'pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\v1_test_kit.ps1'
if (-not (Test-Path $kit)) { throw 'Wrong $repo: v1_test_kit.ps1 not found. Set $repo to the folder that holds pyRevit and specs.' }
$ini = Join-Path $env:APPDATA 'pyRevit\pyRevit_config.ini'   # the output folder the Export window uses
$out = $null; $inSec = $false
if (Test-Path $ini) { foreach ($l in Get-Content $ini) { if ($l -match '^\[') { $inSec = ($l.Trim() -eq '[RevitExtractorExport]') } elseif ($inSec -and $l -match '^output_parent\s*=\s*(.+)$') { $out = $Matches[1].Trim().Trim('"') } } }
if (-not $out) { $out = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'RevitExtractor' }
"Output folder: $out"   # must be the folder you chose in the Export window
$res = 'C:\RX-test\results'; New-Item -ItemType Directory -Force $res | Out-Null
& $kit -Check $out *>&1 | Tee-Object (Join-Path $res 'C9.txt')
```
> Result (owner): works. `-Check` showed 0 leftover RevitExtractor processes and 1 run, NOT STARTED: only `index.json` existed (output=0 logs=0 journals=0 console=0), because the export was cancelled before the Extractor created its folders. `Revit.exe` count 2 = Revit was open.

Owner's `-Check` output (C9):

```text
  == Machine / Komputer
  Print Spooler: StartType=Automatic, Status=Running
  RevitExtractor processes left / procesy RevitExtractor: 0
  Revit.exe processes / procesy Revit.exe: 1
  Revit 2022: Extractor 2025.3.0.12

  == Runs / Eksporty: 1
  run 1: NOT STARTED
    exit code: (none); (none)
    output: 0 files, 0 MB; bubble.json no; Resource no
    folders (1 = present): index=1 output=0 logs=0 journals=0 console=0
    console.log: 0 ERROR line(s), 0 WARN line(s); stderr.log -1 bytes (-1 = missing); about 0 s
```
- [works] **C10** Batch with a shared index: choose the file saved in C5 with two models ticked. If you ticked views in C5 it must be refused with a clear message; with one model ticked it must run.
> Result (owner): works. Message shown: "This index.json selects views, and view ids belong to one model. Select one model or use an index.json without views."
- [no unusal behavior, I checked on detached by default model (e-trasmitted), and the central model and I opened local copy while exporting] **C11** While an export runs, open **the model that is being exported** in Revit. Note anything unusual.
- [Detail below] **C12** Start two exports, then **close Revit** while the first runs. Revit exits fully (no `Revit.exe` left in Task Manager). The Extractor processes of the export that was running keep going on their own until it ends (by design); `RevitAccelerator.exe` belongs to Revit and may stay a while. A new Revit session shows "Waiting: another Extractor is running" until they end. Wait a minute or two (the first export finishes on its own), then run the check: the first run is OK, and the second is NOT STARTED.

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Set-Location $repo
$kit = Join-Path $repo 'pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\v1_test_kit.ps1'
if (-not (Test-Path $kit)) { throw 'Wrong $repo: v1_test_kit.ps1 not found. Set $repo to the folder that holds pyRevit and specs.' }
$ini = Join-Path $env:APPDATA 'pyRevit\pyRevit_config.ini'   # the output folder the Export window uses
$out = $null; $inSec = $false
if (Test-Path $ini) { foreach ($l in Get-Content $ini) { if ($l -match '^\[') { $inSec = ($l.Trim() -eq '[RevitExtractorExport]') } elseif ($inSec -and $l -match '^output_parent\s*=\s*(.+)$') { $out = $Matches[1].Trim().Trim('"') } } }
if (-not $out) { $out = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'RevitExtractor' }
"Output folder: $out"   # must be the folder you chose in the Export window
$res = 'C:\RX-test\results'; New-Item -ItemType Directory -Force $res | Out-Null
Get-Process Revit -ErrorAction SilentlyContinue   # prints nothing when Revit has exited
& $kit -Check $out *>&1 | Tee-Object (Join-Path $res 'C12.txt')
```
> Result (owner, partial): Revit exited fully. Afterwards these stayed running: RevitAccelerator.exe, RevitExtractor.exe, RevitExtractor Client.exe, RevitWorker.exe (x2). A new Revit session then said another Extractor was still running. Still needed: did they end by themselves and after how long, and the `-Check` result after they ended (first run OK, second NOT STARTED).

Owner's `-Check` output (C12, taken while 2 RevitExtractor processes were still running):

```text
== Machine / Komputer
Print Spooler: StartType=Automatic, Status=Running
RevitExtractor processes left / procesy RevitExtractor: 2
Revit.exe processes / procesy Revit.exe: 0
Revit 2022: Extractor 2025.3.0.12

== Runs / Eksporty: 1
run 1: NOT STARTED
  exit code: (none); (none)
  output: 0 files, 0 MB; bubble.json no; Resource no
  folders (1 = present): index=1 output=0 logs=0 journals=0 console=0
  console.log: 0 ERROR line(s), 0 WARN line(s); stderr.log -1 bytes (-1 = missing); about 0 s
```
- [ ] **C13** **No exports in this item.** Make sure no `RevitExtractor.exe`, `RevitExtractor Client.exe` or `RevitWorker.exe` is still running (ignore `RevitAccelerator.exe`), then run the check once more. It only reads the runs you already made. The Print Spooler start type must equal the value of S1. Send the whole output; it also holds the `Success Jobs` lines.

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Set-Location $repo
$kit = Join-Path $repo 'pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\v1_test_kit.ps1'
if (-not (Test-Path $kit)) { throw 'Wrong $repo: v1_test_kit.ps1 not found. Set $repo to the folder that holds pyRevit and specs.' }
$ini = Join-Path $env:APPDATA 'pyRevit\pyRevit_config.ini'   # the output folder the Export window uses
$out = $null; $inSec = $false
if (Test-Path $ini) { foreach ($l in Get-Content $ini) { if ($l -match '^\[') { $inSec = ($l.Trim() -eq '[RevitExtractorExport]') } elseif ($inSec -and $l -match '^output_parent\s*=\s*(.+)$') { $out = $Matches[1].Trim().Trim('"') } } }
if (-not $out) { $out = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'RevitExtractor' }
"Output folder: $out"   # must be the folder you chose in the Export window
$res = 'C:\RX-test\results'; New-Item -ItemType Directory -Force $res | Out-Null
& $kit -Check $out *>&1 | Tee-Object (Join-Path $res 'C13.txt')
```

Owner's `-Check` output (C13):
== Machine / Komputer
Print Spooler: StartType=Automatic, Status=Running
RevitExtractor processes left / procesy RevitExtractor: 0
Revit.exe processes / procesy Revit.exe: 0
Revit 2022: Extractor 2025.3.0.12

== Runs / Eksporty: 1
run 1: NOT STARTED
  exit code: (none); (none)
  output: 0 files, 0 MB; bubble.json no; Resource no
  folders (1 = present): index=1 output=0 logs=0 journals=0 console=0
  console.log: 0 ERROR line(s), 0 WARN line(s); stderr.log -1 bytes (-1 = missing); about 0 s

```text
== Machine / Komputer
Print Spooler: StartType=Automatic, Status=Running
RevitExtractor processes left / procesy RevitExtractor: 0
Revit.exe processes / procesy Revit.exe: 1
Revit 2022: Extractor 2025.3.0.12

== Runs / Eksporty: 1
run 1: NOT STARTED
  exit code: (none); (none)
  output: 0 files, 0 MB; bubble.json no; Resource no
  folders (1 = present): index=1 output=0 logs=0 journals=0 console=0
  console.log: 0 ERROR line(s), 0 WARN line(s); stderr.log -1 bytes (-1 = missing); about 0 s
```

- [WORKS, it installed packages and returned true] **C14** The Node.js notice. Four steps; paste each block in full.
  1. Hide the Analyzer packages (Revit can stay open), then click **Open in Analyzer** on a finished row. The notice appears with the reason, the output folder and the website open, and the error line shows. Tick "Don't show this again" and OK. Click again: no notice, same fallback. Check that the text reads well in English, and in Polish after E1.

```powershell
$repo = $env:RX_REPO
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Rename-Item (Join-Path $repo 'Analyzer\node_modules') 'node_modules.off'
```
  2. To see the notice again, switch the flag off (the file holds only this preference):

```powershell
Remove-Item "$env:APPDATA\RevitExtractor\preferences.json" -ErrorAction SilentlyContinue
```
  3. Run the first-run installer with the packages missing. It installs them (also behind a company proxy, with no extra setup) and starts the server; close its window to stop it:

```powershell
$repo = $env:RX_REPO
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Remove-Item -Recurse -Force (Join-Path $repo 'Analyzer\node_modules.off') -ErrorAction SilentlyContinue
& (Join-Path $repo 'Analyzer\Start-Analyzer.cmd')
```
  4. Check the packages are back, then click Open in Analyzer: the local Analyzer opens and no notice appears.

```powershell
$repo = $env:RX_REPO
Test-Path (Join-Path $repo 'Analyzer\node_modules\pdfjs-dist\build\pdf.mjs')   # must print True
```
- [WORKS] **C15** The row context menu. With two or more rows (one queued or not yet started, one running or finished), right-click a row that is not highlighted: it becomes highlighted, then the menu shows "Show model in File Explorer" and "Show export folder in File Explorer" (Polish after E1). Right-click empty space below the rows: no menu. "Show model" opens Explorer with the model file selected, also for a model whose folder path has Polish letters, spaces, `&` or `%`; rename the model file for a moment: the item opens its folder instead; rename the folder too: the error line says the file and folder were not found. "Show export folder" opens the same folder as Open output folder (the output folder for a finished row, the run folder otherwise, Polish folder path included); on a queued row, or one cancelled before it started, the item is greyed out. Restore any names you changed.

  To test the missing file and folder, pick a model that has a row in the status window. These blocks take the smaller sample; edit `$model` if your row is another model. Do the steps in this order, and run the restore block at the end.

```powershell
$model = (Get-ChildItem 'C:\RX-test\Samples' -Filter *.rvt | Where-Object { $_.Name -notmatch '\.\d{4}\.rvt$' } | Sort-Object Length | Select-Object -First 1).FullName
$model                                                  # check this is the model of your row
Rename-Item $model ((Split-Path $model -Leaf) + '.off')  # file missing: "Show model" must open its folder
```

```powershell
Rename-Item (Split-Path $model -Parent) 'Samples.off'    # folder missing too: the error line must say file and folder were not found
```

```powershell
# restore everything (run it in the same window; otherwise set $model as above first)
if (Test-Path 'C:\RX-test\Samples.off') { Rename-Item 'C:\RX-test\Samples.off' 'Samples' }
Get-ChildItem 'C:\RX-test\Samples' -Filter *.off | ForEach-Object { Rename-Item $_.FullName ($_.Name -replace '\.off$','') }
Get-ChildItem 'C:\RX-test\Samples' | Select-Object Name   # the sample names are back to .rvt
```

- [WORKS] **C16** Clear finished. With a finished, a failed or cancelled, a running and a waiting row: the button is enabled and Clear finished removes only the finished, failed and cancelled rows; the running and waiting rows stay in order and keep updating. With only running or waiting rows the button is greyed out. The output folders of the removed exports are still on disk, and nothing was cancelled. The status window still updates after clearing, and a newly started export appears as a new row (Polish button text after E1).

- [ ] **C17** Queue more from the still-open window. Tick sample A, Export, and do not close the model window. While the export runs, tick sample B (or sample A again: queuing a model twice is allowed) and Export again. The second row appears behind the first in the status window (it only updates, WPF takes no clicks there while the model window is open), and it starts when the first ends. After each Export the ticks are cleared and the window says how many exports were queued; the folder list, the output folder and the search stay as they were. Choose views… on one model and Export from the view window: the view window closes, the model window is still open, and the third row appears. Then click Close: nothing more is queued, and the status window takes clicks again (Cancel export, Clear finished). If you can provoke a failed hand-over (for example pyRevit **Reload** between two Exports), the red error line shows the reason and the ticks are kept, so a second click on Export retries. Note anything unusual.

## Part D: real models (20 minutes; results are private)

Start Revit again with no model open. For D3 and D5, run this before and after, with the real path of that model (the output holds a size and a time, no path; send it):

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Set-Location $repo
$kit = Join-Path $repo 'pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\v1_test_kit.ps1'
if (-not (Test-Path $kit)) { throw 'Wrong $repo: v1_test_kit.ps1 not found. Set $repo to the folder that holds pyRevit and specs.' }
& $kit -Stamp '\\server\share\Project\Central.rvt'    # <- the model's path
```

- [works] **D1** Add a real root on a share. Note the file count and the time until the list is complete (cold). Rescan and note the time again (warm). The window stays responsive.
- [works] **D2** No backup files, no `Backup` folders, and no local copies of centrals are listed.
- [works] **D3** A workshared central on the share, Choose views…: note the open time and any dialog. Views are listed. Afterwards: `-Stamp` unchanged, no new local copy in your Documents, no document open in Revit, and the Export button still enabled.
- [works] **D4** The 1000+ sheet model, Choose views…: note the open time. Ticking, Select all shown and search are as fast as in the slice 1 test.
- [works] **D5** Export that central with the default scope, straight from the share. Result OK; `-Stamp` unchanged afterwards.
- [ ] **D6** An older-version model, Choose views…: note the time. The file is unchanged. Export it: note the result.
- [The model file was not found.] **D7** List a model, rename its file in Explorer, then Choose views…: a readable message in the window's language, and nothing is queued. Rename it back.
> NOTE on this please add reload folders button so it updates the list
- [it is readable] **D8** Open `console.log` of the C6 run from the folder with Polish letters: is the model path readable there? Open it in Notepad with this (it picks the newest run folder; use the run of that model if you have run others since):

```powershell
$ini = Join-Path $env:APPDATA 'pyRevit\pyRevit_config.ini'   # the output folder the Export window uses
$out = $null; $inSec = $false
if (Test-Path $ini) { foreach ($l in Get-Content $ini) { if ($l -match '^\[') { $inSec = ($l.Trim() -eq '[RevitExtractorExport]') } elseif ($inSec -and $l -match '^output_parent\s*=\s*(.+)$') { $out = $Matches[1].Trim().Trim('"') } } }
if (-not $out) { $out = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'RevitExtractor' }
"Output folder: $out"   # must be the folder you chose in the Export window
$run = Get-ChildItem $out -Directory | Sort-Object LastWriteTime | Select-Object -Last 1
notepad (Join-Path $run.FullName 'console.log')
```

## Part E: Polish (3 minutes)

- [works] **E1** Set pyRevit's language to Polish and reload. The button title, the model window, the view window and the status window are in Polish, with no English label left. Screenshots of the three windows with a sample model are welcome.

## Part F: the Revit 2025 machine (10 minutes)
>NOTE I cannot run Exportbutton because Export.pushbutton\script.py", line 16, in <module>
ImportError: Cannot import name FileVersionInfo

- [Details below] **F1** `validate_native_legacy.ps1`: send the output. It needs Python 3 (`python --version`) and finds the Revit 2022-2025 Extractor by itself; if it finds none or the wrong one, add `-ExtractorDirectory 'C:\Program Files\Autodesk\Revit 2025\RevitExtractor'`.

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Set-Location $repo
$tests = Join-Path $repo 'pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests'
$res = 'C:\RX-test\results'; New-Item -ItemType Directory -Force $res | Out-Null
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tests 'validate_native_legacy.ps1') *>&1 | Tee-Object (Join-Path $res 'F1.txt')
```

>OUTPUT
Parser: C:\Program Files\Autodesk\Revit 2022\RevitExtractor\ExtractorUtility.dll; file version 2025.3.0.12; shape Parse (2025.3+)
PASS bundle == lib: defaults
PASS native parser: defaults
PASS bundle == lib: selected-2d
PASS native parser: selected-2d
PASS bundle == lib: selected-3d
PASS native parser: selected-3d
PASS bundle == lib: separate-selections
PASS native parser: separate-selections
PASS bundle == lib: no-database
PASS native parser: no-database
PASS bundle == lib: database-only
PASS native parser: database-only
PASS bundle == lib: advanced
PASS native parser: advanced
PASS bundle == lib: int32-limit
PASS native parser: int32-limit
PASS bundle == lib: 2d-only-no-database
PASS native parser: 2d-only-no-database
PASS bundle == lib: newest-all-options
PASS native parser: newest-all-options property Has2DViewing
PASS native parser: newest-all-options property Has3DViewing
PASS native parser: newest-all-options property GenerateTopologyMetadata
powershell.exe : newest-all-options property GenerateExtendedPropertyDB: expected True, got False
At line:1 char:1
+ powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $t ...
+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (newest-all-opti...True, got False:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError

At C:\Users\m.golabek\OneDrive - Cundall\_Working Locally\0000000 - BIM\01_Revit\01_Scripts\00_RevitExtractor\RevitExtr
actor\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\validate_native_legacy.ps1:234 char:17
+                 throw "${label}: expected $expected, got $actual"
+                 ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : OperationStopped: (newest-all-opti...True, got False:String) [], RuntimeException
    + FullyQualifiedErrorId : newest-all-options property GenerateExtendedPropertyDB: expected True, got False

- [works] **F2** Export is enabled with no model open. One export with the default scope: result OK.
- [untested] **F3** One model, Choose views…, tick two 2D views and one 3D view, Export: only those are in the result (the `ElementId.Value` path).

Nobody can test the 2026 row: its IFC and DWG options stay marked untested.

## Part G: scripts, Revit closed (10 minutes)

- [Detail below] **G1** `validate_native_legacy.ps1`: all lines PASS (2025.3 parser shape). Send the output. Needs Python 3 (`python --version`).

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Set-Location $repo
$tests = Join-Path $repo 'pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests'
$res = 'C:\RX-test\results'; New-Item -ItemType Directory -Force $res | Out-Null
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tests 'validate_native_legacy.ps1') *>&1 | Tee-Object (Join-Path $res 'G1.txt')
```

>OUTPUT:
Parser: C:\Program Files\Autodesk\Revit 2022\RevitExtractor\ExtractorUtility.dll; file version 2025.3.0.12; shape Parse (2025.3+)
PASS bundle == lib: defaults
PASS native parser: defaults
PASS bundle == lib: selected-2d
PASS native parser: selected-2d
PASS bundle == lib: selected-3d
PASS native parser: selected-3d
PASS bundle == lib: separate-selections
PASS native parser: separate-selections
PASS bundle == lib: no-database
PASS native parser: no-database
PASS bundle == lib: database-only
PASS native parser: database-only
PASS bundle == lib: advanced
PASS native parser: advanced
PASS bundle == lib: int32-limit
PASS native parser: int32-limit
PASS bundle == lib: 2d-only-no-database
PASS native parser: 2d-only-no-database
PASS bundle == lib: newest-all-options
PASS native parser: newest-all-options property Has2DViewing
PASS native parser: newest-all-options property Has3DViewing
PASS native parser: newest-all-options property GenerateTopologyMetadata
powershell.exe : newest-all-options property GenerateExtendedPropertyDB: expected True, got False
At line:1 char:1
+ powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $t ...
+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (newest-all-opti...True, got False:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError

At C:\Users\m.golabek\OneDrive - Cundall\_Working Locally\0000000 - BIM\01_Revit\01_Scripts\00_RevitExtractor\RevitExtr
actor\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\validate_native_legacy.ps1:234 char:17
+                 throw "${label}: expected $expected, got $actual"
+                 ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : OperationStopped: (newest-all-opti...True, got False:String) [], RuntimeException
    + FullyQualifiedErrorId : newest-all-options property GenerateExtendedPropertyDB: expected True, got False


- [Detail below] **G2** The parallel run with the two sample models from `C:\RX-test\Samples`. A FAIL is expected (fixed pipe); we need to know for this build. Send the output. It names your Windows user folder: private.

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Set-Location $repo
$tests = Join-Path $repo 'pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests'
$res = 'C:\RX-test\results'; New-Item -ItemType Directory -Force $res | Out-Null
# the two samples (not the .0001.rvt backup), smallest first
$samples = Get-ChildItem 'C:\RX-test\Samples' -Filter *.rvt | Where-Object { $_.Name -notmatch '\.\d{4}\.rvt$' } | Sort-Object Length
$samples | Select-Object Name, Length   # must list exactly two files
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tests 'run_extractor_integration.ps1') -Parallel 2 -ModelPath $samples[0].FullName -ModelPath2 $samples[1].FullName *>&1 | Tee-Object (Join-Path $res 'G2.txt')
```

>OUTPUT:
PS C:\Users\m.golabek\OneDrive - Cundall\_Working Locally\0000000 - BIM\01_Revit\01_Scripts\00_RevitExtractor\RevitExtractor> $samples | Select-Object Name, Length   # must list exactly two files

Name                                      Length
----                                      ------
Roombook Schedule Views INT-ENU.rvt       405504
Flaechenbuch Bauteillisten DIN-DEU.rvt    405504
SampleA_Central.rvt                    164622336
SampleA.rvt                            164622336
SampleB.rvt                            272592896


PS C:\Users\m.golabek\OneDrive - Cundall\_Working Locally\0000000 - BIM\01_Revit\01_Scripts\00_RevitExtractor\RevitExtractor> powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tests 'run_extractor_integration.ps1') -Parallel 2 -ModelPath $samples[0].FullName -ModelPath2 $samples[1].FullName *>&1 | Tee-Object (Join-Path $res 'G2.txt')

== export-runner integration (parallel 2)
Revit:            2025 - C:\Program Files\Autodesk\Revit 2025
Extractor:        C:\Program Files\Autodesk\Revit 2025\RevitExtractor\RevitExtractor.exe
powershell.exe : C:\Users\m.golabek\OneDrive - Cundall\_Working Locally\0000000 -
BIM\01_Revit\01_Scripts\00_RevitExtractor\RevitExtract
At line:1 char:1
+ powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $t ...
+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (C:\Users\m.gola...or\RevitExtract:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError

or\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\run_extractor_integration.ps1 : The property
'VersionInfo' cannot be found on this object. Verify that the property exists.
    + CategoryInfo          : NotSpecified: (:) [run_extractor_integration.ps1], PropertyNotFoundException
    + FullyQualifiedErrorId : PropertyNotFoundStrict,run_extractor_integration.ps1

Both scripts are in `pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\`.

## Part H: Cloud (ACC) models (30 minutes; results are private)

The Cloud source of the Export window lists cloud models from the Revit journals and the `CollaborationCache`, and exports them from copies. **Not run in Revit by the agent: every item below is unverified.** It needs your real ACC model (yours has 28 links), so this part is the exception to the synthetic-data rule, like D4: send **counts and choices only**, never a model, project or file name, a path or a GUID. The commands below print numbers only. Start Revit with no model open, `pyRevit` reloaded.

The paths used by the code are fixed: `%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit <year>\Journals` and `...\CollaborationCache`. Replace `2022` below with the Revit year in use.

- [ ] **H1** Journals and names. Run `& $kit -Check` (after the `$kit` lines of the other blocks); the section "Cloud models" prints: journals folder found (1/0), journal count, named cloud models, cached models, unnamed cached models, cache folder present. Then click **Export**, choose **Cloud (ACC)**, tick your project: real project and file names appear, **Polish letters and `%20` names read correctly**, and **no GUID is ever shown as a name**. Also run this block; it prints only the key names of the model-browser journal lines, to see whether a folder field exists (open question: folder selection):

```powershell
$y = 2022   # your Revit year
$j = Join-Path $env:LOCALAPPDATA "Autodesk\Revit\Autodesk Revit $y\Journals"
$keys = Get-ChildItem $j -Filter 'journal*.txt' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 20 |
  ForEach-Object { Select-String -LiteralPath $_.FullName -Pattern 'ModelBrowserOpenDocumentEvent:open:' } |
  ForEach-Object { [regex]::Matches($_.Line, '"+([A-Za-z]+)"+\s*:') | ForEach-Object { $_.Groups[1].Value } } | Sort-Object -Unique
"Key names: " + ($keys -join ', ')
```

- [ ] **H2** The current-session journal is readable. Open the ACC model (this Revit session), close it without saving, then **Export** > **Cloud (ACC)**: the model is listed, and `-Check` prints `unreadable 0` for the journals.
- [ ] **H3** Background open of the cache copy. Save a size/time list of the cache files (numbers, no names), tick the host model in the Cloud list, click **Choose views...** (a read with all worksets closed; the export that follows opens all worksets), then list again and compare:

```powershell
$y = 2022   # your Revit year
$cache = Join-Path $env:LOCALAPPDATA "Autodesk\Revit\Autodesk Revit $y\CollaborationCache"
$res = 'C:\RX-test\results'; New-Item -ItemType Directory -Force $res | Out-Null
$name = 'H3-before'   # run again with 'H3-after' after Choose views...
$i = 0; Get-ChildItem $cache -Recurse -File -Filter *.rvt -ErrorAction SilentlyContinue | Sort-Object FullName | ForEach-Object { $i++; '{0}: {1} bytes; {2}' -f $i, $_.Length, $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') } | Tee-Object (Join-Path $res "$name.txt")
# after both lists exist:
$d = @(Compare-Object (Get-Content (Join-Path $res 'H3-before.txt')) (Get-Content (Join-Path $res 'H3-after.txt'))); "Lines that differ: " + $d.Count
```

  Pass: the view window opens with no sign-in or cloud dialog, **the link count is 28** (the number your model has), no document stays open, Export is still enabled, and **`Lines that differ: 0`** (for a single file, `& $kit -Stamp <file>` prints size and time). Note the seconds it took.
- [ ] **H4** Staged export. Tick the host in the Cloud list and click **Export**. The status row shows "Copying from the cache", then runs. Pass: the run ends OK, `& $kit -Check <run folder>` shows `Success Jobs: N, Failed Jobs: 0`, and in the Analyzer a federated 3D view shows the host **and its links**. Note how many "Link ... is not in the cache" notes appear (count only).
- [ ] **H5** Copy time and Revit while it copies. Queue the model again. While the row says "Copying from the cache", pan a view and open a ribbon tab. Note the seconds of the copy phase, the size shown (MB) and whether Revit stayed usable (fully / short pauses / froze).
- [ ] **H6** Remember cloud model button. With a sample copy open: the button says it is not a cloud model and writes nothing. With the cloud model open: it confirms and gives a link count (counts only). No change to the model (no Undo entry, nothing to save or synchronise). Afterwards the model is listed under **Cloud (ACC)**, also if no journal names it.
- [ ] **H7** Disk use and clean-up. After H4 and when no RevitExtractor process runs, the run's `model` folder holds only `stage.json` (the copies are deleted). Block (counts only):

```powershell
$ini = Join-Path $env:APPDATA 'pyRevit\pyRevit_config.ini'
$out = $null; $inSec = $false
if (Test-Path $ini) { foreach ($l in Get-Content $ini) { if ($l -match '^\[') { $inSec = ($l.Trim() -eq '[RevitExtractorExport]') } elseif ($inSec -and $l -match '^output_parent\s*=\s*(.+)$') { $out = $Matches[1].Trim().Trim('"') } } }
if (-not $out) { $out = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'RevitExtractor' }
$run = Get-ChildItem $out -Directory | Sort-Object LastWriteTime | Select-Object -Last 1
$m = Join-Path $run.FullName 'model'
"Items in the model folder: " + @(Get-ChildItem $m -Force -ErrorAction SilentlyContinue).Count
"stage.json present: " + (Test-Path (Join-Path $m 'stage.json'))
"RevitExtractor processes: " + @(Get-Process -Name 'RevitExtractor*' -ErrorAction SilentlyContinue).Count
"Free space on the output drive (GB): " + [math]::Round((Get-PSDrive -Name ([IO.Path]::GetPathRoot($out).Substring(0, 1))).Free / 1GB, 1)
```

Expected: `Items in the model folder: 1`, `stage.json present: True`, `RevitExtractor processes: 0`.

- [ ] **H8** A cloud open that fails. If the export or Choose views says "could not be opened", or Revit shows its own dialog while a model opens (for example "The host model failed to open"), close Revit's dialog first; the export then goes on from the cache. The open first tries the model's root cache file (never a `LinkedModels` or `CentralCache` copy), then the cloud path. Every failed open writes a local log to `%APPDATA%\RevitExtractor\logs\cloud-open-<yyyymmdd>.log` (about 200 KB at most per file, the last 10 days; GUIDs are masked, but Revit's own error texts can name the model, so the file stays on your computer). Send the entry of that run **privately**, not through git, and note which Revit dialog text you saw. A copy that fails before the Extractor starts leaves only `model\stage.json` in the run folder (its `error` field gives the exception type, `cache_changed` a count); there are no logs then.

Open questions this part answers (also in `HANDOVER.md`): do journals after Revit 2022 keep the same lines (H1); folders cannot be chosen, only projects, because the journals carry no folder (H1 key names); does a background open of a cache file work without touching the cloud or the file (H3); can the journal or cache folder be moved (the kit only reports whether the fixed paths exist).

## Part I: file names, "named copies" (25 minutes)

With a file-name template set, a successful export gets a `named` folder in its run folder: hard links of every PDF, DWG, IFC and 3D view folder under the template's names; `output` stays as the Extractor wrote it. **Unit-tested and run once on the Dynamo sample with Revit 2023's Extractor (counts); never run in Revit: every item below is unverified there.** Counts and choices only: never send a file, sheet, model or parameter name or a path. The kit prints counts only: `& $kit -Named <run folder>` (state, counts, files and folders under `named`, hard links, longest path, files under `output`). The blocks use the `$kit`, `$out` and `$res` lines of the other parts.

```powershell
$run = Get-ChildItem $out -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'named.json') } | Sort-Object LastWriteTime | Select-Object -Last 1
& $kit -Named $run.FullName *>&1 | Tee-Object (Join-Path $res 'I2.txt')
```

- [ ] **I0** Probe a real export. In the `Analyzer` folder: `node scripts/probe-export-structure.mjs "<output folder>"` (counts only; add `--show-names` only if you agree to send the other attribute names). Record: do the sheet number and name attributes show under `builtIn` (yes/no); the language of those names (English/Polish/other); `viewableIdEqualsExternalId` and `viewables`. Not English: set INCONCLUSIVE and run again with `--show-names`.
- [ ] **I1** The File names row. In the model window: **Presets** fill the field, **Insert** adds a token, **Clear** empties it, the example line follows the field. `{SheetNumber` (no closing brace) shows an error and Export is refused with the ticks kept. After closing and restarting Revit the template and the checkbox are remembered. Polish texts too, if you switch pyRevit to Polish.
- [ ] **I2** Default-scope export with `{SheetNumber} - {SheetName}`. The row says "Naming files: x of y"; `named` appears; run the block above (state `done`, `failed 0`, every checked file has a second hard link, longest path 259 or less). **Open in Analyzer** opens `output` as before. Look at three names by eye: pass or fail only.
- [ ] **I3** Custom parameter: `{SheetNumber} - {param:<one of your sheet parameters>}` (type the real name only in your own session). Three files hold the values: pass or fail.
- [ ] **I4** Clash numbering: template `{Year}` only. The number of files under `named` equals the number of PDFs; names carry " (2)", " (3)" ...
- [ ] **I5** A 200-character template on a deep output folder (about 120 characters): names are cut; the longest path printed is 259 or less.
- [ ] **I6** A 3D view in scope: `named` holds a folder with the whole view subtree; the file count equals that of the view folder under `output\Resource\3D View` (counts only).
- [ ] **I7** A Cloud (ACC) job with a template: named copies appear after the staged copies are cleaned up; `& $kit -Stamp <host cache file>` before and after is equal; no RevitExtractor process left (`-Check`). Needs your ACC model: counts only, like Part H.
- [ ] **I8** The checkbox "A separate folder for each format" on: `named` has one folder per exported format (PDF, DWG, IFC, 3D).
- [ ] **I9** (optional) Close Revit while the row says "Naming files": `named.json` stays `running`; after restarting Revit the next Export works.

If names are not recognised (Revit's language is not English), files keep their original name and a note says so: record the language, set INCONCLUSIVE and run I0 with `--show-names`.

## Part J: cloud staging experiment, no links staged (20 minutes; results are private)

Question: can the Extractor open the cache host **without** a staging folder of real-name links? **Not run in Revit by the agent: unverified.** Needs your ACC model (use a small one), so it follows the Part H rule: counts and choices only, never a name, path or GUID. Run H8 first (the default mode, `links`, is your reference run). The mode is the preference `cloud_staging` in `%APPDATA%\RevitExtractor\preferences.json`, read at each job (no Revit restart): `"links"` (default: host and links as real-name hard links), `"host-only"` (only the host is staged as one hard link, no links), `"direct"` (the Extractor gets the host's cache path itself, nothing is staged). Anything else means `links`. Only the host's own cache file is opened; in these two modes the export may miss the linked models: that is what you are observing. The tool adds no workaround.

- [ ] **J1** Three runs of the same small ACC model, same views, one at a time (wait for each to finish): first the default (`links`), then `host-only`, then `direct`. Set the mode with this block (edit the value; `$null` removes the setting):

```powershell
$mode = 'host-only'   # 'host-only', 'direct', or $null for the default
$p = Join-Path $env:APPDATA 'RevitExtractor\preferences.json'
New-Item -ItemType Directory -Force (Split-Path $p) | Out-Null
$d = [ordered]@{}
if (Test-Path -LiteralPath $p) { try { $o = Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json; foreach ($n in $o.PSObject.Properties) { $d[$n.Name] = $n.Value } } catch {} }
if ($mode) { $d['cloud_staging'] = $mode } else { $d.Remove('cloud_staging') }
[IO.File]::WriteAllText($p, ($d | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
'cloud_staging = ' + $(if ($d.Contains('cloud_staging')) { $d['cloud_staging'] } else { '(not set: links)' })
```

  After each run, print counts of the newest run (no names; edit nothing):

```powershell
$ini = Join-Path $env:APPDATA 'pyRevit\pyRevit_config.ini'
$out = $null; $inSec = $false
if (Test-Path $ini) { foreach ($l in Get-Content $ini) { if ($l -match '^\[') { $inSec = ($l.Trim() -eq '[RevitExtractorExport]') } elseif ($inSec -and $l -match '^output_parent\s*=\s*(.+)$') { $out = $Matches[1].Trim().Trim('"') } } }
if (-not $out) { $out = Join-Path $env:USERPROFILE 'RevitExtractor' }
$run = Get-ChildItem $out -Directory | Sort-Object LastWriteTime | Select-Object -Last 1
$s = Get-Content -LiteralPath (Join-Path $run.FullName 'model\stage.json') -Raw -Encoding UTF8 | ConvertFrom-Json
'mode: ' + $s.mode + '; cache files changed: ' + $s.cache_changed + '; staged items: ' + @($s.items).Count
'Files under output: ' + @(Get-ChildItem (Join-Path $run.FullName 'output') -Recurse -File).Count
'Items in the model folder: ' + @(Get-ChildItem (Join-Path $run.FullName 'model') -Force).Count
```

  Also run `& $kit -Stamp <host cache file>` before the first and after the last run (size and time must be equal). Then, per run, open the result in the Analyzer: does the 3D view show the linked models (yes/no), do the 2D sheets or views show linked content (yes/no), and how many files are under `output` (the count line). Pass = the three counts and answers are recorded; the interesting result is whether `host-only` or `direct` differ from the default. FAIL if a run reports `cache files changed` above 0 or a `-Stamp` differs: stop and do not repeat on this model. When done, set `$mode = $null` (back to the default).

## What to send back, privately

1. This list with PASS, FAIL or a note per item, and the times of D1, D3, D4 and D6.
2. The outputs: the files in `C:\RX-test\results` (`S1.txt`, `C9.txt`, `C12.txt`, `C13.txt`, `G1.txt`, `G2.txt`, and `F1.txt` from the Revit 2025 machine). Part I: `I2.txt` ... `I9.txt` hold counts only. Part J: the three count blocks of J1 (numbers only). Part H: `H1.txt`, `H3-before.txt`, `H3-after.txt` hold numbers only; send the counts, not the files. To list them: `Get-ChildItem C:\RX-test\results | Select-Object Name, Length, LastWriteTime`.
3. For any failure: the text of pyRevit's output window, and `console.log` and `stderr.log` of that run folder. These can name models and paths, so never commit them.

## What the agent does with the results

- Records them in the READMEs' Validation sections and in `HANDOVER.md`.
- Adds 2025 to `TESTED_YEARS` if Part F passed, and sets `PARALLEL_VERIFIED` only if G2 passed.
- Asks before deleting the old buttons (Q12).
