# -*- coding: utf-8 -*-
"""Tests for the Export button (specs/SPEC-export-button.md).

Structure (one class group per layer, so later layers can be added without touching these):
  1. Logic: rx_export_logic.py (pure; criteria 3, 4, 5, 10)
  2. Static checks over the button's files (criterion 12 parts)
  3. (window tests are added below by a later task)
"""
import ast
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parents[1]
LIB = PANEL.parents[1] / "lib"
BUTTON = PANEL / "Export.pushbutton"
LEGACY = PANEL / "ExportSetupLegacy.pushbutton"
OLD2026 = PANEL / "ExportSetup.pushbutton"
REPO = Path(__file__).resolve().parents[5]
LAUNCHER = REPO / "Analyzer" / "public" / "downloads" / "Start-RevitExport.ps1"

# Append, never insert: the old bundles' tests import same-named modules by bare name.
for folder in (LIB, BUTTON):
    if str(folder) not in sys.path:
        sys.path.append(str(folder))
if str(LEGACY) not in sys.path:
    sys.path.append(str(LEGACY))  # extractor_config needs extractor_i18n (parity test only)

import rx_capabilities  # noqa: E402
import rx_export_logic as logic  # noqa: E402
from rx_export_logic import SetupError  # noqa: E402
from rx_index import build_index  # noqa: E402


def polish():
    """pyRevit set to Polish (same resolver shape as test_catalog.polish)."""
    def get_locale_string(string_dict):
        for code in ("pl", "polish", "en_us", "english"):
            if code in string_dict:
                return string_dict[code]
        return None
    applocales = types.SimpleNamespace(get_locale_string=get_locale_string)
    coreutils = types.SimpleNamespace(applocales=applocales)
    return {"pyrevit": types.SimpleNamespace(coreutils=coreutils),
            "pyrevit.coreutils": coreutils, "pyrevit.coreutils.applocales": applocales}


class InPolish(object):
    def __enter__(self):
        self.saved = {k: sys.modules.get(k) for k in polish()}
        sys.modules.update(polish())

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


class Config(object):
    """Stub for a pyRevit config section: a missing option raises AttributeError."""

    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


class Model(object):
    def __init__(self, path, enabled=True):
        self.path = path
        self.enabled = enabled


CAPS_2022 = rx_capabilities.for_revit(2022)
CAPS_2026 = rx_capabilities.for_revit(2026)


# ===== 1. Logic ================================================================================

class SettingsTests(unittest.TestCase):
    DOCS = os.path.join("C:\\", "Users", "x", "Documents")

    def test_missing_values_fall_back(self):
        got = logic.load_settings(Config(), self.DOCS)
        self.assertEqual(got, {"roots": [],
                               "output_parent": os.path.join(self.DOCS, "RevitExtractor"),
                               "max_parallel": 1, "shared_index_path": ""})

    def test_round_trip_through_stub_config(self):
        config = Config()
        values = logic.settings_to_save(["D:\\A", "D:\\B"], "D:\\Out", 1, "D:\\i.json")
        self.assertTrue(logic.save_settings(config, values))
        self.assertEqual(logic.load_settings(config, self.DOCS), values)
        self.assertFalse(logic.save_settings(config, values))   # nothing changed: no save needed

    def test_save_reports_a_single_changed_value(self):
        config = Config(roots=[], output_parent="D:\\Out", max_parallel=1, shared_index_path="")
        values = logic.settings_to_save([], "D:\\Out2", 1, "")
        self.assertTrue(logic.save_settings(config, values))
        self.assertEqual(config.output_parent, "D:\\Out2")

    def test_bad_values_fall_back(self):
        for roots in ("D:\\A", 5, {"a": 1}, None):
            self.assertEqual(logic.load_settings(Config(roots=roots), self.DOCS)["roots"], [], roots)
        for out in ("", "   ", None, 7, ["x"]):
            self.assertEqual(logic.load_settings(Config(output_parent=out), self.DOCS)
                             ["output_parent"], os.path.join(self.DOCS, "RevitExtractor"), out)
        for number in ("abc", "", "-2", "1.5", 0, -1, True, None, 2.5, []):
            self.assertEqual(logic.load_settings(Config(max_parallel=number), self.DOCS)
                             ["max_parallel"], 1, number)
        self.assertEqual(logic.load_settings(Config(max_parallel="3"), self.DOCS)["max_parallel"], 3)
        self.assertEqual(logic.load_settings(Config(max_parallel=2), self.DOCS)["max_parallel"], 2)
        self.assertEqual(logic.load_settings(Config(shared_index_path=5), self.DOCS)
                         ["shared_index_path"], "")

    def test_roots_go_through_normalize_roots(self):
        got = logic.load_settings(
            Config(roots=["  D:\\A  ", "d:\\a", "", None, 3, "D:\\A\\Sub", "D:\\B\\"]), self.DOCS)
        self.assertEqual(got["roots"], [os.path.normpath("D:\\A"), os.path.normpath("D:\\B")])
        saved = logic.settings_to_save(["D:\\A\\Sub", "D:\\A", "D:\\A"], " D:\\O ", "2", " p ")
        self.assertEqual(saved, {"roots": [os.path.normpath("D:\\A")], "output_parent": "D:\\O",
                                 "max_parallel": 2, "shared_index_path": "p"})

    def test_unknown_documents_folder_is_an_error_only_when_needed(self):
        logic.load_settings(Config(output_parent="D:\\Out"), "")      # not needed
        with self.assertRaises(Exception):
            logic.load_settings(Config(), "")

    def test_section_name(self):
        self.assertEqual(logic.CONFIG_SECTION, "RevitExtractorExport")


class TickHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "legacy_config_for_parity", LEGACY / "extractor_config.py")
        cls.legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.legacy)

    def test_tick_targets_equal_legacy(self):
        a, b, c = object(), object(), object()
        cases = [([], a), ([a], a), ([a], b), ([a, b], a), ([a, b], c), ([a, b, c], c),
                 ((a, b), b), ([a, a], a)]
        for selected, source in cases:
            self.assertEqual([id(x) for x in logic.tick_targets(selected, source)],
                             [id(x) for x in self.legacy.tick_targets(selected, source)])

    def test_tick_targets_behaviour(self):
        a, b, c = object(), object(), object()
        self.assertEqual(logic.tick_targets([a, b], a), [a, b])
        self.assertEqual(logic.tick_targets([a, b], c), [c])
        self.assertEqual(logic.tick_targets([a], a), [a])

    def test_toggled_state_equal_legacy(self):
        for states in ([], [True], [False], [True, True], [True, False], [False, False],
                       (True, True), iter([True, False])):
            copy_a = list(states) if not isinstance(states, list) else states
            copy_b = list(copy_a)
            self.assertEqual(logic.toggled_state(copy_a), self.legacy.toggled_state(copy_b))
        self.assertFalse(logic.toggled_state([True, True]))
        self.assertTrue(logic.toggled_state([True, False]))


def launcher_default_index():
    text = LAUNCHER.read_text(encoding="utf-8")
    match = re.search(r"\$defaultIndexJson = @'\r?\n(.*?)\r?\n'@", text, re.DOTALL)
    assert match, "default index here-string not found in Start-RevitExport.ps1"
    return json.loads(match.group(1))


class SharedIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rxexp-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, data, name="index.json"):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_accepts_the_launchers_default_index(self):
        default = launcher_default_index()
        path = self.write(json.dumps(default, indent=2).encode("utf-8"))
        self.assertEqual(logic.load_shared_index(path), default)

    def test_accepts_a_bom_and_non_ascii(self):
        data = {"metadata": {"parameters": {"derivative_type": {"x": "zażółć"}}}}
        raw = b"\xef\xbb\xbf" + json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.assertEqual(logic.load_shared_index(self.write(raw)), data)

    def test_accepts_index_builder_output(self):
        data = build_index(CAPS_2026)
        path = self.write(json.dumps(data).encode("utf-8"))
        self.assertEqual(logic.load_shared_index(path), data)

    def refused(self, raw):
        path = self.write(raw)
        with self.assertRaises(SetupError) as english:
            logic.load_shared_index(path)
        with InPolish():
            with self.assertRaises(SetupError) as pl:
                logic.load_shared_index(path)
        self.assertNotEqual(str(english.exception), str(pl.exception))
        return str(english.exception)

    def test_broken_json_and_bad_bytes(self):
        self.refused(b"{not json")
        self.refused(b"")
        self.refused(b"\xff\xfe\x00\x00bad")

    def test_wrong_shape(self):
        for raw in (b"[]", b"null", b'{"metadata": {}}',
                    b'{"metadata": {"parameters": {"derivative_type": []}}}',
                    b'{"metadata": {"parameters": {}}}'):
            self.refused(raw)

    def test_missing_file(self):
        with self.assertRaises(SetupError):
            logic.load_shared_index(os.path.join(self.tmp, "nope.json"))

    def test_messages_carry_no_path(self):
        text = self.refused(b"{broken")
        self.assertNotIn(self.tmp, text)


def with_views(key, branch="3dviewing", nested=True):
    view = {key: [1, 2]}
    derivative = {branch: view if nested else {"x": {"y": view}}}
    return {"metadata": {"parameters": {"derivative_type": derivative}}}


class PlanJobsTests(unittest.TestCase):
    MODELS = [Model("D:\\m\\a.rvt"), Model("D:\\m\\b.rvt"), Model("D:\\m\\c.rvt")]

    def test_default_scope_one_job_per_model_in_order(self):
        for caps in (CAPS_2022, CAPS_2026):
            jobs = logic.plan_jobs(self.MODELS, caps)
            self.assertEqual([j["model_path"] for j in jobs], [m.path for m in self.MODELS])
            for job in jobs:
                self.assertEqual(job["index"], build_index(caps))
                self.assertEqual(sorted(job), ["index", "model_path"])
        a, b = logic.plan_jobs(self.MODELS[:2], CAPS_2022)
        self.assertIsNot(a["index"], b["index"])

    def test_paths_are_accepted(self):
        jobs = logic.plan_jobs(["D:\\x.rvt"], CAPS_2022)
        self.assertEqual(jobs[0]["model_path"], "D:\\x.rvt")

    def test_models_may_be_any_iterable(self):
        self.assertEqual(len(logic.plan_jobs(iter(self.MODELS), CAPS_2022)), 3)

    def test_shared_index_used_as_given_and_not_aliased(self):
        shared = launcher_default_index()
        original = json.loads(json.dumps(shared))
        jobs = logic.plan_jobs(self.MODELS, CAPS_2022, shared)
        self.assertEqual(len(jobs), 3)
        for job in jobs:
            self.assertEqual(job["index"], original)
        jobs[0]["index"]["metadata"]["x"] = 1
        self.assertEqual(shared, original)
        self.assertNotIn("x", jobs[1]["index"]["metadata"])

    def test_no_model_raises(self):
        for models in ([], None, ()):
            with self.assertRaises(SetupError):
                logic.plan_jobs(models, CAPS_2022)
            with self.assertRaises(SetupError):
                logic.plan_jobs(models, CAPS_2022, launcher_default_index())

    def test_view_ids_with_two_models_refused_in_both_languages(self):
        for key in ("view_ids", "view_unique_ids"):
            for shape in (True, False):
                shared = with_views(key, "2dviewing", shape)
                with self.assertRaises(SetupError) as english:
                    logic.plan_jobs(self.MODELS[:2], CAPS_2022, shared)
                with InPolish():
                    with self.assertRaises(SetupError) as pl:
                        logic.plan_jobs(self.MODELS[:2], CAPS_2022, shared)
                self.assertNotEqual(str(english.exception), str(pl.exception))

    def test_view_ids_with_one_model_pass(self):
        for key in ("view_ids", "view_unique_ids"):
            shared = with_views(key)
            jobs = logic.plan_jobs(self.MODELS[:1], CAPS_2022, shared)
            self.assertEqual(jobs[0]["index"], shared)

    def test_default_scope_never_trips_the_view_id_rule(self):
        self.assertEqual(len(logic.plan_jobs(self.MODELS, CAPS_2022)), 3)

    def test_greyed_out_or_pathless_model_refused(self):
        with self.assertRaises(SetupError):
            logic.plan_jobs([Model("D:\\a.rvt"), Model("D:\\b.rvt", enabled=False)], CAPS_2022)
        for bad in (Model(""), Model(None), object()):
            with self.assertRaises(SetupError):
                logic.plan_jobs([bad], CAPS_2022)

    def test_index_has_view_ids(self):
        self.assertTrue(logic.index_has_view_ids(with_views("view_ids")))
        self.assertTrue(logic.index_has_view_ids([{"a": {"view_unique_ids": []}}]))
        self.assertFalse(logic.index_has_view_ids(launcher_default_index()))
        self.assertFalse(logic.index_has_view_ids(None))


# ===== 2. Static checks over the button's files (criterion 12 parts) ==========================

def py_files(folder):
    return sorted(p for p in folder.glob("*.py"))


def imported_roots(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    return roots


class LogicFileGuards(unittest.TestCase):
    PATH = BUTTON / "rx_export_logic.py"

    def test_imports_nothing_from_revit_or_dotnet(self):
        banned = {"pyrevit", "Autodesk", "System", "clr", "wpf"}
        self.assertFalse(imported_roots(self.PATH) & banned)

    def test_only_lib_and_stdlib_imports(self):
        allowed = {"__future__", "copy", "io", "json", "rx_catalog", "rx_i18n", "rx_index",
                   "rx_runner"}
        self.assertFalse(imported_roots(self.PATH) - allowed)

    def test_ironpython_syntax_rules(self):
        source = self.PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertTrue(source.startswith("# -*- coding: utf-8 -*-"))
        self.assertIn("from __future__ import unicode_literals", source)
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)])
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.assertIsNone(node.returns, node.name)
                every = node.args.args + node.args.kwonlyargs + node.args.posonlyargs
                self.assertFalse([a for a in every if a.annotation], node.name)
            self.assertNotIsInstance(node, (ast.AnnAssign, ast.Nonlocal, ast.Await,
                                            ast.AsyncFunctionDef, ast.NamedExpr))
        for banned in ("pathlib", "os.replace", "scandir", "nonlocal"):
            self.assertNotIn(banned, source)

    def test_every_user_message_goes_through_tr(self):
        tree = ast.parse(self.PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                if getattr(node.exc.func, "id", "") == "SetupError":
                    arg = node.exc.args[0]
                    self.assertIsInstance(arg, ast.Call)
                    self.assertEqual(arg.func.id, "tr")
                    self.assertEqual(len(arg.args), 2)


class ModuleNames(unittest.TestCase):
    def test_no_new_module_name_exists_in_an_old_bundle_or_the_shared_lib(self):
        old = set()
        for folder in (LEGACY, OLD2026):
            old.update(p.stem for p in folder.glob("*.py"))
        old.update(p.stem for p in LIB.glob("*.py")
                   if not p.name.startswith(("rx_export", "rx_status")))
        new = {p.stem for p in BUTTON.glob("*.py")}
        self.assertTrue(new, "no module in the Export.pushbutton folder")
        self.assertEqual(new & old, set())
        for name in new - {"script"}:
            self.assertTrue(name.startswith("rx_export_"), name)


if __name__ == "__main__":
    unittest.main()
