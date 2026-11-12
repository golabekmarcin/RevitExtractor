# HANDOVER: where the work stands

For any AI agent (Claude, Codex, ...) or person picking this up. **Read `CLAUDE.md` first** (project rules), then this file. Update it at each milestone and at the end of every session. Facts are dated; re-check repo state with `git status` / `git log`.

Last updated: 2026-11-11, session 4 (Claude Code, with the repo owner Marcin Golabek).
The full earlier text (decisions Q1-Q29, D1-D13, established facts, verification record, gotchas) is in `specs/HANDOVER-archive.md`. Read its sections 5 and 6 before touching the runner, the cloud code or the tests.

## Goal

One pyRevit button (**Export**) runs the whole Extractor workflow from Revit with no model open: pick models, optionally views, queue, status window. Specs and plans: `specs/` (`SPEC.md` is the map). v1 stops after `export-button`; cloud (ACC, copy from the cache) is v1.1, the IFC command v1.2.

## Current state (2026-11-11)

- **All v1 modules are built and committed locally on `mgo-changes`, not pushed**: shared-ui, capabilities, index-builder, model-catalog, model-reader, export-runner, status-window, export-button (`Export.pushbutton`). Last commits: `f2597a7` (Export button), `7e68ebc` (Codex review fixes).
- **Task 9 of `specs/plan-export-button.md` is done but uncommitted:** `tests/v1_test_kit.ps1`, the final `specs/v1-revit-test.md`, READMEs (Export button EN/PL, `Setup.panel`, `lib` EN/PL), `CLAUDE.md`, this file, `specs/HANDOVER-archive.md`.
- **2026-11-12:** Open in Analyzer now shows a Node.js notice (EN/PL, "Don't show this again", flag in `%APPDATA%\RevitExtractor\preferences.json`) when the local Analyzer is unavailable; `Analyzer\Start-Analyzer.cmd` sets `NODE_USE_SYSTEM_CA=1` so a company proxy certificate works. 577 unit tests, 6 XAML PASS, Codex review clean. Not run in Revit: checklist item C14.
- **Owner's Revit test (2022 + Extractor 2025.3), partial, 2026-11-12:** A1-A3, B1-B7, C1-C11 pass (C6 needed the `dumps_ascii` fix for Polish paths; C3 needed `Start-Analyzer.cmd` for npm). C12 open: after closing Revit the Extractor processes kept running (by design); still need how long they took and the `-Check` result. C13-C16 and Parts D-G not run. Added since: status-window right-click menu (C15), Clear finished (C16).
- Checks on the main machine (Revit 2023, no pyRevit): **554 unit tests OK**; `validate_xaml.ps1` 5 PASS; `run_extractor_integration.ps1` normal PASS and `-Cancel` PASS (parallel FAIL, fixed pipe); kit `-Setup` and `-Check` run for real.
- **Never run in Revit or IronPython.** Everything inside Revit is unverified: the greying, pickers, `BasicFileInfo.Extract` from the scan timer, the background open, the status window's hand-over between script engines, closing Revit during an export, Polish text in the real windows. That is the one test: `specs/v1-revit-test.md`.

## Reviews

**No review is pending.** Codex reviewed the commits up to `f2597a7`; its fixes are in `7e68ebc`. This Task 9 diff (docs and a test script) has not had a Codex review: run `codex review --uncommitted` before the commit that completes the feature (global CLAUDE.md).

Known **unfixed** Codex findings (accepted for v1, fix after the owner's test):
- (a) `rx_runner`'s hold check races between two Revit sessions that start exports at the same moment, and it does not see `cmd.exe` before `RevitExtractor.exe` starts. Two Extractors could then start and collide on the fixed pipe.
- (b) the `finally` block of `run_extractor_integration.ps1` does not kill owned Extractor processes on an early exit (a test-script issue only; the script checks for leftovers at the start of the next run).

## Next steps

1. Codex review of the uncommitted Task 9 diff; fix findings; commit locally (use `git commit -F <file>`).
2. The one push of `mgo-changes` is pre-approved (owner, 2026-11-11). **Never push to `online` or upstream.** Then send the owner `specs/v1-revit-test.md`.
3. After the owner's results: README Validation sections, `TESTED_YEARS` (add 2025 if Part F passes), `PARALLEL_VERIFIED` (only if item G2 passes; today the Extractor build 2024.0.x fails with two at once), the question about deleting the old buttons (Q12), and the two findings above.
4. Nice to have after v1 (owner): Revit Server (`RSN://`) models; an always-enabled "Export status" button (D8 option B); parallel exports (if G2 fails: research per-run isolation around the fixed pipe `Main_Process_to_Client_0_Pipe`).

## Key decisions

- Owner's working mode: agent writes and builds the module specs, one Revit test at the end of v1, a local commit per module, one push before that test.
- D1-D13 are confirmed (2026-11-11); see the archive. Cloud: copy from the `CollaborationCache` (Q29). Exports run one at a time (Q28). Models in a newer Revit are greyed out; older ones get a warning.
- The export queue lives in AppDomain data and only JSON text crosses between script engines (`SPEC-status-window.md`).
- Capabilities: one code base, a table keyed by Revit year; `TESTED_YEARS = (2022,)`.

## Gotchas

- **Privacy:** cloud reports, `catalog-cache.json`, the pyRevit config and `test-*` folders hold client names and paths. Results go to the agent privately, never into git. The public fork once received such a file (2026-11-09; archive section 1). **On the Revit 2022 machine, never `git pull`:** run `git fetch origin; git reset --keep origin/mgo-changes` instead.
- Windows PowerShell 5.1 reads UTF-8 without BOM as ANSI: pass `-Encoding UTF8`, or keep scripts ASCII (the kit does, and builds Polish letters from character codes).
- Passing a `Get-ChildItem -Path 'dir *' -Recurse` wildcard does not descend into the matches: enumerate the directories first.
- pyRevit `forms.Reactive` shares one `PropertyChanged` handler list across all instances: never subscribe per row.
- Tests add the legacy bundle to `sys.path` with append, never insert. Commit messages with quotes: `git commit -F <file>`.
- Old buttons are unchanged and stay until Q12. `git diff --stat` must not touch them.

## How to run and test

Commands and last verified results: `CLAUDE.md` (Commands). Unit tests: `python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v`. Owner's session: `specs/v1-revit-test.md`, kit `tests/v1_test_kit.ps1` (`-Setup`, `-Check`, `-Stamp`).
