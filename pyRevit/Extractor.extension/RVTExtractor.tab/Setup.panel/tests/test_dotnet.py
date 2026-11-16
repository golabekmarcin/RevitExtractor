# -*- coding: utf-8 -*-
"""Tests for lib/rx_dotnet.py: .NET types that moved to separate assemblies on Revit 2025+.

CPython 3 only. Whether the AddReference names are right on a real .NET 8 Revit cannot be tested
here (UNVERIFIED; specs/SPEC-export-button.md).
"""
import ast
import sys
import types
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parents[1]
LIB = PANEL.parents[1] / "lib"
BUTTON = PANEL / "Export.pushbutton"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))

import rx_dotnet  # noqa: E402


class EnsureAssembliesTests(unittest.TestCase):
    def test_adds_every_assembly_on_dotnet_8(self):
        added = []
        result = rx_dotnet.ensure_assemblies(add_reference=added.append, major=8)
        self.assertEqual(added, list(rx_dotnet.NET_CORE_ASSEMBLIES))
        self.assertEqual(result, added)

    def test_does_nothing_on_net_framework(self):
        added = []
        self.assertEqual(rx_dotnet.ensure_assemblies(add_reference=added.append, major=4), [])
        self.assertEqual(added, [])

    def test_does_nothing_when_the_runtime_version_is_unknown(self):
        added = []

        def broken():
            raise RuntimeError("no System")
        self.assertEqual(rx_dotnet.ensure_assemblies(add_reference=added.append,
                                                     major=broken), [])
        self.assertEqual(added, [])

    def test_one_failing_assembly_does_not_stop_the_rest(self):
        added = []

        def add(name):
            if name == rx_dotnet.NET_CORE_ASSEMBLIES[0]:
                raise IOError("not found")
            added.append(name)
        result = rx_dotnet.ensure_assemblies(add_reference=add, major=8)
        self.assertEqual(added, list(rx_dotnet.NET_CORE_ASSEMBLIES[1:]))
        self.assertEqual(result, added)

    def test_the_default_call_never_raises_on_cpython(self):
        rx_dotnet.ensure_assemblies()


class FileVersionTests(unittest.TestCase):
    def info_class(self, version="24.1.0", major=24):
        class Info(object):
            @staticmethod
            def GetVersionInfo(path):
                return types.SimpleNamespace(FileVersion=version, FileMajorPart=major, path=path)
        return Info

    def test_plain_import_works(self):
        added = []
        info = rx_dotnet.version_info("x.dll", importer=lambda: self.info_class(),
                                      add_reference=added.append)
        self.assertEqual(info.FileVersion, "24.1.0")
        self.assertEqual(added, [])

    def test_retries_after_import_error_with_the_assembly_added(self):
        added = []
        calls = []

        def importer():
            calls.append(1)
            if not added:
                raise ImportError("Cannot import name FileVersionInfo")
            return self.info_class()
        info = rx_dotnet.version_info("x.dll", importer=importer, add_reference=added.append)
        self.assertEqual(added, ["System.Diagnostics.FileVersionInfo"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(info.FileMajorPart, 24)

    def test_total_failure_gives_none_and_empty_text(self):
        def importer():
            raise ImportError("no")

        def add(name):
            raise IOError("no assembly")
        self.assertIsNone(rx_dotnet.version_info("x.dll", importer=importer, add_reference=add))
        self.assertEqual(rx_dotnet.file_version("x.dll", importer=importer, add_reference=add), "")

    def test_a_failing_read_gives_none(self):
        class Info(object):
            @staticmethod
            def GetVersionInfo(path):
                raise IOError("missing file")
        self.assertIsNone(rx_dotnet.version_info("x.dll", importer=lambda: Info,
                                                 add_reference=lambda name: None))

    def test_file_version_is_stripped_text(self):
        self.assertEqual(rx_dotnet.file_version("x.dll", importer=lambda: self.info_class(" 2.0 ")),
                         "2.0")
        self.assertEqual(rx_dotnet.file_version("x.dll", importer=lambda: self.info_class(None)),
                         "")


# Types whose assembly is a separate reference on .NET 8: no module may import them at module
# level (a failed import would break the button); inside a function it is fine because
# rx_dotnet.ensure_assemblies() ran at import time of the module.
GUARDED = {("System.Diagnostics", "FileVersionInfo"), ("System.Diagnostics", "Process"),
           ("System.Diagnostics", "ProcessStartInfo"), ("System.Net.Sockets", "TcpListener"),
           ("System.Net", "IPAddress"), ("System.Collections.ObjectModel", "ObservableCollection")}


def module_level_guarded(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            found.extend((node.module, a.name) for a in node.names
                         if (node.module, a.name) in GUARDED)
    return found


class SourceScanTests(unittest.TestCase):
    def test_no_module_imports_a_moved_type_at_module_level(self):
        files = list(LIB.glob("*.py")) + list(BUTTON.glob("*.py"))
        self.assertTrue(files)
        for path in files:
            if path.name == "rx_export_ui.py":
                continue  # ObservableCollection: documented below
            self.assertEqual(module_level_guarded(path), [], path.name)

    def test_export_ui_observable_collection_comes_after_ensure_assemblies(self):
        # rx_export_ui imports ObservableCollection at module level; script.py calls
        # ensure_assemblies() before it imports rx_export_ui.
        text = (BUTTON / "script.py").read_text(encoding="utf-8")
        self.assertLess(text.index("ensure_assemblies()"), text.index("from rx_export_ui import"))
        self.assertIn("import rx_dotnet", text)

    def test_scanner_catches_what_it_claims(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.py"
            path.write_text("from System.Diagnostics import FileVersionInfo\n"
                            "def f():\n    from System.Net.Sockets import TcpListener\n",
                            encoding="utf-8")
            self.assertEqual(module_level_guarded(path), [("System.Diagnostics", "FileVersionInfo")])

    def test_modules_that_import_the_types_in_functions_call_ensure_assemblies(self):
        for name in ("rx_runner.py", "rx_status_ui.py"):
            text = (LIB / name).read_text(encoding="utf-8")
            self.assertIn("ensure_assemblies()", text, name)
            self.assertIn("rx_dotnet", text, name)

    def test_status_ui_and_script_use_the_helper_for_file_versions(self):
        self.assertNotIn("FileVersionInfo", (BUTTON / "script.py").read_text(encoding="utf-8"))
        ui = (LIB / "rx_status_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("import FileVersionInfo", ui)
        self.assertIn("rx_dotnet.version_info", ui)


if __name__ == "__main__":
    unittest.main()
