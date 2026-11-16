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
clean_path(value)                           # the path as it may reach a command line, or RunnerError
Queue(starter, clock, max_parallel=1, hold=None)
                                            # add(job), cancel(job_id), poll(), jobs(), tail(job_id), held
RunnerError                                 # bilingual message
# thin .NET wrapper, the only code that imports System.Diagnostics (inside its methods)
DotNetStarter                               # start(spec, show_window=False) -> handle(pid, has_exited(), exit_code());
                                            # run(spec); extractor_running(); extractor_tree_running()
```

Amendments for `status-window` (2026-11-11, `SPEC-status-window.md`):
- `hold()`: while no job of this queue runs and `hold()` is true, queued jobs wait and `Queue.held` is True. A failing `hold()` counts as false. It is asked only when a job is queued.
- `Queue.tail(job_id)`: the end of `console.log` (64 KiB) as text, read-only; `""` before the job starts.
- `clean_path` is public (was `_clean_path`).
- `DotNetStarter.start(spec, show_window=True)` sets `CreateNoWindow = False` (used for the Analyzer console). `extractor_running()` lists `RevitExtractor` processes with `Process.GetProcessesByName`; it never ends one.

Amendments for `cloud-catalog` (2026-11-16, `SPEC-cloud-catalog.md`, criterion 9):
- `Job(model_path, index, revit_dir, output_parent, stage=None, model_name=None, model_key=None)`. `stage` is plain dicts, `{"items": [{"src", "name", "size", "mtime"}], "notes": [text]}`, host first, as `rx_cloud.plan_stage` gives it and `rx_cloud_stage.copy_steps` accepts. `Queue.add` checks it and fails closed with `RunnerError`: every `src` goes through `clean_path`; every name is one safe file name ending in `.rvt`, unique without regard to case; size and mtime are numbers; the first item is the job's `model_path` and its name is `model_name`. `add` then keeps its own copy. `model_name` without `stage` is refused.
- New state `staging` between `queued` and `running`, for jobs with a stage only. It takes a parallel slot, so runs stay one at a time. When the job starts, the runner checks free space (`rx_cloud_stage.check_space`; an unknown free space lets the copy go on), creates the run folder and `<run>\model\` with `stage.json` (names as given, sizes, cache dates; no source path), and copies the items there. The Extractor's model path is `<run>\model\<model_name>`.
- `poll()` advances `copy_steps` for at most `STAGE_BUDGET` (40 ms), checked after each `STAGE_CHUNK` (1 MiB) step, so one step can run over. The clock is injectable (`stage_clock`), and it is read only while a job is staging. After the copy, `hold()` is asked again before the Extractor starts, and a copied job waits while it is true.
- Same-model check by `model_key` (lower case) when given, else by the model path, over `staging` and `running` jobs.
- Cancel during staging stops the copy and gives `cancelled`, and no process is started. A `StageError` (`rx_cloud`, a `ValueError`), or any other copy or start failure, fails only that job, with "The copy from the cache failed: {0}" / "Kopiowanie z pamięci podręcznej nie powiodło się: {0}". The queue goes on.
- **Staged copies are deleted, and nothing else.** Only the names this job's copy created, directly inside `<run>\model\`, and never a path under a `CollaborationCache` folder or equal to a source. They are deleted once the job's `cmd.exe` has exited and `tree_running()` is false (in Revit, `DotNetStarter.extractor_tree_running`: no `RevitExtractor.exe` or `RevitExtractor_Client.exe` on the computer). If no process was started (failed or cancelled copy, failed start), they are deleted at once. A file that cannot be deleted is retried on later polls. After `CLEANUP_SECONDS` (600) the job's message says "Some copies from the cache could not be deleted; delete them by hand from {0}." / "Nie udało się usunąć części kopii z pamięci podręcznej; usuń je ręcznie z {0}." `busy()` stays true while a deletion is pending, and `clear_finished` does not stop it. `stage.json`, `output\`, logs and any other file stay.
- Stage notes (for example a link missing from the cache) are appended to the result message of a finished job.
- `Job` adds `staged_model`, `stage_done`, `stage_total`, `stage_ready` and `cleanup` (`None` | `pending` | `done` | `incomplete`).
- `Queue(..., stage_clock, stage_budget, stage_chunk, free_space, tree_running, remove, copier)`; every new argument is optional. A job without `stage` behaves exactly as before, and never reads the stage clock.
- If Revit closes while a job copies, the copy stops: the Extractor never starts, and the copies made so far stay in the run folder (no threads, so nothing finishes the copy).

Job states: `queued` → `running` → `ok` | `failed` | `cancelled`; cloud jobs `queued` → `staging` → `running` → …, or `staging` → `failed` | `cancelled`. Jobs are plain records (id, model path, index, paths, pid, times, result, and the stage fields above).

## Design

- **Run folder**, as the launcher: `export-<yyyyMMdd-HHmmss>-<8 hex>\` with `index.json` (UTF-8, no BOM, `rx_index.to_json`), `output\`, `logs\`, `journals\`, `console.log`, `stderr.log`. It is created when the job starts, not when it is queued. An existing folder is never reused: the Extractor empties `<index folder>\output` first.
- **Command line**, as the launcher: index, model, `-RCEPath <Revit folder>`, `-LogPath`, `-journalPath`; trailing backslashes trimmed; working directory = the Revit folder. Paths containing `"`, CR or LF are refused.
- **The process must outlive Revit**, and `console.log` must still be complete. .NET can only redirect output through pipes owned by the parent, so the Extractor is started through `%SystemRoot%\System32\cmd.exe /d /v:off /s /c`, which redirects to the two files itself.
  - The command text is constant. Every path travels in an environment variable of the child (`RX_EXE`, `RX_INDEX`, `RX_MODEL`, `RX_REVIT`, `RX_LOGS`, `RX_JOURNALS`, `RX_CONSOLE`, `RX_STDERR`) and is referenced as `"%RX_…%"`. No path text is parsed by `cmd`, so `%`, `&` and `^` in folder names are safe.
  - `UseShellExecute = False`, `CreateNoWindow = True`, no redirected streams.
- **Cancel** kills the whole tree (`cmd` → `RevitExtractor.exe` → `RevitExtractor_Client.exe`) with `%SystemRoot%\System32\taskkill.exe /PID <pid> /T /F`. Only a job that this queue started and that has not exited can be killed. The run folder stays as it is.
- **Queue without threads or process events.** `poll()` is a pure state machine: it checks running handles, finishes jobs, and starts queued ones up to the limit. `status-window` calls it from a `DispatcherTimer`. No IronPython code runs on a thread-pool thread.
  - FIFO. A failed start marks that job `failed` and the queue goes on.
  - Two jobs for the same model never run at the same time (same `model_key`, or the same path when no key is given; `staging` counts as running).
  - `max_parallel` is a setting, default 1. `effective_parallel` returns 1 until `PARALLEL_VERIFIED` is set with the owner's evidence (Q28).
- **Success check**, as the launcher: exit code 0; the last `Success Jobs: N, Failed Jobs: M` line has `M = 0`; `output\bubble.json` and `output\Resource\` exist. A missing summary line does not fail the run (launcher parity) but is reported in the result.
- After the process exits, nothing is written into the run folder. Results live in the job record. One exception, for cloud jobs: the copies the job staged into `<run>\model\` are deleted after the process tree has exited (amendment above).

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
13. Cloud amendment (`SPEC-cloud-catalog.md` criterion 9), with a fake cache tree and a fake starter:
    - `queued` → `staging` → `running`, with the Extractor's model at `<run>\model\<model_name>` and the bytes identical;
    - each `poll` stays within its budget;
    - Cancel during staging gives `cancelled` with no process started;
    - a changed or missing source, or any copy error, fails that job and the queue goes on;
    - the same `model_key` never runs twice;
    - copies are deleted only after exit and while `tree_running()` is false, only this job's copies, and `stage.json` and other files stay;
    - the cache tree's names, sizes, times and SHA-256 are unchanged;
    - `add` refuses a bad stage;
    - a job without a stage never reads the stage clock.

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

- Never reuse, clean or delete a run folder, including a cancelled one. Only exception: the copies a cloud job staged into `<run>\model\` are deleted after its process tree has exited (cloud amendment). The folder itself, `stage.json`, `output\`, logs and any other file stay.
- Never write, rename, move or delete anything under `CollaborationCache`.
- Never kill a pid this queue did not start.
- Never pass a path through `cmd` text; environment variables only.
- No Python threads; no handlers on process events.
- `Start-RevitExport.ps1` is not changed.
