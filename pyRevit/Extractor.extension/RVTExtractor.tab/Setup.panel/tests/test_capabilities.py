# -*- coding: utf-8 -*-
"""Tests for lib/rx_capabilities.py (pure Python, no Revit)."""
import ast
import sys
import types
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[3] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))

import rx_capabilities  # noqa: E402
from rx_capabilities import UnsupportedRevit, element_id_value, for_revit  # noqa: E402


def polish():
    """pyRevit set to Polish (same resolver shape as test_window_legacy.polish)."""
    def get_locale_string(string_dict):
        for code in ("pl", "polish", "en_us", "english"):
            if code in string_dict:
                return string_dict[code]
        return None
    applocales = types.SimpleNamespace(get_locale_string=get_locale_string)
    coreutils = types.SimpleNamespace(applocales=applocales)
    return {"pyrevit": types.SimpleNamespace(coreutils=coreutils),
            "pyrevit.coreutils": coreutils, "pyrevit.coreutils.applocales": applocales}


class ForRevitTable(unittest.TestCase):
    def test_legacy_years(self):
        for year in (2022, 2023, 2024, 2025):
            caps = for_revit(year)
            self.assertEqual(caps.year, year)
            self.assertTrue(caps.verified)
            self.assertEqual(caps.view_key, "view_ids")
            self.assertEqual(caps.formats, ())
            self.assertFalse(caps.ifc_setups)
            self.assertFalse(caps.extended_properties)
            self.assertFalse(caps.topology_metadata)

    def test_2026(self):
        caps = for_revit(2026)
        self.assertEqual(caps.year, 2026)
        self.assertTrue(caps.verified)
        self.assertEqual(caps.view_key, "view_unique_ids")
        self.assertEqual(caps.formats, ("dwg", "ifc"))
        self.assertTrue(caps.ifc_setups)
        self.assertTrue(caps.extended_properties)
        self.assertTrue(caps.topology_metadata)

    def test_newer_years_use_newest_row_unverified(self):
        for year in (2027, 2030):
            caps = for_revit(year)
            self.assertEqual(caps.year, year)
            self.assertFalse(caps.verified)
            self.assertFalse(caps.tested)
            self.assertEqual(caps.view_key, "view_unique_ids")
            self.assertEqual(caps.formats, ("dwg", "ifc"))
            self.assertTrue(caps.ifc_setups)

    def test_tested_only_2022(self):
        self.assertTrue(for_revit(2022).tested)
        for year in (2023, 2024, 2025, 2026, 2027):
            self.assertFalse(for_revit(year).tested, year)

    def test_input_forms(self):
        for value in ("2022", 2022, " 2022 "):
            self.assertEqual(for_revit(value).year, 2022)

    def test_rejected_inputs(self):
        for value in (2021, "2021", "", None, "abc", "2022.1", True, False, 2022.0, "-2022"):
            with self.assertRaises(UnsupportedRevit):
                for_revit(value)

    def test_unsupported_is_value_error(self):
        self.assertTrue(issubclass(UnsupportedRevit, ValueError))

    def test_message_names_value_and_floor(self):
        with self.assertRaises(UnsupportedRevit) as ctx:
            for_revit("2021")
        self.assertIn("2021", str(ctx.exception))
        self.assertIn("2022", str(ctx.exception))

    def test_read_only(self):
        caps = for_revit(2022)
        with self.assertRaises(AttributeError):
            caps.year = 2030
        with self.assertRaises(AttributeError):
            caps.label = "x"


class Labels(unittest.TestCase):
    def test_english(self):
        self.assertEqual(for_revit(2022).label, "Revit 2022")
        self.assertEqual(for_revit(2024).label, "Revit 2024 (not tested yet)")
        self.assertEqual(for_revit(2026).label, "Revit 2026 (not tested yet)")
        self.assertEqual(for_revit(2027).label, "Revit 2027 (untested, treated as 2026)")

    def test_polish(self):
        saved = {k: sys.modules.get(k) for k in polish()}
        sys.modules.update(polish())
        try:
            self.assertEqual(for_revit(2022).label, "Revit 2022")
            self.assertEqual(for_revit(2024).label, "Revit 2024 (jeszcze nie testowane)")
            self.assertEqual(for_revit(2027).label,
                             "Revit 2027 (nietestowane, traktowane jak 2026)")
            with self.assertRaises(UnsupportedRevit) as ctx:
                for_revit("2021")
            message = str(ctx.exception)
            self.assertIn("2021", message)
            self.assertIn("2022", message)
            self.assertNotIn("Unsupported", message)
        finally:
            for key, value in saved.items():
                if value is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value


class ElementIdValue(unittest.TestCase):
    def test_only_integer_value(self):
        self.assertEqual(element_id_value(types.SimpleNamespace(IntegerValue=42)), 42)

    def test_only_value(self):
        self.assertEqual(element_id_value(types.SimpleNamespace(Value=2 ** 40)), 2 ** 40)

    def test_integer_value_never_read_when_value_exists(self):
        class Both(object):
            Value = 7

            @property
            def IntegerValue(self):
                raise AssertionError("IntegerValue must not be read")
        self.assertEqual(element_id_value(Both()), 7)


class ImportGuard(unittest.TestCase):
    def test_no_revit_imports(self):
        tree = ast.parse((LIB / "rx_capabilities.py").read_text(encoding="utf-8"))
        banned = {"pyrevit", "Autodesk", "System", "clr"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                self.assertNotIn(name.split(".")[0], banned, name)


if __name__ == "__main__":
    unittest.main()
