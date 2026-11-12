# v1 Revit test: the owner's one session

One session, about 90 minutes, on the Revit 2022 + pyRevit machine. Part F (10 minutes) is on the machine with Revit 2025. Answer with the item number and PASS, FAIL or a note, for example `C6 FAIL: second window appeared`. Results come back privately, never through git.

**Everything below is unverified inside Revit.** The unit tests and the real Extractor runs on the agent's machine never ran IronPython, pyRevit or Revit's API. This session is the first time the code runs there, so a first-click failure (Part A) is possible and cheap to find: Part A comes first and takes minutes.

## Before you start (10 minutes, Revit closed)

**Every command block below is complete.** Each one sets the variables it needs (`$repo`, `$kit`, `$out`, `$res`), so you can paste any block into a fresh PowerShell window. `$repo` comes from the variable `RX_REPO` (step 0 below, once per machine), so the blocks hold no personal paths. `$out` is read from the output folder that the Export window uses. `$res` is `C:\RX-test\results`, where the blocks that must be sent back save their output as a text file (with `Tee-Object`), so you can attach the file instead of copying from the window. These files hold no model names or paths, except G2, which names your Windows user folder: private. Never commit them. (`-Setup -Force` would delete `C:\RX-test`, results included, so copy the results out first.)

**Execution policy.** The blocks do not change it. If a script is refused with "not digitally signed" (a file marked as downloaded from the Internet), run `Get-ChildItem -Recurse "$repo\pyRevit" -Filter *.ps1 | Unblock-File` once. A machine policy such as RemoteSigned is fine: it runs local scripts, and `Set-ExecutionPolicy` would only fail against it.

0. Tell the blocks where your clone is, once per machine. Use the folder that contains `pyRevit` and `specs`, and put your real path in place of the example:

```powershell
[Environment]::SetEnvironmentVariable('RX_REPO', 'C:\path\to\your\RevitExtractor', 'User')   # edit this path
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

- [Works] **C1** Tick sample A, default scope, Export. Control returns at once and the status window shows the row, the time running and the finished steps.
- [Works] **C2** Result is Done. Open output folder opens `…\export-<date>-<id>\output`. The run folder has `index.json`, `output\`, `logs\`, `journals\`, `console.log`.
- [Works, I got problem with npm ci so it returned the error with instruction how to do it manually. After resolving it opened local server] **C3** Open in Analyzer: the model shows in the browser (local Analyzer), or the folder and the website open (fallback). Say which. With the local Analyzer: a console window appeared, and closing it stops the server.
- [Works] **C4** Tick sample A, Choose views…: views are listed. Tick two 2D views and one 3D view, Export. Only those three are in the result.
- [Works] **C5** In the view window, Save index.json… writes a file. Back returns to the model list with its ticks.
- [Works] **C6** Tick three models (include the one in the folder with Polish letters, `&` and `%`), Export. They run one after another. **While they run:**
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

- [ ] **C14** The Node.js notice. Four steps; paste each block in full.
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
- [ ] **C15** The row context menu. With two or more rows (one queued or not yet started, one running or finished), right-click a row that is not highlighted: it becomes highlighted, then the menu shows "Show model in File Explorer" and "Show export folder in File Explorer" (Polish after E1). Right-click empty space below the rows: no menu. "Show model" opens Explorer with the model file selected, also for a model whose folder path has Polish letters, spaces, `&` or `%`; rename the model file for a moment: the item opens its folder instead; rename the folder too: the error line says the file and folder were not found. "Show export folder" opens the same folder as Open output folder (the output folder for a finished row, the run folder otherwise, Polish folder path included); on a queued row, or one cancelled before it started, the item is greyed out. Restore any names you changed.

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

- [ ] **C16** Clear finished. With a finished, a failed or cancelled, a running and a waiting row: the button is enabled and Clear finished removes only the finished, failed and cancelled rows; the running and waiting rows stay in order and keep updating. With only running or waiting rows the button is greyed out. The output folders of the removed exports are still on disk, and nothing was cancelled. The status window still updates after clearing, and a newly started export appears as a new row (Polish button text after E1).

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

- [ ] **D1** Add a real root on a share. Note the file count and the time until the list is complete (cold). Rescan and note the time again (warm). The window stays responsive.
- [ ] **D2** No backup files, no `Backup` folders, and no local copies of centrals are listed.
- [ ] **D3** A workshared central on the share, Choose views…: note the open time and any dialog. Views are listed. Afterwards: `-Stamp` unchanged, no new local copy in your Documents, no document open in Revit, and the Export button still enabled.
- [ ] **D4** The 1000+ sheet model, Choose views…: note the open time. Ticking, Select all shown and search are as fast as in the slice 1 test.
- [ ] **D5** Export that central with the default scope, straight from the share. Result OK; `-Stamp` unchanged afterwards.
- [ ] **D6** An older-version model, Choose views…: note the time. The file is unchanged. Export it: note the result.
- [ ] **D7** List a model, rename its file in Explorer, then Choose views…: a readable message in the window's language, and nothing is queued. Rename it back.
- [ ] **D8** Open `console.log` of the C6 run from the folder with Polish letters: is the model path readable there? Open it in Notepad with this (it picks the newest run folder; use the run of that model if you have run others since):

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

- [ ] **E1** Set pyRevit's language to Polish and reload. The button title, the model window, the view window and the status window are in Polish, with no English label left. Screenshots of the three windows with a sample model are welcome.

## Part F: the Revit 2025 machine (10 minutes)

- [ ] **F1** `validate_native_legacy.ps1`: send the output. It needs Python 3 (`python --version`) and finds the Revit 2022-2025 Extractor by itself; if it finds none or the wrong one, add `-ExtractorDirectory 'C:\Program Files\Autodesk\Revit 2025\RevitExtractor'`.

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Set-Location $repo
$tests = Join-Path $repo 'pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests'
$res = 'C:\RX-test\results'; New-Item -ItemType Directory -Force $res | Out-Null
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tests 'validate_native_legacy.ps1') *>&1 | Tee-Object (Join-Path $res 'F1.txt')
```
- [ ] **F2** Export is enabled with no model open. One export with the default scope: result OK.
- [ ] **F3** One model, Choose views…, tick two 2D views and one 3D view, Export: only those are in the result (the `ElementId.Value` path).

Nobody can test the 2026 row: its IFC and DWG options stay marked untested.

## Part G: scripts, Revit closed (10 minutes)

- [ ] **G1** `validate_native_legacy.ps1`: all lines PASS (2025.3 parser shape). Send the output. Needs Python 3 (`python --version`).

```powershell
$repo = $env:RX_REPO   # set once, see "Before you start"
if (-not $repo -or -not (Test-Path $repo)) { throw 'Set RX_REPO first: see Before you start, step 0.' }
Set-Location $repo
$tests = Join-Path $repo 'pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests'
$res = 'C:\RX-test\results'; New-Item -ItemType Directory -Force $res | Out-Null
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tests 'validate_native_legacy.ps1') *>&1 | Tee-Object (Join-Path $res 'G1.txt')
```
- [ ] **G2** The parallel run with the two sample models from `C:\RX-test\Samples`. A FAIL is expected (fixed pipe); we need to know for this build. Send the output. It names your Windows user folder: private.

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

Both scripts are in `pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\`.

## What to send back, privately

1. This list with PASS, FAIL or a note per item, and the times of D1, D3, D4 and D6.
2. The outputs: the files in `C:\RX-test\results` (`S1.txt`, `C9.txt`, `C12.txt`, `C13.txt`, `G1.txt`, `G2.txt`, and `F1.txt` from the Revit 2025 machine). To list them: `Get-ChildItem C:\RX-test\results | Select-Object Name, Length, LastWriteTime`.
3. For any failure: the text of pyRevit's output window, and `console.log` and `stderr.log` of that run folder. These can name models and paths, so never commit them.

## What the agent does with the results

- Records them in the READMEs' Validation sections and in `HANDOVER.md`.
- Adds 2025 to `TESTED_YEARS` if Part F passed, and sets `PARALLEL_VERIFIED` only if G2 passed.
- Asks before deleting the old buttons (Q12).
