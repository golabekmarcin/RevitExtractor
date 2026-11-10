# Spec: model-catalog

Module of `SPEC.md`. Depends on: `capabilities`. Status: **written under the owner's working mode of 2026-11-10**.

## Objective

Produce the local model list (Q4/Q7, Q17, Q19): `.rvt` files under remembered roots with Folder, File Name and Revit Version, without opening any model. Models newer than the running Revit are greyed out; older ones carry the upgrade warning. A cache keeps repeat scans fast (`SPEC.md` open question 2).

## Interface (`lib/rx_catalog.py`; no Revit import, the caller passes `BasicFileInfo`)

```python
iter_model_files(roots, walk=os.walk)     # generator of paths; skip rules applied; sorted, deterministic
classify(info, running_year)              # "ok" | "older" | "newer" | "unknown" | "local_copy"
scan(roots, running_year, read_info, cache, stat=os.stat)   # generator of Row, one file per step
Row                                       # path, folder, name, version, state, enabled, note
Cache(file_path)                          # load(), lookup(path, size, mtime), store(...), prune(...), save()
normalize_roots(values)                   # trimmed, de-duplicated, nested roots collapsed
read_basic_info(path, BasicFileInfo)      # thin wrapper: dict of plain values, or {"error": <type name>}
```

- `scan` is a generator, so the window pulls rows for a time budget per `Dispatcher` tick and stays responsive. No threads.
- Persisting the roots (pyRevit config) belongs to `export-button`. This module only normalizes them.

## Rules

| Rule | Detail |
| --- | --- |
| Backup files | Name ends in `.NNNN.rvt` (four digits) **and** `<name>.rvt` exists in the same folder. A file such as `Tower.2024.rvt` without that sibling is listed. |
| Backup folders | A folder named `Backup` or ending in `_backup` (any case) is not entered. |
| Local copies of centrals | `IsLocal` or `IsCreatedLocal` → not listed, counted as skipped. |
| Version | `BasicFileInfo.Format` when it is a four-digit year. |
| Newer | File year above the running year, or `IsSavedInLaterVersion`: greyed, tooltip "Saved in Revit {0}, newer than this Revit ({1})." / "Zapisany w Revicie {0}, nowszym niż ten Revit ({1})." |
| Older | Enabled, warning "Saved in Revit {0}. The export upgrades a temporary copy; the file is not changed." / "Zapisany w Revicie {0}. Eksport uaktualni tymczasową kopię; plik nie zostanie zmieniony." |
| Unknown | `Extract` failed, or no year and no flag decides: greyed, tooltip "The Revit version could not be read." / "Nie udało się odczytać wersji Revita." |

**Cache.** JSON, keyed by the case-normalized path; an entry is valid while size and modified time match. It stores only the `read_basic_info` dict, so the relation to the running Revit is computed on every scan and one cache serves every Revit version. A missing, corrupt or other-version file gives an empty cache and never raises. Saved once per scan through a temporary file. The caller passes the location (default `%APPDATA%\RevitExtractor\catalog-cache.json`). The cache holds model paths, which are client data: never in the repo, never in logs.

**Speed target** (default, owner confirms): a warm scan of 1,000 files on a local disk lists in 2 s or less. A cold scan fills in progressively without freezing the window; its time is measured in the owner's test and recorded, with no hard limit.

## Revit API members

Checked with `revit-api` on 2026-11-10 in revisions 2022 (CHM `b8ee0868071c9e79…`) and 2026 (CHM `441dcbf9ce355456…`); all documented in both. Member id = `<revision>:<CHM prefix>:<hash>`. Documentation only; not run in Revit. Versions after 2026 are not indexed.

| Member (`Autodesk.Revit.DB.BasicFileInfo`) | Hash | Note |
| --- | --- | --- |
| `Extract(String)` | `731989604463a95b831fc289` | Raises `InvalidOperationException` for a newer format whose storage changed, or a very old file; `FileArgumentNotFoundException` for a missing file |
| `Format` | `6e1a79ba1454e065efb3fc07` | "the major release version such as "2019""; since 2019 |
| `IsSavedInLaterVersion` | `38fb52d70ab5546d44970700` | cannot decide when `Extract` itself failed |
| `IsSavedInCurrentVersion` | `e69ec2406217ff550f98b537` | |
| `IsWorkshared`, `IsCentral` | `fb8fa1356815a9db56a02f9f`, `2dad9094452861c91a7d2d1b` | |
| `IsLocal`, `IsCreatedLocal` | `0485c5c3e31ebff5a4080f54`, `3c9595c360fa791b908a124a` | |
| `Dispose` | `d5b11fff76003cf01789e71c` | always called |

`BasicFileInfo.SavedInVersion` has no page in either revision. Do not use it.

## Acceptance criteria

1. On a temporary tree, `iter_model_files` returns exactly the expected paths: nested folders, several roots, a root inside another root (no duplicates), mixed-case `.RVT`, both backup rules, the `Tower.2024.rvt` case, non-`.rvt` files ignored, a missing or unreadable root reported and not raised.
2. `classify` returns each state for stub infos: same year, older, newer by year, newer by flag only, unreadable `Format`, `error`, local, created-local. `Row.enabled` is True only for `ok` and `older`.
3. Every note exists in English and Polish and follows the language stub.
4. Cache: a hit avoids `read_info` (call count 0 on the second scan); a changed size or time re-reads; a corrupt file, a wrong version and a missing folder all give an empty cache; `prune` drops entries for files gone from a scanned root and keeps entries of other roots.
5. `scan` yields one `Row` per pull, and stopping early leaves the cache consistent and saveable.
6. `read_basic_info` with a stub `BasicFileInfo`: returns plain values only; calls `Dispose` also when a property raises; turns an exception from `Extract` into `{"error": <type name>}`.
7. Timing test: 1,000 empty files with a warm cache scan in under 2 s on this machine (pure overhead only).
8. No module-level import of `pyrevit`, `Autodesk`, `System` or `clr` (AST test).

## Commands

```powershell
python -B -m unittest discover -s .\pyRevit\Extractor.extension\RVTExtractor.tab\Setup.panel\tests -v
```

## Testing

- New `tests/test_catalog.py`, with temporary folders and stub objects.
- Verified here: everything above. **Not verifiable here:** `BasicFileInfo.Extract` itself (it needs a running Revit), real folder trees, network shares, the real cold-scan time. Those go to the owner's test.

## Boundaries

- Never open a model here and never write next to a model. The only file written is the cache.
- Never follow a rule that needs the file open; that belongs to `model-reader`.
- No Revit Server (`RSN://`) browsing in v1; roots are folders (local, mapped or UNC).
