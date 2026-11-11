# v1 Revit test: the owner's one session

One session, about 75 minutes, on the Revit 2022 + pyRevit machine. Part E (10 minutes) is on the machine with Revit 2025. Answer with the item number and PASS, FAIL or a note, for example `B6 FAIL: second window appeared`. Results come back privately, never through git.

## Before you start (5 minutes)

1. Git, on each machine: `git fetch origin; git reset --keep origin/mgo-changes` (`HANDOVER.md` §1). Never `git pull`.
2. Optional, for the local Analyzer: Node.js 24 or later, then `npm ci --ignore-scripts --omit=optional` once in `Analyzer\`. Without it, item B3 tests the website fallback instead; say which one you tested.
3. Pick two small non-client models, for example Revit's own samples under `C:\Program Files\Autodesk\Revit <year>\Samples\`. If you have them, add a model saved in a newer Revit (a Revit 2025 sample) and one saved in an older Revit.
4. Build the sample folder (Revit closed):

```powershell
$kit = '.\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\v1_test_kit.ps1'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $kit -Setup -SampleA '<a.rvt>' -SampleB '<b.rvt>' -Newer '<optional.rvt>' -Older '<optional.rvt>'
```

It creates `C:\RX-test` with: both samples; a copy in a folder with spaces, Polish letters, `&` and `%`; a `Backup` folder; a `.0001.rvt` backup next to its model; a model named like `Tower.2024.rvt`; a text file renamed to `.rvt`; and the optional newer and older models.

## Part 0: scripts, Revit closed (10 minutes)

- [ ] **01** `validate_native_legacy.ps1`: all lines PASS (2025.3 parser shape). Send the output.
- [ ] **02** `run_extractor_integration.ps1 -Parallel 2 -ModelPath '<a.rvt>' -ModelPath2 '<b.rvt>'`. A FAIL is expected (fixed pipe); we need to know for this build. Send the output.
- [ ] **03** `v1_test_kit.ps1 -Check`: note the Print Spooler start type (the "before" value).

## Part A: ribbon and windows, no export yet (10 minutes)

Start Revit with no model open.

- [ ] **A1** The old "Export setup" button still opens and searches as before. Close it.
- [ ] **A2** The new **Export** button is enabled. Open any model: it is greyed. Close the model: enabled again.
- [ ] **A3** Click Export. The window opens with no error in pyRevit's output window. If it does not open, send the output text and stop here.
- [ ] **A4** Add folder… `C:\RX-test`. Rows appear. Not listed: the `Backup` folder's file and the `.0001.rvt` file. Listed: the `Tower.2024` model and the model in the folder with Polish letters.
- [ ] **A5** While rows appear, the window stays responsive (it can be moved, and the search box takes text).
- [ ] **A6** The newer-version model is greyed, cannot be ticked, and has a tooltip. Note whether it shows a year or "could not be read". The renamed text file is greyed as unreadable. The older model can be ticked and shows the upgrade note.
- [ ] **A7** Search, the ▾ filters, Select all shown and Space behave as in the old window. Select all shown does not tick greyed rows.
- [ ] **A8** Close and reopen: the folder and the output folder are remembered, and the list fills faster (the cache file exists in `%APPDATA%\RevitExtractor`).

## Part B: exports with the sample models (25 minutes)

- [ ] **B1** Tick sample A, default scope, Export. Control returns at once and the status window shows the row, the time running and the finished steps.
- [ ] **B2** Result is OK. Open output folder opens `…\export-<date>-<id>\output`. The run folder has `index.json`, `output\`, `logs\`, `journals\`, `console.log`.
- [ ] **B3** Open in Analyzer: the model shows in the browser (local Analyzer), or the folder and the website open (fallback). Say which. With the local Analyzer: a console window appeared, and closing it stops the server.
- [ ] **B4** Tick sample A, Choose views…: views are listed. Tick two 2D views and one 3D view, Export. Only those three are in the result.
- [ ] **B5** In the view window, Save index.json… writes a file. Back returns to the model list with its ticks.
- [ ] **B6** Tick three models (include the one in the folder with Polish letters, `&` and `%`), Export. They run one after another. **While they run:**
  - open a model in Revit: the Export button is greyed, the status window still updates;
  - click X on the status window: it minimises and can be restored from the taskbar;
  - click the old "Export setup" button and close it: the status window still updates.
- [ ] **B7** Still during B6: close the model, run pyRevit **Reload**, then click Export. The **same** status window with the same rows is shown, not a second one. Add one more export: it waits behind the others.
- [ ] **B8** Cancel export on a waiting row: it never starts and no folder is created for it.
- [ ] **B9** Cancel export on the running row. Then `v1_test_kit.ps1 -Check`: no `RevitExtractor.exe` or `RevitExtractor_Client.exe` is left, and the cancelled run folder still exists.
- [ ] **B10** Batch with a shared index: choose the file saved in B5 with two models ticked. If you ticked views in B5 it must be refused with a clear message; with one model ticked it must run.
- [ ] **B11** While an export runs, open **the model that is being exported** in Revit. Note anything unusual.
- [ ] **B12** Start two exports, then **close Revit** while the first runs. Revit exits fully (no `Revit.exe` left in Task Manager). Wait, then run `-Check`: the first run is complete and OK, and the second never started.
- [ ] **B13** `-Check` once more: the Print Spooler start type equals the value of item 03. Send the whole `-Check` output; it also holds the `Success Jobs` lines.

## Part C: real models (20 minutes; results are private)

Start Revit again with no model open. For C3 and C5, run `v1_test_kit.ps1 -Stamp '<model path>'` before and after; it prints only size and time.

- [ ] **C1** Add a real root on a share. Note the file count and the time until the list is complete (cold). Rescan and note the time again (warm). The window stays responsive.
- [ ] **C2** No backup files, no `Backup` folders, and no local copies of centrals are listed.
- [ ] **C3** A workshared central on the share, Choose views…: note the open time and any dialog. Views are listed. Afterwards: `-Stamp` unchanged, no new local copy in your Documents, no document open in Revit, and the Export button still enabled.
- [ ] **C4** The 1000+ sheet model, Choose views…: note the open time. Ticking, Select all shown and search are as fast as in the slice 1 test.
- [ ] **C5** Export that central with the default scope, straight from the share. Result OK; `-Stamp` unchanged afterwards.
- [ ] **C6** An older-version model, Choose views…: note the time. The file is unchanged. Export it: note the result.
- [ ] **C7** List a model, rename its file in Explorer, then Choose views…: a readable message in the window's language, and nothing is queued. Rename it back.
- [ ] **C8** Open `console.log` of the B6 run from the folder with Polish letters: is the model path readable there?

## Part D: Polish (3 minutes)

- [ ] **D1** Set pyRevit's language to Polish and reload. The button title, the model window, the view window and the status window are in Polish, with no English label left. Screenshots of the three windows with a sample model are welcome.

## Part E: the Revit 2025 machine (10 minutes)

- [ ] **E1** `validate_native_legacy.ps1`: send the output.
- [ ] **E2** Export is enabled with no model open. One export with the default scope: result OK.
- [ ] **E3** One model, Choose views…, tick two 2D views and one 3D view, Export: only those are in the result (the `ElementId.Value` path).

Nobody can test the 2026 row: its IFC and DWG options stay marked untested.

## What to send back, privately

1. This list with PASS, FAIL or a note per item, and the times of C1, C3, C4 and C6.
2. The script outputs: 01, 02, E1, and `-Check` from B9, B12 and B13.
3. For any failure: the text of pyRevit's output window, and `console.log` and `stderr.log` of that run folder. These can name models and paths, so never commit them.

## What the agent does with the results

- Records them in the READMEs' Validation sections and in `HANDOVER.md`.
- Adds 2025 to `TESTED_YEARS` if Part E passed, and sets `PARALLEL_VERIFIED` only if item 02 passed.
- Asks before deleting the old buttons (Q12).
