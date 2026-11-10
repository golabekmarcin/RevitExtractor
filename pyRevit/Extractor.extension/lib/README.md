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

Rules:
- Every file starts with `rx_`, so it can't clash with another extension's module in a shared IronPython engine.
- IronPython 2.7 only (see `CLAUDE.md`).
- `rx_capabilities.py` imports nothing from Revit, pyRevit or .NET, and a test enforces that.
- **Temporary duplicates:** `ExportSetupLegacy.pushbutton` still has its own copies of the shared-ui files. `tests/test_shared_ui.py` requires the two copies to stay equal, apart from the `tr` import line. Delete the copies and that test together with the old buttons (Q12).

## Validation

2026-11-10, main machine (Revit 2023, no pyRevit):
- unit tests: 153 OK. The slice 1 search-bar, column-filter and theme tests run against both the bundle and `lib/`;
- `tests/validate_xaml.ps1`: `rx_theme.xaml` and `rx_search_bar.xaml` load in real WPF (.NET Framework, Windows PowerShell 5.1). A broken XAML gives FAIL and exit 1.

**Not verified:** IronPython 2.7 and anything inside Revit.
- Still open: the owner's check in Revit 2022 that the old "Export setup" button still opens and searches with `lib/` present.
- `rx_capabilities` is not used by any button yet.
