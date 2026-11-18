# Plan: cloud-catalog

Implements `SPEC-cloud-catalog.md`. Files: `lib/rx_cloud.py`, `lib/rx_cloud_stage.py`, amendments to `lib/rx_reader.py`, `lib/rx_runner.py`, `lib/rx_status*.py` and `Export.pushbutton/*`, the new `RememberCloudModel.pushbutton/`, `tests/test_cloud*.py`, `tests/fixtures/cloud/`, docs.

## Decisions made while planning

- **Journals and cache are joined only by GUID pair.** File names in the cache are never parsed for meaning.
- **Name memory in the profile.** Journals get cleaned up and the fallback command needs somewhere to write, so one `cloud-catalog.json` keeps selection, names and link lists.
- **Links come from a background open of the cached host**, remembered per cache date. The journals do not record which links a host has, and copying a whole project (about 300 files) is too much.
- **The copy happens in the runner, not in the modal window.** Gigabytes in a modal window would freeze Revit. A time-sliced `staging` state keeps the no-threads rule.
- **A flat staging folder**, because that layout passed the cache-copy test (archive section 2).
- **A separate fallback button.** The Export button is disabled while a document is open, so it cannot read one.
- IronPython 2.7: `io.open`, `os.walk`, `json`, and a `urllib.unquote` / `urllib.parse.unquote` shim; no `os.replace`.

## Tasks

Tasks 1–3 run in parallel. Tasks 5 and 6 run in parallel with Task 4. Task 7 follows Task 6. Task 8 follows Tasks 4, 5 and 7.

### Task 0: API facts (no code)
**Acceptance criteria:** every row of the spec's "to verify" table gets a `revit-api` answer for 2022 and 2026, recorded in the spec with its hash, or marked undocumented.
**Station:** `line-cook`. **Scope:** XS.

### Task 1: Journal parser (test first)
**Acceptance criteria:** spec criteria 1–2; synthetic fixtures `tests/fixtures/cloud/journal-*.txt` (UTF-8, UTF-16, cp1250); privacy guard (criterion 13).
**Verification:** discover command. **Dependencies:** none. **Station:** `line-cook`. **Scope:** S.

### Task 2: Cache scanner
**Acceptance criteria:** spec criterion 3, with temp trees built by the test.
**Verification:** discover command. **Dependencies:** none. **Station:** `line-cook`. **Scope:** S.

### Task 3: Memory (selection, names, links)
**Acceptance criteria:** spec criterion 5; folder created when missing; a failed save is reported, not raised.
**Verification:** discover command. **Dependencies:** none. **Station:** `line-cook`. **Scope:** S.

### Task 4: Matcher, states, notes and the time-sliced `scan`
**Acceptance criteria:** spec criterion 4; every note in English and Polish; `scan` yields one step per journal chunk or cache folder; a timing test (100 synthetic 1 MB journals plus 1,000 cache files) is reported.
**Verification:** discover command. **Dependencies:** Tasks 1–3. **Station:** `line-cook`. **Scope:** S.

### Checkpoint A
- [ ] Pure modules done; all unit tests pass; AST purity holds.

### Task 5: Link reader in `rx_reader`
**Acceptance criteria:** spec criterion 8; the probe's link-reading tests ported; the legacy probe untouched.
**Dependencies:** Task 0. **Station:** `sous-chef` (it opens client models). **Scope:** S.

### Task 6: `plan_stage`, `copy_steps`, `check_space`
**Acceptance criteria:** spec criteria 6–7; a test proves that no code path opens a source for writing.
**Dependencies:** Tasks 2–3. **Station:** `sous-chef` (the cache-never-written rule). **Scope:** M.

### Task 7: Runner and status-window amendments
**Acceptance criteria:** spec criterion 9; `staging` label and progress in both languages; `SPEC-export-runner.md` and `SPEC-status-window.md` amended (including the cleanup boundary once the owner decides).
**Dependencies:** Task 6. **Station:** `sous-chef` (queue state machine). **Scope:** M.

### Checkpoint B
- [ ] Unit tests pass; `run_extractor_integration.ps1` normal and `-Cancel` still PASS.

### Task 8: Export window integration
**Description:** `rx_export_logic.plan_cloud_jobs`; `UI_TEXT` keys; a Cloud tab and projects card in `rx_export_models.xaml`; `ModelWindow(cloud=...)`; kept jobs keyed by `CloudRow.key`; `script.py` wiring (`revit_folders`, `Memory`, `read(..., links=True)`, `_hand_over` passes `stage` and `model_name`).
**Acceptance criteria:** spec criteria 10 and 12; `validate_xaml.ps1` PASS; `preview_windows.ps1` renders the Cloud tab in EN and PL.
**Dependencies:** Tasks 4, 5, 7. **Station:** `line-cook`; the expediter takes the XAML. **Scope:** M.

### Task 9: `RememberCloudModel.pushbutton`
**Acceptance criteria:** spec criterion 11; `bundle.yaml` with `en_us`/`pl`, `min_revit_version: 2022`, context `doc-project`; README EN/PL.
**Dependencies:** Tasks 3, 5; owner question 5. **Station:** `line-cook`, reviewed by `sous-chef`. **Scope:** S.

### Task 10: Integration and kit
**Acceptance criteria:** spec criterion 14 (`-Cloud`); `v1_test_kit.ps1 -Check` prints cloud counts only (journals found, named models, unnamed files, cache folder present).
**Dependencies:** Task 7. **Station:** `line-cook`. **Scope:** S.

### Task 11: Review and docs
**Description:** Codex review of the module diff (milestone). Then: `lib/README.md`/`.pl.md`, the Export README EN/PL, `Setup.panel/README.md`; the `CLAUDE.md` parts table and commands; `SPEC.md` map (depends on `export-runner` too); `HANDOVER.md` (replace "Stale warning shows both dates" with the cache-date rule; add the open questions); checklist Part H in `specs/v1-revit-test.md` and `.html`; `.gitignore` gets `cloud-catalog*.json`.
**Acceptance criteria:** review findings fixed or listed; every doc says what was not run in Revit.
**Dependencies:** Tasks 8–10. **Station:** `line-cook`. **Scope:** S.

### Checkpoint C
- [ ] All checks pass, review clean, local commit. Push only with the end-of-v1 push.

## Owner's Revit 2022 session (ACC model, 28 links): Part H

H1 journals found and names right (Polish and `%20` names); H2 the current-session journal is readable; H3 background open of a cache host lists 28 links and the cache file's `-Stamp` is unchanged; H4 staged export gives `Success Jobs` with `Failed Jobs: 0`, and links appear in a federated 3D view; H5 copy time and whether Revit stays usable; H6 the fallback button; H7 disk use and cleanup.

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Revit refuses, or connects to the cloud, when opening a cache file by path | High | H3 first; fallback: stage the host, then open the copy, or links only from the fallback button |
| Journal lines differ after 2022 | Med | Tolerant parser, memory, message plus fallback |
| Journals saved as ANSI garble Polish names | Med | Decode ladder; check in H1 |
| Staged copies fill the disk | High | Free-space check; cleanup (question 1) |
| The time-sliced copy slows Revit | Med | 40 ms budget, tunable chunk size; H5 |
| The root copy holds unsynced local edits, or is older than `CentralCache` | Med | Newer-of rule, cache date shown; question 6 |
| Client names leak through fixtures, logs or the kit | High | Synthetic-GUID guard test; counts-only output |

## Open questions (**all defaults in brackets accepted by the owner, 2026-11-16**; question 4 and 7 stay "verify in Part H")

1. Remove staged copies after the run? This amends the run-folder boundary [yes, keep `stage.json`].
2. Stale threshold [7 days, note only, never blocks].
3. Projects ticked by default [none].
4. Folder selection: does the browser JSON carry a folder field? H1 lists the keys only [project only in v1].
5. Add the fallback button [yes].
6. Which copy: root, `LinkedModels` or `CentralCache` [newer of root and `LinkedModels`; changed 2026-11-19 by the owner for the host row: the root file whenever one exists (Revit opens it in place, and it is the staged host), `LinkedModels` only when no root copy exists; links keep the newer-of rule; `CentralCache` never].
7. Can the journal or cache folder be moved through `Revit.ini` or Options? [fixed paths; `-Check` reports whether they exist].
8. Missing link: warn or fail [warn and export].
