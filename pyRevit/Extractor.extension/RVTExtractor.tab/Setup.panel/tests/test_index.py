# -*- coding: utf-8 -*-
"""Tests for lib/rx_index.py (pure Python, no Revit).

Parity by execution: the old button builders are loaded by file path and compared case by case.
The parity tests go away with the old buttons (see specs/SPEC-index-builder.md, Risks).
"""
import ast
import importlib.util
import itertools
import json
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PANEL = Path(__file__).resolve().parents[1]
LIB = Path(__file__).resolve().parents[3] / "lib"
REPO = Path(__file__).resolve().parents[5]
LAUNCHER = REPO / "Analyzer" / "public" / "downloads" / "Start-RevitExport.ps1"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))  # append, never insert (same-named modules in the bundles)

import rx_index  # noqa: E402
from rx_capabilities import for_revit  # noqa: E402
from rx_index import (SetupError, build_index, database_warning, defaults,  # noqa: E402
                      require_index_shape, to_json)


def load(name, path, pinned=None):
    """Load a module by file path under a unique name; `pinned` sibling modules are visible
    in sys.modules while it runs (the bundles import extractor_i18n by bare name)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, pinned or {}):
        spec.loader.exec_module(module)
    return module


LEGACY_DIR = PANEL / "ExportSetupLegacy.pushbutton"
NEWEST_DIR = PANEL / "ExportSetup.pushbutton"
legacy_i18n = load("index_test_legacy_i18n", LEGACY_DIR / "extractor_i18n.py")
legacy = load("index_test_legacy_config", LEGACY_DIR / "extractor_config.py",
              {"extractor_i18n": legacy_i18n})
newest = load("index_test_newest_config", NEWEST_DIR / "extractor_config.py")

LEGACY_YEARS = (2022, 2023, 2024, 2025)
NEWEST_YEARS = (2026, 2027)


def polish():
    """pyRevit set to Polish (same resolver shape as test_capabilities.polish)."""
    def get_locale_string(string_dict):
        for code in ("pl", "polish", "en_us", "english"):
            if code in string_dict:
                return string_dict[code]
        return None
    applocales = types.SimpleNamespace(get_locale_string=get_locale_string)
    coreutils = types.SimpleNamespace(applocales=applocales)
    return {"pyrevit": types.SimpleNamespace(coreutils=coreutils),
            "pyrevit.coreutils": coreutils, "pyrevit.coreutils.applocales": applocales}


def outcome(function, *args):
    try:
        return ("ok", function(*args))
    except Exception as error:  # compared by type name and text
        return (type(error).__name__, str(error))


def in_polish(function, *args):
    with patch.dict(sys.modules, polish()):
        return outcome(function, *args)


SEL_OK_2D = [100, "20", "100"]
SEL_OK_3D = ["2147483647", 5]
INVALID_ID_SELECTIONS = [[], [None], [True], [1.5], ["1.5"], ["view-uid"], [0], [-1],
                         [2147483648], [""], ["²"], ["10", None]]
NOT_A_LIST = ["123", 123, None, {"1": 1}, b"12"]
UNKNOWN_SCOPES = [None, 1, "everything"]


def legacy_cases():
    """(settings, selected_2d, selected_3d) covering the nine native-check profiles and every
    case of LegacyConfigTests."""
    cases = [
        # the nine profiles of validate_native_legacy.ps1
        ({}, [], []),
        (dict(enable_3d=False, scope_2d="selected"), [14325], []),
        (dict(enable_2d=False, scope_3d="selected"), [], [14720]),
        (dict(scope_2d="selected", scope_3d="selected"), [14325, 22118], [14720]),
        (dict(pdb=False), [], []),
        (dict(enable_2d=False, enable_3d=False), [], []),
        (dict(aec_model_data=False, design_description=False, generate_master_views=True,
              f2d=True), [], []),
        (dict(scope_3d="selected"), [], [2147483647]),
        (dict(enable_3d=False, pdb=False), [], []),
        # LegacyConfigTests
        (None, None, None),
        (dict(enable_2d=False, enable_3d=False, pdb=False), [], []),
        (dict(scope_2d="selected", scope_3d="selected"), ["100", "20", 100], ["2147483647"]),
        (dict(scope_3d="selected"), [], ("5",)),
        (dict(enable_2d=False, scope_2d="selected"), ["stale-uid"], ["stale-uid"]),
        (dict(aec_model_data=False, design_description=False, generate_master_views=True,
              f2d=True), [], []),
        (dict(pdb=False), [], []),
        (dict(enable_3d=False, pdb=False), [], []),
        (dict(scope_2d="selected"), ["x"], []),
    ]
    for dimension in ("2d", "3d"):
        for selection in INVALID_ID_SELECTIONS:
            cases.append(({"scope_" + dimension: "selected"},
                          selection if dimension == "2d" else [],
                          selection if dimension == "3d" else []))
    for selection in NOT_A_LIST:
        cases.append((dict(scope_2d="selected"), selection, []))
    for scope in UNKNOWN_SCOPES:
        cases.append(({"scope_2d": scope}, [], []))
    for options in ({"ifc": True}, {"dwg": True}, {"ifc_setup_name": "Setup"},
                    {"extended_properties": True}, {"topology_metadata": True}):
        cases.append((options, [], []))
    for enable_2d, enable_3d, pdb in itertools.product((True, False), repeat=3):
        for scope_2d, scope_3d in itertools.product(("default", "selected"), repeat=2):
            cases.append((dict(enable_2d=enable_2d, enable_3d=enable_3d, pdb=pdb,
                               scope_2d=scope_2d, scope_3d=scope_3d), SEL_OK_2D, SEL_OK_3D))
    for flags in itertools.product((True, False), repeat=4):
        cases.append((dict(zip(("aec_model_data", "design_description",
                                "generate_master_views", "f2d"), flags)), [], []))
    return cases


def newest_cases():
    """Every case of test_config.py plus the settings matrix; UniqueId selections."""
    cases = [
        ({}, [], []),
        (None, None, None),
        (dict(enable_3d=False, scope_2d="selected"), ["floor-uid"], []),
        (dict(scope_2d="selected"), ["sheet-uid", "floor-uid", "sheet-uid"], []),
        (dict(scope_2d="selected", scope_3d="selected"), ["plan"], ["3d"]),
        (dict(enable_2d=False, scope_2d="selected"), [], []),
        ({}, ["old-uid"], []),
        (dict(pdb=False, extended_properties=True), [], []),
        (dict(pdb=True, extended_properties=True), [], []),
        (dict(enable_2d=False, enable_3d=False), [], []),
        (dict(enable_2d=False, enable_3d=False, pdb=False), [], []),
        (dict(aec_model_data=False, design_description=False, generate_master_views=True,
              topology_metadata=True, extended_properties=True, f2d=True, dwg=True, ifc=True),
         [], []),
        (dict(enable_2d=False, enable_3d=False, pdb=False, ifc=True), [], []),
        (dict(enable_2d=False, enable_3d=False, pdb=False, dwg=True), [], []),
        (dict(ifc=True, ifc_setup_name="Setup"), [], []),
        (dict(ifc=False, ifc_setup_name="Setup"), [], []),
        (dict(ifc=True, ifc_setup_name=""), [], []),
        (dict(scope_2d="selected"), ["c8923f5e-6a14-4420-9b1d-c31d7ae067d2-00000020"], []),
        (dict(scope_2d="selected"), ["a", "", None, "a"], []),
        (dict(scope_2d="selected"), ("b", "a"), []),
    ]
    for dimension in ("2d", "3d"):
        for selection in ([], [None], [""], ["", None]):
            cases.append(({"scope_" + dimension: "selected"},
                          selection if dimension == "2d" else [],
                          selection if dimension == "3d" else []))
    cases.append((dict(scope_2d="selected"), None, []))
    cases.append((dict(scope_2d="selected"), [], None))
    cases.append((dict(scope_2d="everything"), [], []))
    for enable_2d, enable_3d, pdb in itertools.product((True, False), repeat=3):
        for dwg, ifc in itertools.product((True, False), repeat=2):
            for scope_2d, scope_3d in itertools.product(("default", "selected"), repeat=2):
                cases.append((dict(enable_2d=enable_2d, enable_3d=enable_3d, pdb=pdb, dwg=dwg,
                                   ifc=ifc, scope_2d=scope_2d, scope_3d=scope_3d,
                                   extended_properties=True, topology_metadata=True),
                              ["u2", "u1"], ["u3"]))
    return cases


def describe(case):
    return repr(case)


class LegacyParity(unittest.TestCase):
    def test_defaults(self):
        for year in LEGACY_YEARS:
            self.assertEqual(defaults(for_revit(year)), legacy.DEFAULTS)
            self.assertEqual(len(defaults(for_revit(year))), 9)

    def test_matrix_equals_legacy_builder_in_both_languages(self):
        cases = legacy_cases()
        self.assertGreater(len(cases), 100)
        for year in LEGACY_YEARS:
            caps = for_revit(year)
            for case in cases:
                settings, two, three = case
                with self.subTest(year=year, case=describe(case)):
                    expected = outcome(legacy.build_index, settings, two, three)
                    actual = outcome(build_index, caps, settings, two, three)
                    self.assertEqual(actual[0], expected[0])
                    self.assertEqual(actual[1], expected[1])
                    if expected[0] == "ok":
                        self.assertEqual(to_json(actual[1]), legacy.to_json(expected[1]))
                    expected_pl = in_polish(legacy.build_index, settings, two, three)
                    actual_pl = in_polish(build_index, caps, settings, two, three)
                    self.assertEqual(actual_pl, expected_pl)

    def test_error_cases_exist_in_both_languages(self):
        caps = for_revit(2022)
        english = outcome(build_index, caps, {"enable_2d": False, "enable_3d": False,
                                              "pdb": False})
        polish_text = in_polish(build_index, caps, {"enable_2d": False, "enable_3d": False,
                                                    "pdb": False})
        self.assertEqual(english, ("SetupError", "Enable 2D views, 3D views or the database."))
        self.assertEqual(polish_text,
                         ("SetupError", "Włącz widoki 2D, widoki 3D lub bazę danych."))

    def test_legacy_errors_are_setup_errors(self):
        caps = for_revit(2022)
        with self.assertRaises(SetupError):
            build_index(caps, {"ifc": True})
        self.assertTrue(issubclass(SetupError, ValueError))

    def test_database_warning_equals_legacy(self):
        settings_cases = [None, {}, {"pdb": False}, {"enable_3d": False},
                          {"enable_3d": False, "pdb": False},
                          {"enable_3d": False, "pdb": False, "enable_2d": False}]
        for year in LEGACY_YEARS:
            caps = for_revit(year)
            for settings in settings_cases:
                with self.subTest(year=year, settings=settings):
                    self.assertEqual(database_warning(caps, settings),
                                     legacy.database_warning(settings))
                    with patch.dict(sys.modules, polish()):
                        self.assertEqual(database_warning(caps, settings),
                                         legacy.database_warning(settings))
        self.assertTrue(database_warning(for_revit(2022), {"enable_3d": False, "pdb": False}))

    def test_database_warning_empty_on_newest_row(self):
        for year in NEWEST_YEARS:
            for settings in (None, {"enable_3d": False, "pdb": False}):
                self.assertEqual(database_warning(for_revit(year), settings), "")

    def test_db_export_key_follows_the_row_flag_only(self):
        derivative = build_index(for_revit(2022), {"pdb": False})[
            "metadata"]["parameters"]["derivative_type"]
        self.assertEqual(derivative["3dviewing"], {"db_export": False})
        derivative = build_index(for_revit(2026), {"pdb": False})[
            "metadata"]["parameters"]["derivative_type"]
        self.assertEqual(derivative["3dviewing"], {})


class NewestParity(unittest.TestCase):
    def test_defaults(self):
        for year in NEWEST_YEARS:
            self.assertEqual(defaults(for_revit(year)), newest.DEFAULTS)
            self.assertEqual(len(defaults(for_revit(year))), 13)

    def test_defaults_are_a_copy(self):
        caps = for_revit(2022)
        defaults(caps)["pdb"] = False
        self.assertTrue(defaults(caps)["pdb"])

    def test_matrix_equals_2026_builder(self):
        cases = newest_cases()
        self.assertGreater(len(cases), 100)
        for year in NEWEST_YEARS:
            caps = for_revit(year)
            for case in cases:
                settings, two, three = case
                with self.subTest(year=year, case=describe(case)):
                    expected = outcome(newest.build_index, settings, two, three)
                    with patch.dict(sys.modules, polish()):
                        actual_pl = outcome(build_index, caps, settings, two, three)
                    actual = outcome(build_index, caps, settings, two, three)
                    self.assertEqual(actual[0], expected[0])
                    if expected[0] == "ok":
                        self.assertEqual(actual[1], expected[1])
                        self.assertEqual(to_json(actual[1]), newest.to_json(expected[1]))
                        self.assertEqual(actual_pl, actual)
                    else:
                        # The old texts are Polish only; English must exist and differ.
                        self.assertEqual(actual_pl[1], expected[1])
                        self.assertNotEqual(actual[1], expected[1])

    def test_ifc_setup_name_only_with_ifc(self):
        caps = for_revit(2026)
        parameters = build_index(caps, {"ifc": True, "ifc_setup_name": "Setup"})[
            "metadata"]["parameters"]
        self.assertEqual(parameters["direct_params"], {"IFCExportOption": "Setup"})
        self.assertEqual(parameters["derivative_type"]["export"], {"to": ["ifc"]})
        parameters = build_index(caps, {"ifc_setup_name": "Setup"})["metadata"]["parameters"]
        self.assertNotIn("direct_params", parameters)

    def test_selected_ids_are_sorted_unique_text(self):
        result = build_index(for_revit(2026), {"scope_2d": "selected"}, ["b", "a", "b", "", None])
        self.assertEqual(result["metadata"]["parameters"]["derivative_type"]["2dviewing"],
                         {"view_unique_ids": ["a", "b"]})

    def test_non_text_unique_ids_are_rejected(self):
        for selection in ([5], ["a", 5], [b"a"], [True]):
            with self.subTest(selection=selection), self.assertRaises(SetupError):
                build_index(for_revit(2026), {"scope_3d": "selected"}, [], selection)


class DeliberateDifferences(unittest.TestCase):
    """Invalid input raises SetupError on every row (the 2026 button iterated a string per
    character or raised TypeError)."""

    def test_string_selection_raises_on_every_row(self):
        for year in LEGACY_YEARS + NEWEST_YEARS:
            caps = for_revit(year)
            for selection in ("abc", "123", 123, b"12", {"1": 1}):
                for dimension in ("2d", "3d"):
                    with self.subTest(year=year, selection=selection, dimension=dimension):
                        two = selection if dimension == "2d" else []
                        three = selection if dimension == "3d" else []
                        with self.assertRaises(SetupError):
                            build_index(caps, {"scope_" + dimension: "selected"}, two, three)

    def test_unknown_scope_raises_on_every_row(self):
        for year in LEGACY_YEARS + NEWEST_YEARS:
            caps = for_revit(year)
            for scope in (None, 1, "everything", "", ["default"]):
                for dimension in ("2d", "3d"):
                    with self.subTest(year=year, scope=scope, dimension=dimension):
                        with self.assertRaises(SetupError):
                            build_index(caps, {"scope_" + dimension: scope})

    def test_old_newest_builder_really_differs(self):
        # Documents the old behaviour this module deliberately does not copy.
        derivative = newest.build_index({"scope_2d": "selected"}, "abc", [])[
            "metadata"]["parameters"]["derivative_type"]
        self.assertEqual(derivative["2dviewing"], {"view_unique_ids": ["a", "b", "c"]})
        with self.assertRaises(TypeError):
            newest.build_index({"scope_2d": None})

    def test_messages_exist_in_both_languages(self):
        caps = for_revit(2026)
        cases = [({"scope_2d": "selected"}, "abc", []), ({"scope_2d": None}, [], []),
                 ({"scope_3d": "selected"}, [], [True])]
        for year in (2022, 2026):
            caps = for_revit(year)
            for settings, two, three in cases:
                with self.subTest(year=year, settings=settings):
                    english = outcome(build_index, caps, settings, two, three)
                    polish_text = in_polish(build_index, caps, settings, two, three)
                    self.assertEqual(english[0], "SetupError")
                    self.assertEqual(polish_text[0], "SetupError")
                    self.assertNotEqual(english[1], polish_text[1])


def launcher_default_index():
    text = LAUNCHER.read_text(encoding="utf-8")
    match = re.search(r"\$defaultIndexJson = @'\r?\n(.*?)\r?\n'@", text, re.DOTALL)
    assert match, "default index here-string not found in Start-RevitExport.ps1"
    return json.loads(match.group(1))


class LauncherDefaultAndShape(unittest.TestCase):
    def test_no_argument_index_equals_launcher_default_on_every_row(self):
        default = launcher_default_index()
        for year in LEGACY_YEARS + NEWEST_YEARS + (2030,):
            with self.subTest(year=year):
                self.assertEqual(build_index(for_revit(year)), default)

    def test_require_index_shape_accepts_build_results_and_launcher_default(self):
        require_index_shape(launcher_default_index())
        for year in LEGACY_YEARS + NEWEST_YEARS:
            caps = for_revit(year)
            for settings, two, three in (legacy_cases() if year < 2026 else newest_cases()):
                result = outcome(build_index, caps, settings, two, three)
                if result[0] == "ok":
                    require_index_shape(result[1])

    def test_require_index_shape_rejects_bad_data(self):
        good = {"metadata": {"parameters": {"derivative_type": {}}}}
        require_index_shape(good)
        bad = [None, [], "x", 5, {}, {"metadata": None}, {"metadata": {}},
               {"metadata": {"parameters": {}}}, {"metadata": {"parameters": None}},
               {"metadata": {"parameters": {"derivative_type": None}}},
               {"metadata": {"parameters": {"derivative_type": []}}},
               {"metadata": [], }, {"metadata": {"parameters": []}}]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(SetupError):
                require_index_shape(data)

    def test_require_index_shape_message_in_both_languages(self):
        english = outcome(require_index_shape, None)
        polish_text = in_polish(require_index_shape, None)
        self.assertEqual(english[0], "SetupError")
        self.assertNotEqual(english[1], polish_text[1])


class ToJson(unittest.TestCase):
    def test_format(self):
        text = to_json({"a": {"b": "ł"}})
        self.assertTrue(text.endswith("}\n"))
        self.assertIn("  \"a\"", text)
        self.assertIn("ł", text)  # ensure_ascii False
        self.assertEqual(json.loads(text), {"a": {"b": "ł"}})


class Ironpython27Guard(unittest.TestCase):
    SOURCE = (LIB / "rx_index.py").read_text(encoding="utf-8")

    def test_no_revit_imports(self):
        tree = ast.parse(self.SOURCE)
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

    def test_no_python3_only_syntax(self):
        tree = ast.parse(self.SOURCE)
        for node in ast.walk(tree):
            self.assertNotIsInstance(node, ast.JoinedStr)      # f-strings
            self.assertNotIsInstance(node, ast.AnnAssign)      # annotations
            if isinstance(node, (ast.FunctionDef, ast.arg)):
                if isinstance(node, ast.arg):
                    self.assertIsNone(node.annotation)
                else:
                    self.assertIsNone(node.returns)
        self.assertNotIn("pathlib", self.SOURCE)
        self.assertTrue(self.SOURCE.startswith("# -*- coding: utf-8 -*-"))
        self.assertIn("from __future__ import unicode_literals", self.SOURCE)

    def test_every_raise_goes_through_tr(self):
        tree = ast.parse(self.SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and node.exc is not None:
                text = ast.get_source_segment(self.SOURCE, node)
                self.assertIn("tr(", text, text)


class NoYearComparisons(unittest.TestCase):
    def test_module_never_reads_the_year(self):
        source = (LIB / "rx_index.py").read_text(encoding="utf-8")
        self.assertNotIn(".year", source)


if __name__ == "__main__":
    unittest.main()
