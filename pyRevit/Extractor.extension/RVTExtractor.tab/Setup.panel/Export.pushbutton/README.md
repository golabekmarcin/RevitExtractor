# Export: the one-button export (Revit 2022 and later)

English · [Polski](README.pl.md)

pyRevit button that exports Revit models with Autodesk's native Revit Extractor, with **no model open** in Revit. You pick models from your folders, optionally pick the views of one model, and start the export. The command returns at once; a status window shows progress and the result.

**Status: built and unit-tested outside Revit. Not yet run in Revit.** See Validation.

## Install

Clone the repository and add `<clone>\pyRevit` as a custom extension folder in pyRevit's settings, then **Reload pyRevit**. The button is `Export` on the RevitExtractor tab, Setup panel. The button needs `lib\` of this extension, so it cannot be copied alone. The old `ExportSetup` and `ExportSetupLegacy` buttons are untouched and still work.

For "Open in Analyzer" with the local Analyzer: Node.js 24 or later, and `npm ci --ignore-scripts --omit=optional` once in `Analyzer\`. Without them the button opens the output folder and the website instead.

## Use

1. With no model open, click **Export**. With a model open the button is greyed; if it is clicked anyway you get a message, and nothing is read.
2. **Add folder…** (one or more root folders, searched recursively; local disks or a file server). The list fills while it is scanned. Backup files (`*.0001.rvt`), `Backup` folders and local copies of centrals are skipped. Models saved in a newer Revit are greyed; older ones can be exported with a warning (the export upgrades a copy). Files whose version cannot be read are greyed with a tooltip.
3. Tick models. The search box takes words in any order, or a regex; ▾ on the Folder and Revit version headers filters. **Select all shown** touches only shown, enabled rows.
4. Choose the **output folder** (default `Documents\RevitExtractor`; each export gets its own `export-<date>-<id>` folder) and the scope: **Extractor default scope**, or a **Shared index.json** (refused with several models if it lists view ids).
5. **Export** queues one export per ticked model. **Choose views…** (exactly one model ticked) reads that model in the background (detached, read-only, worksets closed, never saved) and opens the view window: tick 2D views, sheets and 3D views, switch the SQLite database and options, **Save index.json…**, **Back** or **Export**.
6. The **status window** lists the exports one by one with state, progress and time. Open output folder, Open in Analyzer and Cancel export act on the highlighted row. Closing it with X minimises it while exports are queued or running. Exports keep running when it is closed or when Revit closes; not-yet-started ones are dropped when Revit closes.

Exports run **one at a time**: with the Extractor build tested here, a second Extractor fails on a fixed pipe. Another Extractor already running on the machine makes the queue wait.

Settings (folders, output folder) are kept in your pyRevit config file, which then holds folder paths: never share it. The model list cache is `%APPDATA%\RevitExtractor\catalog-cache.json` and also holds model paths.

All text is English and Polish, following pyRevit's language setting (English by default).

## Validation

2026-11-11, main machine (Revit 2023, no pyRevit, CPython 3):
- all unit tests: 554 OK. Both windows run against fake WPF; `validate_xaml.ps1` loads both XAML files in real WPF;
- `run_extractor_integration.ps1`: a real Extractor run started from the same launch spec the queue uses: PASS (also `-Cancel`); `-Parallel 2` FAIL (fixed pipe);
- `v1_test_kit.ps1 -Setup` and `-Check` ran against such a run.

**Not verified:** IronPython 2.7 (the tests run on CPython 3), pyRevit, and everything inside Revit: the greying of the button, the pickers, `BasicFileInfo.Extract` from the scan timer, a real background open, the status window and its hand-over between script engines, closing Revit during an export, the Revit 2025 and 2026 rows, and Polish text in the real windows. The checklist for all of that is `specs/v1-revit-test.md`; results will be recorded here.
