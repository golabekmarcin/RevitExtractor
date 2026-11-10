# v1 Revit test: the owner's one checklist

The owner runs this **once, at the end of v1** (after `export-button`), on the Revit 2022 + pyRevit machine. The second machine has Revit 2025 for the items marked 2025. Every module adds the items that only a real Revit can check. Results come back privately, never through git.

Before pulling on either machine: `git fetch origin; git reset --keep origin/mgo-changes` (`HANDOVER.md` §1).

## shared-ui
- [ ] The old "Export setup" button still opens and searches as before (proves `lib/` on `sys.path` breaks nothing).

## index-builder
- [ ] `validate_native_legacy.ps1` on the Revit 2022 machine (2025.3 parser shape): all lines PASS with the lib builder.
- [ ] One export with the default scope and one with ticked 2D and 3D views: the exported views are the ticked ones.
- [ ] Revit 2025 machine: the same script and one export. Then 2025 is added to `TESTED_YEARS`.
- Nobody can test the 2026 row.

## model-catalog
- [ ] A real root on a local disk and on a share: rows appear, the window stays responsive. Note the cold and warm times and the file count.
- [ ] Backup files, backup folders and local copies of centrals do not appear; a real model named like `Name.2024.rvt` does.
- [ ] A model saved in a newer Revit is greyed with the tooltip (note whether it shows a year or "could not be read"); an older one shows the warning.
- [ ] Paths with Polish letters work; the cache file appears and the second scan is fast.

## model-reader
- [ ] A workshared central on a share: views are listed; the file's size and modified time are unchanged; no local copy is created; Revit still has no document open afterwards and the button stays enabled.
- [ ] A non-workshared model: the same.
- [ ] An older-version model: views are listed after the in-memory upgrade; the file is unchanged; note the time.
- [ ] Note any dialog during the open, and the open time for the 1000+ sheet model.
- [ ] A file that can't be opened gives a readable message in the right language.
- [ ] Revit 2025: view ids are correct (the `ElementId.Value` path).

## export-runner
- [ ] Starting an export returns control at once; the run folder layout is right; the result is `ok`; capture the `Success Jobs` line.
- [ ] Close Revit during an export: it finishes and the folder is complete.
- [ ] Cancel: no `RevitExtractor.exe` or `RevitExtractor_Client.exe` is left; the folder stays.
- [ ] Queue two or three exports: they run one after another.
- [ ] Work in Revit during an export, and open the model that is being exported.
- [ ] Export a workshared central straight from a share: the central is untouched.
- [ ] A model path with spaces, Polish letters and `&` or `%` in a folder name.
- [ ] Print Spooler start type before and after.
- [ ] `run_extractor_integration.ps1 -Parallel 2` with two small non-client models (Revit's own samples). Only a pass here sets `PARALLEL_VERIFIED`. It already **failed** with build 2024.0.x on the main machine (fixed IPC pipe), so expect a FAIL with 2025.3 too. Still run it, so we know.
- [ ] An export started from the button (IronPython `DotNetStarter`) writes a complete `console.log` and reports `ok`. This proves `ProcessStartInfo.EnvironmentVariables` and `ExitCode` work under IronPython.
- [ ] A model path with Polish letters: `console.log` shows the path readably (it might be in the OEM code page).

## status-window, export-button
Added when those modules are specified.
