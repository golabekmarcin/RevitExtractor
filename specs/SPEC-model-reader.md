# Spec: model-reader

Module of `SPEC.md`. Depends on: `capabilities`. Status: **written under the owner's working mode of 2026-11-10**.

## Objective

Read one model's views in the background and leave the file untouched (Q4/Q7, Q15): open detached with all worksets closed, collect the view rows the slice 1 window uses, close without saving.

## Interface (`lib/rx_reader.py`; no Revit import, the caller passes `app` and `DB`)

```python
VIEW_KINDS                              # ViewType name -> (english, polish); moved from extractor_text
collect_views(doc, DB)                  # {"views_2d": [...], "views_3d": [...]}, rows as today
open_options(DB, workshared=None)       # OpenOptions for a background open
read_model(app, DB, path, caps, workshared=None)   # snapshot; raises ReadError
ReadError                               # .kind: "busy" | "open_failed" | "close_failed"; bilingual message
```

- Snapshot: `{"title", "path", "views_2d", "views_3d", "ifc_setups", "ifc_error"}`. `path` is the requested path, and `title` is the file name with its extension, because a detached document has an empty `PathName`. `ifc_error` is `""` when the IFC setups were read. If the read fails, `ifc_setups` is `[]` and the bilingual message goes in `ifc_error`, so the view list survives (added while building, 2026-11-10).
- Rows are today's: `id` (numeric text, through `rx_capabilities.element_id_value`), `uid`, `name`, `kind`, `search`.
- `ifc_setups` is filled only when `caps.ifc_setups` (Q22): names of existing IFC setups, each with `ready` = it has the map the Extractor reads. Read-only port of `ExportSetup/extractor_ifc_storage._records`.
- `read_model` must be called inside the button's command (a modal window). The modeless status window must never call it.

## How the open stays harmless

| Step | Rule |
| --- | --- |
| Guard | `app.Documents.IsEmpty` must be True, else `ReadError("busy")` before anything is opened. `OpenDocumentFile` on a file that is already open may hand back the user's document, and closing it would discard their work. This is a precaution, not a documented behaviour. |
| Options | `DetachFromCentralOption.DetachAndPreserveWorksets`, `WorksetConfiguration(CloseAllWorksets)`, `Audit = False`, `AllowOpeningLocalByWrongUser = True`. When the catalog says the file is not workshared (`workshared is False`), plain `OpenOptions()`. Unknown counts as workshared. |
| Open | `app.OpenDocumentFile(ModelPathUtils.ConvertUserVisiblePathToModelPath(path), options)`: "opens the document into memory but does not make it visible". |
| Read | `collect_views` only. No transaction, no `Save`, no `SaveAs`. |
| Close | `doc.Close(False)` in `finally`, exactly once. A False return gives `ReadError("close_failed")` saying a document may still be open. |

"Read-only" is by construction: `OpenOptions` has no read-only flag in 2022 or 2026.

## Revit API members

Checked with `revit-api` on 2026-11-10 in revisions 2022 (CHM `b8ee0868071c9e79…`) and 2026 (CHM `441dcbf9ce355456…`). Documented in both unless noted. Member id = `<revision>:<CHM prefix>:<hash>`. Documentation only; not run in Revit. Versions after 2026 are not indexed.

| Member | Hash |
| --- | --- |
| `ApplicationServices.Application.OpenDocumentFile(ModelPath, OpenOptions)` | `06ebc3d01cc8f44d27d4f855` |
| `Application.Documents`, `DocumentSet.IsEmpty` | `d7301ee3810d925b6ebf8f99`, `e7c3ed3295a317e96f22b072` |
| `Application.VersionNumber` | `285346c29d65e5560aefdbce` |
| `ModelPathUtils.ConvertUserVisiblePathToModelPath(String)` | `17eab931ac5e34cfcd3df0b4` |
| `OpenOptions()`, `.DetachFromCentralOption` | `a4a36bcbb2607a471ed1928d`, `55971294840070c215ef9c76` |
| `OpenOptions.SetOpenWorksetsConfiguration(WorksetConfiguration)` | `9a50a06e88cc4188b76f92e0` |
| `OpenOptions.Audit`, `.AllowOpeningLocalByWrongUser` | `f79173783f49fe57ad711b59`, `0eda5b86851f76e646de2a09` |
| `DetachFromCentralOption` (same four members in both) | `681d2a6e6bca944b533c4f27` |
| `WorksetConfiguration(WorksetConfigurationOption)`, the enum | `829ab8c901a7a4c4fc1102ed`, `ba5013efb7ec9e1e8eb957d0` |
| `Document.Close(Boolean)` | `84bdb3b97743ad8bdb9de37c` |
| `FilteredElementCollector.OfClass(Type)` | `5a8f0be501f8972f687141d3` |
| `View.IsTemplate`, `.CanBePrinted`, `.ViewType` | `ae2ab88f74b6883070cfdc52`, `70ddd0445a54004128aded02`, `4982c3d39b574458c42d2a7d` |
| `ViewSheet.IsPlaceholder`, `.SheetNumber` | `c8641ad956d43bff01407e03`, `d06e2da50ec0a11c8d1badd0` |
| `Element.Name`, `.UniqueId`, `.Id` | `860419959dfde1f8625371b8`, `d612b9c15e7d183fe0ec28d6`, `799d507638334319f17462db` |
| `ElementId.IntegerValue` | `bd4068ec638e24062a3b9900`: **2022 only, no page in 2026** |
| `ElementId.Value` | `ce360a591fded8c715e8a972`: **2026 only, no page in 2022** |
| IFC list: `Schema.Lookup(Guid)`, `Element.GetEntity(Schema)`, `Entity.IsValid`, `DataStorage` | `8da60e7166091750a4b7b34e`, `4cea435f57764415514cbad0`, `7b9b3de69b807e18515d3729`, `acd6d078c1117671b31b9400` |

- The only cross-version break is the known `ElementId` one; `element_id_value` covers it. `View.Name` has no page of its own in either revision; the rows use the inherited `Element.Name`.
- Not checked: the `FilteredElementCollector(Document)` constructor and `Entity.Get<T>`. Today's buttons use both; the IFC task checks `Entity.Get` before porting.
- Kept in reserve, documented in both revisions, unused in v1: `Application.FailuresProcessing` (`c38fa666db1a86b9b99391c4`) and `UIApplication.DialogBoxShowing` (`f79bb5c99496a61583d25a1e`), in case the owner's test shows dialogs during a background open.

## Acceptance criteria

1. For the same stub document, `collect_views` returns the same `views_2d` and `views_3d` rows as the legacy `extractor_model.collect_views`, in English and Polish. `VIEW_KINDS` equals the bundle's.
2. `open_options`: workshared or unknown sets the four options above; `workshared=False` sets none of them.
3. `read_model` calls, in order: guard, convert path, open (two-argument overload), collect, `Close(False)`. `Close(False)` runs exactly once, also when collecting raises, and the first error is the one reported.
4. Strict stubs: `app`, `doc`, `DB` and the views raise on any member outside the table above. The test fails on `Save`, `SaveAs`, `Close()` without an argument, `Close(True)` or a `Transaction`.
5. `app.Documents.IsEmpty` False raises `ReadError("busy")` and `OpenDocumentFile` is never called.
6. `Close(False)` returning False raises `ReadError("close_failed")`.
7. Each documented open exception type maps to an English and Polish message by type name (file not found, central busy or denied, corrupt, wrong user, cancelled, not enough resources); any other gives a generic message that includes the original text.
8. `title` and `path` come from the argument, not from the document.
9. With `caps.ifc_setups`, `ifc_setups` lists names sorted, with `ready`, from stub storage; with it False the key is an empty list and no storage member is touched.
10. No module-level import of `pyrevit`, `Autodesk`, `System` or `clr` (AST test). All text through `tr`.

## Commands

```powershell
python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v
```

## Testing

- New `tests/test_reader.py` with strict stubs. The parity test loads the legacy `extractor_model.py` with a stub `pyrevit`, as `test_config_legacy.py` does.
- Verified here: the call sequence and the data shaping only. **Nothing about a real open can be verified here** (no pyRevit on this machine). Every Revit-side item is in the owner's checklist.

## Boundaries

- Never save, never start a transaction, never close a document this module did not open.
- Never keep a Revit object after `read_model` returns; the snapshot is plain data.
- Never open with `OpenAndActivateDocument`.
- No write to IFC setups here (Q22); that is `ifc-setup-command`.
