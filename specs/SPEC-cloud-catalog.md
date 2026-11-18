# Spec: cloud-catalog

Module of `SPEC.md`. Depends on: `model-reader`, `capabilities`; amends `export-runner`, `status-window`, `export-button`. Status: **written under the owner's working mode of 2026-11-10**; design decided 2026-11-16 (`HANDOVER.md`, Cloud catalog; refines Q27/Q29). The APS API route is parked: nothing here touches the network.

## Objective

List the cloud (ACC) models that this machine holds in Revit's `CollaborationCache`, under their real project and file names, and export them from a copy (Q27, Q29). The list is built without opening any model, and the cache is never written. Today the folder scan marks these files `local_copy` and hides them. The Export window gets a separate **Cloud** source instead. Limit: only models opened on this machine (directly or as links) that are named in a journal or in the name memory appear.

## Interface

`lib/rx_cloud.py`: pure, no Revit, .NET or `clr` import.
```python
revit_folders(localappdata, year)   # {"cache": ...\Autodesk Revit <year>\CollaborationCache, "journals": ...\Journals}
iter_journals(folder, limit=100, listdir=os.listdir, stat=os.stat)   # journal*.txt, newest first
decode_journal(raw)                 # UTF-16 BOM | UTF-8 strict | ANSI fallback; never raises
parse_journal(text)                 # generator of Sighting(project_guid, project_name, model_guid, file_name, source)
scan_cache(cache_root, walk=os.walk, stat=os.stat)   # generator of CacheFile(account, project_guid, model_guid, place, path, size, mtime)
Memory(file_path)                   # load(), merge(sightings, journal_mtime), included, links_for(key, mtime), store_links(...), save()
scan(folders, memory, now, read=..., budget)   # generator: None per step, finally a Catalog(rows, projects, counts)
CloudRow                            # key "cloud:<p>/<m>", project, name, cache_path, cache_date, size, state, enabled, note
plan_stage(row, link_refs, cache_files, memory)  # StagePlan(items=[StageItem(src, name, size, mtime)], notes)
```
`lib/rx_cloud_stage.py`: file IO only.
```python
check_space(plan, free_bytes)       # RunnerError (bilingual) when the copies and the Extractor's own temp copy do not fit
copy_steps(plan, dest_dir, chunk=8 * 2**20, open=io.open, stat=os.stat)   # generator of (done_bytes, total_bytes, item)
```
Amendments:
- `rx_reader`: `collect_cloud_links(doc, DB, name_of)` returns `[{"name", "project_guid", "model_guid", "region", "nested"}]` (port of `ExportSetupLegacy/extractor_cloud_probe.collect`, with the `element_name` reflection fallback). `read_model(..., links=False)` adds `snapshot["links"]`.
- `rx_runner`: `Job.stage` (plain dicts), `Job.model_name`, `Job.model_key`. New state `staging` between `queued` and `running`. `poll()` advances `copy_steps` for at most 40 ms per call. The Extractor's model path is `<run>\model\<model_name>`. Same-model check by `model_key`.
- `rx_status`: `submit` accepts `stage` and `model_name` (every path through `clean_path`); a staging row shows "Copying from the cache: {0} of {1} MB"; Cancel works during staging.

## Rules

| Rule | Detail |
| --- | --- |
| Journal path line | `ModelPath Created: ... Path = "CLD:\\<region>\{<project GUID>}<project name>\{<model GUID>}<file>.rvt"`. One or two backslashes between parts. `Region = "GLOBAL"` or an all-zero GUID: skipped. A project name with `%XX` is URL-decoded (UTF-8); a plain spelling of the same GUID wins. |
| Journal browser line | `Jrn.RibbonEvent "ModelBrowserOpenDocumentEvent:open:{...}"`: doubled quotes undone, then JSON. Uses `projectGuid`, `modelGuid` and `displayName` (no project name). Broken JSON is skipped without raising. Every other line is ignored. |
| GUIDs | lower case, braces stripped, everywhere (keys, matching, memory). |
| Names | Same GUID pair, different names: the newest journal (file mtime) wins. The memory keeps the last known name, so names survive journal clean-up. A project without any name: "(project name unknown)" / "(nazwa projektu nieznana)". **A GUID is never shown as a name.** |
| Cache layout | `<cache>\<account>\<project GUID>\<model GUID>.rvt` (place `root`) and `…\LinkedModels\<model GUID>.rvt` (place `linked`). `CentralCache\` folders are not used (sizes differ, untested). Other names are ignored. The same project under two accounts: the newest file wins. |
| Copy used | For each model, the newer of `root` and `linked`. **Cache date** = its mtime, shown per row. Nothing is claimed about the cloud version. |
| Version | The cache folder belongs to the running Revit year, so the row's version is that year. No `BasicFileInfo.Extract`. Other years' folders are not read. |
| Row states | `ok`: enabled. `stale` (cache date older than `stale_days`, default 7): enabled, note "Cache copy from {0}; it is as current as the last time this model was opened on this computer." / "Kopia z pamięci podręcznej z {0}; jest tak aktualna, jak ostatnie otwarcie tego modelu na tym komputerze." `not_selected`: disabled, "Not in the selected projects." / "Poza wybranymi projektami." `duplicate` (same project and file name as another row, older copy): disabled, "Another model in this project has the same name; the newer cache copy is listed." / "Inny model w tym projekcie ma tę samą nazwę; na liście jest nowsza kopia." |
| Unnamed files | Never listed. Counted per project: "Cached models without a name: {0}. Open them once in Revit to add them." / "Modele w pamięci podręcznej bez nazwy: {0}. Otwórz je raz w Revicie, aby je dodać." |
| No journal data | Message "No cloud model names were found in the Revit journals. Open the model in Revit and click Remember cloud model." / "W dziennikach Revita nie znaleziono nazw modeli z chmury. Otwórz model w Revicie i kliknij Zapamiętaj model z chmury." The list falls back to the memory. |
| Selection | The user ticks projects (account + project GUID). They are saved in the memory and nothing is ticked by default. Folders are not in the journals (open question). |
| Links | The host's link list comes from the memory while its `cache_mtime` equals the host copy's mtime. Otherwise one background open of the host's cache file through `read_model(..., links=True)`, from the modal window, when Export or Choose views… is clicked; the result is stored. Each link is found by `LinkedModelProjectId` + `LinkedModelModelId` across the whole cache, under the `RevitLinkType` name (`.rvt` added when missing). Nested links are included. |
| Staging | Flat folder `<run>\model\` (the tested layout: host and links side by side), host first. Names are unique without regard to case: a later clash is not copied, "Link {0} was not copied: another file in this export has the same name." / "Nie skopiowano linku {0}: inny plik w tym eksporcie ma tę samą nazwę." A link missing from the cache: "Link {0} is not in the cache; exported without it." / "Linku {0} nie ma w pamięci podręcznej; wyeksportowano bez niego." |
| Copy safety | Sources opened `rb` only. A destination is created new and never overwritten. After each item: the destination size equals the source size, and the source size and mtime have not changed since planning; otherwise the job fails with "The cache file changed while it was copied. Export again." / "Plik w pamięci podręcznej zmienił się podczas kopiowania. Wyeksportuj ponownie." Free space is checked first. |
| After the run | Staged copies are removed once the process tree has exited (open question 1); `model\stage.json` keeps the names, sizes and cache dates. |
| Fallback command | `RememberCloudModel.pushbutton` (context `doc-project`): reads the open cloud model's GUIDs, names (`Autodesk Docs://<project>/<file>.rvt`) and links into the memory. Read-only on the document; no transaction. |

**Memory.** `%APPDATA%\RevitExtractor\cloud-catalog.json`: `version`, `included`, `projects`, `names`, `links`. Saved through a temporary file, like `catalog-cache.json`. A missing, corrupt or other-version file gives an empty memory and never raises. It holds client project and file names: never in the repo, never in logs, and the kit prints counts only.

## Revit API and host facts to verify (`revit-api`, revisions 2022 and 2026, before coding)

| Member or fact | Use |
| --- | --- |
| `Document.IsModelInCloud`, `Document.GetCloudModelPath()` | fallback command |
| `ModelPath.CloudPath`, `.GetProjectGUID()`, `.GetModelGUID()`; `ModelPathUtils.ConvertModelPathToUserVisiblePath` | fallback names |
| `RevitLinkType` with `OfClass`, `.IsNestedLink`; `Element.Name` under IronPython (reflection fallback) | link names |
| `Element.GetExternalResourceReferences()` (declared on `Element`, not on `RevitLinkType`), `ExternalResourceReference.GetReferenceInformation()` | link GUIDs. The keys `LinkedModelModelId`, `LinkedModelProjectId` and `LinkedModelRegion` were observed on Revit 2022 (archive section 5) and are **undocumented** (the docs describe only a `(String, String)` map) |
| `OpenDocumentFile` on a cloud model in place (`DoNotDetach`; `CloseAllWorksets` for Choose views, `OpenAllWorksets` for the export open) | behaviour, owner's test only |
| .NET `System.IO.DriveInfo.AvailableFreeSpace`, and its assembly for `rx_dotnet` on .NET 8 | free-space check |
| IronPython: the `mbcs` codec exists; `io.open` reads a journal that the running Revit holds open | journal reading |
| pyRevit 6.5.5: `context: doc-project` | fallback button. Use the form the Export bundle already uses, `context:` + `rule: "doc-project"`; a bare `context: doc-project` string is not exercised in this repo |

### API facts (checked 2026-11-16)

Source: `revit-api` offline docs, `--python ironpython2.7`. 2022 = CHM `b8ee0868071c9e79` (ADN-DevTech/revit-api-chms, commit `e5347c6f`); 2026 = CHM `441dcbf9ce355456`. Member id = `<revision>:<chm>:<suffix>`; the suffix is the same in both revisions. A documentation hit is not a run in Revit. Rows were also searched in 2023, 2024, 2025 and 2025.3 for the five members marked (*): all five exist there under the same name.

**Revit API rows (all documented in 2022 and 2026; none contradicts the table, one wording fixed in the `GetExternalResourceReferences` row):**

| Member | 2022 / 2026 | Signature (docs) | Id suffix | Notes for IronPython 2.7 code |
| --- | --- | --- | --- | --- |
| `Document.IsModelInCloud` | yes / yes | `bool IsModelInCloud { get; }` (Since 2019.1) | `737478a4…` | Read it as a property: `doc.IsModelInCloud`. |
| `Document.GetCloudModelPath` (*) | yes / yes | `ModelPath GetCloudModelPath()` | `1677ad71…` | Raises `InvalidOperationException` on a non-cloud document, so test `IsModelInCloud` first. Disposable: `ModelPath` implements `IDisposable`. |
| `ModelPath.CloudPath` | yes / yes | `bool CloudPath { get; }` (Since 2019) | `888309f5…` | Property, not a method. Sibling `ModelPath.ServerPath` is also a bool property. |
| `ModelPath.GetProjectGUID` | yes / yes | `Guid GetProjectGUID()` | `efcc43cb…` | Returns `System.Guid`; docs say "BIM 360 Docs or Autodesk Docs project". Format it with `str(g).lower()` (no braces) before comparing with cache folder names. The docs do not say what it returns for a non-cloud path. |
| `ModelPath.GetModelGUID` (*) | yes / yes | `Guid GetModelGUID()` | `804e54c2…` | Same as above. |
| `ModelPathUtils.ConvertModelPathToUserVisiblePath` | yes / yes | `static string ConvertModelPathToUserVisiblePath(ModelPath)` | `4641be1e…` | The `Autodesk Docs://<project>/<file>.rvt` shape is **not** in the docs: it is an observation, so the fallback command must parse defensively and never raise. |
| `RevitLinkType.IsNestedLink` | yes / yes | `bool IsNestedLink { get; }` | `8546abcd…` | `FilteredElementCollector(doc).OfClass(RevitLinkType)` is the same call the legacy button already uses. |
| `Element.Name` | yes / yes | `string Name { get; set; }` | n/a | On element types IronPython often fails to read it. Reuse `element_name()` in `ExportSetupLegacy.pushbutton/config.py` (try `.Name`, fall back to `clr.GetClrType(DB.Element).GetProperty("Name").GetValue(e, None)`). Verified in the owner's Revit 2022 session (probe output), not in docs. |
| `Element.GetExternalResourceReferences` (*) | yes / yes | `IDictionary<ExternalResourceType, ExternalResourceReference> GetExternalResourceReferences()` (Since 2015) | `eb1542ee…` | **Declared on `Element`**; `RevitLinkType` inherits it. Raises `InvalidOperationException` when the element uses no external resource. 2022 text: "full map"; 2026 text adds: with several references per type, only the first is in the map. Singular `Element.GetExternalResourceReference(ExternalResourceType)` also exists (suffix `a1a5503f…`). The dictionary is keyed by `ExternalResourceType`, so iterate `.Values` (or `.Keys`) without importing the type. |
| `ExternalResourceReference.GetReferenceInformation` | yes / yes | `IDictionary<string, string> GetReferenceInformation()` | `d5f544dd…` | Returns a copy. The docs name no keys: `LinkedModelModelId`, `LinkedModelProjectId`, `LinkedModelRegion` (and `ForgeDmItemUrn`, `ForgeDmProjectId`) are observed only on Revit 2022, and may change or be missing on other years. Treat every key as optional (`dict.get`), and keep the case where an id is missing (the row is then "not in the cache"). Values are strings, not `Guid`s. |
| `Application.OpenDocumentFile` | yes / yes | `Document OpenDocumentFile(string)`, `(ModelPath, OpenOptions)`, `(ModelPath, OpenOptions, IOpenFromCloudCallback)` (the last since 2019) | `8cfc6373…` (overload list) | Only the `(ModelPath, OpenOptions)` overload takes options. Opens into memory, not visible. |
| `FilePath(string)` | yes / yes | constructor `FilePath(String)`; `FilePath : ModelPath` | n/a | The way to turn a cache file path into a `ModelPath` for `OpenDocumentFile`. |
| `OpenOptions.DetachFromCentralOption` (*) | yes / yes | property of type `DetachFromCentralOption` | `55971294…` | Doc text: for "a workset-enabled document". Enum values (identical in 2022 and 2026): `DoNotDetach` 0, `DetachAndPreserveWorksets` 1, `DetachAndDiscardWorksets` 2, `ClearTransmittedSaveAsNewCentral` 3. Whether a cloud cache file counts as detachable, and what `DetachAndPreserveWorksets` does to it, is **not in the docs**: owner's test only (as the row says). |
| `OpenOptions.SetOpenWorksetsConfiguration` and `WorksetConfiguration` | yes / yes | `void SetOpenWorksetsConfiguration(WorksetConfiguration)`; `WorksetConfiguration()` (opens all user-created worksets) and `WorksetConfiguration(WorksetConfigurationOption)` | `43056d85…` (class) | `WorksetConfigurationOption` exists in both. The archive's `WorksetConfiguration(CloseAllWorksets)` plan is consistent with the docs. |
| `ModelPathUtils.ConvertCloudGUIDsToCloudPath` (*) | yes / yes | `static ModelPath ConvertCloudGUIDsToCloudPath(string region, Guid projectGuid, Guid modelGuid)` | n/a | Not in the table. Exists for 2022-2026; it is the open-by-GUID route the archive mentions, and is not needed for the copy-from-cache design. Regions: `ModelPathUtils.CloudRegionUS` / `CloudRegionEMEA` (Since 2021). |

**Consequences for the plan.**
- `read_model(..., links=True)` and `collect_cloud_links` must use `link_type.GetExternalResourceReferences()` (inherited from `Element`); `ExternalFileUtils.GetExternalFileReference` throws for cloud links on 2022 (archive section 5), so do not call it on the cloud path.
- Any `ModelPath` obtained from the API is `IDisposable`; the fallback command should read the three values and not hold the object.
- No member in the table is missing from 2022 or 2026. Revisions after 2026 are not indexed: unverified.
- Contradiction with the table: none in the API. The only change is that the `GetExternalResourceReferences` row now names `Element` as the declaring class, and states that the three key names are undocumented rather than "probably".

**Non-Revit rows (repo and docs check; nothing here was run).**

| Row | Established | Unverified |
| --- | --- | --- |
| `System.IO.DriveInfo.AvailableFreeSpace` on .NET 8 | `lib/rx_dotnet.py` lists `NET_CORE_ASSEMBLIES` (Process, FileVersionInfo, Net.Primitives, Net.Sockets, ObjectModel); `DriveInfo` is not among them, and the module is itself marked "UNVERIFIED on a real Revit 2025+". `ensure_assemblies` is a no-op below .NET 5 and never raises. | Whether `from System.IO import DriveInfo` works on .NET 8 without `clr.AddReference` (this repo has no evidence; on .NET Framework it is in mscorlib). Not checked in the Revit API docs (not a Revit API). Safe design: wrap in try/except and treat a failed query as "space unknown, continue and let the copy fail". Do not add an assembly name to `NET_CORE_ASSEMBLIES` without a .NET 8 run. UNC paths and a non-drive-letter target: `DriveInfo(path)` needs a drive root, so decide what happens for them (not covered by the spec). |
| IronPython `mbcs` codec; `io.open` on a journal the running Revit holds open | The repo's own file reads are `io.open(..., encoding="utf-8")` and `open(path, "rb")` only (`rx_catalog.py:182`, `rx_status.py:166`, `rx_runner.py:290`). Nothing in the repo uses `mbcs` or opens a live journal. The spec's `decode_journal` already reads bytes and falls back on its own. | The `mbcs` codec in IronPython 2.7 on Windows: not checked here (this machine has no IronPython; tests run on CPython 3). Do not depend on it: decode the ANSI fallback with an explicit code page (`cp1250`, then `latin-1`, which cannot fail) as criterion 2 already tests. Share mode: open with `open(path, "rb")` and expect `IOError` when Revit holds a lock without sharing; the spec's "unreadable files skipped and counted" covers it. Whether Revit's active journal can be read at all is for the owner's session. |
| pyRevit 6.5.5 `context: doc-project` | `Export.pushbutton/bundle.yaml` uses `context:` + `rule: "(zero-doc)&!(doc-project|doc-family)"`, and `specs/SPEC-export-button.md` records that pyRevit 6.5.5 passes `rule` through and that `doc-project` tests `UIApplication.ActiveUIDocument` (source read, not run). The owner's Revit test item A1 (`specs/v1-revit-test.md`) shows the Export button greyed with a model open, so `doc-project` inside a `rule` works in 6.5.5. | A bare `context: doc-project` string (no `rule:`) is not exercised here: use `rule: "doc-project"`. Whether `doc-project` stays true for a cloud model opened from ACC (it should, it is a project document), and the exact enabled/disabled behaviour with a linked-only or family document, are not tested. |

## Acceptance criteria

1. `parse_journal` on synthetic fixtures: both line formats, one and two backslashes, a URL-encoded name, `GLOBAL` and all-zero GUIDs skipped, upper-case and braced GUIDs normalised, broken JSON skipped, unrelated lines ignored.
2. `decode_journal`: UTF-16 with BOM, UTF-8 with Polish letters, cp1250 bytes; never raises. `iter_journals`: newest first, `limit`, unreadable files skipped and counted.
3. `scan_cache` on a temp tree: `root` and `linked`, `CentralCache` ignored, non-GUID names ignored, two accounts, missing root reported and not raised.
4. The catalog produces each state and the newer-of rule. **No displayed text (name, project, note, counts) matches the GUID pattern.** Unnamed files are counted only.
5. Memory: round trip, the three empty cases, the newest-name rule, saving through a temp file, `links_for` invalid after the host mtime changed.
6. `plan_stage`: host first, cross-project link lookup, a missing link, a case-insensitive clash, `.rvt` added.
7. `copy_steps`: identical bytes. Read-only sources keep size, mtime and SHA-256. An existing destination raises. A source changed during the copy fails. Closing the generator early raises nothing. `check_space` refuses when space is short.
8. `rx_reader` with strict stubs: `collect_cloud_links` touches only the members above; `links=True` still calls `Close(False)` exactly once; `links=False` touches no link member.
9. `rx_runner`: `queued` → `staging` → `running`. Each `poll` stays within its budget. Cancel during staging gives `cancelled` with no process started. A failed copy fails that job and the queue goes on. The same `model_key` never runs twice. Staged copies are removed only after exit. Every existing runner test still passes.
10. Export window with WPF stubbed: a Cloud tab with a projects card; disabled rows cannot be ticked; Export builds jobs with `stage` and `model_name`; Choose views… reads with `links=True` and stores the links; the no-journal message appears; no per-row subscription.
11. Fallback command with stubs: a non-cloud document gives a message and writes nothing; a cloud document stores its names and links; no transaction.
12. Text in both languages; XAML keys and `UI_TEXT` match; AST purity of `rx_cloud`; the IronPython syntax guard passes; no Revit version in any name.
13. Privacy guard: every GUID under `tests/` is in the synthetic allow-list (repeated-digit patterns), and fixture names are invented.
14. Integration on this machine: a fake cache tree in `%TEMP%` (Dynamo sample saved as `<GUID>.rvt`) plus a synthetic journal. Stage, then a real Extractor run: result `ok`, sample SHA-256 unchanged.

## Commands

As `SPEC-export-button.md`, plus:
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\run_extractor_integration.ps1 -Cloud
```

## Testing

- New `tests/test_cloud.py` and `tests/test_cloud_stage.py`, plus amended `test_reader.py`, `test_runner.py`, `test_status.py` and `test_export_button.py`. Fixtures in `tests/fixtures/cloud/` are synthetic only.
- **Not verifiable here** (no ACC model, no pyRevit): real journal lines on any year but 2022, the background open of a cache file, the 28-link mapping, copy speed next to a working Revit, link geometry in federated views, the fallback button. All of these go to the owner's Revit 2022 session (checklist Part H).

## Boundaries

- Never write, rename, move or delete anything under `CollaborationCache` or `Journals`. Never use `CentralCache`.
- No network, no APS, no Desktop Connector.
- No GUID as a name; no client name in the repo, logs, kit output or test fixtures.
- No Python threads; the copy is a time-sliced generator.
