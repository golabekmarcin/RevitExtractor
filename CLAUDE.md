# RevitExtractor

> **Current state, decisions and next steps live in `HANDOVER.md`.** Read it at the start of a session and update it at the end. `AGENTS.md` points other agents here.

Tooling around Autodesk's native **Revit Extractor** (`RevitExtractor.exe`, shipped with Revit).
Three independent parts:

| Part | Path | Runtime |
| --- | --- | --- |
| Analyzer: browser viewer for export output (SVF 3D, PDF, properties, SQLite) | `Analyzer/` | Node.js 24+ (ESM, `"type": "module"`), browser JS without a bundler |
| Export launcher (interactive PowerShell, picks Revit version → index → RVT → output folder) | `Analyzer/public/downloads/Start-RevitExport.ps1` | Windows PowerShell 5.1 |
| pyRevit "Eksport setup" buttons that generate `index.json` | `pyRevit/Extractor.extension/RVTExtractor.tab/Setup.panel/` | **IronPython 2.7** inside Revit |

`extractorScript_v1.ps1` at the root is only a legacy shim that forwards to `Start-RevitExport.ps1`. Put launcher logic in `Start-RevitExport.ps1`.

## Target Revit versions

**2022 through the newest Revit release available** (decided 2026-11-09). 2022 is the compatibility floor.
Current coverage:
- launcher: any year (no fixed list)
- pyRevit `ExportSetupLegacy`: 2022–2025 (closed range)
- pyRevit `ExportSetup`: 2026+, with no `max_revit_version`, so it also opens on 2027+. All 58 Revit API members it uses have exact matches in the 2026 docs (checked 2026-11-09). There are no docs for later versions. It is still Polish-only and has no scripted native-parser check, unlike `ExportSetupLegacy`. Its `build_index` still iterates a string selection per character (`"abc"` → `['a','b','c']`) and raises `TypeError` for an unknown scope. `ExportSetupLegacy` fixed both (2026-11-09).

**Cloud (ACC) models: design open** (decided 2026-11-09: probe first, then the pyRevit button will prepare the files).
- Shift+click on `ExportSetupLegacy` (`config.py` → `extractor_cloud_probe.py`) prints, read-only:
  - model and link paths, cloud project/model GUIDs;
  - file names in `%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit <ver>\CollaborationCache` that contain those GUIDs.
- Known facts: the Extractor's `ResolveLinkfileTask` finds links **by file name**, searching folders depth-first. The cache uses GUID file names in an undocumented layout.
- The two candidates are copying from the cache into a staging folder under real link names, or detached save-as through the API. Don't implement either until the probe output from a real ACC model is in.

One installed Revit is enough for verification. Treat other versions as behaving similarly (user decision, 2026-11-09).
One known exception: the `index.json` parser shape follows the **Extractor build**, not the Revit year.
- builds 2024.0.x: `view_ids` Int32, property DB key `3dviewing.db_export` (default on), no `Parse`
- builds 2025.3+: `properties_data.pdb` / `PropertyDbStorageType`

Prefer indexes that both parser shapes read correctly. Findings: `pyRevit/.../Setup.panel/VERIFICATION-2023.md`.

## Commands (verified 2026-11-09, Node 24.20, Python 3.14)

```powershell
# Analyzer (run inside Analyzer/)
npm ci --ignore-scripts --omit=optional
npm run check        # node --check on every JS module
npm run test:pages   # tests that need no private export; this is what CI runs
npm run build:pages  # → Analyzer/dist (copies public/ + vendored pdf.js, sql.js wasm)
npm start            # local server on http://127.0.0.1:4317
npm test             # all tests; the server tests need the private Snowdon export under ../test-*/output

# pyRevit (run from the repo root)
python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v
# Native-parser check for the 2022-2025 button. Auto-picks the first Revit 2022-2025
# Extractor and handles both parser shapes. Verified 2026-11-09 on Revit 2023 (9/9 pass).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\validate_native_legacy.ps1
# Launcher dry run (no Revit started, no folders created). Needs a local Revit install
# with RevitExtractor; -ModelPath and -OutputParent are mandatory.
# Verified 2026-11-09 against Revit 2023 with a Dynamo sample RVT from C:\ProgramData\Autodesk\RVT 2023\.
.\Analyzer\public\downloads\Start-RevitExport.ps1 -RevitVersion 2023 -ModelPath 'D:\P\Model.rvt' -OutputParent 'D:\Exports' -ValidateOnly
```

On a machine without `test-*` exports, `test:pages` skips 1 test ("actual Snowdon sources…"). That is expected.

## Architecture notes

- **Two Analyzer modes, one interpretation.** The local server (`server.mjs` + `lib/`) and the GitHub Pages build (`public/browser-backend.js`, `local-*.js`, service worker, web worker) must parse exports the same way. Shared logic lives in `public/property-index.js` and `public/source-model-index.js`; `lib/properties.mjs` and `lib/source-models.mjs` import or re-export it. Change the shared module, not a mode-specific copy.
- Pages mode cannot open `file://`. Serve `dist` over localhost or HTTPS, including under the `/RevitExtractor/` subpath.
- `dbId` is the per-export record id, **not** the Revit ElementId. Keep the two separate in UI and code.
- **No Revit versions in names** (folders, files, test classes, button/window titles); state the supported range in descriptive text instead. Exception: verification records of one specific install (e.g. `VERIFICATION-2023.md`).
- Pinned versions: Autodesk Viewer **7.130.0** (Autodesk CDN), `pdfjs-dist` 6.4.299, `sql.js` 1.15.2. Bumping any of them is a separate, deliberate change.
- pyRevit has two **self-contained** button folders that are copied into users' panels: `ExportSetup.pushbutton` (Revit 2026, IFC/DWG and IFC setup storage) and `ExportSetupLegacy.pushbutton` (Revit 2022–2025, numeric `view_ids`, no IFC/DWG on purpose). They do not import each other or the repo.
- Inside `ExportSetupLegacy`, user-facing strings go through `extractor_i18n.tr(english, polish)`. It calls pyRevit's `applocales.get_locale_string`, the same resolver pyRevit uses for `bundle.yaml` title maps, so the ribbon and the window always agree.
  - All static window text lives in `extractor_text.py` (`UI_TEXT`, `VIEW_KINDS`). `ui.xaml` refers to it only through `{DynamicResource ...}`, and a test enforces that the keys match both ways and that no literal label is left. Add new labels there, never in the XAML.
  - "Picks Polish" means pyRevit's language setting. The Revit UI language is deliberately **not** used: `user_locale` defaults to `""`, which resolves to English. `bundle.yaml` uses `en_us:`/`pl:` maps. Tests add that bundle to `sys.path` with **append**, never insert, because the 2026 tests import same-named modules by bare name. Before mirroring a fix from one to the other, check that the feature exists in the target variant.

## Code conventions

- pyRevit code must run on IronPython 2.7: no f-strings, no type hints, no `pathlib`, no Python 3-only stdlib, and no `#! python3` header. The tests run on CPython 3 against host stubs, so passing tests do **not** prove IronPython compatibility. Avoid 3-only syntax even when the tests pass.
- **Bilingual, English by default** (decided 2026-11-09). Every user-facing text (Analyzer UI, launcher prompts, pyRevit XAML and `bundle.yaml` titles, READMEs) must exist in English and Polish, and English is what users see unless they pick Polish. Most text is still Polish-only today. New or changed text must ship in both languages. Don't add English-only or Polish-only strings.
- Record manual or Revit-side verification in `Analyzer/docs/VERIFICATION-*.md`, or in the Validation section of the relevant README, following the existing format. State what was *not* verified.

## Revit API documentation (RevitRAG)

Use the `revit-api` skill (offline, `%LOCALAPPDATA%\Programs\RevitApiSearch\current\revit-api-search.exe`) for every Revit API claim in pyRevit code.
- `revit-api.json` in the repo root sets the default target: the 2022 floor, `ironpython2.7`.
- Indexed revisions (as of 2026-11-09): 2022, 2022.1, 2023, 2024, 2025, 2025.3, 2026. Versions after 2026 are not indexed (`E_VERSION_UNAVAILABLE`). Label API use for them as unverified against docs.
- For code meant to run on several versions, search each target revision explicitly, at least the 2022 floor and the newest indexed one.
- Known cross-version break: `ElementId.IntegerValue` is documented 2022–2025.3 but not in 2026; `ElementId.Value` is documented 2024–2026 but not in 2022–2023. No single property covers 2022–2026. Code spanning that range needs a version-dependent accessor. This matters for numeric `view_ids` (2022 button) versus `view_unique_ids`.

## Boundaries

- **Export data is read-only.** Never write to, copy or modify export folders or `model.sdb` (it is opened `readOnly`; a test checks its SHA-256). The local server binds to `127.0.0.1` only. Nothing uploads model data anywhere.
- `test-*` folders hold private client exports and are gitignored. Never commit them or paste their contents into public docs beyond the counts already cited.
- Root `index.json` is a project-specific sample, not the default config. The default index is embedded in `Start-RevitExport.ps1`. Leave `*.backup` files alone.
- Behaviour inside Revit (button execution, transactions, Undo, real exports) cannot be tested here. Say so in summaries. Never claim it was verified.

## Git and publishing

- `origin` = the fork `golabekmarcin/RevitExtractor`. `upstream` = `kopecp/RevitExtractor` (original author, push **disabled**). Never re-enable pushing to or open changes against upstream without an explicit request.
- Branches: work on `mgo-changes`. `online` is the published branch. There is **no `main`**; upstream also has `master`.
- `.github/workflows/pages.yml` deploys `Analyzer/dist` on every push to `online`. Pushing to `origin/online` publishes the fork's Pages site, so ask first. PRs to `online` and `master` only run the checks.
- Commit or push only when asked.
