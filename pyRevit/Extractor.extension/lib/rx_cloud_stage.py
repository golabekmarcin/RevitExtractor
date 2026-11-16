# -*- coding: utf-8 -*-
"""Copy a cloud model and its links from Revit's CollaborationCache into a run's staging folder.

File IO only, no Revit, .NET or clr import. Compatible with pyRevit IronPython 2.7. Spec:
specs/SPEC-cloud-catalog.md (Rules: Staging, Copy safety). The plan comes from
rx_cloud.plan_stage.

Safety rules, each covered by tests/test_cloud_stage.py:
- a source (a cache file) is only ever opened with mode "rb"; nothing here writes, renames,
  moves or deletes a source;
- a destination is created new and exclusively (os.O_EXCL) and never overwritten;
- after each item the destination size equals the planned size, and the source size and mtime
  are unchanged since planning, else StageError ("The cache file changed ...");
- the copy is a generator, so the runner can time-slice it without threads; closing it early
  raises nothing and removes only the partly written destination of the current item.
"""
from __future__ import unicode_literals

import io
import os

from rx_cloud import StageError, StageItem, safe_file_name  # noqa: F401  (StageError re-exported)
from rx_i18n import tr

CHUNK = 8 * 2 ** 20
_MTIME_TOLERANCE = 0.001    # seconds; the plan may have crossed a JSON round trip
_MB = 2 ** 20
_INTEGER_TYPES = tuple(set([type(0), type(2 ** 64)]))


def _changed():
    return StageError(tr("The cache file changed while it was copied. Export again.",
                         "Plik w pamięci podręcznej zmienił się podczas kopiowania. "
                         "Wyeksportuj ponownie."))


def _bad_plan():
    return StageError(tr("The copy plan is not valid.", "Plan kopiowania jest nieprawidłowy."))


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, _INTEGER_TYPES) or isinstance(value, float):
        return value
    return None


def _items(plan):
    """StageItems of a StagePlan, or of its plain-dict form {"items": [{src, name, size, mtime}]}
    (the runner's Job.stage). StageError when anything is missing or of the wrong type."""
    raw = plan.get("items") if isinstance(plan, dict) else getattr(plan, "items", None)
    if not isinstance(raw, (list, tuple)):
        raise _bad_plan()
    found = []
    for entry in raw:
        if isinstance(entry, dict):
            try:
                entry = StageItem(entry["src"], entry["name"], entry["size"], entry["mtime"])
            except KeyError:
                raise _bad_plan()
        if not isinstance(entry, StageItem):
            raise _bad_plan()
        size, mtime = _number(entry.size), _number(entry.mtime)
        if (not isinstance(entry.src, type("")) or not entry.src or size is None or size < 0
                or mtime is None):
            raise _bad_plan()
        found.append(entry)
    return found


def needed_bytes(plan):
    """Disk space for the staged copies plus the Extractor's own temporary copy (about the same
    size again)."""
    return 2 * sum(item.size for item in _items(plan))


def check_space(plan, free_bytes):
    """Needed bytes, or StageError when they do not fit into `free_bytes`. None means the free
    space is unknown (the query failed): the copy goes ahead and fails on its own if the disk
    fills up."""
    needed = needed_bytes(plan)
    if free_bytes is None:
        return needed
    free = _number(free_bytes)
    if free is None or free < 0:
        raise StageError(tr("The free disk space is not valid.",
                            "Ilość wolnego miejsca na dysku jest nieprawidłowa."))
    if needed > free:
        raise StageError(tr(
            "Not enough free disk space for the copies from the cache: {0} MB needed, {1} MB "
            "free.",
            "Za mało wolnego miejsca na dysku na kopie z pamięci podręcznej: potrzeba {0} MB, "
            "wolne {1} MB.").format(-(-needed // _MB), int(free) // _MB))
    return needed


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _same_path(left, right):
    return _norm(left) == _norm(right)


def _inside(path, folder):
    path, folder = _norm(path), _norm(folder)
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _in_cache(dest_dir, items):
    """True when the destination folder lies in Revit's cache: under a CollaborationCache folder,
    or under the folder of any source of the plan."""
    parts = _norm(dest_dir).replace("/", os.sep).split(os.sep)
    if "collaborationcache" in [part.lower() for part in parts]:
        return True
    return any(_inside(dest_dir, os.path.dirname(item.src)) for item in items)


class _NewFile(object):
    """A destination file created exclusively. io.open has no "x" mode on IronPython 2.7, so
    the file is created through os.open with O_CREAT | O_EXCL and written with os.write."""

    def __init__(self, path):
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        self.fd = os.open(path, flags, 0o666)

    def write(self, data):
        while data:
            written = os.write(self.fd, data)
            if not written:
                raise IOError("short write")
            data = data[written:]

    def close(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)


def _exists_error(name):
    return StageError(tr("A file named {0} is already in the copy folder; it is never "
                         "overwritten.",
                         "Plik {0} jest już w folderze kopii; nigdy nie jest "
                         "nadpisywany.").format(name))


def _matches(st, item):
    return st.st_size == item.size and abs(st.st_mtime - item.mtime) <= _MTIME_TOLERANCE


def copy_steps(plan, dest_dir, chunk=CHUNK, open=io.open, stat=os.stat, create=_NewFile):
    """Generator of (done_bytes, total_bytes, item): one step per chunk written, and one when an
    item is complete and checked. The plan's items are copied in order (host first) into the
    flat folder `dest_dir` (created when missing). StageError when the plan is invalid, a name
    is unsafe or clashes with a source, a destination exists, or a source changed.
    """
    items = _items(plan)
    chunk = max(1, int(chunk))
    total = sum(item.size for item in items)
    if not isinstance(dest_dir, type("")) or not dest_dir or _in_cache(dest_dir, items):
        raise _bad_plan()
    targets = []
    for item in items:
        if not safe_file_name(item.name):
            raise _bad_plan()
        target = os.path.join(dest_dir, item.name)
        if any(_same_path(target, other.src) for other in items):
            raise _bad_plan()
        targets.append(target)
    done = 0
    for item, target in zip(items, targets):
        if not _matches(stat(item.src), item):
            raise _changed()
        if not os.path.isdir(dest_dir):
            os.makedirs(dest_dir)
        source = writer = None
        created = finished = False
        try:
            source = open(item.src, "rb")
            try:
                writer = create(target)
            except EnvironmentError:    # OSError or IOError, depending on the runtime
                if os.path.exists(target):
                    raise _exists_error(item.name)
                raise
            created = True
            copied = 0
            while True:
                data = source.read(chunk)
                if not data:
                    break
                copied += len(data)
                if copied > item.size:
                    raise _changed()
                writer.write(data)
                if copied < item.size:
                    yield done + copied, total, item
            writer.close()
            source.close()
            if copied != item.size or stat(target).st_size != item.size:
                raise _changed()
            if not _matches(stat(item.src), item):
                raise _changed()
            finished = True
        finally:
            for handle in (writer, source):
                if handle is not None:
                    try:
                        handle.close()
                    except Exception:
                        pass
            if created and not finished:
                try:
                    os.remove(target)   # the partial destination only, never a source
                except Exception:
                    pass
        done += item.size
        yield done, total, item
