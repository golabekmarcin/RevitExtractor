# HANDOVER — where the work stands

For any AI agent (Claude, Codex, …) or person picking this up. **Read `CLAUDE.md` first** (project rules), then this file.
**Update this file at the end of every session.** Facts here are dated; re-check anything about the repo state with `git status` / `git log`.

Last updated: 2026-11-09 (Claude Code, session with the repo owner Marcin Golabek).

## 1. Repo and branch state

- Fork `origin` = `golabekmarcin/RevitExtractor`. `upstream` = `kopecp/RevitExtractor`, push disabled. Never push upstream.
- Work branch: `mgo-changes`, all pushed to `origin` (2026-11-09):
  - `0997b78` Fix disabled property DB for Extractor 2024.0.x parsers
  - `e45ef00` Extend legacy export setup button to Revit 2022–2025, English/Polish
  - `144b297` Add CLAUDE.md project rules and RevitRAG target config
  - next commit: Add cloud model check, Explorer-style view selection and handover. It contains:
    - the Shift+click probe: `config.py`, `extractor_cloud_probe.py`;
    - `SelectionMode="Extended"` and Space/checkbox ticking;
    - `HANDOVER.md` and `AGENTS.md`.
- Nothing uncommitted at that point. Check `git status` anyway.
- Stable/default branch decision: `online` (also deploys GitHub Pages). Merge there only after verification. The fork's default branch has not been switched yet.

## 2. Verification (commands in `CLAUDE.md`)

Last run 2026-11-09 on the main machine, which has Revit 2023 only and no pyRevit:
- pyRevit unit tests: **69 OK**.
- `tests/validate_native_legacy.ps1`: **9/9 PASS** with the Revit 2023 parser (Extractor 2024.0.2022.0415).
- Analyzer `npm run check` OK; `npm run test:pages` 15 pass, 1 skip (expected).

**Never verified:** anything inside Revit/pyRevit (the button, the window, the localized `bundle.yaml`, the Shift+click check), the 2024/2025 parsers, and real exports.

## 3. Waiting on the owner's Revit 2022 + pyRevit machine

1. Pull `mgo-changes`, then run `validate_native_legacy.ps1`. Expect a `Parse (2025.3+)` shape. The `no-database` profile shows whether the 2025.3 parser accepts `3dviewing.db_export`.
2. After Reload pyRevit, only one "Export setup" button shows in Revit 2022. Delete any old `ExportSetup22.pushbutton` copy first.
3. The window is fully English or fully Polish depending on the pyRevit language setting. Searching "sheets" or "arkusze" finds sheets. The database note appears with 3D off and SQLite off, and stays after saving.
4. Multi-select: Shift/Ctrl/Ctrl+A select rows; Space or a checkbox ticks all selected rows. Needs the uncommitted work pushed first.
5. **Cloud check:** Shift+click with an ACC model that has cloud links open, and send the report. That report decides the cloud design (§5, Q27). Needs the uncommitted work pushed first.

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
  - Cache layout (Autodesk article, not yet observed here): `%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit 20xx\CollaborationCache\<account>\<projectGUID>\<modelGUID>.rvt`.
  - Journals contain `CLD://{projGUID}(ProjectName)/{modelGUID}(Model.rvt)`.
  - Desktop Connector can't host cloud workshared models.
- **Style reference:** FamilyManager uses `family_standards_resources.xaml` (light palette: `FsAccent #0A64D8`, `FsWindowBackground #F5F5F7`, `FsText #1D1D1F` …), merged after load, so windows use `DynamicResource` only. Our window already uses `DynamicResource` for its English/Polish text.

## 6. Gotchas learned the hard way

- Windows PowerShell 5.1 reads UTF-8 without BOM as ANSI. Always pass `-Encoding UTF8` (`Get-Content -Raw -Encoding UTF8`); otherwise Polish text gets garbled in any artifact you build.
- Passing cmdlet output (e.g. `Join-Path`) to .NET reflection fails ("Constructor not found") unless cast with `[string]`: it is wrapped in a `PSObject`.
- Python tests add the legacy bundle to `sys.path` with **append**, never insert: the 2026 bundle's tests import same-named modules.
- A git commit message with quotes breaks in PS 5.1 here-strings. Use `git commit -F <file>`.
- `ui.xaml` comments must not contain the literal `{DynamicResource word}`: a test counts it as a key.
