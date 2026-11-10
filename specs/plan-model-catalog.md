# Plan: model-catalog

Implements `SPEC-model-catalog.md`. One file pair: `lib/rx_catalog.py`, `tests/test_catalog.py`.

## Decisions made while planning

- **`BasicFileInfo` is a parameter**, so `lib/` never imports Revit and CPython can test the wrapper with a stub.
- **The backup rule needs the sibling file**, because a real model can be named `<something>.2024.rvt`. `os.walk` already gives the folder's file names, so the check is free.
- **The cache stores facts about the file, not about the running Revit.** `classify` runs on every scan.
- **Plain data only leaves `read_basic_info`** (text, bool). No API object is kept.
- IronPython 2.7: `os.walk`, `os.stat`, `io.open` and `json` only; text paths; no `pathlib`, no `os.replace`, no `os.scandir`.

## Tasks

### Task 1: File iteration and skip rules (test first)
**Acceptance criteria:** spec criterion 1; `normalize_roots` cases (blank, duplicate by case, trailing slash, nested).
**Verification:** discover command. **Dependencies:** none. **Station:** `line-cook`. **Scope:** S.

### Task 2: `classify`, `Row`, notes
**Acceptance criteria:** spec criteria 2 and 3.
**Verification:** discover command. **Dependencies:** `rx_i18n`. **Station:** `line-cook`. **Scope:** S.

### Task 3: Cache
**Acceptance criteria:** spec criterion 4; the save goes through a temporary file in the same folder; the folder is created when missing; a failed save is reported to the caller and does not break the scan.
**Verification:** discover command. **Dependencies:** none. **Station:** `line-cook`. **Scope:** S.

### Task 4: `scan` and `read_basic_info`
**Acceptance criteria:** spec criteria 5–8.
**Verification:** discover command; the timing result is reported. **Dependencies:** Tasks 1–3. **Station:** `line-cook`. **Scope:** S.

### Task 5: Docs
**Acceptance criteria:** `lib/README.md` and `README.pl.md` get the module, the cache location and its privacy note, and Validation lines that say `Extract` was never run here. `HANDOVER.md` updated.
**Dependencies:** Task 4. **Station:** `line-cook`. **Scope:** XS.

### Checkpoint: done
- [ ] Spec criteria 1–8 evidenced; all unit tests pass; no bundle touched. Local commit.

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| `Extract` is slow on a network share | Med | Cache; progressive rows; the owner's test records the cold time |
| `Extract` behaves differently for newer files than documented | Med | Three inputs decide (year, flag, error), and `unknown` is a safe greyed state; owner checks with a real newer file |
| A huge root (a whole drive) | Low | Generator: the window can stop the scan at any time |
| The cache leaks client paths | Med | It lives outside the repo; nothing logs its content |

## Open questions

Batched owner list in `HANDOVER.md`: speed target, cache location, the meaning of "server" models, unknown-version rows.
