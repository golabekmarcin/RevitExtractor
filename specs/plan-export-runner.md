# Plan: export-runner

Implements `SPEC-export-runner.md`. Files: `lib/rx_runner.py`, `tests/test_runner.py`, `tests/runner_cli.py`, `tests/run_extractor_integration.ps1`.

## Decisions made while planning

- **`cmd.exe` does the redirection**, so the export does not depend on Revit staying open (Q24). Reading pipes inside Revit would break `console.log`, and with it the success check, when Revit closes.
- **Paths go through environment variables.** It removes command injection through folder names and all `cmd` quoting rules in one step.
- **Polling, not events.** `Process.Exited` fires on a thread-pool thread; running IronPython there is what the "no threads" rule is meant to prevent.
- **`taskkill /T /F`** because the Extractor starts a child (`RevitExtractor_Client.exe`) and .NET Framework's `Process.Kill()` ends one process only.
- **The same launch spec feeds Revit and the test script.** Only about twenty lines of `ProcessStartInfo` code exist twice (IronPython and PowerShell), and they set the same fields.
- **The queue is an object owned by its caller.** Where it lives between button clicks is a `status-window` matter. Job records are plain data so a later owner can list them again.
- The Extractor build shown to the user comes from `ExtractorUtility.dll`'s file version. `RevitExtractor.exe`'s product version is a commit hash on this machine's build.

## Tasks

### Task 1: Run folder and `prepare_run` (test first)
**Acceptance criteria:** spec criterion 1; `default_output_parent`; `extractor_exe` found and missing cases.
**Verification:** discover command. **Dependencies:** `rx_index.to_json`. **Station:** `line-cook`. **Scope:** S.

### Task 2: `launch_spec` and `kill_spec`
**Acceptance criteria:** spec criteria 2, 3 and 9. The stand-in test is skipped with a reason off Windows.
**Verification:** discover command. **Dependencies:** Task 1. **Station:** `sous-chef` (command construction and process kill). **Scope:** S.

### Task 3: `check_result` and `progress_line`
**Acceptance criteria:** spec criteria 4 and 5, with the launcher's three failure cases as fixtures.
**Verification:** discover command. **Dependencies:** none. **Station:** `line-cook`. **Scope:** S.

### Task 4: `Queue`
**Acceptance criteria:** spec criteria 6, 7 and 8.
**Verification:** discover command. **Dependencies:** Tasks 1–3. **Station:** `line-cook`. **Scope:** M.

### Task 5: `DotNetStarter`
**Acceptance criteria:** spec criterion 10: with a stub `System.Diagnostics`, `start` sets file, arguments, working directory, the eight variables, `UseShellExecute False`, `CreateNoWindow True` and no redirection; the handle reports pid, exit state and exit code.
**Verification:** discover command. **Dependencies:** Task 2. **Station:** `sous-chef`. **Scope:** S.

### Checkpoint A
- [ ] All unit tests pass; no bundle and no `.ps1` launcher touched.

### Task 6: Integration script and the run on this machine
**Description:** `runner_cli.py` and `run_extractor_integration.ps1` (Windows PowerShell 5.1, `-Encoding UTF8`, `[string]` casts as in `HANDOVER.md` §6).
**Acceptance criteria:**
- [ ] Spec criterion 11: result `ok`, sample hash unchanged, repo clean, times and spooler state printed.
- [ ] If the run cannot succeed for a reason outside the code (licence, sign-in), the exact output is recorded and the item moves to the owner's checklist. No workaround, no claimed pass.

**Verification:** the script's output in the report. **Dependencies:** Checkpoint A. **Station:** `sous-chef`. **Scope:** M.

### Task 7: Cancel and parallel modes
**Acceptance criteria:** spec criterion 12; the parallel mode's PASS rules as written in the spec; `-ModelPath` and `-ModelPath2` let the owner use two small models of their own.
**Verification:** both outputs in the report. **Dependencies:** Task 6. **Station:** `sous-chef`. **Scope:** S.

### Task 8: Docs
**Acceptance criteria:** the new command in `CLAUDE.md`; `lib/README.md` and `README.pl.md` with Validation lines (what ran here, on which build, what did not); `HANDOVER.md` §2 and §5 updated with what the first real run showed (progress line format, the `Success Jobs` line).
**Dependencies:** Task 7. **Station:** `line-cook`. **Scope:** XS.

### Checkpoint B: done
- [ ] Spec criteria 1–12 evidenced. Local commit.

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| No real export has ever run on this machine (`VERIFICATION-2023.md`); it may need a licence or fail headless | High for criterion 11 | Task 6 records the facts and escalates instead of forcing a pass |
| The Extractor may change the Print Spooler start mode on this machine | Low | State printed before and after; reported |
| `DotNetStarter` differs in IronPython (environment dictionary, exit code) | Med | Kept tiny, mirrored by the script; first item of the owner's checklist |
| Revit ends its child processes on exit after all | Med | Owner's test; if so, the fallback is a detached launcher, a new decision |
| Parallel runs collide in a shared place (temp files, licence, spooler) | Med | Default 1; switch only on the owner's evidence |
| A workshared central is passed straight to the Extractor | Med | Owner's test checks the central is untouched; if not, `export-button` exports a copy |
| Queued jobs are lost when Revit closes | Med | Stated in the status window; batched owner list |

## Open questions

Batched owner list in `HANDOVER.md`: queued jobs when Revit closes; `cmd.exe` and `taskkill.exe`.
