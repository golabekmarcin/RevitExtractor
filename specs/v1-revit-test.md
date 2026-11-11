# v1 Revit test: the owner's one session

One session, about 90 minutes, on the Revit 2022 + pyRevit machine. Part F (10 minutes) is on the machine with Revit 2025. Answer with the item number and PASS, FAIL or a note, for example `C6 FAIL: second window appeared`. Results come back privately, never through git.

**Everything below is unverified inside Revit.** The unit tests and the real Extractor runs on the agent's machine never ran IronPython, pyRevit or Revit's API. This session is the first time the code runs there, so a first-click failure (Part A) is possible and cheap to find: Part A comes first and takes minutes.

## Before you start (10 minutes, Revit closed)

1. Git, on each machine: `git fetch origin; git reset --keep origin/mgo-changes` (`HANDOVER.md` §1). Never `git pull`.
2. Optional, for the local Analyzer: Node.js 24 or later, then `npm ci --ignore-scripts --omit=optional` once in `Analyzer\`. Without it, item C3 tests the website fallback; say which one you tested.
3. Build the sample folder with the test kit, from the repo root:

```powershell
$kit = '.\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\v1_test_kit.ps1'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $kit -Setup
```

   It takes the two smallest different sample models under `C:\ProgramData\Autodesk\RVT <year>\` and builds `C:\RX-test` (change it with `-Root`). Only copies are made; your models are never opened or changed. `-Setup` refuses an existing folder (`-Force` removes one this kit made). It creates:
   - `Samples\` with both samples (A and B), plus a `.0001.rvt` backup of A next to them;
   - `Folder with spaces\` and a folder with Polish letters, `&` and `%` in its name, each with a copy;
   - `Backup\` with a copy;
   - `Tower.2024.rvt` (a model whose name looks like a version);
   - `Not a model.rvt`, a text file;
   - optional `Newer\` and `Older\`: add `-Newer '<model saved in a newer Revit>'` and `-Older '<model saved in an older Revit>'`. A Revit 2025 sample is a good "newer" one. Without them, items B6 and D6 are skipped.
4. **S1** `powershell.exe -NoProfile -ExecutionPolicy Bypass -File $kit -Check`: note the Print Spooler start type (the "before" value) and that no `RevitExtractor` process is running.

The kit has three commands. Its output holds no paths or model names, so it is safe to send:
- `-Setup`: as above.
- `-Check`: machine lines (Print Spooler, leftover `RevitExtractor*` and `Revit.exe` processes, Extractor builds). With a folder (`-Check '<folder>'`) it also reports each run in it: state OK / FAIL / INCOMPLETE / NOT STARTED, exit code, the `Success Jobs` line, output file counts, which folders exist, error counts and the duration. The folder is one run folder, or the output folder that holds several (runs are numbered in the order they were created).
- `-Stamp '<file>'`: the file's size and last-write time, for before and after comparisons.

The output folder is by default `Documents\RevitExtractor`. In this list `$out` means that folder: `$out = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'RevitExtractor'`.

## Part A: the first click (5 minutes; stop here if it fails)

Start Revit with no model open.

- [ ] **A1** The **Export** button is on the ribbon (RevitExtractor tab, Setup panel) and enabled. Open any model: it is greyed. Close the model: enabled again.
- [ ] **A2** Click Export. The window opens, and pyRevit's output window shows no error. **If it does not open, send the text of the output window and stop here.** (An import error under IronPython would show up exactly here.)
- [ ] **A3** The old "Export setup" button still opens and searches as before. Close it.

## Part B: model window, no export yet (10 minutes)

- [ ] **B1** Add folder… `C:\RX-test`. Rows appear. Not listed: the file in `Backup` and the `.0001.rvt` file. Listed: `Tower.2024`, and the model in the folder with Polish letters, `&` and `%`.
- [ ] **B2** While rows appear, the window stays responsive (it can be moved, and the search box takes text).
- [ ] **B3** `Not a model.rvt` is greyed as unreadable, cannot be ticked, and has a tooltip.
- [ ] **B4** Search, the ▾ filters, Select all shown and Space behave as in the old window. Select all shown does not tick greyed rows.
- [ ] **B5** Close and reopen: the folder and the output folder are remembered, and the list fills faster (the cache file `catalog-cache.json` exists in `%APPDATA%\RevitExtractor`).
- [ ] **B6** Only if you built `Newer\` and `Older\`: the newer model is greyed, cannot be ticked, and has a tooltip (note whether it shows a year or "could not be read"). The older model can be ticked and shows the upgrade note.
- [ ] **B7** Note whether the model list scan caused any dialog, or Revit refusing the read (`BasicFileInfo.Extract` runs from the window's timer).

## Part C: exports with the sample models (25 minutes)

- [ ] **C1** Tick sample A, default scope, Export. Control returns at once and the status window shows the row, the time running and the finished steps.
- [ ] **C2** Result is Done. Open output folder opens `…\export-<date>-<id>\output`. The run folder has `index.json`, `output\`, `logs\`, `journals\`, `console.log`.
- [ ] **C3** Open in Analyzer: the model shows in the browser (local Analyzer), or the folder and the website open (fallback). Say which. With the local Analyzer: a console window appeared, and closing it stops the server.
- [ ] **C4** Tick sample A, Choose views…: views are listed. Tick two 2D views and one 3D view, Export. Only those three are in the result.
- [ ] **C5** In the view window, Save index.json… writes a file. Back returns to the model list with its ticks.
- [ ] **C6** Tick three models (include the one in the folder with Polish letters, `&` and `%`), Export. They run one after another. **While they run:**
  - open a model in Revit: the Export button is greyed, the status window still updates;
  - click X on the status window: it minimises and can be restored from the taskbar;
  - click the old "Export setup" button and close it: the status window still updates.
- [ ] **C7** Still during C6: close the model, run pyRevit **Reload**, then click Export. The **same** status window with the same rows is shown, not a second one. Add one more export: it waits behind the others.
- [ ] **C8** Cancel export on a waiting row: it never starts and no folder is created for it.
- [ ] **C9** Cancel export on the running row. Then `$kit -Check $out`: no `RevitExtractor` process is left, and the cancelled run is listed as INCOMPLETE (its folder still exists).
- [ ] **C10** Batch with a shared index: choose the file saved in C5 with two models ticked. If you ticked views in C5 it must be refused with a clear message; with one model ticked it must run.
- [ ] **C11** While an export runs, open **the model that is being exported** in Revit. Note anything unusual.
- [ ] **C12** Start two exports, then **close Revit** while the first runs. Revit exits fully (no `Revit.exe` left in Task Manager). Wait, then run `$kit -Check $out`: the first run is OK, and the second is NOT STARTED.
- [ ] **C13** `$kit -Check $out` once more: the Print Spooler start type equals the value of S1. Send the whole output; it also holds the `Success Jobs` lines.

## Part D: real models (20 minutes; results are private)

Start Revit again with no model open. For D3 and D5, run `$kit -Stamp '<model path>'` before and after.

- [ ] **D1** Add a real root on a share. Note the file count and the time until the list is complete (cold). Rescan and note the time again (warm). The window stays responsive.
- [ ] **D2** No backup files, no `Backup` folders, and no local copies of centrals are listed.
- [ ] **D3** A workshared central on the share, Choose views…: note the open time and any dialog. Views are listed. Afterwards: `-Stamp` unchanged, no new local copy in your Documents, no document open in Revit, and the Export button still enabled.
- [ ] **D4** The 1000+ sheet model, Choose views…: note the open time. Ticking, Select all shown and search are as fast as in the slice 1 test.
- [ ] **D5** Export that central with the default scope, straight from the share. Result OK; `-Stamp` unchanged afterwards.
- [ ] **D6** An older-version model, Choose views…: note the time. The file is unchanged. Export it: note the result.
- [ ] **D7** List a model, rename its file in Explorer, then Choose views…: a readable message in the window's language, and nothing is queued. Rename it back.
- [ ] **D8** Open `console.log` of the C6 run from the folder with Polish letters: is the model path readable there?

## Part E: Polish (3 minutes)

- [ ] **E1** Set pyRevit's language to Polish and reload. The button title, the model window, the view window and the status window are in Polish, with no English label left. Screenshots of the three windows with a sample model are welcome.

## Part F: the Revit 2025 machine (10 minutes)

- [ ] **F1** `validate_native_legacy.ps1`: send the output.
- [ ] **F2** Export is enabled with no model open. One export with the default scope: result OK.
- [ ] **F3** One model, Choose views…, tick two 2D views and one 3D view, Export: only those are in the result (the `ElementId.Value` path).

Nobody can test the 2026 row: its IFC and DWG options stay marked untested.

## Part G: scripts, Revit closed (10 minutes)

- [ ] **G1** `validate_native_legacy.ps1`: all lines PASS (2025.3 parser shape). Send the output.
- [ ] **G2** `run_extractor_integration.ps1 -Parallel 2 -ModelPath '<a.rvt>' -ModelPath2 '<b.rvt>'`, with the two sample models from `C:\RX-test\Samples`. A FAIL is expected (fixed pipe); we need to know for this build. Send the output. It names your Windows user folder: private.

Both scripts are in `pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\`; run them as `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <script> …`.

## What to send back, privately

1. This list with PASS, FAIL or a note per item, and the times of D1, D3, D4 and D6.
2. The outputs: G1, G2, F1, and `$kit -Check` from S1, C9, C12 and C13.
3. For any failure: the text of pyRevit's output window, and `console.log` and `stderr.log` of that run folder. These can name models and paths, so never commit them.

## What the agent does with the results

- Records them in the READMEs' Validation sections and in `HANDOVER.md`.
- Adds 2025 to `TESTED_YEARS` if Part F passed, and sets `PARALLEL_VERIFIED` only if G2 passed.
- Asks before deleting the old buttons (Q12).
