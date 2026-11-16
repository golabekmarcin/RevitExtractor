# -*- coding: utf-8 -*-
"""Assembly references for .NET types that live in their own assembly on .NET 8 (Revit 2025+).

Revit 2022-2024 run .NET Framework 4.8: System.Diagnostics.Process, FileVersionInfo, the socket
types and ObservableCollection come with mscorlib/System/WindowsBase, so a plain import works and
nothing here changes anything (ensure_assemblies is a no-op below .NET 5). On .NET 8 they are in
separate assemblies that IronPython does not reference by default, so `from System.Diagnostics
import FileVersionInfo` raises ImportError until clr.AddReference has loaded the assembly.

UNVERIFIED: written from the .NET 8 assembly layout, never run on a .NET 8 Revit. Pure Python
except the default arguments, which import clr/System only when called, so CPython tests inject
`add_reference`, `major` and `importer`.
"""
from __future__ import unicode_literals

# Assembly -> the types this extension uses from it (UNVERIFIED on a real Revit 2025+):
NET_CORE_ASSEMBLIES = (
    "System.Diagnostics.Process",         # Process, ProcessStartInfo (rx_runner, rx_status_ui)
    "System.Diagnostics.FileVersionInfo",  # FileVersionInfo (script.py, rx_status_ui.node_major)
    "System.Net.Primitives",              # IPAddress (rx_status_ui.free_port)
    "System.Net.Sockets",                 # TcpListener (rx_status_ui.free_port)
    "System.ObjectModel",                 # ObservableCollection (rx_export_ui, rx_status_ui)
)

_done = []


def _add_reference(name):
    import clr
    clr.AddReference(name)


def _runtime_major():
    from System import Environment
    return Environment.Version.Major


def ensure_assemblies(add_reference=None, major=None):
    """Add NET_CORE_ASSEMBLIES on .NET 5+; return the names added. Never raises.

    With no arguments it runs once per process. `major` is the runtime major version or a
    function returning it (4 = .NET Framework, 8 = .NET 8); an unknown version adds nothing.
    """
    default = add_reference is None and major is None
    if default and _done:
        return list(_done[0])
    add = add_reference or _add_reference
    try:
        version = major() if callable(major) else major
        if version is None:
            version = _runtime_major()
        version = int(version)
    except Exception:
        return []
    added = []
    if version >= 5:
        for name in NET_CORE_ASSEMBLIES:
            try:
                add(name)
                added.append(name)
            except Exception:
                pass  # missing or already loaded: the plain import decides
    if default:
        _done.append(tuple(added))
    return added


def _import_file_version_info():
    from System.Diagnostics import FileVersionInfo
    return FileVersionInfo


def version_info(path, importer=None, add_reference=None):
    """FileVersionInfo of `path`, or None on any failure (also when the type cannot be imported).

    Tries the plain import; on ImportError adds System.Diagnostics.FileVersionInfo and retries.
    """
    importer = importer or _import_file_version_info
    try:
        try:
            cls = importer()
        except ImportError:
            (add_reference or _add_reference)("System.Diagnostics.FileVersionInfo")
            cls = importer()
        return cls.GetVersionInfo(path)
    except Exception:
        return None


def file_version(path, importer=None, add_reference=None):
    """The FileVersion text of `path`, or "" when it cannot be read."""
    info = version_info(path, importer, add_reference)
    try:
        version = info.FileVersion if info is not None else None
    except Exception:
        return ""
    return ("%s" % version).strip() if version else ""
