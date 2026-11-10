# Plan: shared-ui

Implements `SPEC-shared-ui.md` (approved 2026-11-10). Status: **draft, waiting for owner approval.**

## Overview

Copy six verified files from `ExportSetupLegacy.pushbutton/` into a new extension-level `pyRevit/Extractor.extension/lib/`. Only one line changes: the `tr` import. A test keeps the copies equal to the bundle originals, the slice 1 tests also run against the `lib/` copies, and a new PowerShell script proves the XAML loads in real WPF. No user-visible change.

## Decisions made while planning

- **Test reuse by parameterizing, not duplicating.** The search-bar, column-filter and theme test classes in `test_window_legacy.py` read the module-level `BUNDLE` and modules loaded at import time. Task 2 moves those into mixins that take a source folder. `test_window_legacy.py` runs them with `BUNDLE` and `test_shared_ui.py` with `LIB`. The assertions do not change; only where the modules come from.
- **Bare-name imports resolve to the wrong copy in tests.** `rx_column_filter_ui.py` imports `rx_search_bar` and `rx_column_filter_model` by bare name. Both folders are on `sys.path` during a test run, and the bundle is appended first. So the lib-side loader must pin the lib copies (`rx_i18n`, `rx_search_bar`, `rx_column_filter_model`) in `sys.modules` while it loads `rx_column_filter_ui`. Otherwise the "lib" tests silently test the bundle.
- **Theme test scope on the lib side:** `test_every_theme_key_the_code_uses_exists` also reads `ui.xaml` and `extractor_ui.py`, which stay in the bundle. On the lib side it checks only `rx_column_filter_ui.py`. Later modules add their own window files.
- **In Revit, nothing changes for the old button.** pyRevit puts a button's own folder ahead of the extension `lib/`, so `ExportSetupLegacy` keeps loading its own copies. The equality guard makes the order irrelevant anyway. Criterion 6 (owner check) confirms it.
- `LIB = Path(__file__).resolve().parents[3] / "lib"` (tests → Setup.panel → RVTExtractor.tab → Extractor.extension).

## Tasks

### Task 1: Copy the six files into `lib/`, with the equality guard (test first)

**Description:** Write `tests/test_shared_ui.py` with the guard tests, watch them fail (no `lib/`), then create `lib/` with the copies.

**Acceptance criteria:**
- [ ] `lib/` holds `rx_i18n.py`, `rx_theme.xaml`, `rx_search_bar.py`, `rx_search_bar.xaml`, `rx_search_placeholder.py`, `rx_column_filter_model.py` and `rx_column_filter_ui.py`. That is seven files, the "six" of the spec counting `rx_search_bar.*` as one.
- [ ] Guard test: each file is byte-identical to its bundle source after replacing `from extractor_i18n import tr` with `from rx_i18n import tr`. `rx_i18n.py` is identical to `extractor_i18n.py`. Each `.py` that has the import contains the replacement exactly once.
- [ ] Guard test: no file in `lib/` contains `extractor_` in an import line.
- [ ] The copies keep the source line endings and encoding (the comparison is on bytes).

**Verification:** `python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v`: new tests pass, 108 old tests still pass.

**Dependencies:** none. **Files:** `lib/*` (7 new), `tests/test_shared_ui.py` (new). **Scope:** S.

### Task 2: Run the slice 1 assertions against `lib/`

**Description:** Refactor the search-bar, column-filter (model and popup) and theme test classes in `test_window_legacy.py` into mixins that load from a given folder. `test_window_legacy.py` keeps running them on the bundle; `test_shared_ui.py` runs them on `lib/` with the pinned imports described above.

**Acceptance criteria:**
- [ ] No assertion is added, removed or weakened. The diff of `test_window_legacy.py` only moves code and replaces `BUNDLE`/module globals with per-class attributes.
- [ ] The lib-side tests prove that they test the lib copies: each loaded module's `__file__` is under `lib/`, and that includes the modules `rx_column_filter_ui` pulled in.
- [ ] The test count rises by the number of reused tests, and every test passes.
- [ ] `WindowTests` (the view window) stays bundle-only and unchanged.

**Verification:** the discover command; compare the test counts before and after. `git diff --stat` shows only `tests/` changed in this task.

**Dependencies:** Task 1. **Files:** `tests/test_window_legacy.py`, `tests/test_shared_ui.py`. **Scope:** S.

### Checkpoint A (after Tasks 1–2)
- [ ] All unit tests pass. `git diff --stat` touches no file in either bundle.

### Task 3: `validate_xaml.ps1`, a WPF load check

**Description:** New `tests/validate_xaml.ps1` for Windows PowerShell 5.1. It loads `PresentationFramework`, reads `lib/rx_theme.xaml` with `-Encoding UTF8` (§6 gotcha), parses it with `XamlReader.Parse` and keeps it as a `ResourceDictionary`. It then parses every other `*.xaml` under `lib/`. When the root is a `FrameworkElement`, it merges the theme into the root's resources. Later modules extend the file list with the new button's folder.

**Acceptance criteria:**
- [ ] One `PASS <relative path>` or `FAIL <relative path>: <message>` line per file, theme first. The exit code is 0 only when every file passes.
- [ ] A deliberately broken XAML in a temp folder (passed with `-Root`, default `lib/`) gives FAIL and exit 1, proving the check can fail.
- [ ] No writes to the repo. Temp files go only to `$env:TEMP`.

**Verification:** `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\validate_xaml.ps1` → 2 PASS, exit 0; the broken-file run → FAIL, exit 1.

**Dependencies:** Task 1. **Files:** `tests/validate_xaml.ps1` (new). **Scope:** XS.

### Task 4: Docs and handover

**Description:** Add the new command to `CLAUDE.md` Commands. Add a short `lib/README.md` in English and Polish (`README.pl.md`): what `lib/` is, the `rx_` prefix rule, that the bundle copies are temporary, and the Validation lines. Update `HANDOVER.md`.

**Acceptance criteria:**
- [ ] Both READMEs state what was verified here and what was not: in Revit, only the owner's criterion 6 check counts.
- [ ] Nothing in the docs puts a Revit version into a name.

**Verification:** read-through; the unit tests still pass.

**Dependencies:** Tasks 1–3. **Files:** `lib/README.md`, `lib/README.pl.md`, `CLAUDE.md`, `HANDOVER.md`. **Scope:** S.

### Checkpoint B: done
- [ ] Spec criteria 1–5 met and evidenced (test output, `validate_xaml.ps1` output, `git diff --stat`).
- [ ] Commit and push only when the owner says so.
- [ ] Owner check in Revit 2022 after pulling (criterion 6): the old "Export setup" button still opens and searches. **Not verifiable here.**

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| The lib tests silently load the bundle copies (bare-name imports) | High: false confidence | Pin the lib modules in `sys.modules`; assert `__file__` (Task 2) |
| The refactor of `test_window_legacy.py` weakens a test | Med | Move-only diff; the count check and the same assertions |
| Git turns LF into CRLF in the copies, so the byte guard fails on another machine | Low | Compare after normalizing line endings, or check `.gitattributes` while doing Task 1, then pick one and note it |
| `lib/` on `sys.path` changes the old button's behaviour in Revit | Low | Bundle-first lookup plus the equality guard; owner check (criterion 6) |

## Open questions for the owner

None. Everything here follows the approved spec.
