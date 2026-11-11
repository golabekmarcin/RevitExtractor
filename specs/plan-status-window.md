# Plan: status-window

Implements `SPEC-status-window.md`. Files: `lib/rx_status.py`, `lib/rx_status_ui.py`, `lib/rx_status.xaml`, `lib/rx_runner.py` (amended), `tests/test_status.py`, `tests/wpf_fakes.py`, `tests/preview_windows.ps1`, `tests/validate_xaml.ps1`, `tests/runner_cli.py`, `tests/run_extractor_integration.ps1`.

## Decisions made while planning

- **AppDomain data, not a module variable.** The old buttons run with `clean: true`, which replaces the extension's cached engine. A module-level queue would silently become two queues.
- **JSON text across the engine boundary.** An exception class or `isinstance` check from one engine does not match the other engine's copy. Text has no such problem, and the handler is testable on CPython.
- **The timer belongs to the session.** A timer owned by the window would stop the queue when the window is hidden.
- **Hide, never destroy.** A new window could not be built safely in an engine that was shut down. It also keeps Cancel reachable while a document is open.
- **The `hold` gate.** It costs a few lines and removes the worst outcome of a lost session, a launcher run or a second Revit: two Extractors on one pipe.
- **A visible console for the Analyzer.** A hidden Node process would keep a port open after Revit closes, with nothing to close it.
- **No confirmation on Cancel**, and no `forms.alert` anywhere in this module: a task dialog from a modeless window is a Revit UI call.

## Tasks

Tasks 2–5 can run in parallel after Task 1.

### Task 1: Runner amendments (test first)
**Acceptance criteria:** spec criterion 12; `clean_path` public; `extractor_running` with a stub `System.Diagnostics`; the existing runner tests unchanged and green; `SPEC-export-runner.md` interface updated.
**Verification:** discover command. **Dependencies:** none. **Station:** `sous-chef` (it decides when a process starts). **Scope:** S.

### Task 2: `progress_info`, `job_view`, `UI_TEXT`
**Acceptance criteria:** spec criteria 1 and 2. Fixture lines are copied from the Dynamo sample run, never from a client log.
**Verification:** discover command. **Dependencies:** Task 1. **Station:** `line-cook`. **Scope:** S.

### Task 3: `SessionCore`, `find_session`, `publish_session`
**Acceptance criteria:** spec criteria 3 and 4.
**Verification:** discover command. **Dependencies:** Task 1. **Station:** `sous-chef` (the engine boundary). **Scope:** S.

### Task 4: `analyzer_plan` and the thin .NET helpers
**Description:** The pure plan, plus `shell_open`, `free_port` and `node_major` in `rx_status_ui.py`, with `System` imported inside the functions.
**Acceptance criteria:** spec criterion 5; the helpers tested with stub `System` modules.
**Verification:** discover command. **Dependencies:** Task 1. **Station:** `sous-chef` (command construction). **Scope:** S.

### Task 5: Move the WPF fakes to `tests/wpf_fakes.py`
**Acceptance criteria:** a pure move; no assertion in `test_window_legacy.py` is added, removed or changed; the test count is the same before and after.
**Verification:** discover command; `git diff --stat` touches only `tests/`. **Dependencies:** none. **Station:** `line-cook`. **Scope:** S.

### Checkpoint A
- [ ] All unit tests pass; neither old bundle is touched.

### Task 6: `rx_status.xaml`, `StatusWindow`, `Session`
**Acceptance criteria:** spec criteria 6–11.
**Verification:** discover command. **Dependencies:** Tasks 2–5. **Station:** `line-cook` for the logic; the expediter may take the XAML layout (UI work, `CLAUDE.md`). **Scope:** M.

### Task 7: XAML load check and preview
**Description:** `validate_xaml.ps1` takes several roots and defaults to `lib/` plus the new button folder (missing folders are skipped until they exist). `preview_windows.ps1` renders each new window with sample rows to PNG, in English and Polish.
**Acceptance criteria:** `rx_status.xaml` PASS; a broken file still gives FAIL and exit 1; the PNGs are written only to `%TEMP%` and looked at by the expediter.
**Verification:** both scripts' output. **Dependencies:** Task 6. **Station:** `line-cook`. **Scope:** S.

### Task 8: Analyzer integration mode
**Description:** `runner_cli.py analyzer-plan` and `run_extractor_integration.ps1 -Analyzer`.
**Acceptance criteria:** spec criterion 13. If Node 24+ or the Analyzer packages are missing, the script prints SKIP with the reason and the item goes to the owner's checklist.
**Verification:** the script's output in the report. **Dependencies:** Task 4. **Station:** `sous-chef`. **Scope:** S.

### Task 9: Docs
**Acceptance criteria:** `lib/README.md` and `README.pl.md` (new files, Validation lines, what was not verified); `SPEC.md` project structure lists `rx_status.py`; the new commands in `CLAUDE.md`; `HANDOVER.md` gets the engine facts and D8–D13.
**Dependencies:** Task 8. **Station:** `line-cook`. **Scope:** XS.

### Checkpoint B: done
- [ ] Spec criteria 1–13 evidenced. Local commit.

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Calling the delegate from another IronPython engine fails in Revit | High | Text-only protocol; a failed call means a new session, and the gate keeps Extractors apart; owner's test items B6/B7 |
| An unhandled error in a timer tick reaches Revit's dispatcher | High | Every handler catches; criterion 9 |
| The window owned by Revit behaves oddly when minimised, or delays Revit's exit | Med | Owner's test; the alternative is D8's status button |
| Ticks stall during long Revit operations | Low | Stated in the spec; exports already running are not affected |
| A stale `RevitExtractor.exe` holds the queue for ever | Low | The row says why; queued jobs can be cancelled; we never end foreign processes |
| pyRevit changes its engine handling in a later version | Med | The design depends only on AppDomain data and .NET delegates |

## Open questions

Batched owner list in `HANDOVER.md`: D8 (reaching the status window with a document open), D9 (fallback website), D10 (Analyzer console window), D13 (waiting for a foreign Extractor).
