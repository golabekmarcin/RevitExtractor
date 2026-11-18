# Export: the one-button export (Revit 2022 and later)

English · [Polski](README.pl.md)

pyRevit button that exports Revit models with Autodesk's native Revit Extractor, with **no model open** in Revit. You pick models from your folders, optionally pick the views of one model, and start the export. The command returns at once; a status window shows progress and the result.

**Status: built and unit-tested outside Revit. Not yet run in Revit.** See Validation.

## Install

Clone the repository and add `<clone>\pyRevit` as a custom extension folder in pyRevit's settings, then **Reload pyRevit**. The button is `Export` on the RevitExtractor tab, Setup panel. The button needs `lib\` of this extension, so it cannot be copied alone. The old `ExportSetup` and `ExportSetupLegacy` buttons are untouched and still work.

Exporting needs only Revit, pyRevit and the Extractor that ships with Revit. **Node.js is optional**: it is used only by "Open in Analyzer" with the local Analyzer.

**Known limit:** Revit 2025 and later run on .NET 8, where some .NET types need an extra assembly reference (`libx_dotnet.py` adds them). This is untested on Revit 2025+ until the owner confirms it; on Revit 2022-2024 nothing changes.

For the local Analyzer:
1. Install Node.js 24 or later yourself, or from the Company Portal. Restart Revit afterwards so it sees the new `PATH`.
2. Double-click `Analyzer\Start-Analyzer.cmd` once. It installs the npm packages (Internet needed) and trusts the Windows certificate store, so a company proxy that re-signs HTTPS works without extra setup; certificate checking stays on. If `npm ci` still reports a certificate error, ask IT for the company root certificate and run `npm config set cafile "<path to root.pem>"`. Do not turn off `strict-ssl`.

Without Node.js and the packages the button opens the output folder and the website instead, after a notice you can switch off with "Don't show this again".

## Use

1. With no model open, click **Export**. With a model open the button is greyed; if it is clicked anyway you get a message, and nothing is read.
2. **Add folder…** (one or more root folders, searched recursively; local disks or a file server). The list fills while it is scanned. Backup files (`*.0001.rvt`), `Backup` folders and local copies of centrals are skipped. Models saved in a newer Revit are greyed; older ones can be exported with a warning (the export upgrades a copy). Files whose version cannot be read are greyed with a tooltip.
3. Tick models. The search box takes words in any order, or a regex; ▾ on the Folder and Revit version headers filters. **Select all shown** touches only shown, enabled rows.
4. Choose the **output folder** (default `%USERPROFILE%\RevitExtractor`, outside OneDrive; a warning shows when the chosen folder is synced by OneDrive; each export gets its own `export-<date>-<id>` folder) and the scope: **Extractor default scope**, or a **Shared index.json** (refused with several models if it lists view ids).
5. **Export** queues one export per ticked model. The window **stays open**: the ticks are cleared and a line says how many exports were queued, so you can tick more and queue them without reopening the button (the same model may be queued again). If the hand-over fails, the red error line says why and the ticks stay for a retry. Close the window when you are done; closing queues nothing more. **Choose views…** (exactly one model ticked) reads that model in the background (detached, read-only, worksets closed, never saved) and opens the view window: tick 2D views, sheets and 3D views, switch the SQLite database and options, **Save index.json…**, **Back** or **Export**.
6. The **status window** lists the exports one by one with state, progress and time. Open output folder, Open in Analyzer and Cancel export act on the highlighted row; right-clicking a row selects it and offers Show model in File Explorer and Show export folder in File Explorer. Clear finished removes the finished, failed and cancelled rows from the list; running and waiting exports stay and no files are deleted. While the model window is open the status window keeps updating but does not take clicks (the model window is modal): close the model window to use Cancel export, Clear finished or the row menu. Closing the status window with X minimises it while exports are queued or running. Exports keep running when it is closed or when Revit closes; not-yet-started ones are dropped when Revit closes. After Revit is started again, **Export** lists an export that is still running from the earlier session (found in your output folder; watched only, so it cannot be cancelled there, and new exports wait for it).

### Cloud (ACC) models

Choose **Cloud (ACC)** in "Models from" to list cloud models that Revit already holds on this computer. Nothing is downloaded and no model is opened to build the list.
1. Names come from the Revit **journals** (`%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit <year>\Journals`) and are matched to the files in `...\CollaborationCache` by project and model id. So only models **opened on this computer** (directly or as links) appear. A file in the cache without a known name is never listed under its id; the project card counts them ("Cached models without a name: N. Open them once in Revit to add them."). If no journal names a cloud model, a message says so; use **Remember cloud model** (next to this button) with the model open.
2. **Tick the projects** to list; none is ticked at first, and the choice is saved per user. Rows of other projects are greyed ("Not in the selected projects."). Two models with the same name in one project: only the newer cache copy can be ticked.
3. Each row shows its **cache date**: the time of the copy in the cache, which is as current as the last time that model was opened on this computer (nothing is claimed about the cloud version). Copies older than 7 days get a note; they can still be exported.
4. **Export** (and **Choose views…**) first reads the model's Revit links once, in the background, from the cache copy (the result is remembered until the copy changes). Each export then stages the files in its `model` folder under their real file names: by default each cache file is **hard-linked** (a second name for the same file: no copy, no extra disk space, seconds instead of minutes; the cache is never written, and a warning appears if a cache file changed during the export). A file that cannot be linked (another drive, or read-only) is copied, with a "Copying from the cache" progress in the status window. Set `"cloud_hardlinks": false` in `%APPDATA%\RevitExtractor\preferences.json` to always copy. The Extractor opens the staged file; the staged names and Revit's `_backup` folders are removed after the run. A link that is not in the cache is exported without, with a note.
5. The cache is **never written**. When the Extractor has finished, the copies are deleted; `model\stage.json` stays (names, sizes and cache dates). Check free disk space first: the copies and the Extractor's own temporary copy have to fit.

Not tested: folder-level selection (journals carry no folder), journal formats after Revit 2022. See Validation.

Exports run **one at a time**: with the Extractor build tested here, a second Extractor fails on a fixed pipe. Another Extractor already running on the machine makes the queue wait.

Settings (folders, output folder) are kept in your pyRevit config file, which then holds folder paths: never share it. The model list cache is `%APPDATA%\RevitExtractor\catalog-cache.json` and also holds model paths. The cloud memory is `%APPDATA%\RevitExtractor\cloud-catalog.json` and holds client project and file names: never share or commit it.

All text is English and Polish, following pyRevit's language setting (English by default).

## File names

The **File names** row of the model window sets a name template (for example `{SheetNumber} - {SheetName}`). **Presets** offers ready templates, **Insert** adds a token at the cursor, **Clear** empties the field, and a line shows an example name. An invalid template shows its error and **Export** is refused; the ticks stay. The template and the checkbox are remembered per user.

After a **successful** export the status window creates `named` in the run folder (the row says "Naming files: x of y"; its menu has **Show named files in File Explorer**) and `named.json` (state, counts, notes; no paths). `named` holds every PDF, DWG, IFC and each 3D view folder under the template's names. `output` is not touched, so the Analyzer opens the export as before.
- **Tokens:** sheet and view values (sheet number and name, current revision and its date and description, issue date, drawn/checked/designed/approved by, sheet size, view name, title on sheet, scale, detail level, discipline, phase, view template, number of the sheet the view is on, element id); any parameter as `{param:<name>}`; system values (year, month, day, hour, minute, second, date, short and long date in the Windows regional format, model name, Windows user, Revit user); and `{OriginalName}`. `{{` and `}}` give literal braces.
- **Hard links:** the entries are hard links (a second name for the same file on the same drive), so they use no extra disk space. A file is copied only when a link cannot be made (another drive, a file system without links). Editing a named file in place changes the original too; saving a new file instead of overwriting does not.
- **Optional split:** the checkbox "A separate folder for each format" makes `named\PDF`, `DWG`, `IFC` and `3D` instead of one flat folder.
- Names are cleaned for Windows, a name already used gets " (2)", " (3)" ..., and names are cut to the path limits.
- **Limits:** only after a successful export, once per run (not for failed, cancelled or adopted runs). Sheet and view values come from the export's own property data (on by default) and are looked up by **English** attribute names; with a localised Revit they may not be recognised, then the files keep their original name and a note says so. Other languages are not added yet.
- **Verified:** unit tests (1224 OK) and one real Extractor run on the Dynamo sample (counts: files, hard links, path length). **Not verified:** everything inside Revit (Part I of `specs/v1-revit-test.md`), IronPython 2.7, real sheet values on a real model, a Cloud job with a template.

## Validation

2026-11-11, main machine (Revit 2023, no pyRevit, CPython 3):
- all unit tests: 554 OK. Both windows run against fake WPF; `validate_xaml.ps1` loads both XAML files in real WPF;
- `run_extractor_integration.ps1`: a real Extractor run started from the same launch spec the queue uses: PASS (also `-Cancel`); `-Parallel 2` FAIL (fixed pipe);
- `v1_test_kit.ps1 -Setup` and `-Check` ran against such a run.

2026-11-16, same machine: all unit tests 924 OK (including the Cloud tab on fake WPF and the staged queue); `validate_xaml.ps1` 6 PASS; `run_extractor_integration.ps1 -Cloud` PASS (fake cache tree in `%TEMP%`, staged copy exported by the real Extractor, cache files unchanged, only `stage.json` left); `v1_test_kit.ps1 -Check` prints cloud counts only.

**Not verified for the Cloud tab:** everything inside Revit: real journal lines (checked on Revit 2022 only, by hand, earlier), the background open of a cache file, the link list of a real cloud model, copy time and Revit's responsiveness while copying, link geometry in a federated 3D view, and the Cloud tab in the real window. The checklist is Part H of `specs/v1-revit-test.md`.

**Not verified:** IronPython 2.7 (the tests run on CPython 3), pyRevit, and everything inside Revit: the greying of the button, the pickers, `BasicFileInfo.Extract` from the scan timer, a real background open, the status window and its hand-over between script engines, closing Revit during an export, the Revit 2025 and 2026 rows, and Polish text in the real windows. The checklist for all of that is `specs/v1-revit-test.md`; results will be recorded here.
