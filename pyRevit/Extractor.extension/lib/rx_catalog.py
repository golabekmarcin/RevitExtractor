# -*- coding: utf-8 -*-
"""Local model list: .rvt files under remembered roots, version read without opening a model.

Pure Python, no Revit import (a test enforces this): the caller passes BasicFileInfo to
read_basic_info. Compatible with pyRevit IronPython 2.7 (os.walk, os.stat, io.open, json only).
Spec: specs/SPEC-model-catalog.md.

The cache holds model paths, which are client data. It lives in the user's profile, never in the
repo, and nothing here logs its content.
"""
from __future__ import unicode_literals

import io
import json
import os
import re
from collections import namedtuple

from rx_i18n import tr
from rx_json import dumps_ascii

CACHE_VERSION = 1

STATES = ("ok", "older", "newer", "unknown", "local_copy")

_BACKUP_NAME = re.compile(r"^(?P<base>.+)\.\d{4}\.rvt$", re.IGNORECASE)
_YEAR = re.compile(r"^\d{4}$")
_MTIME_TOLERANCE = 0.001  # seconds; JSON round trip and filesystem timestamp precision

Row = namedtuple(str("Row"), str("path folder name version state enabled note workshared"))


def _norm_path(path):
    return os.path.normcase(os.path.normpath(path))


def _is_under(path_key, root_key):
    prefix = root_key if root_key.endswith(os.sep) else root_key + os.sep
    return path_key.startswith(prefix)


def normalize_roots(values):
    """Trimmed, de-duplicated (case-insensitive on Windows), nested roots collapsed.

    Keeps the first spelling and the original order of the roots that survive.
    """
    candidates = []
    seen = set()
    for value in values or ():
        if value is None:
            continue
        text = value.strip()
        if not text:
            continue
        path = os.path.normpath(text)
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        candidates.append((path, key))
    result = []
    for path, key in candidates:
        if any(other != key and _is_under(key, other) for _, other in candidates):
            continue
        result.append(path)
    return result


def _is_backup_folder(name):
    lowered = name.lower()
    return lowered == "backup" or lowered.endswith("_backup")


def iter_model_files(roots, walk=os.walk, errors=None):
    """Yield .rvt paths under the roots: sorted, deterministic, each path once.

    Skips folders named Backup or ending in _backup, and files named <name>.NNNN.rvt when
    <name>.rvt sits in the same folder. A missing or unreadable folder is appended to `errors`
    (when given) and never raised.
    """
    def on_error(exc):
        if errors is not None:
            errors.append(getattr(exc, "filename", None) or current_root[0])

    current_root = [None]
    emitted = set()
    for root in normalize_roots(roots):
        current_root[0] = root
        for folder, dirs, files in walk(root, onerror=on_error):
            dirs[:] = sorted((d for d in dirs if not _is_backup_folder(d)), key=os.path.normcase)
            lowered = set(name.lower() for name in files)
            for name in sorted(files, key=os.path.normcase):
                if not name.lower().endswith(".rvt"):
                    continue
                match = _BACKUP_NAME.match(name)
                if match and (match.group("base") + ".rvt").lower() in lowered:
                    continue
                path = os.path.join(folder, name)
                key = _norm_path(path)
                if key in emitted:
                    continue
                emitted.add(key)
                yield path


def _year_of(info):
    text = info.get("format")
    if text is None:
        return None
    text = ("%s" % text).strip()
    return int(text) if _YEAR.match(text) else None


def classify(info, running_year):
    """"ok" | "older" | "newer" | "unknown" | "local_copy" from a read_basic_info dict."""
    if "error" in info:
        return "unknown"
    if info.get("is_local") or info.get("is_created_local"):
        return "local_copy"
    year = _year_of(info)
    # saved_in_later is relative to the Revit that inspected the file, and the cache is shared by
    # every Revit year. A file whose format year is older than the running year cannot be newer,
    # whatever an older-year inspection stored.
    later = bool(info.get("saved_in_later")) and (year is None or year >= running_year)
    if later or (year is not None and year > running_year):
        return "newer"
    if year is None:
        return "unknown"
    return "ok" if year == running_year else "older"


def _note(state, info, running_year):
    year = _year_of(info)
    shown = "%d" % year if year is not None else "?"
    if state == "newer":
        return tr("Saved in Revit {0}, newer than this Revit ({1}).",
                  "Zapisany w Revicie {0}, nowszym niż ten Revit ({1}).").format(shown,
                                                                                running_year)
    if state == "older":
        return tr("Saved in Revit {0}. The export upgrades a temporary copy; "
                  "the file is not changed.",
                  "Zapisany w Revicie {0}. Eksport uaktualni tymczasową kopię; "
                  "plik nie zostanie zmieniony.").format(shown)
    if state == "unknown":
        return tr("The Revit version could not be read.",
                  "Nie udało się odczytać wersji Revita.")
    return ""


def _workshared_of(info):
    """True / False from the BasicFileInfo IsWorkshared fact; None when unknown or unreadable."""
    if "error" in info:
        return None
    value = info.get("is_workshared")
    return value if isinstance(value, bool) else None


def _make_row(path, info, running_year):
    state = classify(info, running_year)
    year = _year_of(info)
    return Row(path=path, folder=os.path.dirname(path), name=os.path.basename(path),
               version="%d" % year if year is not None else "", state=state,
               enabled=state in ("ok", "older"), note=_note(state, info, running_year),
               workshared=_workshared_of(info))


class Cache(object):
    """Path -> BasicFileInfo facts, valid while size and modified time match.

    Stores only the read_basic_info dict, so one cache serves every Revit version. A missing,
    corrupt or other-version file gives an empty cache and never raises.
    """

    def __init__(self, file_path):
        self.file_path = file_path
        self.entries = {}
        self.last_error = None

    def load(self):
        self.entries = {}
        try:
            with io.open(self.file_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if (isinstance(data, dict) and data.get("version") == CACHE_VERSION
                    and isinstance(data.get("entries"), dict)):
                self.entries = data["entries"]
        except Exception:
            self.entries = {}
        return self

    def lookup(self, path, size, mtime):
        entry = self.entries.get(_norm_path(path))
        try:
            if (isinstance(entry, dict) and isinstance(entry.get("info"), dict)
                    and entry["size"] == size
                    and abs(float(entry["mtime"]) - float(mtime)) <= _MTIME_TOLERANCE):
                return dict(entry["info"])
        except (KeyError, TypeError, ValueError):
            pass
        return None

    def store(self, path, size, mtime, info):
        self.entries[_norm_path(path)] = {"size": size, "mtime": mtime, "info": dict(info)}

    def prune(self, roots, seen_paths):
        """Drop entries under the given roots whose file was not seen; keep other roots."""
        root_keys = [_norm_path(root) for root in roots]
        seen = set(_norm_path(path) for path in seen_paths)
        for key in list(self.entries):
            if key not in seen and any(_is_under(key, root) for root in root_keys):
                del self.entries[key]

    def save(self):
        """Write through a temporary file in the same folder. True on success.

        A failure is kept in last_error (the exception type name, no paths) and never raised.
        IronPython 2.7 cannot overwrite through rename, so the old file is removed before the rename.
        """
        temp_path = self.file_path + ".tmp"
        try:
            folder = os.path.dirname(self.file_path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            text = dumps_ascii({"version": CACHE_VERSION, "entries": self.entries},
                               sort_keys=True)
            with io.open(temp_path, "w", encoding="utf-8") as handle:
                handle.write(text)
            if os.path.exists(self.file_path):
                os.remove(self.file_path)
            os.rename(temp_path, self.file_path)
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = type(exc).__name__
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            return False


def scan(roots, running_year, read_info, cache, stat=os.stat, errors=None):
    """Yield one Row per model file, one file per pull, so the window can time-slice.

    Local copies of centrals are yielded too (state "local_copy", enabled False); the caller
    counts them as skipped and does not list them. Results of read_info that carry an error are
    not cached (the file may have been locked). When the scan runs to the end, entries for files
    gone from the scanned roots are pruned (roots that could not be read are left alone). The
    cache is saved once when the generator ends or is closed early; a failed save sets
    cache.last_error and does not stop the scan. An early stop does not prune.
    """
    roots = normalize_roots(roots)
    problems = []
    seen = []
    finished = False
    try:
        for path in iter_model_files(roots, errors=problems):
            seen.append(path)
            try:
                st = stat(path)
                size, mtime = st.st_size, st.st_mtime
            except Exception:
                yield _make_row(path, {"error": "OSError"}, running_year)
                continue
            info = cache.lookup(path, size, mtime)
            if info is None:
                try:
                    info = read_info(path)
                except Exception as exc:
                    info = {"error": type(exc).__name__}
                if "error" not in info:
                    cache.store(path, size, mtime, info)
            yield _make_row(path, info, running_year)
        finished = True
    finally:
        if errors is not None:
            errors.extend(problems)
        if finished:
            keys = [_norm_path(p) for p in problems]
            cache.prune([r for r in roots
                         if not any(k == _norm_path(r) or _is_under(k, _norm_path(r))
                                    for k in keys)], seen)
        cache.save()


def read_basic_info(path, BasicFileInfo):
    """Plain values from BasicFileInfo.Extract(path), or {"error": <exception type name>}.

    Dispose is always called. No API object leaves this function.
    """
    info = None
    try:
        info = BasicFileInfo.Extract(path)
        fmt = info.Format
        return {
            "format": "" if fmt is None else "%s" % fmt,
            "saved_in_later": bool(info.IsSavedInLaterVersion),
            "is_local": bool(info.IsLocal),
            "is_created_local": bool(info.IsCreatedLocal),
            "is_workshared": bool(info.IsWorkshared),
            "is_central": bool(info.IsCentral),
        }
    except Exception as exc:
        return {"error": type(exc).__name__}
    finally:
        if info is not None:
            try:
                info.Dispose()
            except Exception:
                pass
