# HANDOVER — where the work stands

For any AI agent (Claude, Codex, …) or person picking this up. **Read `CLAUDE.md` first** (project rules), then this file.
**Update this file at the end of every session.** Facts here are dated; re-check anything about the repo state with `git status` / `git log`.

Last updated: 2026-11-10, session 3 (Claude Code, with the repo owner Marcin Golabek): window slice 1 **verified in Revit 2022**; cloud cache-copy test **passed**; **cloud decision: copy from the cache** (Q29).

## 1. Repo and branch state

- Fork `origin` = `golabekmarcin/RevitExtractor`. `upstream` = `kopecp/RevitExtractor`, push disabled. Never push upstream.
- Work branch: `mgo-changes`, pushed to `origin`: `0997b78`, `e45ef00`, `144b297`, `4a41c58` (cloud check v1, multi-select, handover), `18ecea1` (ignore cloud reports).
- **Privacy incident, 2026-11-09:** the owner committed a cloud check report (client project name, model name, GUIDs, URN, Windows user name) as `b42b7b4` to this **public** fork.
  - It was removed by resetting to `4a41c58` and force-pushing (`--force-with-lease`), followed by `18ecea1`, which `.gitignore`s `cloudcheck*.html` / `cloudcheck*.txt`.
  - GitHub may keep the orphaned commit reachable by SHA until GitHub Support purges it.
  - **It happened again, same day (session 2):** the Revit 2022 machine still had `b42b7b4`. A `git pull` + push merged it back as `fa6349b` ("Merge branch 'mgo-changes' of …"), which re-added `tests/cloudcheck_output.html` (Autodesk Docs paths, 6 GUIDs, a URN, user paths).
    - Removed again: `git push --force-with-lease=mgo-changes:fa6349b origin 8de9788:mgo-changes`.
    - `git ls-remote origin` afterwards: only `master`, `online` and `mgo-changes` (`8de9788`). No tags or pull-request refs, and no branch contains `b42b7b4`.
    - `b42b7b4` and `fa6349b` may stay reachable by SHA on GitHub until GitHub Support purges them.
  - **Before any pull or push on the Revit 2022 machine:** `git fetch origin; git reset --keep origin/mgo-changes`, then delete `tests\cloudcheck_output.html`. **Never `git pull` there until that is done.** A plain pull merges the leaked commit back in.
  - The cloud check itself writes nothing; the HTML was saved by hand from pyRevit's output window. `.gitignore` blocks new reports, but not a commit that is already in local history.
  - **Cloud reports go to the agent privately, never into the repo.**
- Cloud check **v2** is committed and pushed as `8de9788`.
- **Window slice 1 (§3a) is pushed** as `85ebc6a` (2026-11-09, session 3) and **passed the owner's Revit 2022 test** (§2).
- The owner's Revit 2022 machine was reset to `origin/mgo-changes`. The v2 report was copied to this machine as an ignored `tests/cloudcheck_output_v2.html`, read, and **deleted** (never committed; `git status --ignored` was clean afterwards).
- The cache-copy test results (`cache-test-result.txt`, `journal-lines.txt`) reached this machine as untracked files in `tests/`. They were read and **deleted**, and `.gitignore` now also blocks `cache-test-result*.txt`, `journal-lines*.txt` and `RX-private/`.
- **Next session starts with:** the redesign spec, then the plan (§4). Local/server models come first (Q9), then cloud via the cache (Q29). Nothing is waiting on the owner (§3).
- The fork's default branch is still **`master`**. The owner switches it to `online` in GitHub → Settings → Branches (decision Q16/Q21).

## 2. Verification (commands in `CLAUDE.md`)

Main machine (Revit 2023, no pyRevit), 2026-11-09, after slice 1:
- pyRevit unit tests: **108 OK** (74 before slice 1);
- `ui.xaml`, `rx_theme.xaml` and `rx_search_bar.xaml` load in real WPF (Windows PowerShell). A render with sample rows looked right. No IronPython or pyRevit was involved;
- `validate_native_legacy.ps1`: **9/9 PASS** (Extractor 2024.0.2022.0415);
- Analyzer `check` OK; `test:pages` 15 pass, 1 skip.

**Owner's Revit 2022 + pyRevit machine, 2026-11-09** (pyRevit 6.5.5; Revit 22.1.80.32):
- `validate_native_legacy.ps1`: **9/9 PASS**, `ExtractorUtility.dll` 2025.3.0.12, shape `Parse (2025.3+)`. So the 2025.3 parser **accepts `3dviewing.db_export`**, and the `no-database` / `2d-only-no-database` profiles give `PropertyDbStorageType=None`.
- Only one "Export setup" button shows (it works), and the window language follows pyRevit (it works).
- Multi-select works, but there is **severe lag with 1000+ sheets on every select/unselect**. See §3a.
- **Window slice 1, session 3: all items PASS** on the 1000+ sheet model. Ticking, Select/Unselect all shown and Space are fast. The highlight survives multi-row ticks. The Type ▾ filter works. Search works: any word order, regex, the invalid-regex border, ✕ and Esc. Enter, Close and Esc work. The theme matches FamilyManager in English and Polish. No errors.
- **Cloud check v2: ran without errors** on the same ACC model (28 links). Findings are in §5 Cloud.
- **Cache-copy test, 2026-11-10: PASS.**
  - The host and 2–3 links were copied from the `CollaborationCache` (host from the project root, links from `LinkedModels\`), renamed to their real names, and exported with `Start-RevitExport.ps1` (default index, Extractor 2025.3.0.12).
  - `output\bubble.json` and `output\Resource\` exist, the "Resolve the link files." task reports `completed` (67 s), and 2D views, sheets and 3D views (including a federated view) were exported.
  - No central-model or worksharing errors. `stderr.log` was empty. The only noise was `WARN Failed to enable Error Recovery` and many "mesh number larger than 64k in svf file" notices, both harmless.
  - **Not captured:** the `Success Jobs`/`Failed Jobs` line (the guide's log filter kept only the first 40 matches, all mesh notices), and whether the copied links' geometry appears in the federated 3D view. Check both on the first real cloud export.
- Cloud check v1 on a real ACC model (Revit 2022, workshared), facts:
  - cache layout confirmed: `%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit 2022\CollaborationCache\<account id>\<project GUID>\<model GUID>.rvt`, plus `…\<project GUID>\CentralCache\<model GUID>.rvt` (same size, here 432 MB);
  - the model path is `Autodesk Docs://<ACC project name>/<file>.rvt` (ServerPath and CloudPath both True), and a URN is available.
  - **probe bugs:** all 28 link names were `ERROR: Name` (IronPython quirk), and the links showed no path, status or GUIDs. pyRevit's Markdown renderer merged all tables and dropped headings, so it was unclear whether those rows were missing or lost. v2 fixes all of this (§3).

**Never verified:**
- the 2024/2025 parsers;
- the copied links' geometry inside a cache-copy export (§2);
- real exports from the pyRevit button;
- the headless Extractor running next to an interactive Revit.

## 3. Waiting on the owner (Revit 2022 machine)

**Nothing open (2026-11-10).**
- Done in session 3: the git clean-up, the window slice 1 test (all PASS), the cloud check v2 report, the cache-copy test (PASS), the journal check and the cloud decision (Q29).
- The guide used for those checks stays in the repo for reuse: `pyRevit/…/Setup.panel/tests/cloud-cache-checks.html`, also published as a private claude.ai artifact (`https://claude.ai/artifact/9SGyLicjwoZNbtPsH5jWVF`).
  - Its source is not in the repo, so regenerate the repo copy if the page changes.
  - Known weakness: the result filter (`Select-Object -First 40`) can be swamped by "mesh number larger than 64k" notices and miss the `Success Jobs` line. Exclude `DSM_InternalErrorMessage` before reusing it.
- Results always come back privately, **never through git**.

**Next for the agent:** the redesign spec (`agent-skills:spec`), then the plan (`plan`). Local/server models first (Q9), then cloud via the cache (Q29). The real cloud export later must also check that the copied links' geometry is in the output (§2).

## 3a. Window slice 1 (agreed 2026-11-09; built 2026-11-09, pushed as `85ebc6a`, verified by the owner in Revit 2022)

**What was built** (ExportSetupLegacy only; the 2026 button is unchanged):
- **Lag root cause, confirmed in pyRevit source** (`pyrevitlib/pyrevit/forms/_ipy.py`): `Reactive` declares `PropertyChanged, _propertyChangedCaller = pyevent.make_event()` at **class level**, so all rows share one handler list. The old window added `_on_row_changed` per row (~3,000 handlers), so each tick fired all of them, and each rebuilt the JSON: O(N²).
- Fix as planned: `ViewRow(forms.Reactive)` with plain attributes plus a reactive `Checked`. Lists are an `ObservableCollection` behind a `CollectionView` filter. There are no row subscriptions: one `ButtonBase.ClickEvent` handler per ListView. Bulk changes use `set_quietly` and then one `Items.Refresh()`. JSON is built only while the preview tab is open and on save. A test guards against row subscriptions.
- Ported modules sit flat in the bundle with an `rx_` prefix, so they can't collide with FamilyManager's bare `search_bar` module in a shared engine: `rx_search_bar.py/.xaml` (scope combo dropped; plain search = every word), `rx_column_filter_model.py`, `rx_column_filter_ui.py`, `rx_search_placeholder.py` (inlined MGo dependency) and `rx_theme.xaml` (FamilyManager theme with `Fs*` renamed to `Rx*`, minus the two Rename-only entries, plus a GridViewColumnHeader style). All text uses `tr()`. When they move to the shared `lib/`, move these files unchanged.
- The view-type combo is gone; the Type column (index 2) has the ▾ filter. Labels are "Select all shown" / "Unselect all shown", and the hints say "highlight". Scope hints moved to tooltips. The footer is Reset | summary/status | Close (`IsCancel`) | Save (`IsDefault`, primary). A separate red `error_text` line was added, and `handle_esc=False` (as in FamilyManager).

Original owner feedback and plan:

Owner feedback on the view window and the plan. The ported pieces must move unchanged into the redesign's shared `lib/` later.

- **Lag:** a WPF harness on this machine (the real `ui.xaml`, 1,500 rows, C# row objects) measured 7–15 ms per select-all, tick-all or JSON-preview update, so the cost is on the IronPython side.
  - Rows are pyRevit `TemplateListItem`: `__getattr__` forwards to a dict, and `__bool__` = the tick state.
  - The window subscribes a handler to every row's PropertyChanged, replaces ItemsSource on every filter, and rebuilds the index plus the JSON preview on every tick.
  - **Fix: the FamilyManager pattern** (`workspace_ui.SelectionRow` / `SearchableMultiSelectWindow`):
    - `forms.Reactive` rows with explicit properties;
    - `ObservableCollection` + `CollectionView` filter;
    - no per-row subscriptions; checkbox Click → one refresh;
    - JSON preview built lazily (preview tab / save).
  - IronPython can't be measured here, so the owner confirms the speed on the real model.
- **Search bar:** port FamilyManager `lib/search_bar.py` + `search_bar.xaml`: regex, inline ✕ clear, "Clear all filters". Inline its `MGo_Custom.wpf_search_placeholder` dependency.
- **Column filters:** port `column_filter_model.py` + `column_filter_ui.py` (Excel-style header popups; they work on column headers).
- **Labels:** the tick buttons become **"Select all shown" / "Unselect all shown"** and act only on the filtered (shown) rows. Row highlighting (Ctrl/Shift/Ctrl+A) is then called "highlight" in hints, to avoid two meanings of "select".
- **Layout:** the view list is the main area; options (2D/3D/SQLite, advanced) become compact. Theme `lib/rx_theme.xaml` copied from FamilyManager with `Fs*` → `Rx*` (Q13/Q20).
- All new text in English and Polish.

## 4. Redesign — agreed decisions (grilling session 2026-11-09)

Goal: run the whole workflow from Revit through **one pyRevit button**, with no PowerShell for the user.

| # | Decision |
|---|---|
| Q1 | pyRevit is the main path. `Start-RevitExport.ps1` stays as a smaller fallback (website download). |
| Q2 | Install the whole `Extractor.extension` via pyRevit (git URL). Shared extension-level `lib/` replaces self-contained button folders. |
| Q3 | One button that adapts to the running Revit version: IFC/DWG only where that Extractor supports it; view IDs per version. |
| Q4/Q7 | The button works **only with no document open**. It lists models and reads the chosen one in the background **with all worksets closed** (detached, read-only, `Close(False)`). Lists: local = Folder \| File Name \| Revit Version; live cloud = Project \| File Name \| Revit Version. |
| Q6 | Non-blocking export: the Extractor runs as its own process and a modeless status window shows progress and the result, with Open output folder / Open in Analyzer. |
| Q8 | n/a under Q7. The running Revit's Extractor is used; version handling is in Q19. |
| Q9 | Local/server models first; cloud after the owner's probe report. |
| Q10 | Output `Documents\RevitExtractor\export-<date>-<id>\` (same layout as the `.ps1`), changeable and remembered. |
| Q11 | Open in Analyzer: the local Node Analyzer with the folder if Node.js exists, else the output folder plus the website. |
| Q12 | The new button replaces both old buttons; their logic moves to `lib/`. Old folders are deleted after the owner verifies in Revit 2022. |
| Q13 | Copy FamilyManager's theme (`MGo…\FamilyManager.pushbutton\family_standards_resources.xaml`) and rename it. |
| Q14 | FamilyManager window layout: header, toolbar card, tabs, error line, footer Reset \| Cancel (Esc) + primary (Enter). Search with inline ✕ and **regex** option. |
| Q15 | Background open is detached and read-only (see Q4/Q7). |
| Q16/Q21 | The stable default branch is `online`; develop on `mgo-changes`. |
| Q17 | Local list: one or more remembered root folders, recursive. Skip `*.000N.rvt`, `Backup` folders and local copies of centrals. Version from `BasicFileInfo.Extract` without opening. |
| Q18 | One model gets full view picking. Several models run as a batch, one after another, with the default scope or a shared `index.json`. |
| Q19 | Newer-version models are greyed out with a tooltip; older ones get a warning ("export upgrades a copy"). |
| Q20 | Theme keys `Rx*`, file `lib/rx_theme.xaml`. |
| Q22 | The new flow only **reads/picks** existing IFC setups (2026+). The model-writing "prepare IFC setup" becomes a separate small command used with a document open. |
| Q23 | Owner chose **parallel exports allowed**. Follow-up Q28 is open (collision risk). |
| Q24 | Closing the status window or Revit does not stop the export. A separate **Cancel export** button kills it. No history view in v1. |
| Q25 | The `.ps1` stays as it is: bug fixes only, plus cloud later only if it works without the Revit API. |

| Q26 | Grey out the button while a document is open: `context: {rule: "(zero-doc)&!(doc-project|doc-family)"}` plus a run-time check. The owner verifies the greying. |
| Q27 | Live cloud list = models already on this machine: the `CollaborationCache` plus Project/File names from Revit journals (`CLD://…` lines). Autodesk APS Data Management only later, if this proves too limited. |
| Q28 | Exports go into a **queue** (several can be started, they run one after another). Write a **parallel-run test** (two Extractor runs on small models, separate folders, check both succeed and nothing collides). Enable true parallel runs only if that test passes on the owner's machine. Keep max-parallel as a setting, default 1. |
| Q29 | **Cloud export = copy from the `CollaborationCache`** (decided 2026-11-10 after the cache-copy test passed). The owner opens these models daily, so the cache is fresh enough; downloading fresh copies would only add waiting. Copy the host from `<project>\<model GUID>.rvt` and links from `LinkedModels\<link GUID>.rvt` into a staging folder under their real names, then export. Show each file's cache date. Detached save-as through the API is not planned. |

**Owner's clarifications (2026-11-09):**
- **One code base, no per-version files.** Version differences live in code: a small capability table keyed by the running Revit and Extractor (`index.json` shape, IFC/DWG, IFC setups) plus feature checks (e.g. `ElementId.Value`/`IntegerValue`). A new Revit version should mean a table entry, not new files.
- **Version rule:** a model saved in a newer Revit than the running one is greyed out; an older one gets a warning (the export upgrades a copy). E.g. in Revit 2022 a 2024 model is greyed out; in Revit 2024 the 2022 model works with a warning. View picking on older models is slower (upgrade in memory, never saved).
- **Working during an export is allowed:** the export is its own process and the status window stays available. A new export can only be started with no document open. Add to the real-machine test (with Q28): the headless Extractor engine running next to an interactive Revit (licensing, shared settings), and opening the same model that is being exported.

**All design questions are answered and the shared understanding is confirmed by the owner (2026-11-09).** Next: confirm the shared understanding with the owner, then write a short spec/plan (`agent-skills:spec` / `plan`) before coding. **Nothing of the redesign is implemented yet.**

## 5. Established facts (with evidence)

- **Extractor CLI** (`Start-RevitExport.ps1` L259–285; reflection on the 2023 build): `RevitExtractor.exe "<runRoot\index.json>" "<model.rvt>" -RCEPath "<RevitDir>" -LogPath … -journalPath …`, working directory = Revit dir.
  - Output goes to `<index folder>\output`, which it **empties first** (`CleanDir`).
  - It copies the source RVT and may change the Print Spooler start mode.
  - It runs headless (`RevitExtractor_Client.exe` with RevitNET) and does not start `Revit.exe`.
  - Success = exit 0, `Success Jobs: N, Failed Jobs: 0` in `console.log`, plus `output\bubble.json` and `output\Resource\`.
- **Links:** `ResolveLinkfileTask` finds link files **by file name**, searching folders depth-first.
- **Parser shapes** (`pyRevit/…/VERIFICATION-2023.md`):
  - build 2024.0.x: `new IndexJson(path)`, `view_ids` Int32, DB key `3dviewing.db_export` (default on);
  - build 2025.3+: `IndexJson.Parse`, `properties_data.pdb` / `PropertyDbStorageType`.
  - Shape follows the Extractor build, not the Revit year.
- **ElementId:** `IntegerValue` documented 2022–2025.3; `Value` (Int64) documented 2024–2026.
- **pyRevit:**
  - `context: zero-doc` enables a button with no document; the negation syntax is above (Q26).
  - `*config.py` runs on Shift+click.
  - An extension-level `lib/` applies to all buttons.
  - `TemplateListItem.checked` raises `PropertyChanged("checked")` on change only.
  - `applocales.get_locale_string` resolves `bundle.yaml` `en_us`/`pl` maps and ignores the Revit UI language (`user_locale` defaults to `""` → English).
- **Cloud:**
  - Revit API 2022–2026 **cannot browse ACC**. It can open a known model via `ModelPathUtils.ConvertCloudGUIDsToCloudPath(region, projectGuid, modelGuid)` + `OpenOptions` + `WorksetConfiguration(CloseAllWorksets)`.
  - **Cache layout, observed in cloud check v2 (Revit 2022, real ACC project):** under `%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit 2022\CollaborationCache\<account id>\<project GUID>\`:
    - `<model GUID>.rvt`: models opened directly (local copies);
    - `CentralCache\<model GUID>.rvt`: their central cache;
    - `LinkedModels\<model GUID>.rvt` + `LinkedModels\CentralCache\<model GUID>.rvt`: models loaded **as links**.
    - One project folder held about 300 `.rvt` files, the largest 3.4 GB.
  - **Link → cache mapping works for all 28 of 28 links:**
    - each link's `RevitLinkType.GetExternalResourceReferences()` has `LinkedModelModelId` (= the cache file GUID), `LinkedModelProjectId` (= the project folder), `LinkedModelRegion` (`US`), `ForgeDmItemUrn` and `ForgeDmProjectId`;
    - every link GUID had a file in `LinkedModels\`.
    - Link file names come from the open host (`RevitLinkType` name), not from the cache.
  - **Freshness differs between copies:** a model that was opened directly *and* loaded as a link had a newer root copy than its `LinkedModels\` copy (days apart), and the root and `CentralCache` sizes differed for some models. The cache is not guaranteed current.
  - `ExternalFileUtils.GetExternalFileReference(doc, linkType.Id)` **throws for every cloud link** in Revit 2022 ("elemId does not represent an external file reference"). For cloud links use external resource references, not external file references.
  - **Journals (Revit 2022, checked 2026-11-10): the names are there, in a different format.** Revit 2022 does not write `CLD://{guid}(name)/{guid}(name)`, so the probe's `JOURNAL_RE` in `extractor_cloud_probe.py` matches nothing. The real lines are:
    - `ModelPath Created: Is server path = True, Region = "US", Central server = "", Path = "CLD:\\US\{<project GUID>}<project name>\{<model GUID>}<file name>.rvt"`. The project name is sometimes URL-encoded (`%20`). Lines with `Region = "GLOBAL"` and all-zero GUIDs also appear; skip them.
    - `Jrn.RibbonEvent "ModelBrowserOpenDocumentEvent:open:{""projectGuid"":…,""modelGuid"":…,""id"":""urn:…"",""displayName"":""<file name>"",""region"":""US"",…}"` (JSON with doubled quotes), written when a model is opened from the browser.
    - `Open Cloud Model Method: open, Region: US, Model Guid: <guid>, Project Guid: <guid>.`
    - One journal listed many models of the project with names, including links. So Q27's cloud list (Project | File Name from journals, matched to cache files by GUID) is feasible. The parser must handle these formats; fix or replace `JOURNAL_RE` when the code moves to `lib/`.
  - **Cloud export approach: copy from the cache (Q29, decided 2026-11-10).** The cache-copy test passed (§2).
    - The rejected alternative was detached save-as through the API (`ConvertCloudGUIDsToCloudPath` + `SaveAs`): always current, but slow with up to 28 multi-GB links.
    - Remaining risks: the cache can be stale for models not opened recently (show the cache date), and the layout is undocumented (fail clearly if a GUID has no cached file).
  - Desktop Connector can't host cloud workshared models.
- **Style reference:** FamilyManager uses `family_standards_resources.xaml` (light palette: `FsAccent #0A64D8`, `FsWindowBackground #F5F5F7`, `FsText #1D1D1F` …), merged after load, so windows use `DynamicResource` only. Our window already uses `DynamicResource` for its English/Polish text.

## 6. Gotchas learned the hard way

- Windows PowerShell 5.1 reads UTF-8 without BOM as ANSI. Always pass `-Encoding UTF8` (`Get-Content -Raw -Encoding UTF8`); otherwise Polish text gets garbled in any artifact you build.
- Passing cmdlet output (e.g. `Join-Path`) to .NET reflection fails ("Constructor not found") unless cast with `[string]`: it is wrapped in a `PSObject`.
- Python tests add the legacy bundle to `sys.path` with **append**, never insert: the 2026 bundle's tests import same-named modules.
- A git commit message with quotes breaks in PS 5.1 here-strings. Use `git commit -F <file>`.
- `ui.xaml` comments must not contain the literal `{DynamicResource word}`: a test counts it as a key. Theme keys must start with `Rx`; the text-key test skips them.
- pyRevit `forms.Reactive` / `TemplateListItem` share **one** `PropertyChanged` handler list across all instances. Never subscribe a window handler per row.
- The window tests pin the legacy `extractor_config` in `sys.modules` while loading `extractor_ui.py`, because the 2026 tests prepend a same-named module.
