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
| `rx_reader.py` | model-reader | background open (detached, worksets closed), view list, exactly one `Close(False)`; it never saves |
| `rx_runner.py` | export-runner | run folder, Extractor process through `cmd.exe`, queue (one at a time), cancel with `taskkill /T /F`, success check |

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

**Not verified:** IronPython 2.7 and anything inside Revit. That includes `BasicFileInfo.Extract`, a real background open, `DotNetStarter` (`ProcessStartInfo` under IronPython), closing Revit during an export, and the 2025.3 parser shape. These are all in `specs/v1-revit-test.md` for the owner's test at the end of v1. No button uses these modules yet.
