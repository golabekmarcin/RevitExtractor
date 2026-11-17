# Extractor.extension `lib/`

[Polski](README.pl.md)

Shared modules for every button of this extension. pyRevit puts this folder on `sys.path` for all of them. A button's own folder comes first, so a button keeps using its own copy of a same-named file.

| File | Module (`specs/`) | Purpose |
| --- | --- | --- |
| `rx_i18n.py` | shared-ui | `tr(english, polish)`, follows pyRevit's language setting |
| `rx_theme.xaml` | shared-ui | window theme (`Rx*` keys) |
| `rx_search_bar.py`, `rx_search_bar.xaml`, `rx_search_placeholder.py` | shared-ui | search box with ✕ clear, regex and "Clear all filters" |
| `rx_column_filter_model.py`, `rx_column_filter_ui.py` | shared-ui | Excel-style column header filters |
| `rx_capabilities.py` | capabilities | what the running Revit supports, plus `element_id_value` |
| `rx_index.py` | index-builder | one `build_index` for every Revit version, the same output as the old buttons |
| `rx_catalog.py` | model-catalog | `.rvt` list under remembered roots, with skip rules, newer/older/unknown and a cache in `%APPDATA%\RevitExtractor\catalog-cache.json`. The cache holds model paths: never commit or share it |
| `rx_reader.py` | model-reader | background open (detached, worksets closed), view list, exactly one `Close(False)`; it never saves. `links=True` also lists a cloud model's Revit links (`collect_cloud_links`) |
| `rx_status.py`, `rx_status_ui.py`, `rx_status.xaml` | status-window | the export queue's modeless status window: progress from `console.log`, Open output folder, Open in Analyzer, Cancel export. The queue is published in AppDomain data and only JSON text crosses between script engines |
| `rx_runner.py` | export-runner | run folder, Extractor process through `cmd.exe`, queue (one at a time), cancel with `taskkill /T /F`, success check. A cloud job also has a time-sliced `staging` state that copies the cache files into `<run>\model` before the Extractor starts, and deletes the copies after the process tree has exited (`model\stage.json` stays) |
| `rx_cloud.py` | cloud-catalog | pure logic of the Cloud source: reads Revit journals (UTF-16, UTF-8, ANSI) for project and file names, scans `%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit <year>\CollaborationCache`, joins them by project GUID + model GUID, keeps selection, names and link lists in `%APPDATA%\RevitExtractor\cloud-catalog.json`, and plans which cache files to stage. No Revit, .NET or `clr` import (a test enforces it). **The memory file holds client project and file names: never commit or share it** |
| `rx_cloud_stage.py` | cloud-catalog | the only file IO of the Cloud source: free-space check and the chunked copy. Sources are opened `rb` only, a destination is never overwritten, and a cache file that changed during the copy fails the job. The cache is never written |

Rules:
- Every file starts with `rx_`, so it can't clash with another extension's module in a shared IronPython engine.
- IronPython 2.7 only (see `CLAUDE.md`).
- `rx_capabilities.py` imports nothing from Revit, pyRevit or .NET, and a test enforces that.
- **Temporary duplicates:** `ExportSetupLegacy.pushbutton` still has its own copies of the shared-ui files. `tests/test_shared_ui.py` requires the two copies to stay equal, apart from the `tr` import line. Delete the copies and that test together with the old buttons (Q12).

## Validation

2026-11-10, main machine (Revit 2023, no pyRevit):
- unit tests: 153 OK. The slice 1 search-bar, column-filter and theme tests run against both the bundle and `lib/`;
- `tests/validate_xaml.ps1`: `rx_theme.xaml` and `rx_search_bar.xaml` load in real WPF (.NET Framework, Windows PowerShell 5.1). A broken XAML gives FAIL and exit 1.

Also 2026-11-10, same machine:
- **unit tests: 340 OK** with all modules;
- **`validate_native_legacy.ps1`:** indexes from `rx_index` equal the old buttons' for 9 legacy and 3 newest-row profiles. The native parser accepted them (Extractor 2024.0.2022.0415): 35 PASS, and 2 SKIP because `view_unique_ids` needs a newer Extractor;
- **`run_extractor_integration.ps1`**, a real Extractor run started from `rx_runner`'s launch spec on the Dynamo sample:
  - normal run **PASS**: `Success Jobs: 13, Failed Jobs: 0`, 64 output files, the sample's SHA-256 unchanged;
  - `-Cancel` **PASS**: the whole process tree was ended and the run folder kept;
  - `-Parallel 2` **FAIL**: the second run stopped with `All pipe instances are busy` (fixed pipe `Main_Process_to_Client_0_Pipe`). With this build, exports must run one at a time, so `PARALLEL_VERIFIED` stays False.
- `rx_reader`: strict-stub tests, and 13 of 13 deliberately broken copies were caught (no save, exactly one `Close(False)`).

**Not verified:** IronPython 2.7 and anything inside Revit. That includes `BasicFileInfo.Extract`, a real background open, `DotNetStarter` (`ProcessStartInfo` under IronPython), the status window and its hand-over between script engines, closing Revit during an export, and the 2025.3 parser shape. These are all in `specs/v1-revit-test.md` for the owner's test at the end of v1.

2026-11-11, same machine: all unit tests 554 OK; `validate_xaml.ps1` loads every XAML in `lib/` and `Export.pushbutton/`. `Export.pushbutton` is the first button that uses these modules (`../RVTExtractor.tab/Setup.panel/Export.pushbutton/README.md`).

2026-11-16, same machine (cloud-catalog, `rx_cloud`, `rx_cloud_stage`):
- **unit tests: 924 OK**; `validate_xaml.ps1`: 6 PASS;
- `run_extractor_integration.ps1 -Cloud` **PASS**: a fake cache tree in `%TEMP%` (the Dynamo sample saved under GUID file names, synthetic journal), staged through `rx_runner.Queue` and exported by the real Extractor (`staging` -> `running` -> `ok`, `Success Jobs: 13, Failed Jobs: 0`); both cache copies kept their SHA-256 and times, and only `model\stage.json` was left after the run. The normal run still PASSes;
- scan timing (100 synthetic 1 MB journals + 1,000 cache files): 2.9 s in total, slowest step 0.04 s.

**Not verified for the cloud code:** IronPython 2.7, and anything inside Revit. That covers journal lines on any Revit year but 2022, the background open of a cache file, the link list of a real cloud model, copy speed next to a working Revit, link geometry in a federated view, and the Remember cloud model button. These are Part H of `specs/v1-revit-test.md`.
