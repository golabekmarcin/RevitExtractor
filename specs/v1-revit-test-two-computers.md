# v1 Revit test: the two-computer workflow

Companion to `specs/v1-revit-test.html` (the interactive guide). The older `specs/v1-revit-test.md` is kept for reference.

**Rule:** client project data stays on the Revit computer. The tests use synthetic data (Autodesk sample models copied by `v1_test_kit.ps1`). Only typed values, ticked checks and notes you approved leave it, through a review dialog. The HTML makes no network request and runs no command.

## Computer A (development)

1. Commit the work to be tested. Today the Revit 2025 import fix, the stay-open window and the views-retry fix are **uncommitted**, so Computer B cannot get them from git until you commit (and, with your approval, push `mgo-changes`; never `online` or upstream).
2. `git status` must be clean, then `git rev-parse --short HEAD`: this is the baseline.
3. Open `v1-revit-test.html`, type the baseline into **Expected baseline** on the Start page, click **Save filled HTML**, review, confirm. The saved file now carries the baseline.
4. Carry to Computer B by an approved method: the saved HTML, plus the repository at that commit. Either `git fetch` there, or `git archive --format=zip -o RevitExtractor-<commit>.zip <commit>`. No client file, `test-*` folder, pyRevit config or `catalog-cache.json`.

## Computer B (Revit)

1. Double-click the HTML (Edge, Chrome, Firefox). A red banner means browser storage is unavailable: then save often.
2. Work in order from **P1**. All commands run in Windows PowerShell 5.1 on Computer B; nothing runs on Computer A. Each command has a Copy button and says where to start.
3. Choose a result per test. Progress autosaves in the browser. Use **Save filled HTML** now and then and reopen it once to confirm the progress returns. A saved file stores only what you approved in the review dialog: notes you did not approve are not in it (they stay in the browser).
4. Revit year, Extractor build and pyRevit version go on the Start page (version numbers only).
5. Part F needs the Revit 2025 machine: repeat P1 there, open the same HTML (or the saved copy) and continue.
6. Tests D3, D5, D6 use models you create or copy (D3: a new workshared project saved under `C:\RX-test\Central`). D4 (a very large model) cannot be done synthetically: mark it BLOCKED unless you have a non-confidential large model.

## Returning results

1. Click **Export results** (JSON) or **Copy summary** (text for pasting into Claude Code).
2. Read the review dialog. Notes are excluded unless approved on the test page; a note that matches a path, GUID, e-mail, model file name, long number or user folder is held back until you include it deliberately. The scan helps only; it never proves a note is safe.
3. Tick the confirmation, download or copy, and transfer by an authorized method.
4. Give the summary or JSON to Claude Code. It lists the baseline, statuses, ticked checks, typed values, the remaining tests and the next test. Unticked or missing items are shown as missing, not as success.
5. If exporting is forbidden, finish the tests locally and keep the saved HTML.

## Never send

Result files in `C:\RX-test\results` (G2 names your Windows user folder), `console.log`, `stderr.log`, journals, pyRevit output text, screenshots, `catalog-cache.json`, the pyRevit config. The guide asks only for numbers and state words.
