# Plan: index-builder

Implements `SPEC-index-builder.md`. Baseline: 153 unit tests OK, native parser 9/9 PASS.

## Overview

A new pure module `lib/rx_index.py`, proven equal to both old builders by a parity test matrix and by the native parser. One small amendment to `rx_capabilities` comes first.

## Decisions made while planning

- **Parity by execution, not by reading.** The tests import the old builders and compare results case by case, so a drift in either direction fails.
- **One code path, row flags.** `build_index` branches on `caps.view_key`, `caps.formats`, `caps.extended_properties`, `caps.topology_metadata` and `caps.db_export_key`. No year comparison outside `rx_capabilities`.
- **Insert keys in the same order as the old builders**, so the `to_json` text matches on CPython.
- **Old messages are kept word for word**, including "(Revit 2022-2025)" inside the legacy texts. That is descriptive text, not a name.

## Tasks

### Task 1: `db_export_key` in `rx_capabilities`

**Acceptance criteria:**
- [ ] Rows: 2022–2025 True; 2026 and later False. Record field added; existing tests still pass; new assertions added.
- [ ] `SPEC-capabilities.md`: interface line added and the "property database switch" bullet corrected.

**Verification:** discover command. **Dependencies:** none. **Station:** `line-cook`. **Files:** `lib/rx_capabilities.py`, `tests/test_capabilities.py`, `specs/SPEC-capabilities.md`. **Scope:** XS.

### Task 2: Rows with `view_ids` (test first)

**Description:** Write the parity matrix against the legacy builder, watch it fail, then write `build_index`, `defaults`, `to_json`, `database_warning`, `SetupError`.

**Acceptance criteria:**
- [ ] Spec criteria 1 and 6, for `caps` 2022–2025, English and Polish.
- [ ] Import guard (criterion 8).

**Verification:** discover command; the new test count is reported. **Dependencies:** Task 1. **Station:** `line-cook`. **Files:** `lib/rx_index.py`, `tests/test_index.py`. **Scope:** M.

### Task 3: Newest row

**Acceptance criteria:**
- [ ] Spec criteria 2 and 3 (`caps` 2026 and 2027).
- [ ] The legacy parity from Task 2 still passes unchanged.

**Verification:** discover command. **Dependencies:** Task 2. **Station:** `line-cook`. **Files:** same two. **Scope:** S.

### Task 4: Launcher default and `require_index_shape`

**Acceptance criteria:**
- [ ] Spec criteria 4 and 7. The test extracts the here-string from `Start-RevitExport.ps1` (read with UTF-8) and does not copy it.

**Verification:** discover command. **Dependencies:** Task 3. **Station:** `line-cook`. **Files:** same two. **Scope:** XS.

### Checkpoint A
- [ ] All unit tests pass. `git diff --stat` touches no bundle and not `Start-RevitExport.ps1`.

### Task 5: Native parser check

**Description:** Extend `validate_native_legacy.ps1` as the spec's Testing section says. Keep the `[string]` casts and the UTF-8 rules (`HANDOVER.md` §6).

**Acceptance criteria:**
- [ ] Nine legacy profiles: bundle and lib compared, lib result parsed: 9 PASS here.
- [ ] Newest-row set: compared, parsed, each line PASS or SKIP with its reason. No silent pass.
- [ ] A deliberately different lib result (temporary edit, not committed) makes the script fail, proving the comparison works.

**Verification:** the script's output, pasted into the report. **Dependencies:** Task 3. **Station:** `line-cook`. **Files:** `tests/validate_native_legacy.ps1`. **Scope:** S.

### Task 6: Docs

**Acceptance criteria:**
- [ ] `lib/README.md` and `README.pl.md`: the module and its Validation lines, stating what was not verified (2026 row in Revit, `view_unique_ids` natively, the 2025.3 parser shape until the owner's run).
- [ ] `HANDOVER.md` updated.

**Dependencies:** Task 5. **Station:** `line-cook`. **Scope:** XS.

### Checkpoint B: done
- [ ] Spec criteria 1–10 evidenced. Local commit (owner's working mode 2026-11-10).

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| The 2026 row is correct only by parity with the original author's button | Med, later | Parity tests; label stays "not tested yet"; the SKIP lines state what is unproven |
| IronPython dict order differs from CPython | Low | Parity is on content; the parser ignores key order |
| The parity tests die when the old buttons are deleted (Q12) | Low | Before deleting, freeze the matrix results as literal expectations (a task of that later change) |

## Open questions

None. See the batched owner list in `HANDOVER.md`.
