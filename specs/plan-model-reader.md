# Plan: model-reader

Implements `SPEC-model-reader.md`. One file pair: `lib/rx_reader.py`, `tests/test_reader.py`.

## Decisions made while planning

- **`app` and `DB` are parameters.** `lib/` imports no Revit module; the strict stubs double as the list of API members allowed.
- **Refuse unless no document is open.** It repeats the button's zero-doc rule (Q26) at the lowest level, where a mistake would cost a user's unsaved work.
- **The catalog's `IsWorkshared` picks the options.** Detach options are documented for workset-enabled documents; whether Revit accepts them on a plain file is not documented, so a plain file gets plain options. The owner's test covers both kinds.
- **`element_id_value` comes from `rx_capabilities`**; no third copy.
- **The IFC list is the last task and separable.** No machine can test it in Revit.

## Tasks

### Task 1: `VIEW_KINDS` and `collect_views` (test first)
**Acceptance criteria:** spec criteria 1 and 10.
**Verification:** discover command. **Dependencies:** `rx_capabilities`, `rx_i18n`. **Station:** `line-cook`. **Scope:** S.

### Task 2: `open_options` and `read_model`, happy path with strict stubs
**Acceptance criteria:** spec criteria 2, 3, 4 and 8.
**Verification:** discover command. **Dependencies:** Task 1. **Station:** `sous-chef` (a wrong close loses user data). **Scope:** S.

### Task 3: Guards and errors
**Acceptance criteria:** spec criteria 5, 6 and 7. The exception-name table is built from the documented list of `OpenDocumentFile(ModelPath, OpenOptions)`.
**Verification:** discover command. **Dependencies:** Task 2. **Station:** `sous-chef`. **Scope:** S.

### Checkpoint A
- [ ] All unit tests pass. A review confirms: no path reaches `Close` with anything but `False`, and no document other than the one just opened is closed.

### Task 4: IFC setup names (newest row only)
**Description:** Check `Entity.Get` with `revit-api` for 2026, then port the read part of `_records` and its name validation. `System` imports stay inside the function.
**Acceptance criteria:** spec criterion 9; the cases of `test_ifc_storage.py` that concern reading pass against the port.
**Verification:** discover command. **Dependencies:** Task 3. **Station:** `line-cook`. **Scope:** S.

### Task 5: Docs
**Acceptance criteria:** `lib/README.md` and `README.pl.md` state that no real open was verified and list the owner's checks. `HANDOVER.md` updated.
**Dependencies:** Task 4. **Station:** `line-cook`. **Scope:** XS.

### Checkpoint B: done
- [ ] Spec criteria 1–10 evidenced; no bundle touched. Local commit.

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Revit shows a dialog during a background open (missing links, upgrade) | Med | Owner's test; the two event members are checked and ready |
| Opening a large or older model takes minutes and blocks Revit | Med | It is a deliberate, single open with a wait message from `export-button`; time recorded in the test |
| `Close(False)` leaves a document open | Med | The False return is reported; the next run's guard catches it |
| The stubs pass but IronPython behaves differently (enum access, overload choice) | Med | Owner's test; the two-argument overload is called with typed arguments only |
| The IFC list is wrong on Revit 2026 | Low now | Separable task; labelled untested |

## Open questions

Batched owner list in `HANDOVER.md`: the IFC setup list in v1.
