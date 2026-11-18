# Spec: named-copies

Module of `SPEC.md`. Depends on: `export-runner`, `status-window`, `export-button`, `model-reader`. Status: **written 2026-11-18 from the owner's decisions of that day; not built. Waiting for the owner's answers to the open questions at the end and for the probe run (Phase 2 gate).**

## Objective

The Extractor names its own files (sheet PDFs come out as `<Sheet Number> - <Sheet Name>`), and the Analyzer finds them through the names in `output\bubble.json`, so `output\` must stay as the Extractor wrote it. When a **name template** is set, the runner waits for each export to finish `ok`, then makes `<run>\named\`. That folder holds every deliverable of the export under the owner's names. The entries are hard links, so they use no extra disk space; a file is copied only when a link cannot be made.

## Scope

| Deliverable | Found as | Named entry |
| --- | --- | --- |
| Sheet and view PDF | every `*.pdf` under `output\` | `named\<name>.pdf` |
| DWG | every `*.dwg` under `output\` (only when the export has them) | `named\<name>.dwg` |
| IFC | every `*.ifc` under `output\` (one per model) | `named\<name>.ifc` |
| 3D view (SVF), 2D F2D | the view folder: the outermost folder named by the viewable GUID that holds the `*.svf`/`*.f2d`; with no GUID folder, the folder of the `*.svf`/`*.f2d` | `named\<name>\` holds the whole subtree as links, with file names inside unchanged |

- `named\` is **flat**: no subfolders per kind, except the 3D view folders themselves.
- Excluded: `bubble.json`, `Resource\objects_*`, `model.sdb`, `AECModelData.json`, thumbnails outside a view folder, logs.
- A view folder that holds more than one `*.svf`/`*.f2d` (shared by several views) is skipped with a note.
- Not in scope:
  - renaming inside `output\`;
  - naming again later or with another template (`named\` is made once per run);
  - naming `failed`, `cancelled` or foreign (adopted) runs;
  - Analyzer changes.

## Template

- Syntax: literal text plus tokens `{Token}` (names match without regard to case), custom parameters `{param:<Parameter name>}`, and `{{` / `}}` for literal braces.
- The template applies to the **stem**. The extension comes from the source; folders have none.
- Up to 200 characters. Leading and trailing spaces are trimmed. `""` means off.
- `parse_template` raises `NamingError` (bilingual) for an unknown token, an unbalanced brace, or an empty `{param:}`. Both the window and `Queue.add` call it.
- Token names are language-neutral identifiers. The picker shows each with a translated label.

| Token | Value (B = model source, A = property-database source; see Value sources) |
| --- | --- |
| `SheetNumber`, `SheetName` | `ParameterTypeId.SheetNumber` / `SheetName` (sheet) |
| `CurrentRevision`, `CurrentRevisionDate`, `CurrentRevisionDescription` | `ParameterTypeId.SheetCurrentRevision…` (sheet) |
| `SheetIssueDate`, `DrawnBy`, `CheckedBy`, `DesignedBy`, `ApprovedBy` | `ParameterTypeId.SheetIssueDate`, `SheetDrawnBy`, `SheetCheckedBy`, `SheetDesignedBy`, `SheetApprovedBy` (sheet) |
| `SheetSize` | the first title block on the sheet: `SheetWidth` × `SheetHeight`. The name of an ISO A0–A4 size when both sides match within 1 mm in either orientation, else `<W>x<H>` in whole mm |
| `ViewName`, `TitleOnSheet` | `ParameterTypeId.ViewName` / `ViewDescription` |
| `Scale` | `View.Scale` as a number (`100` for 1:100); empty for a sheet |
| `DetailLevel`, `Discipline`, `Phase` | `ParameterTypeId.ViewDetailLevel` / `ViewDiscipline` / `ViewPhase`, as text in Revit's language |
| `ViewTemplate` | the name of `View.ViewTemplateId`; empty when there is none |
| `ViewSheetNumber` | `ParameterTypeId.ViewerSheetNumber`: the sheet a view is placed on |
| `ElementId` | the sheet's or view's ElementId (`rx_capabilities.element_id_value`) |
| `{param:X}` | an instance parameter of the sheet or view whose definition name is `X` and that is not built in |
| `Year`, `Year2`, `Month`, `Day`, `Hour`, `Minute`, `Second` | the job's start time (the same time as the run folder name), zero-padded to 2 digits (`Year` has 4) |
| `Date`, `DateShort`, `DateLong` | `2026-11-18`, `20261118`, `18 November 2026` / `18 listopada 2026` (month names in pyRevit's language) |
| `ModelName` | the model's file name without `.rvt` (for Cloud, the real name, never a GUID) |
| `WindowsUser`, `RevitUser` | `USERNAME` and `Application.Username`, captured when the job is submitted |
| `OriginalName` | the Extractor's own stem, or the folder name for a 3D view folder |

Presets, shown in the editable list: `{SheetNumber}`, `{SheetNumber} - {SheetName}`, `{SheetNumber}_{CurrentRevision}`, `{ModelName} - {SheetNumber} - {SheetName}`, `{Date} {OriginalName}`.

**Empty values.**
- A token without a value becomes `""`.
- When **every** token in the template is empty for a file, that file keeps its original name. For example, `{SheetNumber}` on a view PDF or an IFC file.
- A name that is empty after cleaning also keeps the original name.
- A template with no tokens is allowed. Clash numbering then applies to every file.

## Names

- `clean_name(raw)`:
  - whitespace (tabs and line breaks included) collapses to one space;
  - `< > : " / \ | ? *` and characters below U+0020 become `_`;
  - leading and trailing spaces and trailing dots are trimmed;
  - a reserved device stem (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`9`, `LPT1`–`9`) gets a `_` prefix.
  - The result always passes `rx_cloud.safe_file_name`.
- Length: IronPython in Revit has no long-path support.
  - Each file path must be at most 259 characters and each folder path at most 247.
  - For a 3D folder, the budget is `247 − len(named root) − 1`, and also `259 − len(named root) − 2 − longest relative path inside`.
  - A file's budget is `259 − len(named root) − 1 − len(ext)`.
  - Each name component is at most 255 characters.
  - The stem is cut to the budget without splitting a surrogate pair, then trimmed again.
  - If even the original name does not fit, the item fails with "path too long".
- Clashes:
  - items are processed in a fixed order (kind, then source path in lower case);
  - the first keeps the name and later ones get ` (2)`, ` (3)`, …;
  - names are compared without regard to case;
  - the stem is cut further when a suffix would break the budget.

## Tying a file to its sheet or view

1. **Viewable:** the GUID folder in the file's path matched against `viewableID`/`guid` in `bubble.json`, as `Analyzer/lib/exports.mjs` does. Otherwise, the stem equal to exactly one viewable `name` in the same top folder under `Resource\`.
2. **Element:** the viewable's id equal to a value key (UniqueId). Otherwise, for a sheet, the viewable name equal to `"<SheetNumber> - <SheetName>"`; for a view, equal to `ViewName`. The match must be unique within the source's values.
3. An untied file gets system tokens and `OriginalName` only. The result note counts untied files. Nothing is guessed beyond these rules.

The probe (`Analyzer/scripts/probe-export-structure.mjs`) on a real export decides how often rule 1 and rule 2 succeed. That is the Phase 2 gate in the plan.

## Value sources (Phase 2; chosen after the probe)

Every source produces the same plain form: `{"<UniqueId>": {"kind": "sheet"|"view", "id": "<ElementId>", "name": "<viewable-style name>", "tokens": {Token: text}, "params": {name: text}}}`.

- **B: from the model, in Revit.**
  - `rx_reader.read_model(..., values=True)` adds `"values"` in the same background open and the same loop as `collect_views`. It covers every printable sheet and view: the built-in tokens above, plus every non-built-in instance parameter (`InternalDefinition.BuiltInParameter` is `INVALID`), using `AsString()` for text and `AsValueString()` otherwise.
  - A job made after Choose views… carries these values.
  - For default-scope jobs, B needs an extra background open per model at Export (B2). Whether to do that is an owner decision.
  - Read only. No transaction. `Close(False)` exactly once (the `model-reader` rules).
- **A: from the export's property database, at the end, in the session.**
  - Read `output\Resource\objects_{ids,offs,avs,attrs,vals}.json.gz`, read-only, with no Revit and no model open.
  - Find the dbIds whose `ids` entry equals a viewable id, then read only their `offs` and `avs` slices and the `vals` entries they point to.
  - Tokens map to the attribute display names `attr[5] or attr[0]` ("Sheet Number", …). `{param:X}` maps to the attribute named `X`.
  - Streaming: 1 MiB compressed chunks through `zlib.decompressobj(16 + zlib.MAX_WBITS)`, with .NET `GZipStream` as a fallback. Skip `offs`/`avs` by `str.count(",")`. Tokenise `ids` and `vals` with one compiled regex and carry the tail across chunks. Never hold a whole array.
  - It is a generator, time-sliced by the runner's budget.
  - Only viable when the probe shows viewable ids equal to property-database external ids, and built-in attributes under English names.
- **C:** B values win; A fills tokens B lacks.

## Runner and session (amendments to `SPEC-export-runner.md` and `SPEC-status-window.md`)

- `Job(..., naming=None)`, where `naming = {"template": text, "system": {Token: text}, "values": {...} | None}`.
  - `Queue.add` runs `rx_naming.check_naming`. A bad template, a non-text value or a missing system token raises `RunnerError` and refuses the job (fail closed).
  - New fields: `naming_state` (`None` | `pending` | `running` | `done` | `partial` | `failed`), `naming_done`, `naming_total`.
- When a job with `naming` ends **`ok`**, `naming_state = "pending"` and the job joins `Queue._namings`, the same pattern as `_cleanups`.
  - `clear_finished` does not stop it. `busy()` stays true until it ends.
  - The next export does not wait for it, and naming never takes the run lock.
- `poll()` advances naming after staging, in the **same budget**: whatever time staging left, at least one step.
  - The generator `rx_naming.named_steps(job, …)` walks `output\` (one step per folder), ties the files, plans the names, then makes links (one step per file) or copies (one step per 1 MiB).
  - `Queue(..., namer=None)` is injectable for tests.
  - The timer runs at `STAGING_TICK_SECONDS` while a job is being named.
- **Writer** (`rx_naming`):
  - links with `rx_hardlink.make_hard_link` and falls back to `rx_cloud_stage.copy_steps` (`link=` given; sources opened `"rb"`; targets `O_EXCL`; only a partly written target is ever removed);
  - before the first fallback copy it checks free space for the rest (`free_space`; unknown space lets it go on);
  - creates folders with `os.makedirs` only under `named\`;
  - skips symbolic links in the source tree.
- **Record** `<run>\named.json` (`dumps_ascii`, ASCII), outside `named\` so it never travels with the deliverables:
  - `schema`, `version`, `template`, `state`;
  - per item: `source` (relative to `output\`), `name` (relative to `named\`), `kind` (`file` | `dir`), `mode` (`linked` | `copied` | `failed`), `error` (exception type and code only, as `_short_error`);
  - `notes` and counts.
  - Written when the step starts (`running`) and when it ends.
- **Result note**, appended to the job's message in EN/PL:
  - "Named copies: {n} in named\ ({c} copied instead of linked)." / "Kopie z nazwami: {n} w named\ ({c} skopiowano zamiast dowiązać).";
  - "Named copies: {n} of {t}; {f} failed, see named.json." / "Kopie z nazwami: {n} z {t}; {f} nieudanych, zobacz named.json.";
  - "{u} files could not be tied to a sheet or view and kept their name." / "{u} plików nie powiązano z arkuszem ani widokiem; zachowały nazwę.";
  - "Named copies were not made: {0}" / "Nie utworzono kopii z nazwami: {0}".
- **Status row** while naming: State stays "Done" / "Gotowe". Progress reads "Naming files: {0} of {1}" / "Nadawanie nazw: {0} z {1}". Open in Analyzer stays enabled, because `output\` is untouched. New row-menu item: "Show named files in File Explorer" / "Pokaż pliki z nazwami w Eksploratorze", enabled once `named\` exists.
- `submit` accepts `"naming"`. A wrong type is that job's error. `PROTOCOL` becomes 2, so an older session without this feature is replaced and never ignores the field silently; the run lock keeps runs one at a time.

## Failure rules

1. The named step **never changes `job.state`**, and never writes, renames, moves or deletes anything in `output\` or outside `<run>\named\` and `<run>\named.json`.
2. If `<run>\named\` already exists, nothing is done: the result is `failed` with a note.
3. A failure on one item (link and copy both failed, path too long, a source that changed or vanished) fails that item only. The rest go on, and the result is `partial`.
4. Any other error (unreadable `bubble.json`, a broken value source, an exception in the generator) gives `failed` with a note. Items already made stay.
5. If Revit closes during the step, `named.json` stays at `running`. Nothing resumes it. The guide says so.
6. Every error is caught inside `poll()`. The queue and the status window go on.

## Settings and window (amendment to `SPEC-export-button.md`)

- New setting `name_template` (text, `""` = off) in `SETTING_NAMES`, `load_settings` and `settings_to_save`. A non-text value falls back to `""`.
- The "What to export" card gets a second row "File names":
  - an editable ComboBox (`name_template_cb`, presets above);
  - "Insert token ▾" (`name_token_cb`, a non-editable list of translated token labels plus "Custom parameter…", which inserts `{param:}` with the caret inside), inserting at the caret;
  - Clear.
- Under the row:
  - a preview "Example: A101 - Ground floor.pdf → {result}", computed from synthetic sample values in both languages; an invalid template shows its `NamingError` there instead;
  - the hint "Empty = off. Named copies go to <run>\named as hard links (no extra space); the export itself is not changed. A named file edited in place changes the original too."
- Export refuses an invalid template on the error line and keeps the ticks.
- Every label is a `{DynamicResource}` in `UI_TEXT`.
- `script.py` adds `naming` to each job: the template, and `system` (Windows user from the environment, `app.Username`, the model name). The time tokens are filled by the runner at start.

## Revit API members (source B)

Checked with `revit-api` on 2026-11-18 in revisions 2022 (CHM `b8ee0868071c9e79…`) and 2026 (CHM `441dcbf9ce355456…`). All are documented in both, under the same member hash. This is documentation only, not run in Revit. Versions after 2026 are not indexed.

| Member | Hash |
| --- | --- |
| `Application.Username` | `0ce3207b8a992658b0025818` |
| `Element.GetParameter(ForgeTypeId)` | `6dfa5c599472f61f41f9401b` |
| `Element.Parameters` / `Element.UniqueId` | `300a592bf0e0adb256c94a05` / `d612b9c15e7d183fe0ec28d6` |
| `Parameter.AsString` / `AsValueString` / `AsDouble` / `HasValue` / `StorageType` / `Definition` | `4357913789441f6efeb7e914` / `a900ec96ea7d83bb6f092b2e` / `171eab748a4d01122c5bc118` / `c764abb7ae07234a2333dbbf` / `9a50f98b782cafe80ada5884` / `7b23da55a9b6043afd7b5187` |
| `Definition.Name` / `InternalDefinition.BuiltInParameter` | `53ab12a6a1f9ad218f1a29cf` / `567805f3ec34b8f32bd6409f` |
| `View.Scale` / `View.ViewTemplateId` / `Document.GetElement(ElementId)` | `e532dbd051eff09ec7a3cbfa` / `27fd5c83334fcf9487e2cdcd` / `3667fd6665fd7c0559360c1a` |
| `FilteredElementCollector(Document, ElementId)` / `OfCategory` / `WhereElementIsNotElementType` | `997cff90e3e0b901328d66b5` / `e7729c4f27289650d75dcee3` / `d3fc4e8bd621ee4f4c5a31e9` |
| `ParameterTypeId` `SheetNumber`, `SheetName`, `ViewName`, `ViewDescription` | `8cc4e8e06e3095b5437d161e`, `41c8437c99e051e1bee2fe30`, `faf6c9f7321fe723b4af0bd6`, `543ec7721546f08e76bddfba` |
| `ParameterTypeId` `SheetCurrentRevision`, `…Date`, `…Description`, `SheetIssueDate` | `f11c9681862167dd13a29bb5`, `07a55a406c7003fe987dbf5a`, `56164c950901a17fc09370cd`, `90dca2c1405449672108840e` |
| `ParameterTypeId` `SheetDrawnBy`, `SheetCheckedBy`, `SheetDesignedBy`, `SheetApprovedBy` | `2e3cfb622a105c010f494045`, `830602b22b4d716b63c7bb89`, `ec642ea859ca35da83769ad2`, `026811751955e881e3b255cb` |
| `ParameterTypeId` `ViewDetailLevel`, `ViewDiscipline`, `ViewPhase`, `ViewerSheetNumber`, `SheetWidth`, `SheetHeight` | `5775b22bbcc43fec224d2fe6`, `85d95769c6e79c6f50e3ddc6`, `6a260f9734d75a0f320f7fb2`, `2157688702afdd3b503d80d1`, `2c84a0a7ea5f60cc3dabb147`, `3715fc8dc15d4129f623c0f9` |

- `BuiltInCategory.OST_TitleBlocks` appears on the enum page in both revisions (match `all`; enum members are not indexed one by one).
- `ParameterTypeId.ViewerSheetName` is documented in 2026 only, so there is no `ViewSheetName` token.
- `AsDouble` is in feet; mm = feet × 304.8.

## Acceptance criteria

1. `parse_template`/`format_name`:
   - every token in the table parses;
   - unknown tokens, unbalanced braces and an empty `{param:}` raise `NamingError` in EN and PL;
   - `{{`/`}}` give literal braces;
   - names match without regard to case;
   - the all-tokens-empty rule falls back to the original name.
2. `system_values` for a fixed time: every system token, `DateLong` in both languages, zero padding.
3. `clean_name`, length and clashes:
   - every forbidden character, control character, reserved stem, trailing dot or space, and whitespace run;
   - a 300-character name under a 150-character root fits 259/247;
   - a surrogate pair is never split;
   - ` (2)`, ` (3)` without regard to case, still within the budget;
   - "path too long" when nothing fits.
4. Discovery and tying on synthetic trees:
   - PDFs in GUID folders, flat PDFs, DWG, IFC, SVF and F2D view folders;
   - a shared SVF folder is skipped with a note;
   - excluded files are never listed;
   - ties by GUID, by unique stem and by value name; an ambiguous match is untied.
5. Writer on a real temporary NTFS folder:
   - links are real hard links (`st_nlink` 2, same `st_ino`);
   - the 3D subtree is complete;
   - a forced link failure copies with bytes identical;
   - free space too low for the rest gives `partial`;
   - an existing `named\` gives `failed` and nothing is touched;
   - a vanished source fails that item only.
6. **`output\` is unchanged**: names, sizes, mtimes and SHA-256 of every file before and after the step, in every test of criteria 5, 7 and 13.
7. Runner hook with a fake starter and namer:
   - only `ok` jobs with `naming` are named;
   - `job.state` never changes;
   - the shared budget is respected (at least one step);
   - `clear_finished` does not stop naming;
   - `busy()` is true until it ends;
   - the next job starts while naming runs;
   - a raising namer gives `failed` and a note, and the queue goes on;
   - a job without `naming` never calls the namer.
8. `named.json` is ASCII, written at start and end, and contains no absolute path.
9. Session: `submit` takes `naming` and reports a wrong type as that job's error; `PROTOCOL == 2`; `job_view` gives the naming texts in EN/PL; the menu item is enabled only when `named\` exists.
10. Settings round trip for `name_template`, with a non-text value falling back. Window with WPF stubbed: preset choice, token insertion at the caret, preview, invalid template refused on Export with the ticks kept.
11. Text: XAML keys and `UI_TEXT` match both ways; no literal label; every runtime string goes through `tr`.
12. AST: `rx_naming` imports no `pyrevit`, `Autodesk`, `System` or `clr` at module level, and passes the IronPython syntax guard. Value-source code follows the `rx_reader` rules (no Revit import; `app`/`DB` passed in).
13. Integration on this machine: `run_extractor_integration.ps1 -Named` runs a real export of the Dynamo sample, then the namer with `{OriginalName} {Date}`. PASS needs all of the following:
    - every PDF and SVF folder in `named\`;
    - links verified;
    - `output\` hashes unchanged;
    - the probe on that output reports the tie counts;
    - no leftover process.
14. `validate_xaml.ps1` passes. `preview_windows.ps1` renders the card in EN and PL.

## Testing

- New `tests/test_naming.py` (criteria 1–8), additions to `test_runner.py`, `test_status.py`, `test_export_button.py`, `test_reader.py` (B) and `Analyzer/tests/probe.test.mjs` (probe additions).
- Verified here: criteria 1–14 on CPython 3 and Windows PowerShell 5.1.
- **Not verifiable here:**
  - IronPython 2.7: `CreateHardLinkW`, `zlib` gzip mode, regex speed on large arrays;
  - anything inside Revit: the window field, the background read of values, the session at protocol 2, naming next to a working Revit, a real ACC export;
  - the owner's Extractor build and real file layout.
  - These are Part I of `v1-revit-test.md`.

## Boundaries

- `output\` stays read-only. The only new writes are `<run>\named\` and `<run>\named.json`. Nothing under `CollaborationCache` is ever touched (named sources are in `output\`).
- No Revit API call outside the modal command. The session reads only files.
- No new dependency. Only JSON text crosses between engines (`dumps_ascii`). No threads.
- No client names in tests or docs: synthetic sheet names (`A101 - Ground floor`) and repeated-digit GUIDs.

## Open questions for the owner (recommended answer first)

1. Extend the probe before the owner runs it (does `viewableID` equal the property-database id; where do PDF, DWG and SVF files sit; does each SVF folder hold one view)? Recommended: yes (Task 0 of the plan).
2. Default-scope exports need sheet values from somewhere. If the property database (source A) is ruled out, open each model in the background at Export to read parameters (B2)? Recommended: yes, but only when the template uses a sheet or view token.
3. Hard links share content with `output\`: editing a named PDF in place changes the original. Warning only, or a `named_hardlinks: false` preference that copies? Recommended: warning only for now.
4. `named\` flat, or a subfolder per kind? Recommended: flat.
5. Name only `ok` exports, or also a `failed` one that left files? Recommended: `ok` only.
6. Date formats `{Date}` 2026-11-18, `{DateShort}` 20261118, `{DateLong}` "18 November 2026" / "18 listopada 2026", from the export's start time? Recommended: yes.
