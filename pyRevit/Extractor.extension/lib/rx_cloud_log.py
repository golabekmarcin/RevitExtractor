# -*- coding: utf-8 -*-
"""Local diagnostics log of failed in-place cloud opens (rx_reader.read_cloud):
%APPDATA%\\RevitExtractor\\logs\\cloud-open-<yyyymmdd>.log, appended, each file capped at
MAX_BYTES (the oldest lines are cut), at most KEEP_FILES files kept.

The log stays on this computer and may hold model names from Revit's own exception texts.
Every GUID-shaped text is masked before it is written; GUIDs are described by shape only.
Never written under a CollaborationCache folder. Pure file IO, no Revit or .NET import.
Compatible with pyRevit IronPython 2.7.
"""
from __future__ import unicode_literals

import datetime
import io
import os
import re

FOLDER_TEXT = "%APPDATA%\\RevitExtractor\\logs"   # what the UI shows: no user name in it
MAX_BYTES = 200 * 1024
KEEP_FILES = 10
_PREFIX = "cloud-open-"
_GUID = re.compile(r"[0-9A-Fa-f]{8}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4}-?"
                   r"[0-9A-Fa-f]{12}")
_CANONICAL = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                        r"[0-9a-fA-F]{12}$")
_MAX_INNER = 8

try:
    text = unicode  # IronPython 2.7
except NameError:
    text = str


def log_folder(appdata):
    return os.path.join(appdata, "RevitExtractor", "logs")


def mask(value):
    return _GUID.sub("<guid>", value)


def guid_shape(value):
    """'len=36 canonical=yes': never the value itself."""
    try:
        value = text(value)
    except Exception:
        return "unreadable"
    return "len=%d canonical=%s" % (len(value), "yes" if _CANONICAL.match(value) else "no")


def _safe(value):
    try:
        return text(value)
    except Exception:
        try:
            return text(repr(value))
        except Exception:
            return "<unreadable>"


def exception_lines(error, indent="  "):
    """The Python type and text, then the .NET exception (clsException, or the error itself)
    and its InnerException chain: full type name, HResult, Message, StackTrace."""
    lines = [indent + "python: %s: %s" % (type(error).__name__, _safe(error))]
    current = getattr(error, "clsException", None)
    if current is None and hasattr(error, "GetType"):
        current = error
    depth = 0
    while current is not None and depth < _MAX_INNER:
        label = "exception" if depth == 0 else "inner %d" % depth
        try:
            name = _safe(current.GetType().FullName)
        except Exception:
            name = "?"
        lines.append(indent + "%s: %s" % (label, name))
        for member in ("HResult", "Message", "Source", "StackTrace"):
            value = getattr(current, member, None)
            if value is not None and value != "":
                for number, part in enumerate(_safe(value).splitlines() or [""]):
                    lines.append(indent + ("  %s: %s" % (member, part) if number == 0
                                           else "    " + part))
        current = getattr(current, "InnerException", None)
        depth += 1
    return lines


def _in_cache(path):
    parts = os.path.normcase(os.path.abspath(path)).replace("/", "\\").split("\\")
    return "collaborationcache" in parts


def _prune(folder):
    try:
        names = sorted(name for name in os.listdir(folder)
                       if name.startswith(_PREFIX) and name.endswith(".log"))
    except OSError:
        return
    for name in names[:-KEEP_FILES] if len(names) > KEEP_FILES else []:
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


def append(folder, lines, now=None, max_bytes=MAX_BYTES):
    """Append one entry (GUIDs masked) to today's log in `folder`; cut the oldest lines so the
    file stays within max_bytes. Returns the file path, or None when nothing could be written.
    Never raises."""
    try:
        if not folder or _in_cache(folder):
            return None
        now = now or datetime.datetime.now()
        entry = mask("\n".join(_safe(line) for line in lines)).rstrip("\n") + "\n\n"
        data = entry.encode("utf-8")
        if len(data) > max_bytes:
            data = data[:max_bytes - 20] + "\n[entry cut]\n".encode("utf-8")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, _PREFIX + now.strftime("%Y%m%d") + ".log")
        old = b""
        if os.path.isfile(path):
            with io.open(path, "rb") as handle:
                old = handle.read()
        if len(old) + len(data) > max_bytes:
            old = old[len(old) + len(data) - max_bytes:]
            cut = old.find(b"\n")
            old = old[cut + 1:] if cut >= 0 else b""
            with io.open(path, "wb") as handle:
                handle.write(old + data)
        else:
            with io.open(path, "ab") as handle:
                handle.write(data)
        _prune(folder)
        return path
    except Exception:
        return None
