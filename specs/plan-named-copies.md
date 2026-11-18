# Plan: named-copies

Implements `SPEC-named-copies.md`. Files: `lib/rx_naming.py` (new), `lib/rx_runner.py`, `lib/rx_status.py`, `lib/rx_status_ui.py`, `lib/rx_status.xaml`, `lib/rx_reader.py` (Phase 2 B), `Export.pushbutton/{rx_export_logic.py, rx_export_text.py, rx_export_ui.py, rx_export_models.xaml, script.py}`, `tests/*`, `Analyzer/scripts/probe-export-structure.mjs`, `Analyzer/tests/probe.test.mjs`.

Status 2026-11-18: written; **waiting for the owner's approval and answers to the open questions in the spec**. Task 0 (probe) is safe to start at once.

## Decisions made while planning

- **Reuse, don't rewrite:** `rx_hardlink.make_hard_link`, `rx_cloud_stage.copy_steps` (per destination folder; its `"rb"` and `O_EXCL` rules are exactly the rules needed here; its messages are replaced by our own notes), `rx_cloud.safe_file_name`, `rx_runner._short_error`, `_with_message`, and the `_cleanups` pattern.
- **The step runs in the session's `poll()`**, because only the status session is alive after the export ends. That makes it time-sliced and thread-free, the same as staging.
- **Flat `named\` and the record outside it**, so the folder can be zipped and sent as it is.
- **Phase 1 is useful on its own:** system tokens plus `OriginalName` and `ModelName` work with no value source. Phase 2 adds sheet and view parameters.
- **`PROTOCOL` 2** instead of a silent extra field, so an older live session cannot drop the template without saying so.

## Phase 1: everything that does not depend on the probe

### Task 0: Probe additions and a local run (can start at once, in parallel)
**Files:** `Analyzer/scripts/probe-export-structure.mjs`, `Analyzer/tests/probe.test.mjs`.
**Tests first:** the synthetic export gets a UniqueId-style `viewableID` equal to its `ids` entry, a DWG and an SVF view folder.
**Acceptance:**
- New `mapping` counts (still counts only, no names):
  - `viewableIdEqualsExternalId`, `viewableIdLooksLikeUniqueId`;
  - `pdfInGuidFolder`, `svfInGuidFolder`, `svfFoldersWithOneSvf`;
  - `dwgFiles`, `ifcFiles`, `f2dFiles`;
  - `dwgStemEqualsViewableName`;
  - `viewNameEqualsViewableName` (views category).
- The privacy test still passes.
- Run once on the output of `run_extractor_integration.ps1` here (Revit 2023 Extractor). The counts go into HANDOVER.
**Station:** `line-cook`. **Scope:** S.

### Task 1: Template parser, formatter, system tokens
**Files:** `lib/rx_naming.py`, `tests/test_naming.py`.
**Interface:** `TOKENS` (name → (EN label, PL label, scope)), `PRESETS`, `NamingError`, `parse_template(text)`, `format_name(parsed, values, original)`, `system_values(when, windows_user, revit_user, model_name)`, `check_naming(naming)`.
**Tests first:** spec criteria 1 and 2; `check_naming` refuses a non-dict, non-text values and a bad template, in EN and PL.
**Station:** `line-cook`. **Scope:** S.

### Task 2: Clean names, length budget, clashes (parallel with Task 1)
**Files:** `lib/rx_naming.py`, `tests/test_naming.py`.
**Interface:** `clean_name(raw)`, `fit_name(stem, ext, budget)`, `Namer` (the taken set, `unique(stem, ext, budget)`), `budgets(named_root, kind, inner_max)`.
**Tests first:** spec criterion 3, plus `clean_name` output always passes `safe_file_name` (table of 40 hostile inputs).
**Station:** `line-cook`. **Scope:** S.

### Task 3: Discovery and tying
**Files:** `lib/rx_naming.py`, `tests/test_naming.py` (synthetic trees in `%TEMP%`, repeated-digit GUIDs).
**Interface:** `discover_steps(output_dir)` (generator, one step per folder) → `[Deliverable(src, rel, kind, viewable)]`; `tie(deliverables, manifest, values)` → `[(deliverable, value_record or None)]` plus the untied count.
**Tests first:** spec criterion 4; symbolic links are skipped; nothing is opened for writing (an `open` spy).
**Station:** `line-cook`. **Scope:** M.

### Task 4: Writer and record
**Files:** `lib/rx_naming.py`, `tests/test_naming.py`.
**Interface:** `named_steps(run_paths, naming, values, started_at, link=make_hard_link, copier=copy_steps, free_space=None)`. It yields `(done, total)` and keeps `state`, `counts`, `notes` and `items` for the runner and for `<run>\named.json`.
**Tests first:**
- spec criteria 5, 6 and 8;
- a forced `link` failure copies;
- a `copier` failure fails one item;
- closing the generator early leaves only completed items and the record at `running`.
**Acceptance:** an `output\` snapshot (names, sizes, mtimes, SHA-256) is equal before and after in every test.
**Station:** `sous-chef` (file writes beside client export data; links share content). **Scope:** M.

### Checkpoint A
- [ ] All unit tests pass; `rx_naming` passes the AST and IronPython syntax guards; no old bundle touched.

### Task 5: Runner hook
**Files:** `lib/rx_runner.py`, `tests/test_runner.py`; amendment lines in `SPEC-export-runner.md`.
**Acceptance:**
- spec criterion 7;
- `Job(..., naming=None)`, `as_dict` includes the naming fields;
- `Queue(..., namer=None)` defaults to `rx_naming.named_steps`;
- `_advance_staging` returns the time it used, and naming gets the rest of the budget (at least one step);
- the result note is appended once;
- a cancelled or failed job never gets `naming_state`.
**Station:** `sous-chef` (queue state machine, budget, failure isolation). **Scope:** M. **Depends on:** Task 4.

### Task 6: Session, row and menu
**Files:** `lib/rx_status.py`, `lib/rx_status_ui.py`, `lib/rx_status.xaml`, `tests/test_status.py`; amendment lines in `SPEC-status-window.md`.
**Acceptance:**
- spec criterion 9;
- the fast tick while naming;
- `model_target`-style rule for the new menu item (an existing `named\` only, `explorer_arguments`);
- EN/PL texts in `UI_TEXT`.
**Station:** `line-cook`. **Scope:** S. **Depends on:** Task 5.

### Task 7: Setting and window field (parallel with Tasks 3–6, after Task 1)
**Files:** `rx_export_logic.py`, `rx_export_text.py`, `rx_export_ui.py`, `rx_export_models.xaml`, `tests/test_export_button.py`; amendment lines in `SPEC-export-button.md`.
**Acceptance:**
- spec criteria 10, 11 and 14;
- the preview uses only synthetic sample values;
- the setting is saved with the others (`save_settings` changes only when it differs);
- the card still fits at the window's minimum size (preview PNG).
**Station:** `line-cook` (front end; the expediter may take it). **Scope:** M.

### Task 8: Hand-over wiring
**Files:** `script.py`, `rx_export_logic.plan_jobs` / `plan_cloud_jobs` (add `naming`), `tests/test_export_button.py`.
**Acceptance:**
- `naming` is present only when the template is not empty;
- `system` holds `WindowsUser` from an injected environ, `RevitUser` from a stub `app.Username` and `ModelName` (cloud: `model_name` stem);
- the request JSON is ASCII (`dumps_ascii`);
- jobs from the view window carry it too.
**Station:** `line-cook`. **Scope:** S. **Depends on:** Tasks 6 and 7.

### Task 9: Integration mode
**Files:** `tests/runner_cli.py` (new command `name`), `tests/run_extractor_integration.ps1` (`-Named`).
**Acceptance:** spec criterion 13 on this machine; output printed as counts only; Task 0's probe output shown.
**Station:** `sous-chef`. **Scope:** S. **Depends on:** Task 5.

### Checkpoint B (milestone): Codex review `--uncommitted`, fixes, local commit
- [ ] 1–14 evidenced except the value-source parts; HANDOVER updated; review pending logged if Codex is unavailable.

## Phase 2: value source, chosen after the probe

**Gate (owner runs the extended probe on one real default-scope export and one Choose-views export):**
- **A is viable** when all of these hold:
  - `viewableIdEqualsExternalId` ≥ 95 % of `viewables`;
  - sheet elements carry non-empty `Sheet Number` and `Sheet Name` under `builtIn`, which means English attribute names;
  - `pdfInGuidFolder + pdfStemEqualsViewableName` covers the PDFs.
- **B ties** when `viewableIdLooksLikeUniqueId`, or `pdfStemEqualsNumberDashName`/`viewNameEqualsViewableName`, cover the files.

### Task 10: Source B from the model (always built)
**Files:** `lib/rx_reader.py`, `tests/test_reader.py`, `Export.pushbutton/rx_export_ui.py` (snapshot to job).
**Interface:** `collect_name_values(doc, DB, views)`, called inside `read_model(..., values=True)` before `Close(False)`.
**Tests first (stub DB):**
- every token in the table;
- a missing parameter gives `""`;
- `AsString` versus `AsValueString`;
- built-in parameters are excluded from `params`;
- title block size to ISO names and `WxH`;
- `Close(False)` is still called exactly once when a parameter read raises;
- no transaction, no `Save`.
**Acceptance:**
- each member is in the spec's API table (re-checked with `revit-api` for 2022 and 2026; members outside the table are added with hashes);
- values JSON for 3,000 synthetic views is under 4 MB;
- a job from Choose views… carries `values`.
**Station:** `sous-chef` (Revit API, background-open rules). **Scope:** M.

### Task 11a: Source A from the property database (only if the gate says viable)
**Files:** `lib/rx_naming_pdb.py` (new), `tests/test_naming_pdb.py`.
**Interface:** `pdb_value_steps(resource_dir, viewable_ids, chunk=2**20)` → generator; its final value is the values dict.
**Tests first:**
- the probe's synthetic database plus a generated one with 200,000 elements (CPython timing printed);
- strings with escapes and commas across chunk boundaries;
- a missing file gives no values and a note;
- files are opened `"rb"` only.
**Acceptance:**
- memory stays bounded (no full-array `json.loads` except `attrs`);
- each step is under 40 ms on CPython for 1 MiB chunks;
- `.NET GZipStream` fallback behind a feature check (`rx_dotnet.ensure_assemblies` adds `System.IO.Compression` on .NET 8);
- runner integration via `values=None` → A inside `named_steps`.
**Station:** `sous-chef` (performance and IronPython risk). **Scope:** L.

### Task 11b: Source B2, a pre-read for default scope (only if A is not viable and the owner wants default-scope names)
**Files:** `rx_export_ui.py`, `script.py`, tests.
**Acceptance:**
- when the template uses a sheet/view token and the scope is default, Export reads each ticked model in the background first, one at a time, with a wait line "Reading sheet and view parameters: model {0} of {1}…" (EN/PL);
- a `ReadError` queues that model without values and with a note;
- a `close_failed` stops the batch as today.
**Station:** `sous-chef`. **Scope:** M.

### Checkpoint C (milestone): Codex review, fixes, local commit.

## Phase 3: live test and docs

### Task 12: Test kit and guide
**Files:** `tests/v1_test_kit.ps1` (`-Named <run folder>`), `specs/v1-revit-test.md`, `specs/v1-revit-test.html` (Part I).
**Kit:** `-Named` prints counts only:
- items by kind, linked, copied, failed and untied;
- longest path length;
- links verified by file index;
- `output\` file count;
- `named.json` state.
**Guide entries (synthetic templates only, no model edits):**
- **I1** Template field: presets, Insert token, preview and the invalid-template error in EN and PL; remembered after a Revit restart.
- **I2** Default-scope export with `{SheetNumber}`: `named\` count equals the PDF count; sheet names are right (owner looks, sends only pass/fail); Analyzer opens `output\` as before; kit `-Named`.
- **I3** Choose views… export with `{SheetNumber} - {CurrentRevision} {param:<owner's sheet parameter>}`: values come from the model.
- **I4** `{Year}` only: clashes give ` (2)` … ` (n)`.
- **I5** A 200-character template on a deep output folder: names are cut and no path is over 259 (kit).
- **I6** A 3D view folder in `named\` holds the whole SVF subtree (kit counts equal the `output\` folder).
- **I7** A Cloud job with a template: named after the staged copies are cleaned up; cache untouched (kit `-Check`).
- **I8** (optional) Close Revit during naming: `named.json` stays `running`; the next Export is unaffected.
**Station:** `line-cook`. **Scope:** M.

### Task 13: Docs
**Acceptance:**
- `SPEC.md` capability map row `named-copies`;
- Export `README.md`/`README.pl.md` section "File names" (hard-link note included);
- `lib/README.md`/`README.pl.md` Validation lines (what ran here and on which build; what did not);
- `CLAUDE.md` part table and the `-Named` command;
- HANDOVER.
**Station:** `line-cook`. **Scope:** XS.

### Checkpoint D: done
- [ ] Everything evidenced here; Part I handed to the owner; review clean or logged as pending.

## Parallel work

- Tasks 0, 1 and 2 can start together.
- Task 3 needs Task 2. Task 4 needs Tasks 2 and 3.
- Task 7 can run alongside Tasks 3–6 once Task 1 is done.
- Task 10 can start after Checkpoint A, without waiting for the gate.
- Tasks 11a and 11b wait for the gate.

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| A hard link shares content: a named PDF edited in place changes `output\` | Med (Analyzer data) | Hint in the window and README; open question on a copy switch |
| IronPython `zlib` without gzip mode, or the regex too slow on large `vals` | High for A | Task 11a feature check, `.NET GZipStream` fallback, B as the guaranteed source |
| The Extractor's attribute names follow its language, not English | Med for A | Gate requires English built-in names; B uses `ForgeTypeId`, not names |
| Viewable ids are not UniqueIds | Med | Name ties (rule 2); untied files keep their name and are counted |
| Long outputs (100k SVF files) slow on the UI thread | Low | Shared 40 ms budget, one step per folder or file |
| Older live session at protocol 1 | Low | Protocol 2 publishes a new session; the run lock serialises Extractors |
| Copy fallback on FAT/exFAT or SMB fills the disk | Low | Free-space check before the first fallback; `partial` with a note |
