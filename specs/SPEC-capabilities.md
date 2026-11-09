# Spec: capabilities

Module of `SPEC.md`. Depends on: nothing. Status: **approved by the owner 2026-11-10**.

## Objective

One place that answers "what does the Revit I am running in support?". Today that knowledge is split across two button folders (owner clarification: *one code base, no per-version files*). Other modules ask this table instead of checking years themselves. A new Revit version means a new table row, not new files.

## Interface (`lib/rx_capabilities.py`, pure Python, no Revit import)

```python
caps = for_revit("2022")          # VersionNumber string or int from the running Revit
caps.year                          # 2022
caps.verified                      # False for years newer than the newest row
caps.view_key                      # "view_ids" or "view_unique_ids"
caps.formats                       # () or ("dwg", "ifc")
caps.ifc_setups                    # bool: existing IFC export setups can be picked (Q22)
caps.extended_properties           # bool
caps.topology_metadata             # bool
caps.label                         # human text for the window, e.g. "Revit 2022 (verified)"

element_id_value(element_id)       # int: ElementId.Value if present, else IntegerValue
UnsupportedRevit                   # raised for years below the floor or unreadable input
```

`caps` is a read-only record. The view-id limits that `index-builder` enforces (numeric, 1…2147483647 for `view_ids`) live in `index-builder`, which owns the index format. `capabilities` only says which key applies.

## The table

| Revit years | `view_key` | `formats` | `ifc_setups` | extended props / topology | Evidence |
| --- | --- | --- | --- | --- | --- |
| below 2022 | — | — | — | — | `UnsupportedRevit` (floor decided 2026-11-09) |
| 2022–2025 | `view_ids` (numeric) | none | no | no | owner's Revit 2022 (9/9 parser, slice 1 test); Revit 2023 parser here; `VERIFICATION-2023.md` |
| 2026 | `view_unique_ids` | `dwg`, `ifc` | yes | yes | the original author's 2026 button; **not verified here** (no Revit 2026 on any test machine) |
| 2027+ | as the newest row | as the newest row | as the newest row | as the newest row | `verified = False`; the window shows that the version is untested |

- The 2022–2025 row keeps today's legacy behaviour exactly, including "no IFC/DWG on purpose".
- The property database switch is **not** a table entry. `index-builder` always writes a form that both parser shapes read (`properties_data.pdb`, plus `3dviewing.db_export: false` when the database is off), as today. The parser shape follows the Extractor build, not the Revit year (`CLAUDE.md`), so a year-keyed table couldn't decide it anyway.
- `element_id_value` is a feature check, not a table entry: `ElementId.Value` is documented 2024–2026 and `IntegerValue` 2022–2025.3 (RevitRAG). This is the existing function, moved.

## Acceptance criteria

1. `for_revit` returns the rows above for 2022, 2023, 2024, 2025 and 2026, and the newest row with `verified = False` for 2027 and 2030.
2. `for_revit` accepts `"2022"`, `2022` and `" 2022 "`, and raises `UnsupportedRevit` for 2021, `""`, `None`, `"abc"`, `"2022.1"` and `True`.
3. `element_id_value` returns `Value` when present, otherwise `IntegerValue`, and never reads `IntegerValue` when `Value` exists (stub objects with only one of the two, and with both).
4. `caps.label` and the `UnsupportedRevit` message exist in English and Polish (`tr`).
5. Nothing in `lib/rx_capabilities.py` imports `pyrevit`, `Autodesk` or `System`. A test enforces this.
6. No behaviour change for any user yet. The old buttons don't use the module; `index-builder` and `model-reader` adopt it in their own modules.

## Commands

```powershell
python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v
```

## Testing

- New `tests/test_capabilities.py` covers every acceptance criterion, with plain stub objects for `ElementId`.
- No Revit-side check is needed for this module alone. Its effect is verified through `index-builder` (native parser) and `export-button` (owner, Revit 2022).

## Boundaries

- Add a row only with evidence (a verification record or the owner's test), or mark it `verified = False`.
- Never key behaviour on the Extractor build here. If a build-dependent difference appears, `index-builder` handles it by writing a form both builds read.
