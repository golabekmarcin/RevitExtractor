# Spec: shared-ui

Module of `SPEC.md`. Depends on: nothing. Status: **approved by the owner 2026-11-10**.

## Objective

Make the window building blocks from slice 1 available to every button by moving them into the extension-level `lib/`. They are already verified in Revit 2022: the theme, search bar, column filters and placeholder. The language helper moves too. Later modules (`status-window`, `export-button`) import them from there instead of copying them.

## Scope

Copy these files from `ExportSetupLegacy.pushbutton/` to `pyRevit/Extractor.extension/lib/`:

| Source | Target | Change allowed |
| --- | --- | --- |
| `extractor_i18n.py` | `rx_i18n.py` | none (only the file name) |
| `rx_theme.xaml` | `rx_theme.xaml` | none |
| `rx_search_bar.py`, `rx_search_bar.xaml` | same names | the import line only: `from extractor_i18n import tr` → `from rx_i18n import tr` |
| `rx_search_placeholder.py` | same | same import line only |
| `rx_column_filter_model.py`, `rx_column_filter_ui.py` | same | same import line only |

- **The old buttons are not touched.** `ExportSetupLegacy.pushbutton` keeps its own copies until v1 is verified and the old buttons are deleted (Q12). `ExportSetup.pushbutton` doesn't use these files.
- Window-specific files (`extractor_text.py`, `ui.xaml`, `extractor_ui.py`) stay in the bundle. `export-button` gets its own.

## Why the same names are safe during the transition

`lib/` and the legacy bundle will both contain `rx_search_bar` and its siblings. In a shared engine, whichever loads first is reused under that name. That's harmless only if both copies behave the same, so a test enforces it: each lib file must equal its bundle copy, apart from the allowed import line. The test is deleted together with the old buttons.

## Acceptance criteria

1. The six files exist in `lib/`. No file in `lib/` imports an `extractor_*` module.
2. A test compares each `lib/` file with its bundle copy: identical after replacing `from extractor_i18n import tr` with `from rx_i18n import tr`, and `rx_i18n.py` identical to `extractor_i18n.py`.
3. The existing search-bar, column-filter and theme-key tests in `test_window_legacy.py` also run against the `lib/` copies (same assertions, loaded from `lib/`).
4. `rx_theme.xaml` and `rx_search_bar.xaml` from `lib/` load in real WPF (PowerShell, .NET Framework).
5. All existing tests still pass (108 at the time of writing). The legacy and 2026 buttons are unchanged (`git diff` touches neither bundle).
6. Owner check in Revit 2022 after pulling: the existing "Export setup" button still opens and searches as before. That proves `lib/` on `sys.path` breaks nothing.

## Commands

```powershell
python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v
# WPF load check (new script, part of this module):
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\validate_xaml.ps1
```

`validate_xaml.ps1` loads every `*.xaml` under `lib/` (and later the new button) with `System.Windows.Markup.XamlReader`, merging `rx_theme.xaml` first. It prints one PASS/FAIL line per file and exits non-zero on any failure.

## Testing

- New `tests/test_shared_ui.py`: covers the equality guard (criterion 2) and the lib-side run of the existing assertions (criterion 3). It adds `lib/` to `sys.path` with **append**, and pins `rx_i18n` in `sys.modules` as needed.
- No Revit API is involved. WPF behaviour inside Revit was verified in slice 1 and is not re-tested beyond criterion 6.

## Boundaries

- Never edit the moved files' logic in this module; behaviour changes come later, in the module that needs them, with their own tests.
- Never delete the bundle copies here.
