# Spec: status-window

Module of `SPEC.md`. Depends on: `export-runner`, `shared-ui`. Status: **written under the owner's working mode of 2026-11-10**.

## Objective

One modeless window per Revit session that owns the export queue (Q6, Q24, Q28). It shows each export's progress and result, and offers Open output folder, Open in Analyzer (Q11) and Cancel export. It keeps working while the user works in Revit, after the main window closes, and after another button or a pyRevit reload replaces the script engine.

## Interface

`lib/rx_status.py`, pure (no `pyrevit`, `Autodesk`, `System` or `clr` import):

```python
progress_info(console_tail)          # {"task", "status", "percent"}; each may be None
job_view(job, info, now, position)   # plain dict for one row: texts, and which buttons apply
analyzer_plan(output, lib_dir, environ, exists, node_major, free_port)
                                     # ("local", LaunchSpec, url) | ("web", reason)
SessionCore(queue, clock)            # handle(request_json) -> response_json; ops: ping, submit, show
find_session(domain)                 # the published handler, or None when absent or stale
publish_session(domain, handler)
UI_TEXT, resources()                 # window text in English and Polish, as slice 1
SESSION_KEY, PROTOCOL, WEBSITE_URL
```

`lib/rx_status_ui.py` (WPF, IronPython only) and `lib/rx_status.xaml`:

```python
open_session(max_parallel)   # this Revit process's session handler; created on first use
Session                      # queue + StatusWindow + DispatcherTimer
StatusWindow(forms.WPFWindow)
```

Amendments to the built `rx_runner` (`SPEC-export-runner.md` gets the same lines):
- `Queue(..., hold=None)` and `Queue.held`: while no job of this queue runs and `hold()` is true, queued jobs wait. A failing `hold()` counts as false.
- `Queue.tail(job_id)`: the console tail as text, read-only.
- `clean_path` becomes public.
- `DotNetStarter.start(spec, show_window=False)` and `DotNetStarter.extractor_running()`.

## Where the queue lives

Facts from the pyRevit source, tag `v6.5.5.26237+2044` (the owner's version) and develop 7.1.0, read 2026-11-11. Read, not run: this machine has no pyRevit.

| Fact | Source file |
| --- | --- |
| The engine cache key is session id + engine type + extension, so all buttons of the extension share one cached IronPython engine | `ScriptEngines.cs` (`TypeId`) |
| `engine: clean: true` creates a new engine that replaces the cached one. The replaced engine gets `Shutdown()`: its pyRevit builtins become `None` and its output streams are disposed. Both old buttons set `clean: true` | `ScriptEngineManager.cs`, `IronPythonEngine.cs` |
| A pyRevit reload starts a new session id, so the old engines are dropped the same way | same |
| Without `persistent: true` only the script's own globals are deleted after a run. Imported modules stay | `IronPythonEngine.Execute` |

A module-level queue would therefore be lost to the next click after an old button or a reload, while its window and timer live on. Two queues would start two Extractors, which collide on the fixed pipe (`HANDOVER.md` §5).

Decision:
1. The session is published in **AppDomain data**: `AppDomain.CurrentDomain.GetData(SESSION_KEY)` holds one `System.Func[String, String]`, the session's `handle`.
2. **Only JSON text crosses.** The button sends `{"op": "submit", "jobs": [{"model_path", "index", "revit_dir", "output_parent"}]}` and gets `{"ok", "added", "errors"}` back. No Python object, class or exception type is shared between engines.
3. Session code may run in an engine that was shut down. It never prints, never uses pyRevit's logger or output, and never imports `pyrevit.script`. Every timer tick and event handler catches its errors and shows them on the window's error line.
4. A handler that raises, or answers with another `PROTOCOL`, counts as absent. A new session is published and the old one keeps running its own jobs.
5. Second line of defence: the `hold` gate is `DotNetStarter.extractor_running()`. A queue starts nothing while a `RevitExtractor.exe` it did not start is running. This also covers the `.ps1` launcher and a second Revit.

## Window

Layout as Q14, about 760 × 420: title and a summary line, the job list, a hint line, a red error line, the footer.

| Part | Rule |
| --- | --- |
| List | Model, State, Progress / result, Started, Time. One row per job, in queue order. Rows stay until Revit closes (no history, Q24). Rows are plain objects; no row subscriptions; one `Items.Refresh()` per tick, only when something changed. |
| Timer | A `DispatcherTimer` (1 s) owned by the session, not by the window. Each tick calls `queue.poll()`, then `progress_info(queue.tail(id))` for running jobs. It stops when the queue is idle and starts on submit. Ticks wait while Revit is busy or shows a modal dialog, so the next queued export can start late. |
| Progress | Running row: elapsed time, the last finished step (`rvt-TaskName` of the last `rvt-TaskData` line, as the Extractor writes it, in English) and the last `[[progress]]` percentage, if any. Task lines arrive only when a step completes. |
| Waiting | Queued row: its position. When `queue.held`: "another Extractor is running on this computer". |
| Result | The runner's `Result.message`. A failed row also says the logs are in the run folder. |
| Footer | Cancel export, Open output folder, Open in Analyzer, Close. They act on the highlighted row and are enabled by `job_view`. |
| Cancel | `queue.cancel(id)`, no confirmation: the run folder stays. |
| Open output folder | `output` for an `ok` job, the run folder otherwise. Shell-open of an existing folder, no arguments. |
| Close | The window is created once and never destroyed. X or Close minimises it while exports are queued or running, and hides it when idle. When the queue becomes idle the window is restored without taking focus. Reason: with a document open the button is greyed (Q26), so there would be no way back to Cancel. |
| Hint | With queued jobs: queued exports start only while Revit is open; if Revit closes, the running one finishes and the rest are dropped (D5). |

The window has no text input (modeless WPF keyboard input inside Revit is unreliable) and makes no Revit API call.

## Open in Analyzer (Q11, `SPEC.md` open question 1)

| Step | Rule |
| --- | --- |
| Node.js | First `node.exe` on `PATH`, else `%ProgramFiles%\nodejs\node.exe`. Major version 24 or later, read from the file version; no process is started for the check. |
| Analyzer | `<clone>\Analyzer\server.mjs`, three folders above `lib/`, with its packages installed (`node_modules\pdfjs-dist\build\pdf.mjs`, the check `Start-Analyzer.cmd` uses). This module never runs `npm`. |
| Start | `node.exe server.mjs --output "<output>" --port <free port> --open`, working folder `Analyzer`, in a visible console window; closing that window stops the server. The path goes through `clean_path`. The Analyzer is unchanged and binds `127.0.0.1`. |
| Again | A second click on the same job while its server runs only opens the URL. |
| Fallback | Open the output folder and `WEBSITE_URL`; the error line says what was missing. |

## Acceptance criteria

1. `progress_info` on lines taken from the real run of 2026-11-10: returns the last task name and status and the last percentage; ignores metrics lines without `rvt-TaskData`; survives a first line cut in half, broken JSON, `None` and `""`.
2. `job_view` gives texts in English and Polish for `queued`, held, `running`, `ok`, `failed` and `cancelled`. Cancel applies to queued and running jobs that are not already being cancelled; Open output folder needs a run folder; Open in Analyzer only `ok`.
3. `SessionCore.handle`: `ping` reports `PROTOCOL` and busy; `submit` builds `Job`s from plain data and adds them; one bad job is reported as text and the others are still added; broken JSON or an unknown op returns `{"ok": false, "error": ...}` and never raises.
4. `find_session` returns `None` for no data, a non-callable, a handler that raises and a handler with another protocol. `publish_session` then replaces it.
5. `analyzer_plan` returns `local` only when Node 24+, `server.mjs` and the installed packages are all found, with the command above; otherwise `web` with a reason for each missing piece, in both languages. A path with a quote is refused.
6. Window logic with WPF stubbed: a tick polls once and refreshes at most once; the window never subscribes to a row; buttons follow the highlighted row; Cancel calls `queue.cancel` once; the open actions pass the expected target to the shell wrapper; a second Analyzer click reuses the URL.
7. With the window hidden, a queued job still starts when the running one exits. The timer stops when idle and restarts on submit.
8. Closing never destroys the window: minimised while busy, hidden when idle, restored when the queue becomes idle.
9. An exception from `poll()` or any handler is caught and shown on the error line, and the next tick still runs.
10. AST tests: `rx_status.py` is pure. `rx_status_ui.py` imports no `Autodesk`, `rx_reader`, `rx_catalog` or `pyrevit.script`, and contains no `print`. Both pass the IronPython syntax guard used for the other lib modules.
11. `rx_status.xaml` keys and `UI_TEXT` match both ways, with no literal label; the file loads in real WPF (`validate_xaml.ps1`).
12. Runner amendments: a queued job waits while `hold()` is true and nothing of the queue runs, `held` is set, and it can still be cancelled; `tail` reads without writing; `start(show_window=True)` sets `CreateNoWindow` False.
13. On this machine, `run_extractor_integration.ps1 -Analyzer` passes: after a real run it starts the `local` plan, `/api/session` lists exactly one export, and the script ends the Node process it started.

## Commands

```powershell
python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\validate_xaml.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\run_extractor_integration.ps1 -Analyzer
# Renders the new windows with sample rows to PNG files in %TEMP%, in English and Polish:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\preview_windows.ps1
```

## Testing

- New `tests/test_status.py`. The WPF fakes of `test_window_legacy.py` move unchanged into `tests/wpf_fakes.py`, so they outlive the old buttons.
- Verified here: criteria 1–13.
- **Not verifiable here:** a call between two IronPython engines through the delegate, the modeless window inside Revit, the timer next to Revit's own work, minimise and restore, Revit closing with the window hidden. All are in `v1-revit-test.md`.

## Boundaries

- No Revit API call, and never `read_model`: that belongs to the button's modal command.
- Nothing but JSON text crosses between engines.
- Never print or log through pyRevit; never raise into the dispatcher.
- Never write into a run folder. Never run `npm`. Never end a process this session did not start.
- No per-row subscriptions and no Python threads.
