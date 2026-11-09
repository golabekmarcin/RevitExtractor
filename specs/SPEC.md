# Spec: one-button export (pyRevit)

Status: **capability map approved by the owner 2026-11-10**. Module specs are written and approved one by one, in build order.
Decisions referenced as Q1–Q29 are in `HANDOVER.md` §4.

All spec and plan files for this work live in this folder (`specs/`). This replaces the skill default `tasks/`:

| File | Content |
| --- | --- |
| `SPEC.md` | This file: objective, capability map, rules shared by every module, v1 success criteria |
| `SPEC-<module id>.md` | One spec per module, named by the module id in the map |
| `plan-<module id>.md` | Implementation plan and task list for that module, written after its spec is approved |

## Objective

Run the whole export from Revit through **one pyRevit button**, with no PowerShell for the user (Q1).
- The user is a BIM coordinator with Revit 2022+ and pyRevit, working on local, server and ACC models.
- Today they need two buttons (one for Revit 2022–2025, one for 2026+) to write an `index.json`, then the PowerShell launcher to run the Extractor.
- Success means: with no document open, the user picks a model and its views, starts the export, keeps working in Revit while it runs, and opens the result in the Analyzer.

## Capability map

| Module id | Responsibility | Depends on |
| --- | --- | --- |
| `shared-ui` | English/Polish text helper, theme, search bar and column filters, in the extension-level `lib/` | — |
| `capabilities` | Table of what the running Revit supports (view id key, IFC/DWG, IFC setups, extra metadata), plus the `ElementId` accessor | — |
| `index-builder` | One `build_index` for every version, driven by `capabilities` | `capabilities` |
| `model-catalog` | Local/server model list: remembered roots, recursive scan, skip rules, version read without opening, newer = greyed, older = warning | `capabilities` |
| `model-reader` | Background open (detached, read-only, worksets closed), view list, `Close(False)` | `capabilities` |
| `export-runner` | Run folder, `index.json`, `RevitExtractor.exe` as its own process, queue (max 1 parallel), cancel, success check | `index-builder` |
| `status-window` | Modeless progress/result window: Open output folder, Open in Analyzer, Cancel export | `export-runner`, `shared-ui` |
| `export-button` | The one ribbon button (zero-doc only) and its main window: model → views → options → queue | all of the above |
| `cloud-catalog` | Cloud list from journals + `CollaborationCache`, staging copies under real names with cache dates (Q27, Q29) | `model-reader`, `capabilities` |
| `ifc-setup-command` | Separate small command with a document open: prepare an IFC setup (Q22) | `shared-ui`, `capabilities` |

Build order: `shared-ui`, `capabilities` → `index-builder`, `model-catalog`, `model-reader`, `export-runner` → `status-window` → `export-button`.

**v1 stops after `export-button`** (owner decision 2026-11-10): local/server models end to end, verified by the owner in Revit 2022. `cloud-catalog` is v1.1 and `ifc-setup-command` is v1.2. Their specs are written when v1 is done.

Out of scope: `Start-RevitExport.ps1` stays as it is, with bug fixes only (Q25). The Analyzer is unchanged.

## Tech stack

- **pyRevit with IronPython 2.7** (pyRevit's default engine). No CPython engine, no `#! python3`.
- .NET Framework through IronPython: WPF windows loaded from XAML, `System.Diagnostics.Process` for the Extractor, the WPF `Dispatcher` for UI updates from process events. No Python threads.
- Revit API, 2022 floor (`revit-api.json`). Every API member is checked with the `revit-api` skill for the 2022 floor and the newest indexed revision.
- The Extractor shipped with the running Revit: `<Revit folder>\RevitExtractor\RevitExtractor.exe` (same lookup as `Start-RevitExport.ps1`).
- Settings (remembered roots, output folder, max parallel) in pyRevit's per-user config (`script.get_config()`).

## Commands

```powershell
# pyRevit unit tests (CPython 3 with host stubs), from the repo root
python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v

# Native parser check of generated indexes (needs a Revit 2022-2025 Extractor)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\validate_native_legacy.ps1
```

Modules that need more (WPF load checks, an Extractor integration run) name their own command in their spec.

## Project structure (target for v1)

```
pyRevit/Extractor.extension/
  lib/                                  shared modules, on sys.path for every button
    rx_i18n.py                          tr(english, polish)                 [shared-ui]
    rx_theme.xaml, rx_search_bar.*,     theme and controls                  [shared-ui]
    rx_search_placeholder.py, rx_column_filter_*.py
    rx_capabilities.py                                                      [capabilities]
    rx_index.py                                                             [index-builder]
    rx_catalog.py                                                           [model-catalog]
    rx_reader.py                                                            [model-reader]
    rx_runner.py                                                            [export-runner]
    rx_status_ui.py, rx_status.xaml                                         [status-window]
  RVTExtractor.tab/Setup.panel/
    Export.pushbutton/                  the new button: script.py, bundle.yaml, window [export-button]
    ExportSetup.pushbutton/             unchanged until the owner verifies v1, then deleted (Q12)
    ExportSetupLegacy.pushbutton/       same
    tests/                              test_<module>.py for every module, plus *.ps1 checks
specs/                                  this folder
```

- Every shared module starts with `rx_`, so it can't clash with another extension's module in a shared engine (lesson from slice 1).
- Button-specific code (window layout, wiring) stays in `Export.pushbutton/`. Anything another button or test needs goes to `lib/`.
- Install stays as today: clone the repo and add `<clone>\pyRevit` as a pyRevit custom extension folder (owner confirmed 2026-11-10).

## Code style

The existing conventions in `CLAUDE.md` apply. In short:

```python
# -*- coding: utf-8 -*-
"""One-line purpose; compatible with pyRevit IronPython 2.7."""
from __future__ import unicode_literals

from rx_i18n import tr


def element_id_value(element_id):
    """Feature check, not a version check: ElementId.Value (2024+), else IntegerValue."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


class SetupError(ValueError):
    pass


def require_views(ids, dimension):
    if not ids:
        raise SetupError(tr("Select at least one {0} view.",
                            "Zaznacz co najmniej jeden widok {0}.").format(dimension))
```

- IronPython 2.7 syntax only: no f-strings, type hints, `pathlib` or 3-only stdlib.
- Every user-facing string goes through `tr(english, polish)`. Window labels are XAML `{DynamicResource key}` entries backed by a text table, as in slice 1.
- Keep pure logic (tables, parsing, path rules, index building) free of Revit/WPF imports so CPython can test it. Revit/WPF code stays in thin wrappers.
- No Revit version in any file, folder, class or title name; state ranges in descriptive text.
- Windows: no per-row event subscriptions on `forms.Reactive` rows (slice 1 lesson); one handler per list.

## Testing strategy

| Level | What | Where |
| --- | --- | --- |
| Unit (CPython, stubs) | All pure logic: tables, index building, path and skip rules, journal parsing, command lines, result parsing, window logic with WPF stubbed | `tests/test_<module>.py`, run by the discover command |
| WPF load (PowerShell, .NET Framework) | Every new XAML loads, with its theme, in real WPF | named per module |
| Native parser | Generated indexes parse as expected with the installed Extractor | `validate_native_legacy.ps1` (extended by `index-builder`) |
| Extractor integration (this machine) | A real Extractor run on a small sample model (Revit 2023 Extractor, Dynamo sample RVT), started the way `export-runner` starts it | named in `SPEC-export-runner.md` |
| In Revit (owner, Revit 2022 + pyRevit) | Background open, windows, queue, status window, real exports | checklist per module, results in the module's README Validation section |

- Tests follow the existing pattern: modules added to `sys.path` with **append**, and a module pinned in `sys.modules` where names clash.
- Passing CPython tests do not prove IronPython compatibility. Behaviour inside Revit is never claimed as verified until the owner reports it.

## Boundaries

- **Always:**
  - run the unit tests before every commit;
  - write a failing test first for logic changes;
  - keep English and Polish for every new text;
  - check Revit API members with `revit-api` for the 2022 floor and the newest indexed revision;
  - record what was and was not verified.
- **Ask first:**
  - adding any dependency or a new external tool;
  - deleting the old buttons (after the owner verifies v1);
  - changing `Start-RevitExport.ps1` behaviour;
  - committing or pushing;
  - anything touching the `online` branch.
- **Never:**
  - write to a model file or save an opened model (background opens are detached, read-only, `Close(False)`);
  - write to or modify an existing export folder after its run (every run gets a new folder);
  - put client data (reports, logs, model names, GUIDs) in the repo;
  - put Revit versions in names;
  - use Python-3-only syntax in pyRevit code.

## v1 success criteria

1. In Revit 2022 + pyRevit, the button is enabled only when no document is open, and refuses at run time if one is (Q26).
2. The local list shows `.rvt` files from one or more remembered root folders (recursive) with Folder, File Name and Revit Version.
   - `*.000N.rvt`, `Backup` folders and local copies of centrals are skipped.
   - Newer-version models are greyed out with a tooltip; older ones show the upgrade warning (Q17, Q19).
3. For one model, the window lists its views after a background open that leaves the file unchanged (worksets closed). View picking works as in slice 1 (Q7, Q18).
4. For several models, a batch runs one after another with the default scope (Q18).
5. Starting an export returns control to Revit at once. The modeless status window shows progress and the result. Closing it or Revit does not stop the export, and Cancel export stops it (Q6, Q24).
6. The run folder layout and the success check match `Start-RevitExport.ps1`: `export-<date>-<id>\index.json`, `output\`, `logs\`, `journals\`; exit 0, no failed jobs, `bubble.json` and `Resource\` present (Q10).
7. Exports queue: several can be started and run one after another (max parallel 1, a setting) (Q28).
8. Open in Analyzer starts the local Analyzer with the output folder when Node.js and the Analyzer are found. Otherwise it opens the output folder and the website (Q11).
9. For the same settings and views, `index-builder` produces the same `index.json` as today's buttons, proven by tests and the native parser check.
10. All new text exists in English and Polish, and follows pyRevit's language setting.

## Open questions

1. ~~Install layout.~~ **Resolved 2026-11-10 (owner):** users clone the repo and add `<clone>\pyRevit` as a pyRevit custom extension folder. Open in Analyzer finds the Analyzer at `<clone>\Analyzer`, relative to the extension. A `pyrevit extend` git-URL install is not supported, so the repo layout stays.
2. **Model list speed.** Reading versions with `BasicFileInfo.Extract` for many files may be slow. `SPEC-model-catalog.md` will propose a cache (path + size + modified time) and a target time; the owner confirms the target.
