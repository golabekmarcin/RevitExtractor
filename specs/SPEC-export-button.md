# Spec: export-button

Module of `SPEC.md`. Depends on: every other v1 module. Status: **written under the owner's working mode of 2026-11-10**.

## Objective

The one ribbon button (Q1, Q3): with no document open, the user picks one or more models, optionally picks views of one model, and starts the export. The command returns at once and the status window takes over. It closes v1 (`SPEC.md` criteria 1–10).

## Files (`RVTExtractor.tab/Setup.panel/Export.pushbutton/`)

| File | Content |
| --- | --- |
| `bundle.yaml` | titles and tooltips (`en_us`, `pl`), `min_revit_version: 2022`, no maximum, context rule, engine |
| `script.py` | guards, settings, the windows, hand-over to the session |
| `rx_export_logic.py` | pure: settings, tick helpers, shared index, job planning |
| `rx_export_text.py` | `UI_TEXT` for both windows, `resources()` |
| `rx_export_ui.py` | `ModelWindow`, `ViewWindow` |
| `rx_export_models.xaml`, `rx_export_views.xaml` | layouts; every label is `{DynamicResource key}` |
| `README.md`, `README.pl.md` | use, install (`npm ci` in `Analyzer` once for the local Analyzer), Validation |

Module names are unique (`rx_export_*`). The extension's buttons share one cached engine, and after an old button ran, `extractor_ui`, `extractor_text` and `extractor_config` in `sys.modules` are the old button's.

```yaml
context:
  rule: "(zero-doc)&!(doc-project|doc-family)"
engine:
  persistent: true
```

pyRevit 6.5.5 passes a `rule` through unchanged (`genericcomps._parse_context_directives`). `zero-doc` makes the command available without a document, and `doc-project` / `doc-family` test `UIApplication.ActiveUIDocument` (`ScriptCommands.cs`). `clean` stays off. `persistent` is a precaution: no handler of a surviving window refers to `script.py` globals.

## Flow

1. **Guards** (`script.py`), in this order:
   - a document is open (`ActiveUIDocument` is not `None`, or `Application.Documents.IsEmpty` is not a real `True`): message; if a session exists, its window is shown; stop;
   - `rx_capabilities.for_revit(app.VersionNumber)` raises: message; stop;
   - `rx_runner.extractor_exe(<folder of Revit.exe>)` raises: message; stop.
2. **Model window** (modal): roots, output folder, the model list.
3. **Export** queues one job per ticked model. **Choose views…** (exactly one ticked) reads the model and opens the view window.
4. The jobs go to the session as JSON (`submit`), the status window is shown (`show`), and the command ends.

## Model window

| Part | Rule |
| --- | --- |
| Header | title, `caps.label`, the Extractor build (file version of `ExtractorUtility.dll`; left out if unreadable) |
| Card | remembered root folders with Add folder… and Remove; output folder with Change… |
| List | ✓, File name, Folder, Revit version, Note. Search bar with regex; ▾ filters on Folder and Revit version. |
| Rows | `ModelRow(forms.Reactive)`, plain attributes plus reactive `Checked`, as slice 1. `newer` and `unknown` rows are greyed, cannot be ticked, and show the catalog note as tooltip (Q19, D4). `older` rows show the note in the Note column. `local_copy` rows are not listed, only counted. |
| Ticking | Select all shown / Unselect all shown touch only enabled, shown rows. Ctrl/Shift highlight and Space work as in slice 1. One handler per list. |
| Scan | `rx_catalog.scan` is pulled from a window-owned `DispatcherTimer`, at most 40 ms per tick; rows appear as they are read. Rescan, a change of roots and closing all close the generator, which saves the cache. Cache file: `%APPDATA%\RevitExtractor\catalog-cache.json` (D2). |
| Counter | selected / all, shown, skipped local copies, folders that could not be read |
| Scope | Extractor default scope, or Shared index.json with Choose… |
| Footer | Rescan, summary and status, Close (Esc), Choose views…, Export (primary, Enter; at least one ticked) |

**Reading a model.** `script.py` passes `read(path, workshared)`, which calls `rx_reader.read_model(app, DB, path, caps, workshared)`. `workshared` comes from the catalog (`Row.workshared`, a new field; `None` when unknown). The window shows a wait line, forces one render, calls `read`, and restores the cursor in `finally`. A `ReadError` goes to the error line. After `close_failed` the window closes without queuing anything, and the next click hits the first guard.

## View window

Slice 1's layout and behaviour (`ExportSetupLegacy/ui.xaml`, `extractor_ui.py`), with these differences:

| Slice 1 | Here |
| --- | --- |
| `extractor_config` | `rx_index.build_index(caps, …)`, `defaults(caps)`, `database_warning(caps, …)` |
| ids from `ElementId` | `id` when `caps.view_key` is `view_ids`, else `uid` |
| footer: Close, Save index.json | Back, Save index.json…, Export (primary) |
| formats note | with `caps.formats`: DWG and IFC switches and the IFC setup list from the snapshot (only `ready` setups can be chosen; `ifc_error` is shown). All marked untested (D7). Without formats: today's note. |
| — | extended properties and topology switches only when the table row has them |
| header note | the views were read from a background copy and the file was not changed; plus the upgrade note for an older model |

Export from this window makes exactly one job.

## Batch and shared index (Q18)

- Export with one or more ticked models: one job per model, in list order, each with `build_index(caps)` or the shared index.
- Shared index.json: read as UTF-8 (BOM allowed) and checked with `rx_index.require_index_shape`.
- A shared index that holds `view_ids` or `view_unique_ids` is refused when more than one model is ticked: those ids belong to one model (D11).
- The summary line counts older-version models (the export upgrades a temporary copy).

## Settings

`script.get_config("RevitExtractorExport")`: `roots` (list), `output_parent`, `max_parallel`, `shared_index_path`. Saved with `script.save_config()` when changed. Missing or bad values fall back: no roots, `rx_runner.default_output_parent(<Documents>)`, 1. There is no control for `max_parallel` while `PARALLEL_VERIFIED` is False. pyRevit keeps these in the user's pyRevit config file, which then holds folder paths: never share that file.

## Revit API members

Checked with `revit-api` on 2026-11-11 in revisions 2022 (CHM `b8ee0868071c9e79…`) and 2026 (CHM `441dcbf9ce355456…`); documented in both. Member id = `<revision>:<CHM prefix>:<hash>`. Documentation only; not run in Revit. Versions after 2026 are not indexed.

| Member | Hash |
| --- | --- |
| `Autodesk.Revit.UI.UIApplication.ActiveUIDocument` | `7c3145a733b89d4945077590` |
| `Autodesk.Revit.UI.UIApplication.Application` | `22fe7fa70c47792e5e8c8216` |

Used again, cited in `SPEC-model-reader.md` and `SPEC-model-catalog.md`: `Application.Documents`, `DocumentSet.IsEmpty`, `Application.VersionNumber`, the `BasicFileInfo` members. From pyRevit (source of tag 6.5.5, not the Revit API): `HOST_APP.uiapp`, `HOST_APP.proc_path`, `script.get_config`, `script.save_config`, `forms.WPFWindow`, `forms.Reactive`, `forms.pick_folder`, `forms.pick_file`, `forms.save_file`, `forms.alert`.

## Acceptance criteria

1. `bundle.yaml` has `en_us` and `pl` titles and tooltips, the context rule above, `min_revit_version: 2022`, no maximum and no `clean`. No Revit version appears in a file, folder, class or title name.
2. `script.py` with stubs: each guard stops before any window opens; with a document open nothing is read and the session's `show` is called when a session exists; only a real `True` from `IsEmpty` passes.
3. Settings: a round trip through a stub config; a non-list `roots`, an empty output folder and a non-numeric `max_parallel` fall back; roots go through `normalize_roots`.
4. `load_shared_index` accepts the launcher's default index and a BOM; broken JSON and a wrong shape raise `SetupError` in both languages.
5. `plan_jobs`: default scope gives one job per model in order, each with `build_index(caps)`; a shared index is used as given; ids plus two models raise `SetupError`, ids plus one model pass; no model raises.
6. Model window with WPF stubbed: disabled rows cannot be ticked by click, Space or Select all shown; local copies are counted and not listed; the scan is time-sliced and its generator is closed on Rescan and on close; Choose views… needs exactly one tick and Export at least one; no row subscription.
7. Reading: `read` gets the row's path and `workshared`; a `ReadError` is shown and nothing is queued; `close_failed` closes the window.
8. View window with WPF stubbed: the slice 1 window tests pass against it (ticking, search, type filter, lazy preview, invalid selection disables Export and Save); ids follow `caps.view_key`; format and metadata controls follow `caps`; Export returns one job.
9. Hand-over: the request is JSON text with plain values only; errors in the answer are shown; the command ends without waiting for the export.
10. `tick_targets` and `toggled_state` equal the legacy ones while the old button exists.
11. Text: the keys of both XAML files and `UI_TEXT` match both ways, no literal label; every runtime string goes through `tr`.
12. AST tests: `rx_export_logic.py` and `rx_export_text.py` are pure; `rx_export_ui.py` imports no `Autodesk` and no `rx_reader`; every new file passes the IronPython syntax guard; no new module name exists in either old bundle.
13. `rx_catalog.Row` has `workshared`; the catalog tests cover it; the cache format is unchanged.
14. `validate_xaml.ps1` passes for both XAML files, and `preview_windows.ps1` renders both windows in English and Polish.
15. `git diff --stat` touches neither old bundle.

## Commands

As `SPEC-status-window.md`. `validate_xaml.ps1` now covers `lib/` and `Export.pushbutton/` by default.

## Testing

- New `tests/test_export_button.py`, with `tests/wpf_fakes.py`. The slice 1 window cases become a mixin run against both windows, as `shared-ui` did for the search bar.
- New `tests/v1_test_kit.ps1` for the owner's session: `-Setup` builds the sample test folder, `-Stamp` prints a file's size and time, `-Check` prints the facts to send back. It prints no model name or path.
- Verified here: criteria 1–15 and the rendered pictures.
- **Not verifiable here:** everything inside Revit and pyRevit. That includes the greying, the folder and file pickers, `BasicFileInfo.Extract` from the scan timer, a real background open, the hand-over to the session and real exports. `v1-revit-test.md` is the one test.

## Boundaries

- `read_model` is called only from the modal model window, never from the status window.
- Never export a model that the catalog greyed out. Never widen a selection: an invalid or empty one is an error, as in `rx_index`.
- The old buttons are not touched before Q12.
- Nothing is kept in the repo or printed that names a client model: roots and the cache live in the user's profile.
- No object from `script.py` outlives the command: no function, window or Revit object is handed to the session.
