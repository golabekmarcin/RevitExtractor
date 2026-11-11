# Plan: export-button

Implements `SPEC-export-button.md`. Starts after `status-window` Checkpoint B. Files: `Export.pushbutton/*`, `lib/rx_catalog.py` (one field), `tests/test_export_button.py`, `tests/v1_test_kit.ps1`, `specs/v1-revit-test.md`, docs.

## Decisions made while planning

- **Two modal windows, the second opened from the first.** Back returns to the model list with its state. The view window is slice 1 with a different footer, so its verified behaviour and its tests carry over.
- **Export and Choose views… are separate buttons.** Default-scope export of one model needs no background open, and a batch is the same Export with more ticks.
- **Save index.json… stays** (D12). The shared-index batch needs a way to make that file, and so does the `.ps1` fallback once the old buttons are gone.
- **`read` and `read_info` are passed in by `script.py`.** The UI module imports no Revit, and the window tests can prove that nothing else opens a model.
- **Unique module names.** A shared engine may already hold the old bundle's `extractor_*` modules.
- **A named config section**, not pyRevit's default (command name + `_config`), so a renamed button keeps its settings.
- **A test kit script.** The owner's effort is the scarce thing: one command builds the test folder and one prints what to send back.

## Tasks

Tasks 1–3 can run in parallel. Tasks 4 and 5 can run in parallel after them.

### Task 1: `Row.workshared` in `rx_catalog` (test first)
**Acceptance criteria:** spec criterion 13; `SPEC-model-catalog.md` interface line updated.
**Verification:** discover command. **Dependencies:** none. **Station:** `line-cook`. **Scope:** XS.

### Task 2: Settings and tick helpers in `rx_export_logic.py`
**Acceptance criteria:** spec criteria 3 and 10.
**Verification:** discover command. **Dependencies:** none. **Station:** `line-cook`. **Scope:** S.

### Task 3: Shared index and `plan_jobs`
**Acceptance criteria:** spec criteria 4 and 5.
**Verification:** discover command. **Dependencies:** none. **Station:** `line-cook`. **Scope:** S.

### Checkpoint A
- [ ] All unit tests pass; pure logic only so far.

### Task 4: Model window
**Description:** `rx_export_text.py`, `rx_export_models.xaml`, `ModelWindow` with the scan timer, roots, output folder, scope and footer.
**Acceptance criteria:** spec criteria 6, 7 and the model-window half of 11.
**Verification:** discover command; `validate_xaml.ps1`. **Dependencies:** Tasks 1–3. **Station:** `line-cook`; the expediter may take the XAML layout. **Scope:** M.

### Task 5: View window
**Description:** Port `ui.xaml` and `ExportSetupWindow` to `rx_export_views.xaml` and `ViewWindow`; turn the slice 1 window tests into a mixin.
**Acceptance criteria:** spec criterion 8 and the view-window half of 11; `test_window_legacy.py` keeps its assertions.
**Verification:** discover command; `validate_xaml.ps1`. **Dependencies:** Tasks 2–3. **Station:** `line-cook`. **Scope:** M.

### Task 6: `script.py` and `bundle.yaml`
**Description:** The guards, the `read` wiring and the hand-over to the session.
**Acceptance criteria:** spec criteria 1, 2 and 9.
**Verification:** discover command. **Dependencies:** Tasks 4–5. **Station:** `sous-chef` (the guard and the read protect the user's open work). **Scope:** S.

### Task 7: Guards across the bundle, and the preview
**Acceptance criteria:** spec criteria 12, 14 and 15; the expediter looks at the four PNGs (two windows, two languages) plus the status window's.
**Verification:** discover command; both scripts. **Dependencies:** Task 6. **Station:** `line-cook`. **Scope:** S.

### Checkpoint B
- [ ] Unit tests, `validate_xaml.ps1`, `validate_native_legacy.ps1` and `run_extractor_integration.ps1` (normal, `-Cancel`, `-Analyzer`) all pass on this machine.

### Task 8: Review
**Description:** One review of both modules' diff: IronPython 2.7 traps the guard cannot see (`str` and `unicode`, `.NET` bool identity, dict order, `except` clauses that span engines), every `Close`, every process start.
**Acceptance criteria:** findings fixed or listed in `HANDOVER.md`.
**Dependencies:** Checkpoint B. **Station:** `sous-chef`. **Scope:** S.

### Task 9: Test kit, checklist and docs
**Description:** `tests/v1_test_kit.ps1` (Windows PowerShell 5.1, `-Encoding UTF8`); the final `specs/v1-revit-test.md`; the button's README in English and Polish; `Setup.panel/README.md`; `lib/README.md` and `README.pl.md`; `CLAUDE.md` (parts table, coverage, commands); `HANDOVER.md`.
**Acceptance criteria:** `-Setup` run here builds the folder from two Dynamo or Revit samples; `-Check` run on an integration run folder prints the result lines and no path; every doc says what was not verified.
**Dependencies:** Task 8. **Station:** `line-cook`. **Scope:** S.

### Checkpoint C: v1 ready for the owner
- [ ] Local commit. One push of `mgo-changes`, then the checklist goes to the owner (working mode, `HANDOVER.md`).
- [ ] After the owner's results: the README Validation sections, `TESTED_YEARS`, `PARALLEL_VERIFIED`, and the question about deleting the old buttons (Q12).

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| A Python 3 habit breaks import under IronPython, and the single test fails at the first click | High | Syntax guard on every file; review Task 8; the checklist starts with the click, so a failure costs minutes, not the session |
| `BasicFileInfo.Extract` from a timer tick inside the modal window is refused by Revit | Med | Owner's item A5; the fallback is one blocking scan with a wait line |
| The background open shows dialogs or takes minutes | Med | Wait line before the call; times recorded; the reserved event members of `SPEC-model-reader.md` |
| The context rule does not grey the button | Low | The run-time guard is independent of it |
| A workshared central goes straight to the Extractor | Med | Owner's item C5; if the central changes, export a copy (new decision) |
| An old button's click between two exports confuses the user (two "Export" entries on the ribbon) | Low | Tooltips say which is which; Q12 removes the old ones |

## Open questions

Batched owner list in `HANDOVER.md`: D11 (shared index with view ids), D12 (Save index.json… kept).
