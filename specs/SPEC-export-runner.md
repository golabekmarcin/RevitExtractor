# Spec: export-runner

Module of `SPEC.md`. Depends on: `index-builder`. Status: **written under the owner's working mode of 2026-11-10**.

## Objective

Run the Extractor as its own process, the way `Start-RevitExport.ps1` does (Q6, Q10): a new run folder for every export, the same command line and the same success check. Exports wait in a queue (Q28) and can be cancelled (Q24). Closing Revit must not stop a running export.

## Interface (`lib/rx_runner.py`)

```python
# pure
default_output_parent(documents_dir)        # <Documents>\RevitExtractor
plan_run(output_parent, now, token)         # RunPaths: root, index, output, logs, journals, console, stderr
prepare_run(paths, index)                   # creates the folders, writes index.json; refuses an existing root
extractor_exe(revit_dir, exists=os.path.isfile)       # <revit_dir>\RevitExtractor\RevitExtractor.exe
launch_spec(exe, revit_dir, model_path, paths, system_root)   # LaunchSpec(file, arguments, working_dir, env)
kill_spec(pid, system_root)                 # taskkill /PID <pid> /T /F
check_result(exit_code, console_text, has_bubble, has_resource)   # Result(state, success_jobs, failed_jobs, message)
progress_line(console_tail)                 # last meaningful line
effective_parallel(setting)                 # 1 while PARALLEL_VERIFIED is False
Queue(starter, clock, max_parallel=1)       # add(job), cancel(job_id), poll(), jobs()
RunnerError                                 # bilingual message
# thin .NET wrapper, the only code that imports System.Diagnostics (inside its methods)
DotNetStarter                               # start(spec) -> handle(pid, has_exited(), exit_code()); run(spec)
```

Job states: `queued` → `running` → `ok` | `failed` | `cancelled`. Jobs are plain records (id, model path, index, paths, pid, times, result).

## Design

- **Run folder**, as the launcher: `export-<yyyyMMdd-HHmmss>-<8 hex>\` with `index.json` (UTF-8, no BOM, `rx_index.to_json`), `output\`, `logs\`, `journals\`, `console.log`, `stderr.log`. It is created when the job starts, not when it is queued. An existing folder is never reused: the Extractor empties `<index folder>\output` first.
- **Command line**, as the launcher: index, model, `-RCEPath <Revit folder>`, `-LogPath`, `-journalPath`; trailing backslashes trimmed; working directory = the Revit folder. Paths containing `"`, CR or LF are refused.
- **The process must outlive Revit**, and `console.log` must still be complete. .NET can only redirect output through pipes owned by the parent, so the Extractor is started through `%SystemRoot%\System32\cmd.exe /d /v:off /s /c`, which redirects to the two files itself.
  - The command text is constant. Every path travels in an environment variable of the child (`RX_EXE`, `RX_INDEX`, `RX_MODEL`, `RX_REVIT`, `RX_LOGS`, `RX_JOURNALS`, `RX_CONSOLE`, `RX_STDERR`) and is referenced as `"%RX_…%"`. No path text is parsed by `cmd`, so `%`, `&` and `^` in folder names are safe.
  - `UseShellExecute = False`, `CreateNoWindow = True`, no redirected streams.
- **Cancel** kills the whole tree (`cmd` → `RevitExtractor.exe` → `RevitExtractor_Client.exe`) with `%SystemRoot%\System32\taskkill.exe /PID <pid> /T /F`. Only a job that this queue started and that has not exited can be killed. The run folder stays as it is.
- **Queue without threads or process events.** `poll()` is a pure state machine: it checks running handles, finishes jobs, and starts queued ones up to the limit. `status-window` calls it from a `DispatcherTimer`. No IronPython code runs on a thread-pool thread.
  - FIFO. A failed start marks that job `failed` and the queue goes on.
  - Two jobs for the same model never run at the same time.
  - `max_parallel` is a setting, default 1. `effective_parallel` returns 1 until `PARALLEL_VERIFIED` is set with the owner's evidence (Q28).
- **Success check**, as the launcher: exit code 0; the last `Success Jobs: N, Failed Jobs: M` line has `M = 0`; `output\bubble.json` and `output\Resource\` exist. A missing summary line does not fail the run (launcher parity) but is reported in the result.
- After the process exits, nothing is written into the run folder. Results live in the job record.

## Acceptance criteria

1. `plan_run` gives the layout above for a fixed time and token. `prepare_run` creates exactly those folders and `index.json`, with bytes equal to `to_json(index)` in UTF-8 without BOM, and raises `RunnerError` when the root exists.
2. `launch_spec`: `file` is `cmd.exe` under the given system root; `arguments` contains none of the path texts; `env` holds the eight values; paths with `"`, CR or LF raise `RunnerError`.
3. Windows-only test: the spec is really started with a stand-in `.cmd` as `RX_EXE` that prints its arguments and exits with 3. `console.log` shows the eight arguments in the launcher's order, intact for paths with spaces, Polish letters, `&`, `%TEMP%` and `^`; the exit code read back is 3.
4. `check_result` returns `ok`, `failed` (exit code), `failed` (failed jobs), `failed` (output incomplete) for the launcher's cases, takes the **last** summary line, and flags a missing one. Messages in English and Polish.
5. `progress_line` skips blank lines and the known noise ("mesh number larger than 64k", `DSM_InternalErrorMessage`).
6. `Queue` with a fake starter and clock:
   - with `max_parallel=1` the second job starts only after the first has exited, in order;
   - cancelling a queued job means it never starts and no folder is created;
   - cancelling a running job runs the kill spec once and ends as `cancelled`;
   - a start failure does not stop the queue;
   - the same model is never running twice;
   - `max_parallel=2` runs two.
7. `effective_parallel` returns 1 for any input while `PARALLEL_VERIFIED` is False, and clamps to 1…4 otherwise.
8. A folder snapshot (names, sizes, times) taken when a fake process exits is unchanged after `poll()` and `check_result`.
9. `kill_spec` accepts only an integer pid and uses the full `taskkill.exe` path.
10. No module-level import of `pyrevit`, `Autodesk`, `System` or `clr` (AST test). `DotNetStarter` is tested with a stub `System.Diagnostics`.
11. **Integration run on this machine** passes (see Testing).
12. The cancel and parallel modes of the integration script run on this machine and their results are recorded.

## Commands

```powershell
python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v
# Real Extractor run, started from rx_runner's launch spec (new script, part of this module):
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests\run_extractor_integration.ps1
#   -Cancel       start, then kill the tree and check nothing is left
#   -Parallel 2   the Q28 parallel-run test
#   -RevitDirectory, -ModelPath, -ModelPath2, -OutputParent   override the defaults
```

## Testing

- New `tests/test_runner.py` (criteria 1–10) and `tests/runner_cli.py`, a small CPython helper that exposes `plan`, `check` and `kill-spec` from `rx_runner` as JSON for the script.
- **Integration run (this machine: Revit 2023 Extractor, build 2024.0.x, Dynamo sample RVT).** The script:
  1. finds a Revit folder with `RevitExtractor` (any year) and a sample under `C:\ProgramData\Autodesk\RVT *\Dynamo\samples\Data\`;
  2. asks `runner_cli.py` to prepare a run under `%TEMP%\rx-integration-<id>` with the default index and to print the launch spec;
  3. starts it with `System.Diagnostics.Process` using exactly the spec's file, arguments, working directory and environment, the same fields `DotNetStarter` sets;
  4. waits, then asks `runner_cli.py check` for the result.
  - PASS needs: result `ok`; the sample's SHA-256 unchanged; `git status` clean. The script prints the wall time and the Print Spooler start type before and after.
  - It never writes into the repo or into a `test-*` folder.
- **Cancel mode:** start, wait until `RevitExtractor_Client.exe` appears under the pid (or 30 s), run the kill spec, and assert that no process of the tree is left and the run folder still exists.
- **Parallel mode (Q28):** copy two small models to the temp folder under different names, run each alone as a baseline, then start both at once into separate run folders. PASS needs: both results `ok`; each run's file count under `output` and its `Success Jobs` number equal to its baseline; neither `console.log` nor the journals of one run name the other model. Wall times are printed. A pass here is evidence for build 2024.0.x only. `PARALLEL_VERIFIED` changes only after the owner's run on the Revit 2022 machine.
- **Not verifiable here:** `DotNetStarter` in IronPython, anything next to a running Revit, closing Revit during an export.

## Boundaries

- Never reuse, clean or delete a run folder, including a cancelled one.
- Never kill a pid this queue did not start.
- Never pass a path through `cmd` text; environment variables only.
- No Python threads; no handlers on process events.
- `Start-RevitExport.ps1` is not changed.
