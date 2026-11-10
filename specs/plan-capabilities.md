# Plan: capabilities

Implements `SPEC-capabilities.md` (approved 2026-11-10). Status: **draft, waiting for owner approval.**

## Overview

A new pure-Python module, `lib/rx_capabilities.py`, holds the Revit-year table (`for_revit`), the read-only record it returns, `UnsupportedRevit`, and a copy of `element_id_value`. No button uses it yet. `index-builder` and `model-reader` adopt it later.

## Decisions made while planning

- **The record is a `namedtuple` subclass**, which makes it read-only and works the same on IronPython 2.7 and CPython 3. Its fields: `year`, `verified`, `view_key`, `formats`, `ifc_setups`, `extended_properties`, `topology_metadata`. `label` is a property, so it is translated when it is read and follows pyRevit's language at that moment.
- **The table is data:** a list of `(first_year, values)` rows, sorted. `for_revit` takes the last row whose `first_year <= year`. Years above the newest row get that row with `verified = False`. A new Revit version means adding one row.
- **Input parsing**, on both engines:
  - `bool` is rejected before the integer check (`True` is an `int`);
  - accepted: `int`, plus `long` on IronPython, and strings that are digits after `strip()`;
  - everything else raises `UnsupportedRevit`, including `"2022.1"`, `""`, `None` and `"abc"`.
  - The message says what was received and the floor, in English and Polish.
- **`element_id_value` is copied, not moved.** Spec criterion 6 says the old buttons don't change, so `ExportSetupLegacy/extractor_model.py` keeps its own copy until the old buttons are deleted. The copy keeps the RevitRAG note. The 2022 + 2026 docs check was already done (`CLAUDE.md`), and Task 2 re-runs it for 2022 and 2026 with the `revit-api` skill before the code is written.
- **Import guard:** the test parses the file with `ast` and fails on any `import`/`from` of `pyrevit`, `Autodesk`, `System` or `clr`. The one allowed import is `rx_i18n`, which only imports pyRevit lazily inside `tr`.
- **Dependency:** this module needs `lib/rx_i18n.py` from shared-ui Task 1. Build it after that task; the rest is independent of shared-ui.

## Tasks

### Task 1: The table and `for_revit` (test first)

**Description:** `tests/test_capabilities.py` covers spec criteria 1, 2 and 5. Write it first and watch it fail, then write `lib/rx_capabilities.py`.

**Acceptance criteria:**
- [ ] For 2022, 2023, 2024 and 2025: `view_ids`, `formats == ()`, no IFC setups, no extended properties or topology, `verified` True.
- [ ] For 2026: `view_unique_ids`, `("dwg", "ifc")`, IFC setups, extended properties and topology all True.
- [ ] For 2027 and 2030: the 2026 values with `verified` False and `year` equal to the input year.
- [ ] `"2022"`, `2022` and `" 2022 "` all give `year == 2022`. `2021`, `""`, `None`, `"abc"`, `"2022.1"` and `True` each raise `UnsupportedRevit`, a `ValueError` subclass.
- [ ] Assigning a field raises (the record is read-only).
- [ ] The import guard passes.

**Verification:** the discover command (`python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v`).

**Dependencies:** shared-ui Task 1 (`lib/rx_i18n.py`). **Files:** `lib/rx_capabilities.py`, `tests/test_capabilities.py`. **Scope:** S.

### Task 2: `element_id_value`

**Description:** Re-check `ElementId.Value` and `ElementId.IntegerValue` with `revit-api` for 2022 and 2026, then copy the function in and add its tests (spec criterion 3).

**Acceptance criteria:**
- [ ] Stub with only `IntegerValue` → that value. Stub with only `Value` (`2**40`) → that value.
- [ ] Stub with both, where `IntegerValue` is a property that raises when read → returns `Value`, proving `IntegerValue` is never read.
- [ ] The docstring cites the documented ranges from the re-check.

**Verification:** the discover command; the `revit-api` result is recorded in the commit message.

**Dependencies:** Task 1. **Files:** same two. **Scope:** XS.

### Task 3: English/Polish label and message

**Description:** `caps.label` and the `UnsupportedRevit` text via `tr` (spec criterion 4). The test uses the same Polish stub as `test_window_legacy.polish()`.

**Acceptance criteria:**
- [ ] Each label and the error message have an English and a Polish form, and the Polish form appears when the stub says Polish.
- [ ] The wording is decided by the owner (open question 1). The test checks for the agreed text.

**Verification:** the discover command.

**Dependencies:** Task 1; open question 1 answered. **Files:** same two. **Scope:** XS.

### Checkpoint: done
- [ ] Spec criteria 1–6 met. All unit tests pass (108 + shared-ui + these).
- [ ] `git diff --stat` touches no bundle (criterion 6).
- [ ] `HANDOVER.md` updated. Commit and push only when the owner says so.
- [ ] No Revit-side check for this module (spec). Its effect is verified later through `index-builder` and `export-button`.

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| The 2026 row is wrong (it comes from the original author's button, and there is no Revit 2026 to test on) | Med, later | The label shows what was tested (question 1); the native parser check runs in `index-builder` |
| `long` vs `int` or `unicode` vs `str` differences on IronPython | Low | Explicit `try: long` / `text` shims as in `extractor_model.py`; review against the IronPython 2.7 rules in `CLAUDE.md` |

## Open questions for the owner

1. **Resolved 2026-11-10 (owner): add `tested`.**
   - `tested` = the owner has tested that year in Revit with pyRevit.
   - Today only **2022** counts. The owner's other machine has Revit 2022 and 2025, so **2025 switches to `tested = True` after the owner's test**, with the evidence recorded.
   - 2023 has only the native parser check on the main machine, which is not a test in Revit, so it stays untested. So do 2024 and 2026.
   - Labels:

     | Case | English | Polish |
     | --- | --- | --- |
     | tested year | "Revit 2022" | "Revit 2022" |
     | untested year that has its own row | "Revit 2024 (not tested yet)" | "Revit 2024 (jeszcze nie testowane)" |
     | year above the newest row | "Revit 2027 (untested, treated as 2026)" | "Revit 2027 (nietestowane, traktowane jak 2026)" |

   The original proposal follows, for the record.

   **Label wording for 2026.** The spec sets `verified = False` only for years above the newest row, so 2026 comes back `verified = True`. But 2026 has **never been tested** on any of our machines. A label like "Revit 2026 (verified)" would be wrong. Proposal:
   - **2022–2025:** "Revit 2022" (EN) / "Revit 2022" (PL), with no suffix.
   - **2026:** "Revit 2026 (not tested yet)" / "Revit 2026 (jeszcze nie testowane)".
   - **2027+:** "Revit 2027 (untested, treated as 2026)" / "Revit 2027 (nietestowane, traktowane jak 2026)".

   To support this, the record gets a separate `tested` field next to `verified`. `verified` keeps the spec's meaning ("has its own row"), and `tested` is True only for 2022–2025. Alternatively, keep the spec as written and drop the suffix for 2026. **Which do you want?**
