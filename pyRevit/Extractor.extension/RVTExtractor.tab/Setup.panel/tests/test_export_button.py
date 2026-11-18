# -*- coding: utf-8 -*-
"""Tests for the Export button (specs/SPEC-export-button.md).

Structure (one class group per layer, so later layers can be added without touching these):
  1. Logic: rx_export_logic.py (pure; criteria 3, 4, 5, 10)
  2. Static checks over the button's files (criteria 1, 11, 12, 15 parts)
  3. Text table of both windows (criterion 11)
  4. Model window, WPF and pyRevit stubbed (criteria 6, 7)
  5. View window: the slice 1 cases as a mixin, plus ids, formats and Export (criterion 8)
  6. script.py: guards, wiring and the hand-over to the session (criteria 2, 9)

CPython 3 with stubs: passing here does not prove IronPython, pyRevit or Revit behaviour.
"""
import ast
import copy
import datetime
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
                               "max_parallel": 1, "shared_index_path": "",
                               "subfolders": True})

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
        # A root inside another stays: it matters when subfolders are not searched.
        self.assertEqual(got["roots"], [os.path.normpath("D:\\A"), os.path.normpath("D:\\A\\Sub"),
                                        os.path.normpath("D:\\B")])
        self.assertTrue(logic.has_nested_roots(got["roots"]))
        self.assertFalse(logic.has_nested_roots(["D:\\A", "D:\\B"]))
        saved = logic.settings_to_save(["D:\\A", "D:\\A"], " D:\\O ", "2", " p ")
        self.assertEqual(saved, {"roots": [os.path.normpath("D:\\A")], "output_parent": "D:\\O",
                                 "max_parallel": 2, "shared_index_path": "p",
                                 "subfolders": True})

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


class OneDriveCheck(unittest.TestCase):
    ENV = {"OneDrive": r"C:\Users\x\OneDrive", "OneDriveCommercial": r"C:\Users\x\OneDrive - Acme"}

    def test_inside_the_environment_roots_or_a_onedrive_named_folder(self):
        check = lambda path: logic.inside_onedrive(path, self.ENV)
        self.assertTrue(check(r"C:\Users\x\OneDrive\Documents\RevitExtractor"))
        self.assertTrue(check(r"c:\users\x\onedrive - acme\Exports"))
        self.assertTrue(check(r"D:\Work\OneDrive - Other\Exports"), "named, not in the variables")
        self.assertFalse(check(r"C:\Users\x\RevitExtractor"))
        self.assertFalse(check(r"C:\Users\x\Projects\Exports"))
        self.assertFalse(check(""))
        self.assertFalse(check(None))

    def test_a_root_that_only_shares_a_prefix_is_not_inside(self):
        self.assertFalse(logic.inside_onedrive(r"C:\Users\x\Docs\a", {"OneDrive": r"C:\Users\x\Doc"}))

    def test_the_default_output_is_not_made_in_documents(self):
        source = (BUTTON / "script.py").read_text(encoding="utf-8")
        self.assertIn("SpecialFolder.UserProfile", source)
        self.assertNotIn("SpecialFolder.MyDocuments", source)



class LogicFileGuards(unittest.TestCase):
    PATH = BUTTON / "rx_export_logic.py"

    def test_imports_nothing_from_revit_or_dotnet(self):
        banned = {"pyrevit", "Autodesk", "System", "clr", "wpf"}
        self.assertFalse(imported_roots(self.PATH) & banned)

    def test_only_lib_and_stdlib_imports(self):
        allowed = {"__future__", "copy", "io", "json", "os", "rx_catalog", "rx_cloud", "rx_i18n",
                   "rx_index", "rx_runner"}
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
        # script.py is every bundle's entry point; pyRevit runs it as __main__, never imports it.
        new = {p.stem for p in BUTTON.glob("*.py")} - {"script"}
        self.assertTrue(new, "no module in the Export.pushbutton folder")
        self.assertEqual(new & old, set())
        for name in new:
            self.assertTrue(name.startswith("rx_export_"), name)
        self.assertTrue((BUTTON / "script.py").is_file())


# --- IronPython 2.7: the shared guard of test_status.py plus stricter checks for this bundle ----

PY3_ONLY_NAMES = {
    "FileNotFoundError", "FileExistsError", "PermissionError", "TimeoutError",
    "ModuleNotFoundError", "RecursionError", "ConnectionError", "BrokenPipeError",
    "IsADirectoryError", "NotADirectoryError", "ProcessLookupError", "ChildProcessError",
    "InterruptedError", "BlockingIOError", "ascii", "breakpoint",
}
PY3_ONLY_MODULES = {"pathlib", "typing", "dataclasses", "enum", "asyncio", "concurrent",
                    "configparser", "queue", "builtins", "secrets", "statistics", "zoneinfo",
                    "html", "http", "urllib.request", "urllib.parse", "importlib.util",
                    "contextvars", "graphlib", "tomllib", "selectors", "ipaddress"}
PY3_ONLY_TEXT = (".isascii(", ".casefold(", "str.maketrans", "math.inf", "os.scandir",
                 "shutil.which", "json.JSONDecodeError", ".to_bytes(", ".from_bytes(")


def extra_ironpython_problems(source):
    """Python-3-only constructs the shared guard does not look for."""
    tree = ast.parse(source)
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.cause is not None:
            problems.append("raise ... from")
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None)
            if name == "super" and not node.args:
                problems.append("super() without arguments")
            if name == "open" and any(k.arg in ("encoding", "newline", "errors")
                                      for k in node.keywords):
                problems.append("open() with encoding/newline/errors (use io.open)")
            if sum(isinstance(a, ast.Starred) for a in node.args) > 1:
                problems.append("several *args in one call")
            if sum(1 for k in node.keywords if k.arg is None) > 1:
                problems.append("several **kwargs in one call")
        if isinstance(node, ast.Dict) and any(k is None for k in node.keys):
            problems.append("{**dict} unpacking")
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)) and \
                any(isinstance(e, ast.Starred) for e in node.elts):
            problems.append("starred element in a literal")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.MatMult):
            problems.append("@ operator")
        if isinstance(node, (ast.FunctionDef, ast.Lambda)) and node.args.posonlyargs:
            problems.append("positional-only parameters")
        if isinstance(node, ast.Name) and node.id in PY3_ONLY_NAMES:
            problems.append("Python 3 name: " + node.id)
        if type(node).__name__ in ("Match", "TryStar"):
            problems.append(type(node).__name__)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) \
                else [node.module or ""]
            for full in names:
                if full in PY3_ONLY_MODULES or full.split(".")[0] in PY3_ONLY_MODULES:
                    problems.append("Python 3 module: " + full)
    for snippet in PY3_ONLY_TEXT:
        if snippet in source:
            problems.append("text: " + snippet)
    return problems


class IronPythonGuards(unittest.TestCase):
    def test_every_python_file_of_the_bundle_passes_both_guards(self):
        import test_status
        files = py_files(BUTTON)
        self.assertEqual({p.name for p in files},
                         {"rx_export_logic.py", "rx_export_naming_ui.py", "rx_export_text.py",
                          "rx_export_ui.py", "script.py"})
        for path in files:
            source = path.read_text(encoding="utf-8")
            self.assertEqual(test_status.ironpython_problems(source), [], path.name)
            self.assertEqual(extra_ironpython_problems(source), [], path.name)
            self.assertNotIn("\t", source, path.name)
            self.assertTrue(source.startswith("# -*- coding: utf-8 -*-\n") or
                            source.startswith("# -*- coding: utf-8 -*-\r\n"), path.name)

    def test_the_extra_guard_catches_what_it_claims(self):
        bad = ("raise A from b\nsuper().x()\nopen(p, encoding='u')\nf(*a, *b)\n{**d}\n[*a]\n"
               "a @ b\ndef g(a, /): pass\ntry:\n    pass\nexcept FileNotFoundError:\n    pass\n"
               "import pathlib\nimport urllib.request\nx.isascii()\n")
        problems = extra_ironpython_problems(bad)
        for expected in ("raise ... from", "super() without arguments", "open() with encoding",
                         "several *args", "{**dict}", "starred element", "@ operator",
                         "positional-only", "FileNotFoundError", "pathlib", "urllib.request",
                         ".isascii("):
            self.assertTrue([p for p in problems if expected in p], expected)


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


class BoundaryGuards(unittest.TestCase):
    def test_text_module_is_pure(self):
        self.assertEqual(set(imported_modules(BUTTON / "rx_export_text.py")),
                         {"__future__", "rx_i18n"})

    def test_ui_imports_no_revit_reader_catalog_or_script(self):
        names = imported_modules(BUTTON / "rx_export_ui.py")
        roots = {name.split(".")[0] for name in names}
        self.assertFalse(roots & {"Autodesk", "RevitServices", "rx_reader", "rx_catalog",
                                  "rx_status_ui", "clr"}, roots)
        self.assertNotIn("pyrevit.script", names)
        tree = ast.parse((BUTTON / "rx_export_ui.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "pyrevit":
                self.assertEqual([a.name for a in node.names], ["forms"])

    def test_no_row_subscription_and_no_thread(self):
        for name in ("rx_export_ui.py", "script.py"):
            source = (BUTTON / name).read_text(encoding="utf-8")
            self.assertNotIn("PropertyChanged +=", source, name)
            self.assertNotIn("PropertyChanged+=", source, name)
            self.assertNotIn("dispatch(", source, name)      # forms.WPFWindow.dispatch = thread
            # A Python or .NET thread; System.Windows.Threading (DispatcherTimer) is allowed.
            self.assertNotRegex(source, r"\bThread\b|\bthreading\b|ThreadPool|BackgroundWorker",
                                name)

    def test_read_model_only_in_script(self):
        for path in py_files(BUTTON):
            source = path.read_text(encoding="utf-8")
            if path.name == "script.py":
                self.assertEqual(source.count("read_model("), 1)
            else:
                self.assertNotIn("read_model", source, path.name)

    def test_script_hands_only_json_text_to_the_session(self):
        source = (BUTTON / "script.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertIn("json.dumps", source)
        # No module-level window, function or Revit object is published anywhere.
        self.assertNotIn("SetData", source)
        self.assertNotIn("publish_session", source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                self.fail("global statement in script.py")


# --- criterion 11: runtime strings go through tr ------------------------------------------------

TEXT_ATTRIBUTES = {"Text", "ToolTip", "Content", "Title"}


def literal_text(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and \
        bool(node.value.strip()) and any(ch.isalpha() for ch in node.value)


class RuntimeTextGuards(unittest.TestCase):
    def check(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr in TEXT_ATTRIBUTES:
                        self.assertFalse(literal_text(node.value),
                                         "%s:%d literal UI text" % (path.name, node.lineno))
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name in ("alert", "SetupError", "_show_error", "_set_status") and node.args:
                    self.assertFalse(literal_text(node.args[0]),
                                     "%s:%d literal message" % (path.name, node.lineno))
                if name == "tr":
                    self.assertEqual(len(node.args), 2, "%s:%d" % (path.name, node.lineno))
                for keyword in node.keywords:
                    if keyword.arg in ("title", "tooltip", "files_filter"):
                        self.assertFalse(literal_text(keyword.value),
                                         "%s:%d literal %s" % (path.name, node.lineno,
                                                               keyword.arg))

    def test_ui_and_script(self):
        self.check(BUTTON / "rx_export_ui.py")
        self.check(BUTTON / "script.py")


# --- criterion 1: bundle.yaml, names -----------------------------------------------------------

class BundleTests(unittest.TestCase):
    TEXT = (BUTTON / "bundle.yaml").read_text(encoding="utf-8") if (BUTTON / "bundle.yaml").is_file() \
        else ""

    def section(self, name):
        match = re.search(r"^%s:\n((?:[ ]+.*\n)+)" % name, self.TEXT, re.MULTILINE)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def test_titles_and_tooltips_in_both_languages(self):
        for name in ("title", "tooltip"):
            body = self.section(name)
            self.assertRegex(body, r"^  en_us: ", name)
            self.assertRegex(body, r"(?m)^  pl: ", name)
        self.assertNotRegex(self.section("title"), r"20\d\d")

    def test_versions_context_and_engine(self):
        self.assertRegex(self.TEXT, r"(?m)^min_revit_version: 2022$")
        self.assertNotIn("max_revit_version", self.TEXT)
        self.assertIn('context:\n  rule: "(zero-doc)&!(doc-project|doc-family)"\n', self.TEXT)
        self.assertIn("engine:\n  persistent: true\n", self.TEXT)
        self.assertNotIn("clean", self.TEXT)

    def test_no_revit_version_in_any_name(self):
        for path in BUTTON.iterdir():
            self.assertNotRegex(path.name, r"20\d\d", path.name)
        self.assertNotRegex(BUTTON.name, r"\d{4}")
        for path in py_files(BUTTON):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    self.assertNotRegex(node.name, r"20\d\d", node.name)


# ===== 3. Text table of both windows (criterion 11) ===========================================

import xml.etree.ElementTree as ET  # noqa: E402
from unittest.mock import Mock, patch  # noqa: E402

import rx_catalog  # noqa: E402
import rx_reader  # noqa: E402
import test_window_legacy as legacy  # noqa: E402
from wpf_fakes import Args, Collection, Control, Event, SharedEventReactive, reactive  # noqa: E402
from wpf_fakes import FakeView, polish as polish_modules, stub_module  # noqa: E402

XNAME = legacy.XNAME
MODELS_XAML = BUTTON / "rx_export_models.xaml"
VIEWS_XAML = BUTTON / "rx_export_views.xaml"
NAMING_XAML = BUTTON / "rx_export_naming.xaml"
LANGUAGE_NEUTRAL = {"✓", "ElementId"}


def xaml_text(path):
    return path.read_text(encoding="utf-8")


def xaml_names(path):
    return dict((element.get(XNAME), element.get("Tag"))
                for element in ET.parse(str(path)).getroot().iter() if element.get(XNAME))


def load_text_module():
    return legacy.load("rx_export_text_under_test", "rx_export_text.py", folder=BUTTON)


class TextTableTests(unittest.TestCase):
    def setUp(self):
        self.text = load_text_module()

    def test_keys_of_both_xaml_files_and_the_table_match_both_ways(self):
        used = set()
        for path in (MODELS_XAML, VIEWS_XAML, NAMING_XAML):
            keys = set(key for key in re.findall(r"\{DynamicResource (\w+)\}", xaml_text(path))
                       if not key.startswith("Rx"))
            self.assertTrue(keys, path.name)
            used |= keys
        self.assertEqual(used, set(self.text.UI_TEXT))
        self.assertFalse([key for key in self.text.UI_TEXT if key.startswith("Rx")])

    def test_no_hard_coded_label_left_in_either_xaml(self):
        for path in (MODELS_XAML, VIEWS_XAML):
            xaml = xaml_text(path)
            attributes = re.findall(r'\b(Title|Text|Content|Header|ToolTip)="([^"]*)"', xaml)
            literals = {value for name, value in attributes if value and not value.startswith("{")}
            self.assertEqual(literals - LANGUAGE_NEUTRAL, set(), path.name)
            for element in ET.fromstring(xaml).iter():
                if element.text and element.text.strip():
                    self.fail("%s: literal element text %r" % (path.name, element.text.strip()))
            self.assertNotIn("{DynamicResource", "".join(re.findall(r"<!--.*?-->", xaml, re.S)),
                             "a comment must not look like a key")

    def test_every_entry_has_english_and_polish(self):
        for key, (english, polish_text) in self.text.UI_TEXT.items():
            with self.subTest(key=key):
                self.assertTrue(english.strip() and polish_text.strip())
                self.assertNotEqual(english, polish_text)

    def test_resources_follow_language(self):
        self.assertEqual(self.text.resources()["close"], "Close")
        self.assertEqual(self.text.resources()["models_export"], "Export")
        with patch.dict(sys.modules, polish_modules()):
            self.assertEqual(self.text.resources()["close"], "Zamknij")
            self.assertEqual(self.text.resources()["models_export"], "Eksportuj")

    def test_no_revit_version_in_window_titles(self):
        for key in ("models_title", "window_title", "models_header", "header"):
            for value in self.text.UI_TEXT[key]:
                self.assertNotRegex(value, r"20\d\d", key)

    def test_every_theme_key_used_exists_in_the_lib_theme(self):
        theme = ET.parse(str(LIB / "rx_theme.xaml")).getroot()
        keys = {element.get("{http://schemas.microsoft.com/winfx/2006/xaml}Key")
                for element in theme.iter()}
        used = set()
        for path in (MODELS_XAML, VIEWS_XAML):
            used |= set(re.findall(r"\{DynamicResource (Rx\w+)\}", xaml_text(path)))
            self.assertNotIn("StaticResource Rx", xaml_text(path), "theme keys merge after load")
        used |= set(re.findall(r'"(Rx[A-Z]\w+)"', xaml_text(BUTTON / "rx_export_ui.py")))
        self.assertTrue(used)
        self.assertEqual(used - keys, set())


class XamlShapeTests(unittest.TestCase):
    def test_model_window_footer_and_rows(self):
        xaml = xaml_text(MODELS_XAML)
        self.assertRegex(xaml, r'<Button x:Name="close_btn"[^>]*IsCancel="True"')
        self.assertRegex(xaml, r'<Button x:Name="export_btn"[^>]*IsDefault="True"')
        self.assertRegex(xaml, r'<Button x:Name="export_btn"[^>]*RxPrimaryButton')
        self.assertRegex(xaml, r'<ContentControl x:Name="search_host"')
        self.assertRegex(xaml, r'<ListView[^>]*x:Name="models_lv"[^>]*SelectionMode="Extended"')
        # Greyed rows: the item is disabled, its tooltip still shows.
        self.assertRegex(xaml, r'<Setter Property="IsEnabled" Value="\{Binding Enabled\}"/>')
        self.assertRegex(xaml, r'<Setter Property="ToolTipService.ShowOnDisabled" Value="True"/>')
        self.assertRegex(xaml, r'<Setter Property="ToolTip" Value="\{Binding Tip\}"/>')
        for name in ("views_btn", "rescan_btn", "add_root_btn", "remove_root_btn", "output_btn",
                     "default_scope_rb", "shared_scope_rb", "shared_choose_btn", "all_btn",
                     "none_btn", "roots_lb", "count_text", "error_text", "summary_text",
                     "status_text", "caps_text", "output_text", "shared_path_text", "source_bar",
                     "source_local_rb", "source_cloud_rb", "cloud_panel", "cloud_lv",
                     "cloud_projects_lb", "cloud_message_text", "subfolders_cb",
                     "search_folder_cb"):
            self.assertIn(name, xaml_names(MODELS_XAML), name)

    def test_view_window_footer(self):
        xaml = xaml_text(VIEWS_XAML)
        self.assertRegex(xaml, r'<Button x:Name="back_btn"[^>]*IsCancel="True"')
        self.assertRegex(xaml, r'<Button x:Name="export_btn"[^>]*IsDefault="True"')
        self.assertNotRegex(xaml, r'<Button x:Name="save_btn"[^>]*IsDefault')
        self.assertNotIn("close_btn", xaml_names(VIEWS_XAML))
        self.assertNotIn("kind2d_cb", xaml_names(VIEWS_XAML))
        # Every name the slice 1 window had, except its Close button, is still there.
        legacy_names = set(legacy.XAML_NAMES) - {"close_btn"}
        self.assertEqual(legacy_names - set(xaml_names(VIEWS_XAML)), set())


# ===== 4. Model window (criteria 6, 7) =========================================================

class WinControl(Control):
    def __init__(self, name, tag=None):
        Control.__init__(self, name, tag)
        self.Visibility = "Visible"
        self.SelectedItem = None
        self.Content = None
        self.focused = False
        self.View = types.SimpleNamespace(Columns=[types.SimpleNamespace(Header=None)
                                                   for unused in range(6)])

    def Focus(self):
        self.focused = True
        return True


class FakeDispatcher(object):
    def __init__(self):
        self.invoked = []

    def Invoke(self, priority, callback):
        self.invoked.append(priority)
        callback()


class FakeButtonWindow(object):
    """forms.WPFWindow for the button's XAML files: one control per x:Name of the given file."""

    def __init__(self, xaml_path, literal_string=False, handle_esc=True, set_owner=True):
        self.xaml_path = xaml_path
        self.handle_esc = handle_esc
        self.Resources = {}
        self.merged = []
        self.closed = False
        self.closes = 0
        self.dialogs = 0
        self.IsEnabled = True
        self.Loaded = Event()
        self.Closed = Event()
        self.Dispatcher = FakeDispatcher()
        for name, tag in xaml_names(Path(xaml_path)).items():
            setattr(self, name, WinControl(name, tag))

    def merge_resource_dict(self, path):
        self.merged.append(path)

    def FindResource(self, key):
        raise KeyError(key)

    def show_dialog(self):
        self.dialogs += 1
        self.Loaded.fire(self, None)

    def Close(self):
        self.closes += 1
        if not self.closed:
            self.closed = True
            self.Closed.fire(self, None)


class Coll(Collection):
    def Clear(self):
        del self[:]

    def Remove(self, item):
        if item in self:
            self.remove(item)
            return True
        return False


class FakeComboItem(object):
    def __init__(self):
        self.Content = None
        self.Tag = None
        self.IsEnabled = True
        self.ToolTip = None


class FakeTimer(object):
    def __init__(self):
        self.Tick = Event()
        self.Interval = None
        self.IsEnabled = False
        self.starts = 0
        self.stops = 0

    def Start(self):
        self.IsEnabled = True
        self.starts += 1

    def Stop(self):
        self.IsEnabled = False
        self.stops += 1


TIMERS = []
MOUSE = types.SimpleNamespace(OverrideCursor=None)
FORMS = types.SimpleNamespace(WPFWindow=FakeButtonWindow, Reactive=SharedEventReactive,
                              reactive=reactive, save_file=Mock(return_value=None),
                              pick_folder=Mock(return_value=None),
                              pick_file=Mock(return_value=None), alert=Mock())


def new_timer():
    timer = FakeTimer()
    TIMERS.append(timer)
    return timer


def export_ui_stubs():
    return {
        "System": stub_module("System", Action=lambda fn: fn, Environment=Mock(),
                              Predicate={object: lambda fn: fn},
                              TimeSpan=types.SimpleNamespace(FromMilliseconds=lambda ms: ("ms", ms))),
        "System.Collections": stub_module("System.Collections"),
        "System.Collections.ObjectModel": stub_module("System.Collections.ObjectModel",
                                                      ObservableCollection={object: Coll}),
        "System.IO": stub_module("System.IO", File=Mock()),
        "System.Text": stub_module("System.Text", UTF8Encoding=Mock()),
        "System.Windows": stub_module("System.Windows", RoutedEventHandler=lambda fn: fn,
                                      Visibility=types.SimpleNamespace(Visible="Visible",
                                                                       Collapsed="Collapsed")),
        "System.Windows.Controls": stub_module("System.Windows.Controls",
                                               ComboBoxItem=FakeComboItem),
        "System.Windows.Controls.Primitives": stub_module(
            "System.Windows.Controls.Primitives",
            ButtonBase=types.SimpleNamespace(ClickEvent="ButtonBase.Click")),
        "System.Windows.Data": stub_module(
            "System.Windows.Data", CollectionViewSource=types.SimpleNamespace(GetDefaultView=FakeView)),
        "System.Windows.Input": stub_module(
            "System.Windows.Input", Key=types.SimpleNamespace(Space="Space", A="A"),
            Cursors=types.SimpleNamespace(Wait="Wait"), Mouse=MOUSE),
        "System.Windows.Threading": stub_module(
            "System.Windows.Threading", DispatcherTimer=new_timer,
            DispatcherPriority=types.SimpleNamespace(Background="Background")),
        "pyrevit": types.SimpleNamespace(forms=FORMS),
        "rx_search_bar": stub_module("rx_search_bar", SearchBar=legacy.FakeSearchBar),
        "rx_column_filter_ui": stub_module("rx_column_filter_ui",
                                           ColumnFilterController=legacy.FakeFilters),
    }


def load_export_ui():
    if not (BUTTON / "rx_export_ui.py").is_file():
        return None
    return legacy.load("rx_export_ui_under_test", "rx_export_ui.py", export_ui_stubs(), BUTTON)


EXPORT_UI = load_export_ui()


def reset_fakes():
    SharedEventReactive.PropertyChanged = Event()
    SharedEventReactive.raised = []
    legacy.FakeSearchBar.instances = []
    del TIMERS[:]
    MOUSE.OverrideCursor = None
    for name in ("save_file", "pick_folder", "pick_file", "alert"):
        getattr(FORMS, name).reset_mock(return_value=True, side_effect=True)
        getattr(FORMS, name).return_value = None


ROOT_M = os.path.join("D:\\", "m")
ROOT_N = os.path.join("D:\\", "n")


def catalog_row(name, state, version="2022", folder=ROOT_M, workshared=False, note=""):
    path = os.path.join(folder, name)
    return rx_catalog.Row(path=path, folder=folder, name=name, version=version, state=state,
                          enabled=state in ("ok", "older"), note=note, workshared=workshared)


def sample_rows():
    return [
        catalog_row("a.rvt", "ok"),
        catalog_row("b.rvt", "older", "2021", workshared=True,
                    note="Saved in Revit 2021. The export upgrades a temporary copy; "
                         "the file is not changed."),
        catalog_row("c.rvt", "newer", "2024", workshared=None,
                    note="Saved in Revit 2024, newer than this Revit (2022)."),
        catalog_row("d.rvt", "unknown", "", workshared=None,
                    note="The Revit version could not be read."),
        catalog_row("a-local.rvt", "local_copy", workshared=True),
        catalog_row("e.rvt", "ok", folder=ROOT_N, workshared=None),
    ]


class FakeScan(object):
    """rx_catalog.scan stand-in: a real generator that records pulls, ends and early closes."""

    def __init__(self, rows, errors=()):
        self.rows = rows
        self.errors = list(errors)
        self.calls = []
        self.subfolders = []
        self.pulled = 0
        self.finished = 0
        self.closed_early = 0

    def __call__(self, roots, running_year, read_info, cache, errors=None, subfolders=True):
        self.calls.append((list(roots), running_year, read_info, cache))
        self.subfolders.append(subfolders)

        def generate():
            try:
                for row in self.rows:
                    self.pulled += 1
                    yield row
                if errors is not None:
                    errors.extend(self.errors)
                self.finished += 1
            except GeneratorExit:
                self.closed_early += 1
                raise
        return generate()


class StepClock(object):
    def __init__(self, step=0.0):
        self.now = 100.0
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


def forms_alerts():
    return FORMS.alert.call_count


class ModelWindowHarness(object):
    """Set-up and helpers of the model window tests; the cloud tests reuse them."""

    def setUp(self):
        reset_fakes()
        self.tmp = tempfile.mkdtemp(prefix="rxexp-ui-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = patch.dict(os.environ, {"APPDATA": self.tmp})   # the window writes its preferences here
        env.start()
        self.addCleanup(env.stop)
        # Most tests are about other things: file naming is off for them (Default is on in a
        # fresh install; the file-names tests delete this file first).
        os.makedirs(os.path.join(self.tmp, "RevitExtractor"))
        io.open(os.path.join(self.tmp, "RevitExtractor", "preferences.json"), "w",
                encoding="utf-8").write('{"naming": {"selected": "none"}}')
        self.reads = []
        self.read_links = []
        self.read_answer = None
        self.read_error = None
        self.cloud_opens = []
        self.cloud_answer = None
        self.cloud_error = None
        self.saved = []
        self.cache = object()
        self.read_info = Mock(name="read_info")
        self.submitted = []
        self.submit_result = None
        self.submit_error = None
        self.submit_hook = None

    def read(self, path, workshared, links=False):
        self.reads.append((path, workshared, TIMERS[-1].IsEnabled, MOUSE.OverrideCursor,
                           self.window.IsEnabled))
        self.read_links.append(links)
        if self.read_error is not None:
            raise self.read_error
        return self.read_answer

    def read_cloud(self, region, project_guid, model_guid, all_worksets=True, values=True):
        self.cloud_opens.append({"args": (region, project_guid, model_guid),
                                 "all_worksets": all_worksets, "values": values,
                                 "status": self.window.status_text.Text,
                                 "timer_on": TIMERS[-1].IsEnabled, "cursor": MOUSE.OverrideCursor,
                                 "enabled": self.window.IsEnabled})
        if self.cloud_error is not None:
            raise self.cloud_error
        if self.cloud_answer is not None:
            return copy.deepcopy(self.cloud_answer)
        return {"title": "", "path": "", "views_2d": [], "views_3d": [], "ifc_setups": [],
                "ifc_error": "", "links": []}

    def submit(self, jobs, output_parent):
        self.submitted.append({"jobs": jobs, "output_parent": output_parent,
                               "ticked": self.ticked(), "closed": self.window.closed,
                               "export_enabled": self.window.export_btn.IsEnabled})
        if self.submit_hook is not None:
            self.submit_hook()
        if self.submit_error is not None:
            raise self.submit_error
        if self.submit_result is not None:
            return self.submit_result
        return {"queued": len(jobs), "failed": [], "warning": ""}

    def open(self, rows=None, roots=(ROOT_M, ROOT_N), step=0.0, shared="", build="2025.3.0.12",
             caps=CAPS_2022, show=True, cloud=None):
        self.scan = FakeScan(sample_rows() if rows is None else rows)
        settings = {"roots": list(roots), "output_parent": os.path.join("D:\\", "Out"),
                    "max_parallel": 1, "shared_index_path": shared}
        self.window = EXPORT_UI.ModelWindow(caps, settings, self.read_info, self.cache, self.read,
                                            self.saved.append, extractor_build=build,
                                            scan=self.scan, clock=StepClock(step),
                                            submit=self.submit, cloud=cloud,
                                            read_cloud=self.read_cloud)
        if show:
            self.window.show_dialog()
        return self.window

    # -- file names (named copies): the profile dropdown

    def names_window(self):
        os.remove(os.path.join(self.tmp, "RevitExtractor", "preferences.json"))   # a fresh install
        with patch.object(logic, "NAMED_COPIES_READY", True):
            return self.open()

    def pick(self, combo, item):
        combo.SelectedItem = item
        combo.SelectionChanged.fire(combo, None)

    def entry(self, window, tag):
        return [i for i in window.name_profile_cb.Items.items if i.Tag == tag][-1]

    def ready_job(self, window):
        self.tick()
        row = [r for r in self.rows() if r.Enabled][0]
        row.set_quietly(True)
        window._refresh_state()
        with patch.object(logic, "NAMED_COPIES_READY", True):
            self.fire("export_btn")
        return self.submitted[-1]["jobs"][0]

    def test_the_file_names_row_follows_the_readiness_switch(self):
        self.assertEqual(self.open().naming_panel.Visibility, "Visible")
        with patch.object(logic, "NAMED_COPIES_READY", False):
            self.assertEqual(self.open().naming_panel.Visibility, "Collapsed")

    def test_the_dropdown_lists_none_default_and_load_and_starts_on_default(self):
        window = self.names_window()
        tags = [i.Tag for i in window.name_profile_cb.Items.items]
        self.assertEqual(tags, ["none", "default", "load"])
        self.assertEqual(window.name_profile_cb.SelectedItem.Tag, "default")
        self.assertTrue(window.name_edit_btn.IsEnabled)

    def test_the_default_profile_goes_with_the_jobs_as_view_and_sheet_templates(self):
        sent = self.ready_job(self.names_window())
        self.assertEqual(sent["naming"], {
            "templates": {"view": "{ViewFamily} - {ViewName}", "sheet": "{SheetNumber} - {SheetName}"},
            "split": False})

    def test_none_sends_a_plain_job_disables_edit_and_is_remembered(self):
        window = self.names_window()
        self.pick(window.name_profile_cb, self.entry(window, "none"))
        self.assertFalse(window.name_edit_btn.IsEnabled)
        self.assertNotIn("naming", self.ready_job(window))
        import rx_status
        self.assertEqual(rx_status.read_preferences(window._prefs_path)["naming"]["selected"], "none")
        self.pick(window.name_profile_cb, self.entry(window, "default"))
        self.assertEqual(window.name_profile_cb.SelectedItem.Tag, "default")

    def test_a_missing_remembered_file_falls_back_to_default_with_a_note(self):
        import rx_status
        prefs = rx_status.preferences_path(self.tmp)
        gone = os.path.join(self.tmp, "gone.rx-naming.json")
        io.open(prefs, "w", encoding="utf-8").write(json.dumps(
            {"naming": {"selected": gone, "profiles": [{"name": "Office", "path": gone}]}}))
        with patch.object(logic, "NAMED_COPIES_READY", True):
            window = self.open()
        self.assertEqual(window.name_profile_cb.SelectedItem.Tag, "default")
        self.assertEqual(window.name_note_text.Visibility, "Visible")
        self.assertIn("Office", window.name_note_text.Text)

    def test_the_example_text_uses_the_normal_text_brush_not_a_code_set_one(self):
        xaml = xaml_text(NAMING_XAML)
        self.assertIn('x:Name="preview_text" Foreground="{DynamicResource RxText}"', xaml)

    def test_nothing_is_attached_while_the_feature_is_off(self):
        window = self.names_window()
        with patch.object(logic, "NAMED_COPIES_READY", False):
            self.assertEqual(window._with_naming([{"model_path": "x"}]), [{"model_path": "x"}])

    def test_onedrive_output_folder_shows_a_warning(self):
        window = self.open()
        self.assertEqual(window.output_warn_text.Visibility, "Collapsed")
        window.output_parent = os.path.join("C:\\", "Users", "x", "OneDrive - Acme", "Exports")
        window._show_output()
        self.assertEqual(window.output_warn_text.Visibility, "Visible")
        window.output_parent = os.path.join("C:\\", "Users", "x", "RevitExtractor")
        window._show_output()
        self.assertEqual(window.output_warn_text.Visibility, "Collapsed")

    def test_folders_section_is_open_only_while_no_folder_is_set(self):
        self.assertFalse(self.open().folders_exp.IsExpanded)
        self.assertIn(ROOT_M, self.window.folders_summary_text.Text)
        empty = self.open(roots=())
        self.assertTrue(empty.folders_exp.IsExpanded)
        self.assertIn("none yet", empty.folders_summary_text.Text)

    def test_the_front_is_taken_back_only_from_revit(self):
        reclaim = EXPORT_UI.reclaim_front
        window = types.SimpleNamespace(IsActive=False, activated=0)
        window.Activate = lambda: setattr(window, "activated", window.activated + 1)
        self.assertTrue(reclaim(window, 111, foreground=lambda: 111))
        self.assertEqual(window.activated, 1)
        self.assertFalse(reclaim(window, 111, foreground=lambda: 222), "another program: left alone")
        self.assertFalse(reclaim(window, 111, foreground=lambda: None), "unknown: left alone")
        self.assertFalse(reclaim(window, 0, foreground=lambda: 0), "no Revit handle: nothing to do")
        window.IsActive = True
        self.assertFalse(reclaim(window, 111, foreground=lambda: 111), "already in front")
        self.assertEqual(window.activated, 1)
        broken = types.SimpleNamespace(IsActive=False)
        self.assertFalse(reclaim(broken, 111, foreground=lambda: 111), "never raises")

    def test_handles_compare_the_same_signed_or_not(self):
        self.assertEqual(EXPORT_UI._masked(-2147418111), 0x80010001)
        self.assertEqual(EXPORT_UI._masked(0x80010001), 0x80010001)
        self.assertIsNone(EXPORT_UI._masked(None))
        self.assertIsNone(EXPORT_UI._masked("x"))
        window = types.SimpleNamespace(IsActive=False, activated=0)
        window.Activate = lambda: setattr(window, "activated", 1)
        self.assertTrue(EXPORT_UI.reclaim_front(window, 0x80010001, foreground=lambda: -2147418111))
        self.assertEqual(window.activated, 1)

    def test_keep_in_front_listens_for_deactivation(self):
        class Pointer(object):
            def __init__(self, value):
                self.value = value
            def ToInt64(self):
                return self.value
        window = types.SimpleNamespace()
        window.Deactivated = Event()
        self.assertTrue(EXPORT_UI.keep_in_front(window, Pointer(77)))
        self.assertEqual(len(window.Deactivated.handlers), 1)
        self.assertFalse(EXPORT_UI.keep_in_front(types.SimpleNamespace(), Pointer(77)),
                         "a window without the event is left as it is")
        self.assertFalse(EXPORT_UI.keep_in_front(window, None), "no handle, no listener")

    def test_child_windows_are_owned_by_the_model_window(self):
        window = self.open()
        child = types.SimpleNamespace()
        window._own(child)
        self.assertIs(child.Owner, window)

        class Refuses(object):
            def __setattr__(self, name, value):
                raise RuntimeError("no owner")
        window._own(Refuses())   # must not raise

    def tick(self):
        timer = TIMERS[-1]
        timer.Tick.fire(timer, None)

    def rows(self):
        return list(self.window._rows)

    def shown(self):
        return list(self.window.models_lv.ItemsSource)

    def by_name(self, name):
        return [row for row in self.rows() if row.Name == name][0]

    def ticked(self):
        return [row.Name for row in self.rows() if row.Checked]

    def click(self, row):
        row.Checked = not row.Checked                 # what the TwoWay binding does first
        list_view = self.window.models_lv
        event, handler = list_view.routed[0]
        self.assertEqual("ButtonBase.Click", event)
        handler(list_view, Args(source=legacy.Source(row)))

    def fire(self, name):
        control = getattr(self.window, name)
        control.Click.fire(control, None)


@unittest.skipIf(EXPORT_UI is None, "rx_export_ui.py not built yet")
class ModelWindowTests(ModelWindowHarness, unittest.TestCase):
    # -- setup and header

    def test_window_basics(self):
        window = self.open()
        self.assertFalse(window.handle_esc)
        self.assertEqual(["rx_theme.xaml"], [Path(p).name for p in window.merged])
        self.assertEqual(Path(window.merged[0]).parent, LIB)
        self.assertEqual(Path(window.xaml_path).name, "rx_export_models.xaml")
        self.assertEqual(window.Resources["close"], "Close")
        self.assertIn("Revit 2022", window.caps_text.Text)
        self.assertIn("2025.3.0.12", window.caps_text.Text)
        self.assertEqual(list(window.roots_lb.ItemsSource), [ROOT_M, ROOT_N])
        self.assertEqual(window.output_text.Text, os.path.join("D:\\", "Out"))
        self.assertTrue(window.default_scope_rb.IsChecked)
        self.assertEqual(self.submitted, [])

    def test_header_leaves_out_an_unreadable_build(self):
        window = self.open(build="")
        self.assertIn("Revit 2022", window.caps_text.Text)
        self.assertNotIn("Extractor", window.caps_text.Text)

    def test_scan_starts_only_when_shown(self):
        self.open(show=False)
        self.assertEqual(self.scan.calls, [])
        self.assertFalse(TIMERS[-1].IsEnabled)
        self.window.show_dialog()
        self.assertEqual(len(self.scan.calls), 1)
        roots, year, read_info, cache = self.scan.calls[0]
        self.assertEqual((roots, year), ([ROOT_M, ROOT_N], 2022))
        self.assertIs(read_info, self.read_info)
        self.assertIs(cache, self.cache)
        self.assertTrue(TIMERS[-1].IsEnabled)
        self.assertEqual(TIMERS[-1].Interval[0], "ms")

    def test_no_roots_no_scan(self):
        self.open(roots=())
        self.assertEqual(self.scan.calls, [])
        self.assertTrue(self.window.status_text.Text)

    # -- scan

    def test_scan_is_time_sliced_and_rows_appear_as_they_are_read(self):
        self.open(step=0.015)
        self.tick()
        first = self.scan.pulled
        self.assertGreater(first, 0)
        self.assertLess(first, len(sample_rows()))
        self.assertEqual(len(self.rows()), first)
        self.assertTrue(TIMERS[-1].IsEnabled)
        for unused in range(10):
            self.tick()
        self.assertEqual(self.scan.finished, 1)
        self.assertFalse(TIMERS[-1].IsEnabled, "the timer stops when the scan ends")

    def test_local_copies_are_counted_not_listed(self):
        self.open()
        self.tick()
        names = [row.Name for row in self.rows()]
        self.assertEqual(names, ["a.rvt", "b.rvt", "c.rvt", "d.rvt", "e.rvt"])
        self.assertIn("Local copies skipped: 1", self.window.count_text.Text)
        self.assertIn("Selected: 0 / 5", self.window.count_text.Text)

    def test_unreadable_folders_are_counted(self):
        self.scan_errors = [ROOT_N]
        self.open(rows=[])
        self.scan.errors = [ROOT_N]
        self.window.rescan_btn.Click.fire(self.window.rescan_btn, None)
        self.tick()
        self.assertIn("could not be read: 1", self.window.count_text.Text)
        self.assertNotIn(ROOT_N, self.window.count_text.Text)

    def test_rows(self):
        self.open()
        self.tick()
        a, b, c, d, e = self.rows()
        self.assertEqual((a.Name, a.Folder, a.Version, a.Note), ("a.rvt", ROOT_M, "2022", ""))
        self.assertTrue(a.Enabled and b.Enabled)
        self.assertFalse(c.Enabled or d.Enabled)
        self.assertIn("2024", c.Tip)
        self.assertIn("could not be read", d.Tip)
        self.assertIn("upgrades a temporary copy", b.Note)
        self.assertEqual(a.Tip, a.path)
        self.assertEqual((b.path, b.workshared), (os.path.join(ROOT_M, "b.rvt"), True))
        self.assertIsNone(e.workshared)

    def test_rescan_and_close_close_the_generator(self):
        self.open(step=1.0)                 # one row per tick
        self.tick()
        self.assertEqual(self.scan.pulled, 1)
        self.fire("rescan_btn")
        self.assertEqual(self.scan.closed_early, 1)
        self.assertEqual(len(self.scan.calls), 2)
        self.tick()
        self.window.Close()
        self.assertEqual(self.scan.closed_early, 2)
        self.assertFalse(TIMERS[-1].IsEnabled)
        timer_stops = TIMERS[-1].stops
        self.tick()                         # a late tick after Close does nothing
        self.assertEqual(self.scan.pulled, 2)
        self.assertGreaterEqual(TIMERS[-1].stops, timer_stops)

    def test_rescan_keeps_ticks_by_path(self):
        self.open()
        self.tick()
        self.click(self.by_name("e.rvt"))
        self.fire("rescan_btn")
        self.tick()
        self.assertEqual(self.ticked(), ["e.rvt"])

    # -- ticking

    def test_disabled_rows_cannot_be_ticked_by_click_space_or_select_all(self):
        self.open()
        self.tick()
        self.click(self.by_name("c.rvt"))
        self.assertEqual(self.ticked(), [])
        list_view = self.window.models_lv
        list_view.SelectedItems = self.rows()
        args = Args("Space", legacy.Source(self.rows()[0]))
        list_view.PreviewKeyDown.fire(list_view, args)
        self.assertTrue(args.Handled)
        self.assertEqual(self.ticked(), ["a.rvt", "b.rvt", "e.rvt"])
        list_view.PreviewKeyDown.fire(list_view, Args("Space", legacy.Source(self.rows()[0])))
        self.assertEqual(self.ticked(), [])
        self.fire("all_btn")
        self.assertEqual(self.ticked(), ["a.rvt", "b.rvt", "e.rvt"])
        self.fire("none_btn")
        self.assertEqual(self.ticked(), [])
        # A highlighted multi-row tick skips the greyed rows too.
        list_view.SelectedItems = self.rows()[:3]
        self.click(self.rows()[0])
        self.assertEqual(self.ticked(), ["a.rvt", "b.rvt"])

    def test_select_all_shown_only_touches_shown_rows_with_one_refresh(self):
        self.open()
        self.tick()
        search = legacy.FakeSearchBar.instances[0]
        self.assertIs(search.host, self.window.search_host)
        self.assertTrue(search.regex)
        search.Text = "e.rvt"
        self.assertEqual([row.Name for row in self.shown()], ["e.rvt"])
        before = self.window.models_lv.Items.refreshes
        self.fire("all_btn")
        self.assertEqual(self.ticked(), ["e.rvt"])
        self.assertEqual(before + 1, self.window.models_lv.Items.refreshes)
        self.assertEqual(SharedEventReactive.raised, [])

    def test_search_is_by_file_name_unless_the_folder_box_is_ticked(self):
        self.open()
        self.tick()
        search = legacy.FakeSearchBar.instances[0]
        search.Text = "n"          # only the folder of e.rvt contains an n
        self.assertEqual([row.Name for row in self.shown()], [])
        self.window.search_folder_cb.IsChecked = True
        self.fire("search_folder_cb")
        self.assertEqual([row.Name for row in self.shown()], ["e.rvt"])

    def test_subfolders_switch_is_remembered_and_rescans(self):
        self.open()
        self.assertTrue(self.window.subfolders_cb.IsChecked)
        self.assertEqual(self.scan.subfolders, [True])
        self.window.subfolders_cb.IsChecked = False
        self.fire("subfolders_cb")
        self.assertEqual(self.scan.subfolders, [True, False])
        self.assertIs(self.saved[-1]["subfolders"], False)

    def test_folder_and_version_column_filters(self):
        self.open()
        self.tick()
        filters = legacy.FakeSearchBar.instances[0].bound
        self.assertEqual([(title, attribute) for column, title, attribute in filters.registered],
                         [("Folder", "Folder"), ("Revit version", "Version")])
        self.assertIs(filters.registered[0][0], self.window.models_lv.View.Columns[2])
        self.assertIs(filters.registered[1][0], self.window.models_lv.View.Columns[3])
        filters.Filters["Version"] = {"2022"}
        filters.refresh()
        self.assertEqual([row.Name for row in self.shown()], ["a.rvt", "e.rvt"])

    def test_no_row_subscription(self):
        self.open()
        self.tick()
        self.click(self.by_name("a.rvt"))
        self.fire("all_btn")
        self.assertEqual(SharedEventReactive.PropertyChanged.handlers, [])
        self.assertEqual(SharedEventReactive.raised, [(self.by_name("a.rvt"), "Checked")])
        self.assertEqual(len(self.window.models_lv.routed), 1, "one handler per list")

    def test_choose_views_needs_exactly_one_tick_and_export_at_least_one(self):
        self.open()
        self.tick()
        self.assertFalse(self.window.views_btn.IsEnabled)
        self.assertFalse(self.window.export_btn.IsEnabled)
        self.click(self.by_name("a.rvt"))
        self.assertTrue(self.window.views_btn.IsEnabled)
        self.assertTrue(self.window.export_btn.IsEnabled)
        self.click(self.by_name("e.rvt"))
        self.assertFalse(self.window.views_btn.IsEnabled)
        self.assertTrue(self.window.export_btn.IsEnabled)
        self.fire("views_btn")              # a click that slips through does nothing
        self.assertEqual(self.reads, [])
        self.assertTrue(self.window.error_text.Text)

    # -- export

    def test_export_default_scope_one_job_per_model_in_list_order(self):
        self.open()
        self.tick()
        self.click(self.by_name("e.rvt"))
        self.click(self.by_name("b.rvt"))
        self.fire("export_btn")
        self.assertFalse(self.window.closed, "the window stays open after Export")
        self.assertEqual(len(self.submitted), 1)
        jobs = self.submitted[0]["jobs"]
        self.assertEqual([job["model_path"] for job in jobs],
                         [os.path.join(ROOT_M, "b.rvt"), os.path.join(ROOT_N, "e.rvt")])
        for job in jobs:
            self.assertEqual(job["index"], build_index(CAPS_2022))
        self.assertEqual(self.submitted[0]["output_parent"], os.path.join("D:\\", "Out"))
        self.assertEqual(self.reads, [], "a default-scope export reads no model")

    def test_summary_counts_older_models(self):
        self.open()
        self.tick()
        self.click(self.by_name("b.rvt"))
        self.assertIn("older", self.window.summary_text.Text)

    def test_shared_index_is_used_and_view_ids_need_one_model(self):
        default = launcher_default_index()
        plain = os.path.join(self.tmp, "plain.json")
        with open(plain, "w") as handle:
            json.dump(default, handle)
        FORMS.pick_file.return_value = plain
        self.open()
        self.tick()
        self.fire("shared_choose_btn")
        self.assertTrue(self.window.shared_scope_rb.IsChecked)
        self.assertEqual(self.window.shared_path_text.Text, plain)
        self.assertEqual(self.saved[-1]["shared_index_path"], plain)
        self.click(self.by_name("a.rvt"))
        self.click(self.by_name("e.rvt"))
        self.fire("export_btn")
        self.assertEqual([job["index"] for job in self.submitted[0]["jobs"]], [default, default])

    def test_shared_index_with_view_ids_and_two_models_is_refused(self):
        with_ids = os.path.join(self.tmp, "ids.json")
        with open(with_ids, "w") as handle:
            json.dump(with_views("view_ids"), handle)
        self.open(shared=with_ids)
        self.tick()
        self.window.default_scope_rb.IsChecked = False
        self.window.shared_scope_rb.IsChecked = True
        self.window._on_scope_changed(None, None)
        self.click(self.by_name("a.rvt"))
        self.click(self.by_name("e.rvt"))
        self.fire("export_btn")
        self.assertEqual(self.submitted, [])
        self.assertFalse(self.window.closed)
        self.assertIn("view", self.window.error_text.Text)
        self.click(self.by_name("e.rvt"))
        self.fire("export_btn")
        self.assertEqual(len(self.submitted[0]["jobs"]), 1)

    def test_shared_scope_without_a_file_or_a_broken_file_is_refused(self):
        self.open()
        self.tick()
        self.window.default_scope_rb.IsChecked = False
        self.window.shared_scope_rb.IsChecked = True
        self.window._on_scope_changed(None, None)
        self.click(self.by_name("a.rvt"))
        self.fire("export_btn")
        self.assertEqual(self.submitted, [])
        self.assertTrue(self.window.error_text.Text)
        broken = os.path.join(self.tmp, "broken.json")
        with open(broken, "w") as handle:
            handle.write("{broken")
        FORMS.pick_file.return_value = broken
        self.fire("shared_choose_btn")
        self.assertIn("JSON", self.window.error_text.Text)
        self.assertEqual(self.saved, [], "a broken file is not remembered")

    # -- the window stays open after Export (queue more without reopening)

    def tick_two(self):
        self.open()
        self.tick()
        self.click(self.by_name("a.rvt"))
        self.click(self.by_name("e.rvt"))

    def test_export_hands_over_at_once_and_the_window_stays_open(self):
        self.tick_two()
        self.fire("export_btn")
        self.assertEqual(len(self.submitted), 1)
        call = self.submitted[0]
        self.assertEqual([job["model_path"] for job in call["jobs"]],
                         [os.path.join(ROOT_M, "a.rvt"), os.path.join(ROOT_N, "e.rvt")])
        self.assertFalse(call["closed"])
        self.assertEqual(self.window.closes, 0)
        self.assertFalse(self.window.closed)

    def test_success_clears_ticks_and_shows_a_confirmation(self):
        self.tick_two()
        self.window.error_text.Text = "old error"
        self.fire("export_btn")
        self.assertEqual(self.ticked(), [])
        self.assertEqual(self.window.error_text.Text, "")
        self.assertIn("2", self.window.status_text.Text)
        self.assertIn("queued", self.window.status_text.Text)
        self.assertFalse(self.window.export_btn.IsEnabled, "nothing is ticked any more")
        self.assertIn("No model selected", self.window.summary_text.Text)
        self.assertEqual(forms_alerts(), 0, "no modal alert")

    def test_success_keeps_folders_output_and_filters_and_saves_settings(self):
        self.tick_two()
        self.window._search.Text = "a"
        self.fire("export_btn")
        self.assertEqual(list(self.window.roots_lb.ItemsSource), [ROOT_M, ROOT_N])
        self.assertEqual(self.window.output_parent, os.path.join("D:\\", "Out"))
        self.assertEqual(self.window.output_text.Text, os.path.join("D:\\", "Out"))
        self.assertEqual(self.window._search.Text, "a")
        self.assertEqual(len(self.rows()), 5)
        self.assertEqual(self.saved[-1]["max_parallel"], 1)
        self.assertEqual(self.saved[-1]["roots"], [ROOT_M, ROOT_N])
        self.assertEqual(self.saved[-1]["output_parent"], os.path.join("D:\\", "Out"))

    def test_success_resets_the_shared_index_scope_but_remembers_the_file(self):
        plain = os.path.join(self.tmp, "plain.json")
        with open(plain, "w") as handle:
            json.dump(launcher_default_index(), handle)
        self.open(shared=plain)
        self.tick()
        self.window.default_scope_rb.IsChecked = False
        self.window.shared_scope_rb.IsChecked = True
        self.window._on_scope_changed(None, None)
        self.click(self.by_name("a.rvt"))
        self.fire("export_btn")
        self.assertEqual(len(self.submitted), 1)
        self.assertTrue(self.window.default_scope_rb.IsChecked)
        self.assertFalse(self.window.shared_scope_rb.IsChecked)
        self.assertEqual(self.window.shared_path_text.Text, plain)

    def test_a_second_batch_can_be_queued_and_a_model_can_be_queued_twice(self):
        self.tick_two()
        self.fire("export_btn")
        self.click(self.by_name("a.rvt"))
        self.fire("export_btn")
        self.assertEqual(len(self.submitted), 2)
        self.assertEqual([job["model_path"] for job in self.submitted[1]["jobs"]],
                         [os.path.join(ROOT_M, "a.rvt")])
        self.assertEqual(self.submitted[0]["jobs"][0]["model_path"],
                         self.submitted[1]["jobs"][0]["model_path"])

    def test_a_failed_hand_over_shows_the_error_and_keeps_the_ticks(self):
        self.tick_two()
        self.submit_error = RuntimeError("The exports were not queued. no session")
        self.fire("export_btn")
        self.assertIn("no session", self.window.error_text.Text)
        self.assertEqual(self.ticked(), ["a.rvt", "e.rvt"])
        self.assertTrue(self.window.export_btn.IsEnabled, "retry is possible")
        self.assertFalse(self.window.closed)
        self.assertNotIn("queued:", self.window.status_text.Text)
        self.assertEqual(forms_alerts(), 0)
        self.submit_error = None
        self.fire("export_btn")
        self.assertEqual(len(self.submitted), 2)
        self.assertEqual(self.ticked(), [])
        self.assertEqual(self.window.error_text.Text, "")

    def test_any_exception_from_submit_is_shown_not_raised(self):
        self.tick_two()
        self.submit_error = ValueError()
        self.fire("export_btn")
        self.assertTrue(self.window.error_text.Text)
        self.assertEqual(self.ticked(), ["a.rvt", "e.rvt"])

    def test_partial_errors_clear_the_queued_ticks_and_keep_the_failed_ones(self):
        self.tick_two()
        self.submit_result = {"queued": 1, "failed": [1],
                              "warning": "Some exports were not queued: Export 2: bad path"}
        self.fire("export_btn")
        self.assertEqual(self.ticked(), ["e.rvt"])
        self.assertIn("Export 2: bad path", self.window.error_text.Text)
        self.assertIn("1", self.window.status_text.Text)
        self.assertTrue(self.window.export_btn.IsEnabled)
        self.assertFalse(self.window.closed)

    def test_a_warning_without_failed_jobs_clears_the_ticks_and_is_shown(self):
        self.tick_two()
        self.submit_result = {"queued": 2, "failed": [], "warning": "The status window failed: x"}
        self.fire("export_btn")
        self.assertEqual(self.ticked(), [])
        self.assertIn("status window failed", self.window.error_text.Text)

    def test_a_double_click_queues_once(self):
        self.tick_two()
        self.submit_hook = lambda: self.fire("export_btn")   # a second click during the hand-over
        self.fire("export_btn")
        self.assertEqual(len(self.submitted), 1)
        self.assertFalse(self.submitted[0]["export_enabled"], "the button is off during hand-over")
        self.fire("export_btn")                              # a click after it: nothing ticked
        self.assertEqual(len(self.submitted), 1)

    def test_the_button_works_again_after_a_failure_during_a_double_click(self):
        self.tick_two()
        self.submit_error = RuntimeError("down")
        self.submit_hook = lambda: self.fire("export_btn")
        self.fire("export_btn")
        self.assertEqual(len(self.submitted), 1)
        self.submit_hook = None
        self.submit_error = None
        self.fire("export_btn")
        self.assertEqual(len(self.submitted), 2)

    def test_no_submit_callable_is_an_error_on_the_window(self):
        self.tick_two()
        self.window._submit = None
        self.fire("export_btn")
        self.assertTrue(self.window.error_text.Text)
        self.assertEqual(self.ticked(), ["a.rvt", "e.rvt"])

    def test_closing_hands_nothing_over(self):
        self.tick_two()
        self.fire("close_btn")
        self.assertTrue(self.window.closed)
        self.assertEqual(self.submitted, [])

    def test_the_views_export_is_handed_over_and_the_list_stays(self):
        self.read_answer = {"title": "a.rvt", "path": os.path.join(ROOT_M, "a.rvt"),
                            "views_2d": [], "views_3d": []}
        job = {"model_path": os.path.join(ROOT_M, "a.rvt"), "index": {"x": 1}}

        class OkWindow(object):
            def __init__(inner, *args, **kwargs):
                inner.job = job

            def show_dialog(inner):
                pass

        self.open()
        self.tick()
        self.click(self.by_name("a.rvt"))
        with patch.object(EXPORT_UI, "ViewWindow", OkWindow):
            self.fire("views_btn")
        self.assertEqual(self.submitted[0]["jobs"], [job])
        self.assertEqual(self.submitted[0]["output_parent"], os.path.join("D:\\", "Out"))
        self.assertFalse(self.window.closed)
        self.assertEqual(self.ticked(), [])
        self.assertIn("queued", self.window.status_text.Text)
        self.assertTrue(self.window.IsEnabled)
        self.assertEqual(len(self.rows()), 5)

    def test_a_failed_views_hand_over_keeps_the_tick_and_shows_the_error(self):
        self.read_answer = {"title": "a.rvt", "path": os.path.join(ROOT_M, "a.rvt"),
                            "views_2d": [], "views_3d": []}

        class OkWindow(object):
            def __init__(inner, *args, **kwargs):
                inner.job = {"model_path": os.path.join(ROOT_M, "a.rvt"), "index": {}}

            def show_dialog(inner):
                pass

        self.open()
        self.tick()
        self.click(self.by_name("a.rvt"))
        self.submit_error = RuntimeError("no session")
        with patch.object(EXPORT_UI, "ViewWindow", OkWindow):
            self.fire("views_btn")
        self.assertIn("no session", self.window.error_text.Text)
        self.assertEqual(self.ticked(), ["a.rvt"])
        self.assertFalse(self.window.closed)

    # -- a failed views hand-over keeps the configured job for the retry

    def failed_views_submit(self):
        """a.rvt ticked, Choose views... produced a job, the hand-over failed. Returns the job."""
        self.read_answer = {"title": "a.rvt", "path": os.path.join(ROOT_M, "a.rvt"),
                            "views_2d": [], "views_3d": []}
        job = {"model_path": os.path.join(ROOT_M, "a.rvt"), "index": {"picked": "views"}}

        class OkWindow(object):
            def __init__(inner, *args, **kwargs):
                inner.job = job

            def show_dialog(inner):
                pass

        self.open()
        self.tick()
        self.click(self.by_name("a.rvt"))
        self.submit_error = RuntimeError("no session")
        with patch.object(EXPORT_UI, "ViewWindow", OkWindow):
            self.fire("views_btn")
        self.submit_error = None
        return job

    def test_a_failed_views_hand_over_says_the_views_are_kept(self):
        self.failed_views_submit()
        self.assertIn("no session", self.window.error_text.Text)
        self.assertIn("selected views are kept", self.window.error_text.Text)

    def test_the_kept_views_note_is_polish_in_polish(self):
        with patch.dict(sys.modules, polish_modules()):
            self.failed_views_submit()
            self.assertIn("Wybrane widoki", self.window.error_text.Text)

    def test_export_after_a_failed_views_submit_sends_the_views_job_not_the_default(self):
        job = self.failed_views_submit()
        self.fire("export_btn")
        self.assertEqual(len(self.submitted), 2)
        self.assertEqual(self.submitted[1]["jobs"], [job])
        self.assertEqual(self.ticked(), [])
        self.assertEqual(self.window.error_text.Text, "")

    def test_the_kept_job_is_used_for_its_row_only_next_to_other_ticked_rows(self):
        job = self.failed_views_submit()
        self.click(self.by_name("e.rvt"))
        self.fire("export_btn")
        sent = self.submitted[1]["jobs"]
        self.assertEqual([item["model_path"] for item in sent],
                         [os.path.join(ROOT_M, "a.rvt"), self.by_name("e.rvt").path])
        self.assertEqual(sent[0], job)
        self.assertEqual(sent[1]["index"], build_index(CAPS_2022))

    def test_a_kept_job_is_retried_even_when_the_shared_index_is_missing(self):
        job = self.failed_views_submit()
        self.window.default_scope_rb.IsChecked = False
        self.window.shared_scope_rb.IsChecked = True       # shared scope, but no file chosen
        self.window._on_scope_changed(None, None)
        self.fire("export_btn")
        self.assertEqual(self.submitted[1]["jobs"], [job])
        self.assertEqual(self.window.error_text.Text, "")

    def test_shared_validation_still_applies_to_rows_without_a_kept_job(self):
        self.failed_views_submit()
        self.window.default_scope_rb.IsChecked = False
        self.window.shared_scope_rb.IsChecked = True
        self.window._on_scope_changed(None, None)
        self.click(self.by_name("e.rvt"))                  # a second row, no kept job
        self.fire("export_btn")
        self.assertEqual(len(self.submitted), 1)           # nothing new was handed over
        self.assertTrue(self.window.error_text.Text)

    def test_unticking_drops_the_kept_job(self):
        self.failed_views_submit()
        self.click(self.by_name("a.rvt"))              # untick
        self.click(self.by_name("a.rvt"))              # tick again
        self.fire("export_btn")
        self.assertEqual(self.submitted[1]["jobs"][0]["index"], build_index(CAPS_2022))

    def test_a_successful_hand_over_clears_the_kept_job(self):
        self.failed_views_submit()
        self.fire("export_btn")                        # queues the kept job
        self.click(self.by_name("a.rvt"))
        self.fire("export_btn")
        self.assertEqual(self.submitted[2]["jobs"][0]["index"], build_index(CAPS_2022))

    def test_a_rescan_drops_the_kept_job(self):
        self.failed_views_submit()
        self.fire("rescan_btn")
        while TIMERS[-1].IsEnabled:
            self.tick()
        self.assertEqual(self.ticked(), ["a.rvt"])               # the tick survives
        self.fire("export_btn")
        self.assertEqual(self.submitted[1]["jobs"][0]["index"], build_index(CAPS_2022))

    def test_a_partially_failed_views_job_is_kept_and_a_queued_one_is_not(self):
        self.read_answer = {"title": "a.rvt", "path": os.path.join(ROOT_M, "a.rvt"),
                            "views_2d": [], "views_3d": []}
        job = {"model_path": os.path.join(ROOT_M, "a.rvt"), "index": {"picked": "views"}}

        class OkWindow(object):
            def __init__(inner, *args, **kwargs):
                inner.job = job

            def show_dialog(inner):
                pass

        self.open()
        self.tick()
        self.click(self.by_name("a.rvt"))
        self.submit_result = {"queued": 0, "failed": [0], "warning": "Export 1: bad path"}
        with patch.object(EXPORT_UI, "ViewWindow", OkWindow):
            self.fire("views_btn")
        self.assertIn("Export 1: bad path", self.window.error_text.Text)
        self.assertIn("selected views are kept", self.window.error_text.Text)
        self.submit_result = None
        self.fire("export_btn")
        self.assertEqual(self.submitted[1]["jobs"], [job])

    def test_new_texts_follow_language(self):
        english = {}
        self.tick_two()
        self.fire("export_btn")
        english["queued"] = self.window.status_text.Text
        self.window._submit = None
        self.click(self.by_name("a.rvt"))
        self.fire("export_btn")
        english["unavailable"] = self.window.error_text.Text
        with patch.dict(sys.modules, polish_modules()):
            self.tick_two()
            self.fire("export_btn")
            self.assertNotEqual(english["queued"], self.window.status_text.Text)
            self.assertIn("2", self.window.status_text.Text)
            self.window._submit = None
            self.click(self.by_name("a.rvt"))
            self.fire("export_btn")
            self.assertNotEqual(english["unavailable"], self.window.error_text.Text)

    # -- reading a model

    def test_choose_views_reads_the_row_and_opens_the_view_window(self):
        self.read_answer = {"title": "b.rvt", "path": os.path.join(ROOT_M, "b.rvt"),
                            "views_2d": [], "views_3d": [], "ifc_setups": [], "ifc_error": ""}
        made = []

        class FakeViewWindow(object):
            def __init__(inner, snapshot, caps, note="", save_dir=""):
                made.append((snapshot, caps, note, save_dir, TIMERS[-1].IsEnabled))
                inner.job = {"model_path": snapshot["path"], "index": {"x": 1}}

            def show_dialog(inner):
                pass

        self.open(step=1.0)
        for unused in range(6):
            self.tick()
        self.click(self.by_name("b.rvt"))
        with patch.object(EXPORT_UI, "ViewWindow", FakeViewWindow):
            self.fire("views_btn")
        path, workshared, timer_on, cursor, enabled = self.reads[0]
        self.assertEqual((path, workshared), (os.path.join(ROOT_M, "b.rvt"), True))
        self.assertFalse(timer_on, "the scan pauses while a model is read")
        self.assertEqual((cursor, enabled), ("Wait", False))
        self.assertEqual(self.window.Dispatcher.invoked, ["Background"], "one forced render")
        snapshot, caps, note, save_dir, timer_during_view = made[0]
        self.assertIs(snapshot, self.read_answer)
        self.assertIs(caps, CAPS_2022)
        self.assertIn("upgrades", note)
        self.assertEqual(self.submitted[0]["jobs"], [{"model_path": os.path.join(ROOT_M, "b.rvt"),
                                                      "index": {"x": 1}}])
        self.assertFalse(self.window.closed, "the window stays open after the views export")
        self.assertIsNone(MOUSE.OverrideCursor)

    def test_back_from_the_view_window_keeps_the_list(self):
        self.read_answer = {"title": "a.rvt", "path": os.path.join(ROOT_M, "a.rvt"),
                            "views_2d": [], "views_3d": []}

        class BackWindow(object):
            def __init__(inner, *args, **kwargs):
                inner.job = None

            def show_dialog(inner):
                pass

        self.open(rows=sample_rows() * 1)
        self.tick()
        self.click(self.by_name("a.rvt"))
        with patch.object(EXPORT_UI, "ViewWindow", BackWindow):
            self.fire("views_btn")
        self.assertFalse(self.window.closed)
        self.assertEqual(self.submitted, [])
        self.assertEqual(self.ticked(), ["a.rvt"])
        self.assertTrue(self.window.IsEnabled)
        self.assertIsNone(MOUSE.OverrideCursor)

    def test_a_read_error_is_shown_and_nothing_is_queued(self):
        self.read_error = rx_reader.ReadError("open_failed", "The model file was not found.")
        self.open(step=1.0)
        for unused in range(6):
            self.tick()
        self.click(self.by_name("a.rvt"))
        with patch.object(EXPORT_UI, "ViewWindow", Mock(side_effect=AssertionError("opened"))):
            self.fire("views_btn")
        self.assertEqual(self.window.error_text.Text, "The model file was not found.")
        self.assertEqual(self.submitted, [])
        self.assertFalse(self.window.closed)
        self.assertIsNone(MOUSE.OverrideCursor)
        self.assertTrue(self.window.IsEnabled)

    def test_any_other_error_is_shown_too(self):
        self.read_error = RuntimeError("boom")
        self.open()
        self.tick()
        self.click(self.by_name("a.rvt"))
        self.fire("views_btn")
        self.assertIn("boom", self.window.error_text.Text)
        self.assertIsNone(MOUSE.OverrideCursor)

    def test_close_failed_closes_the_window_without_queuing(self):
        self.read_error = rx_reader.ReadError("close_failed", "Revit did not close the model.")
        self.open()
        self.tick()
        self.click(self.by_name("a.rvt"))
        self.fire("views_btn")
        self.assertTrue(self.window.closed)
        self.assertEqual(self.submitted, [])
        self.assertEqual(self.window.fatal_error, "Revit did not close the model.")
        self.assertIsNone(MOUSE.OverrideCursor)
        self.assertFalse(TIMERS[-1].IsEnabled, "the scan does not resume after Close")

    def test_the_greyed_row_is_never_read(self):
        self.open()
        self.tick()
        row = self.by_name("c.rvt")
        row.set_quietly(True)               # whatever happened, a greyed tick is refused
        self.window._refresh_state()
        self.fire("views_btn")
        self.fire("export_btn")
        self.assertEqual(self.reads, [])
        self.assertEqual(self.submitted, [])

    # -- settings

    def test_add_and_remove_roots_save_and_rescan(self):
        FORMS.pick_folder.return_value = os.path.join("D:\\", "x")
        self.open(roots=(ROOT_M,))
        self.fire("add_root_btn")
        self.assertEqual(self.saved[-1]["roots"], [ROOT_M, os.path.join("D:\\", "x")])
        self.assertEqual(self.scan.calls[-1][0], [ROOT_M, os.path.join("D:\\", "x")])
        self.assertEqual(list(self.window.roots_lb.ItemsSource), self.saved[-1]["roots"])
        self.window.roots_lb.SelectedItem = ROOT_M
        self.fire("remove_root_btn")
        self.assertEqual(self.saved[-1]["roots"], [os.path.join("D:\\", "x")])
        self.assertEqual(len(self.scan.calls), 3)
        self.window.roots_lb.SelectedItem = None
        self.fire("remove_root_btn")
        self.assertEqual(len(self.saved), 2)
        FORMS.pick_folder.return_value = None
        self.fire("add_root_btn")
        self.assertEqual(len(self.saved), 2, "a cancelled picker changes nothing")
        title = FORMS.pick_folder.call_args[1]["title"]
        self.assertTrue(title)

    def test_output_folder_change_is_checked_and_saved(self):
        FORMS.pick_folder.return_value = os.path.join("D:\\", "Exports")
        self.open()
        self.fire("output_btn")
        self.assertEqual(self.window.output_text.Text, os.path.join("D:\\", "Exports"))
        self.assertEqual(self.saved[-1]["output_parent"], os.path.join("D:\\", "Exports"))
        self.assertEqual(self.saved[-1]["max_parallel"], 1)
        FORMS.pick_folder.return_value = "D:\\"
        self.fire("output_btn")
        self.assertEqual(self.window.output_text.Text, os.path.join("D:\\", "Exports"))
        self.assertTrue(self.window.error_text.Text)
        self.assertEqual(len(self.saved), 1)

    def test_a_failing_save_is_shown_not_raised(self):
        FORMS.pick_folder.return_value = os.path.join("D:\\", "Exports")
        self.open()

        def fail(values):
            raise IOError("disk full")
        self.window._save_settings = fail
        self.fire("output_btn")
        self.assertIn("disk full", self.window.error_text.Text)

    def test_texts_follow_language(self):
        with patch.dict(sys.modules, polish_modules()):
            self.open()
            self.tick()
            self.assertEqual(self.window.Resources["close"], "Zamknij")
            self.assertIn("Zaznaczone: 0 / 5", self.window.count_text.Text)


# ===== 5. View window (criterion 8) ============================================================

def view_snapshot(ifc_setups=(), ifc_error=""):
    data = legacy.snapshot()
    data.pop("modified")
    data["title"] = "b.rvt"
    data["path"] = os.path.join(ROOT_M, "b.rvt")
    data["ifc_setups"] = list(ifc_setups)
    data["ifc_error"] = ifc_error
    return data


@unittest.skipIf(EXPORT_UI is None, "rx_export_ui.py not built yet")
class ViewWindowSliceTests(legacy.WindowCases, unittest.TestCase):
    """The slice 1 window cases, unchanged, against the Export button's view window."""

    def make_window(self, data):
        return EXPORT_UI.ViewWindow(data, CAPS_2022)


@unittest.skipIf(EXPORT_UI is None, "rx_export_ui.py not built yet")
class ViewWindowTests(unittest.TestCase):
    def setUp(self):
        reset_fakes()

    def open(self, caps=CAPS_2022, note="", **snapshot_args):
        self.window = EXPORT_UI.ViewWindow(view_snapshot(**snapshot_args), caps, note=note,
                                           save_dir="D:\\idx")
        return self.window

    def row(self, dimension, element_id):
        return [r for r in self.window._rows[dimension] if r.ElementId == element_id][0]

    def tick_3d(self, element_id):
        self.window.default3d_rb.IsChecked = False
        self.window.selected3d_rb.IsChecked = True
        row = self.row("3d", element_id)
        row.set_quietly(True)
        self.window._on_settings_changed(None, None)

    def fire(self, name):
        control = getattr(self.window, name)
        control.Click.fire(control, None)

    def derivative(self):
        return self.window._payload()["metadata"]["parameters"]["derivative_type"]

    def test_window_file_and_header(self):
        window = self.open(note="Saved in Revit 2021. The export upgrades a temporary copy.")
        self.assertEqual(Path(window.xaml_path).name, "rx_export_views.xaml")
        self.assertEqual(Path(window.merged[0]).parent, LIB)
        self.assertEqual(window.model_title.Text, "b.rvt")
        self.assertEqual(window.model_path.Text, os.path.join(ROOT_M, "b.rvt"))
        self.assertIn("not changed", window.model_note.Text)
        self.assertIn("upgrades a temporary copy", window.model_note.Text)

    def test_ids_follow_the_view_key(self):
        self.open(CAPS_2022)
        self.tick_3d("21")
        self.assertEqual(self.derivative()["3dviewing"], {"view_ids": [21]})
        self.open(CAPS_2026)
        self.tick_3d("21")
        self.assertEqual(self.derivative()["3dviewing"], {"view_unique_ids": ["uid-21"]})
        self.assertEqual(self.row("3d", "21").ElementId, "21", "the list still shows the id")

    def test_without_formats_the_note_and_no_format_or_metadata_control(self):
        window = self.open(CAPS_2022)
        self.assertEqual(window.formats_panel.Visibility, "Collapsed")
        self.assertEqual(window.formats_note_text.Visibility, "Visible")
        self.assertEqual(window.database_panel.Visibility, "Collapsed")
        self.assertEqual(window.topology_cb.Visibility, "Collapsed")
        settings = window._settings()
        for key in ("dwg", "ifc", "extended_properties", "topology_metadata", "ifc_setup_name"):
            self.assertNotIn(key, settings)
        self.assertEqual(window._payload(), build_index(CAPS_2022))

    def test_with_formats_dwg_ifc_and_metadata_follow_caps(self):
        setups = [{"name": "Coordination", "ready": True}, {"name": "Raw", "ready": False}]
        window = self.open(CAPS_2026, ifc_setups=setups)
        self.assertEqual(window.formats_panel.Visibility, "Visible")
        self.assertEqual(window.formats_note_text.Visibility, "Collapsed")
        self.assertEqual(window.database_panel.Visibility, "Visible")
        self.assertEqual(window.topology_cb.Visibility, "Visible")
        self.assertEqual(window._payload(), build_index(CAPS_2026))
        items = list(window.ifc_setup_cb.ItemsSource)
        self.assertEqual([(i.Tag, i.IsEnabled) for i in items],
                         [("", True), ("Coordination", True), ("Raw", False)])
        self.assertFalse(window.ifc_setup_cb.IsEnabled, "IFC off: no setup to choose")
        window.dwg_cb.IsChecked = True
        window.ifc_cb.IsChecked = True
        window._on_settings_changed(None, None)
        self.assertTrue(window.ifc_setup_cb.IsEnabled)
        self.assertEqual(self.derivative()["export"], {"to": ["dwg", "ifc"]})
        self.assertNotIn("direct_params", window._payload()["metadata"]["parameters"])
        window.ifc_setup_cb.SelectedItem = items[1]
        window._on_settings_changed(None, None)
        self.assertEqual(window._payload()["metadata"]["parameters"]["direct_params"],
                         {"IFCExportOption": "Coordination"})
        window.ifc_setup_cb.SelectedItem = items[2]   # not ready: never used
        window._on_settings_changed(None, None)
        self.assertNotIn("direct_params", window._payload()["metadata"]["parameters"])
        window.extended_cb.IsChecked = True
        window.topology_cb.IsChecked = True
        window._on_settings_changed(None, None)
        self.assertEqual(self.derivative()["metadata"], {"extended_properties": True})
        self.assertTrue(self.derivative()["3dviewing"]["topology_metadata"])
        window.pdb_cb.IsChecked = False
        window._on_settings_changed(None, None)
        self.assertFalse(window.extended_cb.IsEnabled)

    def test_ifc_error_is_shown(self):
        window = self.open(CAPS_2026, ifc_error="An IFC setup in the model has invalid JSON.")
        self.assertEqual(window.ifc_error_text.Text, "An IFC setup in the model has invalid JSON.")
        self.assertEqual(window.ifc_error_text.Visibility, "Visible")
        window = self.open(CAPS_2026)
        self.assertEqual(window.ifc_error_text.Visibility, "Collapsed")

    def test_reset_restores_the_row_defaults(self):
        window = self.open(CAPS_2026)
        window.dwg_cb.IsChecked = True
        window.extended_cb.IsChecked = True
        self.fire("reset_btn")
        self.assertFalse(window.dwg_cb.IsChecked)
        self.assertFalse(window.extended_cb.IsChecked)
        self.assertEqual(window._payload(), build_index(CAPS_2026))

    def test_export_returns_one_job_and_closes(self):
        window = self.open(CAPS_2022)
        self.tick_3d("20")
        self.fire("export_btn")
        self.assertTrue(window.closed)
        self.assertEqual(window.job, {"model_path": os.path.join(ROOT_M, "b.rvt"),
                                      "index": build_index(CAPS_2022, {"scope_3d": "selected"},
                                                           [], ["20"])})

    def test_invalid_selection_disables_export_too(self):
        window = self.open(CAPS_2022)
        window.default3d_rb.IsChecked = False
        window.selected3d_rb.IsChecked = True
        window._on_settings_changed(None, None)
        self.assertFalse(window.export_btn.IsEnabled)
        self.assertFalse(window.save_btn.IsEnabled)
        self.fire("export_btn")
        self.assertIsNone(window.job)
        self.assertFalse(window.closed)

    def test_back_queues_nothing(self):
        window = self.open()
        self.fire("back_btn")
        self.assertTrue(window.closed)
        self.assertIsNone(window.job)

    def test_save_writes_the_index_through_the_atomic_writer(self):
        window = self.open()
        FORMS.save_file.return_value = os.path.join("D:\\", "idx", "index.json")
        written = []
        with patch.object(EXPORT_UI, "write_index_atomic", lambda p, c: written.append((p, c))):
            self.fire("save_btn")
        self.assertEqual(written[0][0], os.path.join("D:\\", "idx", "index.json"))
        self.assertEqual(json.loads(written[0][1]), build_index(CAPS_2022))
        self.assertEqual(FORMS.save_file.call_args[1]["init_dir"], "D:\\idx")
        self.assertIsNone(window.job)
        self.assertFalse(window.closed)

    def test_texts_follow_language(self):
        with patch.dict(sys.modules, polish_modules()):
            window = self.open()
        self.assertEqual(window.Resources["back"], "Wstecz")
        self.assertIn("Zaznaczone: 0 / 4", window.count2d_text.Text)


# ===== 6. script.py (criteria 2, 9) ============================================================

class FakeDomain(object):
    def __init__(self, handler=None):
        self.data = {}
        if handler is not None:
            from rx_status import SESSION_KEY
            self.data[SESSION_KEY] = handler

    def GetData(self, key):
        return self.data.get(key)

    def SetData(self, key, value):
        raise AssertionError("script.py must never publish a session")


class SessionHandler(object):
    """A live session's Func[String, String]: answers ping, records every request."""

    def __init__(self, answer=None):
        self.requests = []
        self.answer = answer or {"ok": True, "added": ["job-1"], "errors": []}

    def __call__(self, text):
        assert isinstance(text, str), "only text crosses between engines"
        request = json.loads(text)
        self.requests.append(request)
        if request["op"] == "ping":
            from rx_status import PROTOCOL
            return json.dumps({"ok": True, "protocol": PROTOCOL, "busy": False})
        if request["op"] == "show":
            return json.dumps({"ok": True})
        return json.dumps(self.answer)

    def ops(self):
        return [request["op"] for request in self.requests if request["op"] != "ping"]


class FakeModelWindow(object):
    """The real window calls submit(jobs, output_parent) while it is open; this one does it for
    each batch in `batches` (a click on Export) from inside show_dialog."""
    made = []
    batches = []
    fatal_error = None
    raise_on_show = None
    output_override = None
    ops_source = None

    def __init__(self, caps, settings, read_info, cache, read, save_settings, extractor_build="",
                 scan=None, submit=None, cloud=None, read_cloud=None):
        self.cloud = cloud
        self.read_cloud = read_cloud
        self.caps, self.settings, self.read_info = caps, settings, read_info
        self.cache, self.read, self.save_settings = cache, read, save_settings
        self.extractor_build = extractor_build
        self.scan = scan
        self.submit = submit
        self.output_parent = FakeModelWindow.output_override or settings["output_parent"]
        self.shown = 0
        self.stopped = 0
        self.results = []
        self.submit_errors = []
        self.ops_at_end_of_dialog = None
        FakeModelWindow.made.append(self)

    def show_dialog(self):
        self.shown += 1
        if FakeModelWindow.raise_on_show is not None:
            raise FakeModelWindow.raise_on_show
        for batch in FakeModelWindow.batches:
            try:
                self.results.append(self.submit(batch, self.output_parent))
            except Exception as error:
                self.submit_errors.append(str(error))
        self.fatal_error = FakeModelWindow.fatal_error
        if FakeModelWindow.ops_source is not None:
            self.ops_at_end_of_dialog = FakeModelWindow.ops_source()

    def stop_scan(self):
        self.stopped += 1


class FakeConfig(object):
    pass


def plain(value):
    if isinstance(value, dict):
        return all(isinstance(k, str) and plain(v) for k, v in value.items())
    if isinstance(value, list):
        return all(plain(v) for v in value)
    return value is None or isinstance(value, (str, int, float, bool))


@unittest.skipIf(not (BUTTON / "script.py").is_file(), "script.py not built yet")
class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rxexp-script-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.revit_dir = os.path.join(self.tmp, "Revit")
        os.makedirs(os.path.join(self.revit_dir, "RevitExtractor"))
        open(os.path.join(self.revit_dir, "RevitExtractor", "RevitExtractor.exe"), "w").close()
        self.appdata = os.path.join(self.tmp, "AppData")
        self.documents = os.path.join(self.tmp, "Documents")
        self.profile = os.path.join(self.tmp, "Profile")   # the default output is made here
        FakeModelWindow.made = []
        FakeModelWindow.batches = []
        FakeModelWindow.output_override = None
        FakeModelWindow.ops_source = lambda: getattr(self.handler, "ops", list)()
        FakeModelWindow.fatal_error = None
        FakeModelWindow.raise_on_show = None
        self.sessions = []
        self.handler = SessionHandler()
        self.domain = FakeDomain()
        self.alerts = []
        self.config = FakeConfig()
        self.config_saves = 0
        self.versions = {}
        self.module = self.load()

    def open_session(self, max_parallel):
        self.sessions.append(max_parallel)
        return self.handler

    def folder(self, which):
        return {"ApplicationData": self.appdata, "MyDocuments": self.documents,
                "UserProfile": self.profile}[which]

    def load(self):
        test = self
        special = types.SimpleNamespace(ApplicationData="ApplicationData",
                                        MyDocuments="MyDocuments", UserProfile="UserProfile")

        def file_version(path):
            if path not in test.versions:
                raise IOError("no version")
            return types.SimpleNamespace(FileVersion=test.versions[path])

        def save_config():
            test.config_saves += 1

        forms = types.SimpleNamespace(alert=lambda msg, **kw: test.alerts.append((msg, kw)))
        script = types.SimpleNamespace(get_config=Mock(return_value=self.config),
                                       save_config=save_config,
                                       get_logger=lambda: Mock())
        self.db = types.SimpleNamespace(BasicFileInfo=object())
        self.host = types.SimpleNamespace(uiapp=self.uiapp(),
                                          proc_path=os.path.join(self.revit_dir, "Revit.exe"))
        stubs = {
            "pyrevit": types.SimpleNamespace(DB=self.db, HOST_APP=self.host, forms=forms,
                                             script=script),
            "System": stub_module(
                "System", AppDomain=types.SimpleNamespace(CurrentDomain=None),
                Environment=types.SimpleNamespace(GetFolderPath=self.folder, SpecialFolder=special)),
            "rx_export_ui": stub_module("rx_export_ui", ModelWindow=FakeModelWindow),
            "rx_status_ui": stub_module("rx_status_ui", open_session=self.open_session),
        }
        module = legacy.load("export_script_under_test", "script.py", stubs, BUTTON)
        # script.py reads the build through rx_dotnet (real System is absent on CPython).
        info_class = types.SimpleNamespace(GetVersionInfo=file_version)
        real = module.rx_dotnet.file_version
        module.rx_dotnet.file_version = lambda path: real(path, importer=lambda: info_class)
        self.addCleanup(setattr, module.rx_dotnet, "file_version", real)
        self.script_stub = script
        return module

    def uiapp(self, active=None, empty=True, version="2022"):
        self.documents_set = types.SimpleNamespace(IsEmpty=empty)
        self.app = types.SimpleNamespace(Documents=self.documents_set, VersionNumber=version)
        return types.SimpleNamespace(ActiveUIDocument=active, Application=self.app)

    def run_main(self, **uiapp_args):
        if uiapp_args:
            self.host.uiapp = self.uiapp(**uiapp_args)
        with patch.object(self.module, "AppDomain", types.SimpleNamespace(CurrentDomain=self.domain)):
            self.module.main()

    def job(self, name="a.rvt"):
        return {"model_path": os.path.join("D:\\", "m", name), "index": build_index(CAPS_2022)}

    # -- guards (criterion 2)

    def test_a_document_open_stops_before_any_window_and_shows_the_session(self):
        self.domain = FakeDomain(self.handler)
        with patch.object(rx_reader, "read_model", Mock(side_effect=AssertionError("read"))):
            self.run_main(active=object())
        self.assertEqual(FakeModelWindow.made, [])
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(self.handler.ops(), ["show"])
        self.assertEqual(self.sessions, [], "no new session is created")

    def test_a_document_open_without_a_session_only_alerts(self):
        self.run_main(active=object())
        self.assertEqual(FakeModelWindow.made, [])
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(self.handler.requests, [])

    def test_only_a_real_true_from_is_empty_passes(self):
        for value in (False, 1, "True", None, object()):
            FakeModelWindow.made = []
            self.alerts = []
            self.run_main(empty=value)
            self.assertEqual(FakeModelWindow.made, [], repr(value))
            self.assertEqual(len(self.alerts), 1, repr(value))
        self.alerts = []
        self.run_main(empty=True)
        self.assertEqual(len(FakeModelWindow.made), 1)
        self.assertEqual(self.alerts, [])

    def test_documents_that_cannot_be_asked_count_as_open(self):
        broken = types.SimpleNamespace(ActiveUIDocument=None)   # no Application attribute
        self.host.uiapp = broken
        self.run_main()
        self.assertEqual(FakeModelWindow.made, [])
        self.assertEqual(len(self.alerts), 1)

    def test_unsupported_revit_stops(self):
        for version in ("2021", "abc", None):
            FakeModelWindow.made = []
            self.alerts = []
            self.run_main(version=version)
            self.assertEqual(FakeModelWindow.made, [], version)
            self.assertEqual(len(self.alerts), 1)

    def test_missing_extractor_stops(self):
        os.remove(os.path.join(self.revit_dir, "RevitExtractor", "RevitExtractor.exe"))
        self.run_main()
        self.assertEqual(FakeModelWindow.made, [])
        self.assertIn("RevitExtractor.exe", self.alerts[0][0])

    def test_messages_follow_language(self):
        with patch.dict(sys.modules, polish_modules()):
            self.run_main(active=object())
        english = self.alerts[0][0]
        self.alerts = []
        self.run_main(active=object())
        self.assertNotEqual(english, self.alerts[0][0])

    # -- wiring

    def test_window_gets_caps_settings_cache_and_build(self):
        utility = os.path.join(self.revit_dir, "RevitExtractor", "ExtractorUtility.dll")
        self.versions[utility] = "2025.3.0.12"
        self.config.roots = [os.path.join("D:\\", "m")]
        self.run_main()
        window = FakeModelWindow.made[0]
        self.assertEqual(window.caps, rx_capabilities.for_revit(2022))
        self.assertEqual(window.settings["roots"], [os.path.join("D:\\", "m")])
        self.assertEqual(window.settings["output_parent"],
                         os.path.join(self.profile, "RevitExtractor"))
        self.assertEqual(window.extractor_build, "2025.3.0.12")
        self.assertEqual(window.cache.file_path,
                         os.path.join(self.appdata, "RevitExtractor", "catalog-cache.json"))
        self.script_stub.get_config.assert_called_with("RevitExtractorExport")
        # The UI module imports no rx_catalog: script.py hands it the scan.
        self.assertIs(window.scan, rx_catalog.scan)
        self.assertEqual(window.shown, 1)
        self.assertEqual(window.stopped, 1, "the scan timer is stopped after the dialog")

    def test_an_extractor_from_an_earlier_session_is_announced(self):
        with patch.object(self.module, "_orphan_extractor_running", Mock(return_value=True)):
            self.run_main()
        self.assertEqual(len(self.alerts), 1)
        self.assertIn("earlier Revit session", self.alerts[0][0])
        self.assertEqual(len(FakeModelWindow.made), 1, "the window still opens")

    def test_an_earlier_session_run_is_put_into_the_status_window(self):
        run = types.SimpleNamespace(root=os.path.join(self.profile, "RevitExtractor",
                                                      "export-20261118-110000-bbbbbbbb"))
        self.domain = FakeDomain(self.handler)
        with patch.object(self.module, "_orphan_extractor_running", Mock(return_value=True)),                 patch.object(self.module, "find_orphan_run", Mock(return_value=run)):
            self.run_main()
        self.assertEqual(self.alerts, [], "the status window shows it: no alert")
        self.assertEqual(self.handler.ops(), ["adopt", "show"])
        adopt = [r for r in self.handler.requests if r["op"] == "adopt"][0]
        self.assertEqual(adopt["run_root"], run.root)
        self.assertEqual(len(FakeModelWindow.made), 1, "the window still opens")

    def test_a_run_that_cannot_be_found_or_adopted_still_gets_the_alert(self):
        run = types.SimpleNamespace(root=os.path.join(self.profile, "x", "export-20261118-110000-bbbbbbbb"))
        for found, answer in ((None, None), (run, {"ok": False, "error": "no"})):
            self.alerts[:] = []
            self.handler.answer = answer or self.handler.answer
            with patch.object(self.module, "_orphan_extractor_running", Mock(return_value=True)),                     patch.object(self.module, "find_orphan_run", Mock(return_value=found)):
                self.run_main()
            self.assertEqual(len(self.alerts), 1, found)
            self.assertIn("earlier Revit session", self.alerts[0][0])

    def test_orphan_check_needs_no_session_and_a_running_extractor(self):
        running = Mock(return_value=True)
        starter = types.SimpleNamespace(extractor_running=running)
        with patch.object(self.module, "DotNetStarter", Mock(return_value=starter)):
            self.assertTrue(self.module._orphan_extractor_running(self.domain))
            self.domain = FakeDomain(self.handler)
            self.assertFalse(self.module._orphan_extractor_running(self.domain),
                             "a session of this Revit shows its own rows")
        running.side_effect = RuntimeError("no System")
        with patch.object(self.module, "DotNetStarter", Mock(return_value=starter)):
            self.assertFalse(self.module._orphan_extractor_running(FakeDomain()))

    def test_build_is_read_from_a_year_named_utility(self):
        folder = os.path.join(self.revit_dir, "RevitExtractor")
        utility = os.path.join(folder, "ExtractorUtility_2025.dll")
        open(utility, "w").close()
        self.versions[utility] = "2026.6.7.22"
        self.run_main()
        self.assertEqual(FakeModelWindow.made[0].extractor_build, "2026.6.7.22")

    def test_unreadable_build_is_left_out(self):
        self.run_main()
        self.assertEqual(FakeModelWindow.made[0].extractor_build, "")

    def test_read_and_read_info_wiring(self):
        self.run_main()
        window = FakeModelWindow.made[0]
        with patch.object(rx_reader, "read_model", Mock(return_value="snap")) as read_model:
            self.assertEqual(window.read("D:\\m\\a.rvt", None), "snap")
        read_model.assert_called_once_with(self.app, self.db, "D:\\m\\a.rvt", window.caps, None)
        with patch.object(rx_catalog, "read_basic_info", Mock(return_value={"format": "2022"})) \
                as basic:
            self.assertEqual(window.read_info("D:\\m\\a.rvt"), {"format": "2022"})
        basic.assert_called_once_with("D:\\m\\a.rvt", self.db.BasicFileInfo)

    def test_settings_are_saved_only_when_changed(self):
        self.run_main()
        window = FakeModelWindow.made[0]
        values = logic.settings_to_save([os.path.join("D:\\", "m")], "D:\\Out", 1, "")
        window.save_settings(values)
        self.assertEqual(self.config_saves, 1)
        self.assertEqual(self.config.roots, [os.path.join("D:\\", "m")])
        window.save_settings(values)
        self.assertEqual(self.config_saves, 1)

    # -- hand-over (criterion 9): the window calls submit while it is open

    def queue(self, *batches):
        FakeModelWindow.batches = [list(batch) for batch in batches]

    def test_jobs_go_to_the_session_as_json_then_show(self):
        self.queue([self.job("a.rvt"), self.job("b.rvt")])
        self.config.max_parallel = 3
        self.run_main()
        self.assertEqual(self.sessions, [3])
        self.assertEqual(self.handler.ops(), ["submit", "show"])
        submit = [r for r in self.handler.requests if r["op"] == "submit"][0]
        self.assertTrue(plain(submit))
        self.assertEqual([sorted(job) for job in submit["jobs"]],
                         [["index", "model_path", "output_parent", "revit_dir"]] * 2)
        self.assertEqual([job["model_path"] for job in submit["jobs"]],
                         [os.path.join("D:\\", "m", "a.rvt"), os.path.join("D:\\", "m", "b.rvt")])
        for job in submit["jobs"]:
            self.assertEqual(job["revit_dir"], self.revit_dir)
            self.assertEqual(job["output_parent"], os.path.join(self.profile, "RevitExtractor"))
            self.assertEqual(job["index"], build_index(CAPS_2022))
        self.assertEqual(self.alerts, [])
        self.assertEqual(FakeModelWindow.made[0].results[0]["queued"], 1)

    def test_the_hand_over_happens_while_the_window_is_open(self):
        self.queue([self.job()])
        self.run_main()
        window = FakeModelWindow.made[0]
        self.assertEqual(window.ops_at_end_of_dialog, ["submit", "show"])

    def test_the_output_folder_of_the_window_goes_with_the_jobs(self):
        self.queue([self.job()])
        FakeModelWindow.output_override = os.path.join("D:\\", "Elsewhere")
        self.run_main()
        submit = [r for r in self.handler.requests if r["op"] == "submit"][0]
        self.assertEqual(submit["jobs"][0]["output_parent"], os.path.join("D:\\", "Elsewhere"))

    def test_two_batches_use_one_session_and_both_are_submitted(self):
        self.queue([self.job("a.rvt")], [self.job("b.rvt")])
        self.run_main()
        self.assertEqual(self.handler.ops(), ["submit", "show", "submit", "show"])

    def test_main_never_hands_over_after_the_dialog(self):
        with patch.object(self.module, "_hand_over", Mock()) as hand_over:
            self.run_main()                       # window closed with nothing queued
            hand_over.assert_not_called()
            self.queue([self.job()])
            self.run_main()                       # one batch: submitted once, by the window
            self.assertEqual(hand_over.call_count, 1)

    def test_errors_in_the_answer_come_back_as_a_warning_and_failed_numbers(self):
        self.queue([self.job("a.rvt"), self.job("b.rvt")])
        self.handler.answer = {"ok": True, "added": ["job-1"], "errors": ["Export 2: bad path"]}
        self.run_main()
        result = FakeModelWindow.made[0].results[0]
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["failed"], [1])
        self.assertIn("Export 2: bad path", result["warning"])
        self.assertEqual(self.alerts, [], "no modal alert")

    def test_polish_error_numbers_are_understood_and_unnumbered_errors_fail_nothing(self):
        self.queue([self.job("a.rvt"), self.job("b.rvt")])
        self.handler.answer = {"ok": True, "added": ["job-1"],
                               "errors": ["Eksport 1: zła ścieżka", "Błąd okna statusu: x"]}
        self.run_main()
        result = FakeModelWindow.made[0].results[0]
        self.assertEqual(result["failed"], [0])
        self.assertIn("Błąd okna statusu: x", result["warning"])

    def test_a_refused_request_raises_with_the_reason(self):
        self.queue([self.job()])
        self.handler.answer = {"ok": False, "error": "Nothing to export"}
        self.run_main()
        window = FakeModelWindow.made[0]
        self.assertEqual(window.results, [])
        self.assertIn("Nothing to export", window.submit_errors[0])
        self.assertEqual(self.alerts, [])

    def test_a_broken_answer_raises(self):
        self.queue([self.job()])
        self.handler = lambda text: "not json"
        self.run_main()
        window = FakeModelWindow.made[0]
        self.assertEqual(len(window.submit_errors), 1)
        self.assertTrue(window.submit_errors[0])
        self.assertEqual(self.alerts, [])

    def test_a_session_that_cannot_be_opened_raises(self):
        self.queue([self.job()])

        def broken(max_parallel):
            raise RuntimeError("no engine")
        self.module.open_session = broken
        self.run_main()
        self.assertIn("no engine", FakeModelWindow.made[0].submit_errors[0])

    def test_failure_texts_follow_language(self):
        self.queue([self.job()])
        self.handler.answer = {"ok": False, "error": "x"}
        self.run_main()
        english = FakeModelWindow.made[0].submit_errors[0]
        FakeModelWindow.made = []
        with patch.dict(sys.modules, polish_modules()):
            self.run_main()
        self.assertNotEqual(english, FakeModelWindow.made[0].submit_errors[0])

    def test_nothing_ticked_creates_no_session(self):
        self.run_main()
        self.assertEqual(self.sessions, [])
        self.assertEqual(self.alerts, [])

    def test_close_failed_is_shown_and_nothing_more_is_queued(self):
        FakeModelWindow.fatal_error = "Revit did not close the model."
        self.run_main()
        self.assertEqual(self.sessions, [])
        self.assertIn("Revit did not close the model.", self.alerts[0][0])

    def test_close_failed_after_an_earlier_batch_keeps_that_batch_and_alerts(self):
        self.queue([self.job()])
        FakeModelWindow.fatal_error = "Revit did not close the model."
        self.run_main()
        self.assertEqual(self.handler.ops(), ["submit", "show"])
        self.assertIn("Revit did not close the model.", self.alerts[0][0])
        self.assertEqual(FakeModelWindow.made[0].stopped, 1)

    def test_a_window_error_is_shown_and_the_scan_stopped(self):
        FakeModelWindow.raise_on_show = RuntimeError("xaml broke")
        self.run_main()
        self.assertIn("xaml broke", self.alerts[0][0])
        self.assertEqual(FakeModelWindow.made[0].stopped, 1)
        self.assertEqual(self.sessions, [])

    # -- cloud wiring (specs/SPEC-cloud-catalog.md, Task 8)

    def local_appdata(self):
        return os.path.join(self.tmp, "Local")

    def run_with_env(self, **env):
        with patch.dict(os.environ, env, clear=False):
            self.run_main()

    def test_the_window_gets_the_cloud_source(self):
        self.run_with_env(LOCALAPPDATA=self.local_appdata())
        cloud = FakeModelWindow.made[0].cloud
        self.assertEqual(cloud["folders"], rx_cloud.revit_folders(self.local_appdata(), 2022))
        self.assertEqual(cloud["memory"].file_path,
                         os.path.join(self.appdata, "RevitExtractor", "cloud-catalog.json"))
        self.assertIsInstance(cloud["memory"], Memory)

    def test_the_cloud_memory_is_loaded(self):
        folder = os.path.join(self.appdata, "RevitExtractor")
        os.makedirs(folder)
        memory = cloud_memory(folder)
        memory.set_included([CP1_KEY])
        self.assertTrue(memory.save())
        self.run_with_env(LOCALAPPDATA=self.local_appdata())
        loaded = FakeModelWindow.made[0].cloud["memory"]
        self.assertEqual(loaded.included, {CP1_KEY})
        self.assertEqual(loaded.model_name(CP1, CM3), "Alpha-Architecture.rvt")

    def test_no_local_appdata_means_no_cloud_source(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOCALAPPDATA", None)
            self.run_main()
        self.assertIsNone(FakeModelWindow.made[0].cloud)
        self.assertEqual(self.alerts, [])

    def test_read_forwards_links_only_when_asked(self):
        self.run_with_env(LOCALAPPDATA=self.local_appdata())
        window = FakeModelWindow.made[0]
        with patch.object(rx_reader, "read_model", Mock(return_value="snap")) as read_model:
            window.read("C:\\cache\\x.rvt", None, links=True)
            read_model.assert_called_once_with(self.app, self.db, "C:\\cache\\x.rvt",
                                               window.caps, None, links=True)
            read_model.reset_mock()
            window.read("C:\\cache\\x.rvt", None)
            read_model.assert_called_once_with(self.app, self.db, "C:\\cache\\x.rvt",
                                               window.caps, None)

    def cloud_job(self):
        stage = {"items": [{"src": os.path.join(CACHE_ROOT, CACC, CP1, CM3 + ".rvt"),
                            "name": "Alpha-Architecture.rvt", "size": 11, "mtime": CNOW - CDAY}],
                 "notes": []}
        return {"model_path": stage["items"][0]["src"], "model_name": "Alpha-Architecture.rvt",
                "model_key": "cloud:%s/%s" % (CP1, CM3), "index": build_index(CAPS_2022),
                "stage": stage}

    def test_the_hand_over_passes_stage_model_name_and_model_key(self):
        job = self.cloud_job()
        self.queue([job, self.job("b.rvt")])
        self.run_main()
        submit = [r for r in self.handler.requests if r["op"] == "submit"][0]
        self.assertTrue(plain(submit))
        cloud, local = submit["jobs"]
        self.assertEqual(cloud["stage"], job["stage"])
        self.assertEqual(cloud["model_name"], "Alpha-Architecture.rvt")
        self.assertEqual(cloud["model_key"], job["model_key"])
        self.assertEqual(cloud["model_path"], job["model_path"])
        self.assertEqual(sorted(local), ["index", "model_path", "output_parent", "revit_dir"],
                         "a local job is unchanged")

    def test_a_job_with_a_template_carries_it_with_the_system_tokens(self):
        job = dict(self.job("a.rvt"), naming={"template": "{SheetNumber}", "split": True})
        self.queue([job, self.job("b.rvt")])
        with patch.object(self.module, "_windows_dates",
                          Mock(return_value=("18.11.2026", "środa, 18 listopada 2026"))),                 patch.dict(os.environ, {"USERNAME": "tester"}):
            self.run_main()
        submit = [r for r in self.handler.requests if r["op"] == "submit"][0]
        self.assertTrue(plain(submit), "ASCII JSON only")
        named, other = submit["jobs"]
        naming = named["naming"]
        self.assertEqual((naming["template"], naming["split"], naming["values"]),
                         ("{SheetNumber}", True, None))
        self.assertEqual(naming["system"]["ModelName"], "a")
        self.assertEqual(naming["system"]["DateShort"], "18.11.2026")
        self.assertEqual(naming["system"]["WindowsUser"], "tester")
        self.assertEqual(len(naming["system"]["Year"]), 4)
        self.assertNotIn("naming", other, "a job without a template is unchanged")

    def test_the_values_of_a_job_naming_go_to_the_session_and_stay_out_of_a_plain_job(self):
        values = {"uid1": {"kind": "view", "id": "1", "name": "Plan", "tokens": {}, "params": {}}}
        job = dict(self.job("a.rvt"), naming={"templates": {"view": "{ViewName}"}, "split": False,
                                              "values": values})
        request = self.module._job_request(job, "R", "O", system=lambda j: {})
        self.assertEqual(request["naming"]["values"], values)
        plain_job = self.module._job_request(self.job("b.rvt"), "R", "O", system=lambda j: {})
        self.assertNotIn("naming", plain_job)

    def test_read_cloud_forwards_to_the_reader_and_adds_the_catalog_names(self):
        self.run_with_env(LOCALAPPDATA=self.local_appdata())
        window = FakeModelWindow.made[0]
        values = {"u": {"kind": "view", "id": "1", "name": "n", "tokens": {},
                        "params": {"Zone": "A"}}}
        with patch.object(rx_reader, "read_cloud",
                          Mock(return_value={"values": values})) as read_cloud:
            snapshot = window.read_cloud("US", CP1, CM3)
        read_cloud.assert_called_once_with(self.app, self.db, "US", CP1, CM3, window.caps,
                                           values=True, all_worksets=True)
        with patch.object(rx_reader, "read_cloud", Mock(return_value={})) as closed:
            window.read_cloud("US", CP1, CM3, all_worksets=False, values=False)
        closed.assert_called_once_with(self.app, self.db, "US", CP1, CM3, window.caps,
                                       values=False, all_worksets=False)
        self.assertEqual(snapshot["catalog"], {"views": ["Zone"], "sheets": []})

    def test_system_tokens_name_the_model_by_its_real_file_name(self):
        app = types.SimpleNamespace(Username="jan.k")
        cloud = {"model_path": os.path.join("D:\\", "run", "GUID.rvt"), "model_name": "Alpha-Architecture.rvt"}
        local = {"model_path": os.path.join("D:\\", "m", "Office tower.rvt")}
        now = datetime.datetime(2026, 11, 18, 9, 5, 7)
        got = self.module._system_tokens(app, cloud, now=now, environ={"USERNAME": "u"},
                                         dates=lambda: ("d", "D"))
        self.assertEqual((got["ModelName"], got["RevitUser"], got["WindowsUser"]),
                         ("Alpha-Architecture", "jan.k", "u"))
        self.assertEqual((got["Hour"], got["Minute"], got["Second"], got["Date"]),
                         ("09", "05", "07", "2026-11-18"))
        self.assertEqual((got["DateShort"], got["DateLong"]), ("d", "D"))
        again = self.module._system_tokens(types.SimpleNamespace(), local, now=now, environ={},
                                           dates=lambda: ("", ""))
        self.assertEqual((again["ModelName"], again["RevitUser"], again["WindowsUser"]),
                         ("Office tower", "", ""))

    def test_a_cloud_job_request_is_read_back_by_the_session(self):
        import rx_status
        job = self.cloud_job()
        self.queue([job])
        self.run_main()
        submit = [r for r in self.handler.requests if r["op"] == "submit"][0]
        parsed = rx_status._job_from(submit["jobs"][0])
        self.assertEqual(parsed.model_name, "Alpha-Architecture.rvt")
        self.assertEqual(parsed.model_key, job["model_key"])
        self.assertEqual(parsed.stage["items"][0]["src"], job["model_path"])


# ===== 7. Cloud source (specs/SPEC-cloud-catalog.md criteria 10 and 12) ========================
# Synthetic data only: repeated-digit GUIDs and the invented names of test_cloud.py.

import rx_cloud  # noqa: E402
import rx_runner  # noqa: E402
from rx_cloud import CacheFile, Memory, Sighting  # noqa: E402

CP1 = "11111111-1111-1111-1111-111111111111"
CP2 = "22222222-2222-2222-2222-222222222222"
CM3, CM4, CM5, CM6, CM9 = ("%s-%s-%s-%s-%s" % (c * 8, c * 4, c * 4, c * 4, c * 12) for c in "34569")
CACC = "99999999"
CNOW = 1800000000.0
CDAY = 86400.0
GUID_ANYWHERE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                           r"[0-9a-fA-F]{12}")
CACHE_ROOT = os.path.join("C:\\", "cache-root")
CP1_KEY = rx_cloud.project_key(CACC, CP1)
CP2_KEY = rx_cloud.project_key(CACC, CP2)


def cloud_file(project, model, mtime=CNOW - CDAY, size=10, place="root"):
    sub = "LinkedModels" if place == "linked" else ""
    return CacheFile(CACC, project, model, place,
                     os.path.join(CACHE_ROOT, CACC, project, sub, model + ".rvt"), size, mtime)


def cloud_cache_files():
    return [
        cloud_file(CP1, CM3, mtime=CNOW - CDAY, size=11),          # ok
        cloud_file(CP1, CM4, mtime=CNOW - 30 * CDAY, size=12),     # stale
        cloud_file(CP1, CM5),                                      # no name known: counted only
        cloud_file(CP2, CM6, size=13),                             # other project
    ]


def cloud_memory(folder, names=True):
    memory = Memory(os.path.join(folder, "cloud-catalog.json"))
    if names:
        memory.merge([
            Sighting(CP1, "Demo Tower", CM3, "Alpha-Architecture.rvt", "journal"),
            Sighting(CP1, "Demo Tower", CM4, "Beta-MEP.rvt", "journal"),
            Sighting(CP2, "Przykładowy Budynek Ż", CM6, "Zażółć-Konstrukcja.rvt", "journal"),
        ], CNOW)
    return memory


class FakeCloudScan(object):
    """rx_cloud.scan stand-in: a real generator (two steps, then the real Catalog)."""

    def __init__(self, files, steps=2, fail=None):
        self.files = files
        self.steps = steps
        self.fail = fail
        self.calls = []
        self.finished = 0
        self.closed_early = 0
        self.pulled = 0

    def __call__(self, folders, memory, now):
        self.calls.append((folders, memory, now))

        def generate():
            try:
                for unused in range(self.steps):
                    self.pulled += 1
                    yield None
                if self.fail is not None:
                    raise self.fail
                yield rx_cloud.build_catalog(
                    self.files, memory, now, counts={"sightings": 3 if memory.names else 0},
                    message="" if memory.names else rx_cloud._no_journal_message())
                self.finished += 1
            except GeneratorExit:
                self.closed_early += 1
                raise
        return generate()


def displayed_texts(window):
    """Every text the Cloud source shows, for the no-GUID check."""
    found = [window.count_text.Text, window.summary_text.Text, window.status_text.Text,
             window.error_text.Text, window.cloud_message_text.Text]
    for row in window._cloud_rows:
        found += [row.Name, row.Project, row.CacheDate, row.Note, row.Tip, row.SearchText]
    for row in window.cloud_projects_lb.ItemsSource or []:
        found += [row.Label, row.Tip]
    return found


# --- logic: plan_cloud_jobs ---------------------------------------------------------------------

class CloudPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rxexp-cloud-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.memory = cloud_memory(self.tmp)
        self.memory.set_included([CP1_KEY, CP2_KEY])
        self.files = cloud_cache_files()
        self.catalog = rx_cloud.build_catalog(self.files, self.memory, CNOW)
        self.rows = dict((row.name, row) for row in self.catalog.rows)
        self.alpha = self.rows["Alpha-Architecture.rvt"]
        self.beta = self.rows["Beta-MEP.rvt"]
        self.zazolc = self.rows["Zażółć-Konstrukcja.rvt"]

    def link(self, name, project, model):
        return {"name": name, "project_guid": project, "model_guid": model, "region": "US",
                "nested": False}

    def test_a_job_has_the_cache_path_the_real_name_the_key_and_a_stage(self):
        jobs = logic.plan_cloud_jobs([self.alpha], CAPS_2022, self.files, self.memory,
                                     {self.alpha.key: [self.link("Beta-MEP", CP1, CM4)]})
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(sorted(job), ["index", "model_key", "model_name", "model_path", "stage"])
        self.assertEqual(job["model_path"], self.alpha.cache_path)
        self.assertEqual(job["model_name"], "Alpha-Architecture.rvt")
        self.assertEqual(job["model_key"], self.alpha.key)
        self.assertEqual(job["index"], build_index(CAPS_2022))
        items = job["stage"]["items"]
        self.assertEqual([item["name"] for item in items],
                         ["Alpha-Architecture.rvt", "Beta-MEP.rvt"], "host first, .rvt added")
        self.assertEqual(items[0], {"src": self.alpha.cache_path, "name": "Alpha-Architecture.rvt",
                                    "size": 11, "mtime": CNOW - CDAY})
        self.assertEqual(items[1]["src"], self.beta.cache_path)
        self.assertEqual(job["stage"]["notes"], [])
        self.assertTrue(plain(job), "plain values only: the job goes to the session as JSON")
        json.dumps(job)

    def test_the_stage_is_accepted_by_the_runner(self):
        job = logic.plan_cloud_jobs([self.alpha], CAPS_2022, self.files, self.memory,
                                    {self.alpha.key: [self.link("Beta-MEP", CP1, CM4)]})[0]
        runner_job = rx_runner.Job(job["model_path"], job["index"], "C:\\Revit", "D:\\Out",
                                   stage=job["stage"], model_name=job["model_name"],
                                   model_key=job["model_key"])
        checked = rx_runner._checked_stage(runner_job)
        self.assertEqual([item["name"] for item in checked["items"]],
                         ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])

    def test_one_job_per_row_in_order_each_with_its_own_index(self):
        jobs = logic.plan_cloud_jobs([self.zazolc, self.alpha], CAPS_2026, self.files,
                                     self.memory)
        self.assertEqual([job["model_name"] for job in jobs],
                         ["Zażółć-Konstrukcja.rvt", "Alpha-Architecture.rvt"])
        self.assertEqual(jobs[0]["index"], build_index(CAPS_2026))
        self.assertIsNot(jobs[0]["index"], jobs[1]["index"])

    def test_the_link_list_comes_from_the_memory_when_not_given(self):
        self.memory.store_links(logic.link_key(self.alpha), self.alpha.cache_mtime,
                                [self.link("Beta-MEP", CP1, CM4)])
        job = logic.plan_cloud_jobs([self.alpha], CAPS_2022, self.files, self.memory)[0]
        self.assertEqual(len(job["stage"]["items"]), 2)

    def test_a_missing_link_becomes_a_note_and_the_export_goes_on(self):
        job = logic.plan_cloud_jobs([self.alpha], CAPS_2022, self.files, self.memory,
                                    {self.alpha.key: [self.link("Missing-Link", CP1, CM9)]})[0]
        self.assertEqual(len(job["stage"]["items"]), 1)
        self.assertEqual(len(job["stage"]["notes"]), 1)
        self.assertIn("Missing-Link.rvt", job["stage"]["notes"][0])

    def test_host_only_stages_the_host_alone_with_a_note_in_both_languages(self):
        self.memory.store_links(logic.link_key(self.alpha), self.alpha.cache_mtime,
                                [self.link("Beta-MEP", CP1, CM4)])
        args = ([self.alpha], CAPS_2022, self.files, self.memory)
        english = logic.plan_cloud_jobs(*args, host_only={self.alpha.key})[0]
        with InPolish():
            polish_job = logic.plan_cloud_jobs(*args, host_only={self.alpha.key})[0]
        self.assertEqual(len(english["stage"]["items"]), 1)
        self.assertEqual(len(english["stage"]["notes"]), 1)
        self.assertNotEqual(english["stage"]["notes"], polish_job["stage"]["notes"])

    def test_no_job_text_carries_a_guid(self):
        jobs = logic.plan_cloud_jobs(
            [self.alpha], CAPS_2022, self.files, self.memory,
            {self.alpha.key: [self.link("Missing-Link", CP1, CM9), self.link("", CP1, CM5)]})
        job = jobs[0]
        texts = [job["model_name"]] + [item["name"] for item in job["stage"]["items"]] + \
            job["stage"]["notes"]
        for text in texts:
            self.assertIsNone(GUID_ANYWHERE.search(text), text)

    def test_a_greyed_row_no_row_or_a_bad_name_is_refused(self):
        greyed = self.alpha._replace(enabled=False, state="not_selected")
        with self.assertRaises(SetupError):
            logic.plan_cloud_jobs([greyed], CAPS_2022, self.files, self.memory)
        for rows in ([], None):
            with self.assertRaises(SetupError):
                logic.plan_cloud_jobs(rows, CAPS_2022, self.files, self.memory)
        with self.assertRaises(rx_cloud.StageError):
            logic.plan_cloud_jobs([self.alpha._replace(name="a:b.rvt")], CAPS_2022, self.files,
                                  self.memory)

    # -- refresh_stat: the cache files an in-place open rewrote

    def disk_stat(self, changed=None, missing=()):
        sizes = dict((f.path, (f.size, f.mtime)) for f in self.files)
        sizes.update(changed or {})

        def stat(path):
            if path in missing or path not in sizes:
                raise OSError(path)
            return types.SimpleNamespace(st_size=sizes[path][0], st_mtime=sizes[path][1])
        return stat

    def refreshed_job(self, stat):
        links = [self.link("Beta-MEP", CP1, CM4)]
        row, files = rx_cloud.refresh_stat(self.alpha, links, self.files, stat)
        return row, files, logic.plan_cloud_jobs([row], CAPS_2022, files, self.memory,
                                                 {row.key: links})[0]

    def test_refresh_takes_the_new_size_and_time_of_the_host_and_its_links(self):
        stat = self.disk_stat({self.alpha.cache_path: (99, CNOW), self.beta.cache_path: (77, CNOW)})
        row, files, job = self.refreshed_job(stat)
        self.assertEqual((row.size, row.cache_mtime), (99, CNOW))
        items = job["stage"]["items"]
        self.assertEqual([(i["size"], i["mtime"]) for i in items], [(99, CNOW), (77, CNOW)])
        self.assertEqual(job["stage"]["notes"], [])
        self.assertEqual(len(files), len(self.files))

    def test_a_file_that_did_not_change_is_left_as_it_is(self):
        row, files, job = self.refreshed_job(self.disk_stat())
        self.assertEqual(row, self.alpha)
        self.assertEqual(files, self.files)

    def test_a_link_that_cannot_be_stat_ed_is_missing_with_the_usual_note(self):
        row, files, job = self.refreshed_job(self.disk_stat(missing=[self.beta.cache_path]))
        self.assertEqual([i["name"] for i in job["stage"]["items"]], ["Alpha-Architecture.rvt"])
        self.assertEqual(len(job["stage"]["notes"]), 1)
        self.assertIn("Beta-MEP.rvt", job["stage"]["notes"][0])

    def test_a_host_that_cannot_be_stat_ed_keeps_its_scan_time_values(self):
        row, files, job = self.refreshed_job(self.disk_stat(missing=[self.alpha.cache_path]))
        self.assertEqual(row, self.alpha)

    def test_a_file_changed_after_the_plan_is_still_caught_by_the_copy(self):
        import rx_cloud_stage
        stat = self.disk_stat({self.alpha.cache_path: (99, CNOW)})
        row, files, job = self.refreshed_job(stat)
        later = self.disk_stat({self.alpha.cache_path: (100, CNOW + 5)})
        with self.assertRaises(rx_cloud.StageError):
            list(rx_cloud_stage.copy_steps(job["stage"], os.path.join(self.tmp, "run"),
                                           stat=later))

    def test_shared_index_is_copied_and_view_ids_need_one_model(self):
        shared = launcher_default_index()
        jobs = logic.plan_cloud_jobs([self.alpha, self.zazolc], CAPS_2022, self.files,
                                     self.memory, shared_index=shared)
        self.assertEqual([job["index"] for job in jobs], [shared, shared])
        self.assertIsNot(jobs[0]["index"], shared)
        views = with_views("view_ids")
        with self.assertRaises(SetupError):
            logic.plan_cloud_jobs([self.alpha, self.zazolc], CAPS_2022, self.files,
                                  self.memory, shared_index=views)
        one = logic.plan_cloud_jobs([self.alpha], CAPS_2022, self.files, self.memory,
                                    shared_index=views)
        self.assertEqual(one[0]["index"], views)


# --- the Cloud source in the model window -------------------------------------------------------

@unittest.skipIf(EXPORT_UI is None, "rx_export_ui.py not built yet")
class CloudWindowTests(ModelWindowHarness, unittest.TestCase):
    def setUp(self):
        ModelWindowHarness.setUp(self)
        self.memory = cloud_memory(self.tmp)
        self.files = cloud_cache_files()
        self.cscan = FakeCloudScan(self.files)
        self.walks = []
        self.disk = {}          # path -> (size, mtime) a cache file has now (default: as scanned)
        self.unreadable = set()

    def stat(self, path):
        if path in self.unreadable:
            raise OSError(path)
        size, mtime = self.disk.get(path) or [(f.size, f.mtime) for f in self.files
                                              if f.path == path][0]
        return types.SimpleNamespace(st_size=size, st_mtime=mtime)

    def cloud(self, memory=None, scan=None):
        def scan_cache(root):
            self.walks.append(root)
            return list(self.files)
        return {"folders": {"cache": CACHE_ROOT, "journals": os.path.join("C:\\", "journals")},
                "memory": memory or self.memory, "scan": scan or self.cscan,
                "scan_cache": scan_cache, "now": lambda: CNOW, "stat": self.stat}

    def open_cloud(self, included=(CP1_KEY,), switch=True, **kwargs):
        if included:
            self.memory.set_included(included)
        kwargs.setdefault("roots", ())
        window = self.open(rows=[], cloud=self.cloud(), **kwargs)
        if switch:
            self.switch("cloud")
            self.pump()
        return window

    def switch(self, source):
        window = self.window
        window.source_cloud_rb.IsChecked = source == "cloud"
        window.source_local_rb.IsChecked = source == "local"
        control = window.source_cloud_rb if source == "cloud" else window.source_local_rb
        control.Checked.fire(control, None)

    def pump(self, limit=50):
        for unused in range(limit):
            if not TIMERS[-1].IsEnabled:
                return
            self.tick()
        self.fail("the scan never finished")

    def crows(self):
        return list(self.window._cloud_rows)

    def cby(self, name):
        return [row for row in self.crows() if row.Name == name][0]

    def cticked(self):
        return [row.Name for row in self.crows() if row.Checked]

    def cclick(self, row):
        row.Checked = not row.Checked
        list_view = self.window.cloud_lv
        event, handler = list_view.routed[0]
        handler(list_view, Args(source=legacy.Source(row)))

    def projects(self):
        return list(self.window.cloud_projects_lb.ItemsSource or [])

    def pclick(self, label_part):
        row = [p for p in self.projects() if label_part in p.Label][0]
        row.Checked = not row.Checked
        box = self.window.cloud_projects_lb
        event, handler = box.routed[0]
        handler(box, Args(source=legacy.Source(row)))
        return row

    def link(self, name, project, model):
        return {"name": name, "project_guid": project, "model_guid": model, "region": "US",
                "nested": False}

    # -- the source switch

    def test_without_cloud_the_switch_is_hidden_and_nothing_is_scanned(self):
        self.open(rows=[], roots=())
        self.assertEqual(self.window.source_bar.Visibility, "Collapsed")
        self.assertEqual(self.window.cloud_panel.Visibility, "Collapsed")
        self.assertEqual(self.cscan.calls, [])

    def test_the_cloud_source_starts_hidden_and_scans_on_the_first_switch(self):
        self.open_cloud(switch=False)
        self.assertEqual(self.window.source_bar.Visibility, "Visible")
        self.assertTrue(self.window.source_local_rb.IsChecked)
        self.assertEqual(self.window.cloud_panel.Visibility, "Collapsed")
        self.assertEqual(self.window.models_lv.Visibility, "Visible")
        self.assertEqual(self.cscan.calls, [], "a user who never opens Cloud pays nothing")
        self.switch("cloud")
        self.assertEqual(self.window.cloud_panel.Visibility, "Visible")
        self.assertEqual(self.window.models_lv.Visibility, "Collapsed")
        self.assertEqual(len(self.cscan.calls), 1)
        folders, memory, now = self.cscan.calls[0]
        self.assertEqual(folders["cache"], CACHE_ROOT)
        self.assertIs(memory, self.memory)
        self.assertEqual(now, CNOW)
        self.assertTrue(TIMERS[-1].IsEnabled)
        self.switch("local")
        self.switch("cloud")
        self.assertEqual(len(self.cscan.calls), 1, "switching back and forth never rescans")
        self.assertEqual(self.window.models_lv.Visibility, "Collapsed")

    def test_the_cloud_scan_is_time_sliced_one_step_per_tick(self):
        self.open_cloud(step=1.0, switch=False)
        self.switch("cloud")
        self.tick()
        self.assertEqual(self.cscan.pulled, 1)
        self.assertEqual(self.crows(), [])
        self.assertTrue(TIMERS[-1].IsEnabled)
        self.tick()
        self.assertEqual(self.cscan.pulled, 2)
        self.assertEqual(self.crows(), [])
        self.tick()
        self.assertEqual(self.cscan.finished, 1)
        self.assertEqual(len(self.crows()), 3)
        self.assertFalse(TIMERS[-1].IsEnabled, "the timer stops when both scans have ended")

    def test_the_local_and_cloud_scans_share_the_timer(self):
        self.open(rows=sample_rows(), cloud=self.cloud(), step=0.0)
        self.assertTrue(TIMERS[-1].IsEnabled)
        self.switch("cloud")
        self.tick()
        self.assertEqual(self.scan.finished, 1)
        self.assertEqual(self.cscan.finished, 1)
        self.assertFalse(TIMERS[-1].IsEnabled)
        self.assertEqual(len(self.rows()), 5, "the local list is kept")

    # -- rows, projects and states

    def test_rows_show_project_name_cache_date_state_and_note(self):
        self.open_cloud()
        alpha, beta, zazolc = self.cby("Alpha-Architecture.rvt"), self.cby("Beta-MEP.rvt"), \
            self.cby("Zażółć-Konstrukcja.rvt")
        self.assertEqual((alpha.Project, alpha.Name), ("Demo Tower", "Alpha-Architecture.rvt"))
        self.assertRegex(alpha.CacheDate, r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual((alpha.state, alpha.Enabled, alpha.Note), ("ok", True, ""))
        self.assertEqual((beta.state, beta.Enabled), ("stale", True))
        self.assertIn("Cache copy from", beta.Note, "stale: a warning, still enabled")
        self.assertEqual((zazolc.state, zazolc.Enabled), ("not_selected", False))
        self.assertIn("Not in the selected projects", zazolc.Note)
        self.assertIn("Not in the selected projects", zazolc.Tip)
        self.assertIn("Alpha-Architecture.rvt", alpha.Tip)
        self.assertEqual(self.window.cloud_lv.ItemsSource.Count, 2,
                         "a ticked project hides the models of the other projects")

    def test_duplicate_rows_are_disabled(self):
        self.memory.merge([Sighting(CP1, "Demo Tower", CM5, "Alpha-Architecture.rvt", "journal")],
                          CNOW)
        self.files[2] = cloud_file(CP1, CM5, mtime=CNOW - 3 * CDAY)
        self.open_cloud()
        older = [row for row in self.crows() if row.state == "duplicate"]
        self.assertEqual(len(older), 1)
        self.assertFalse(older[0].Enabled)
        self.assertIn("same name", older[0].Note)

    def test_nothing_is_ticked_by_default_and_the_projects_card_lists_each_project(self):
        self.open_cloud(included=())
        self.assertEqual(self.memory.included, set())
        self.assertEqual([row.Checked for row in self.projects()], [False, False])
        labels = [row.Label for row in self.projects()]
        self.assertIn("Demo Tower", labels[0])
        self.assertIn("Przykładowy Budynek Ż", labels[1])
        self.assertEqual([row.state for row in self.crows()], ["not_selected"] * 3)
        self.assertFalse(self.window.export_btn.IsEnabled)

    def test_ticking_a_project_enables_its_rows_and_saves_the_selection(self):
        self.open_cloud(included=())
        row = self.pclick("Demo Tower")
        self.assertTrue(row.Checked)
        self.assertEqual(self.memory.included, {CP1_KEY})
        self.assertEqual(self.walks, [CACHE_ROOT], "the cache is walked once, not per click")
        self.assertEqual([r.state for r in self.crows()], ["ok", "stale", "not_selected"])
        saved = json.loads(Path(self.memory.file_path).read_text(encoding="utf-8"))
        self.assertEqual(saved["included"], [CP1_KEY])
        self.pclick("Przykładowy")
        self.assertEqual(self.memory.included, {CP1_KEY, CP2_KEY})
        self.assertEqual(self.walks, [CACHE_ROOT])
        self.assertEqual(self.window.error_text.Text, "")

    def test_unticking_a_project_greys_its_rows_and_drops_their_ticks(self):
        self.open_cloud()
        self.cclick(self.cby("Alpha-Architecture.rvt"))
        self.assertEqual(self.cticked(), ["Alpha-Architecture.rvt"])
        self.pclick("Demo Tower")
        self.assertEqual(self.memory.included, set())
        self.assertEqual(self.cticked(), [])
        self.assertFalse(self.cby("Alpha-Architecture.rvt").Enabled)

    def test_a_failed_save_of_the_selection_is_shown_not_raised(self):
        self.open_cloud(included=())
        real_save = Memory.save

        def failing_save(memory):
            memory.last_error = "OSError"
            return False
        with patch.object(Memory, "save", failing_save):
            self.pclick("Demo Tower")
        self.assertIn("could not be saved", self.window.error_text.Text)
        self.assertEqual(self.memory.included, {CP1_KEY}, "the selection works for this session")
        self.assertIsNotNone(real_save)

    def test_disabled_rows_cannot_be_ticked_by_click_space_or_select_all(self):
        self.open_cloud()
        self.cclick(self.cby("Zażółć-Konstrukcja.rvt"))
        self.assertEqual(self.cticked(), [])
        list_view = self.window.cloud_lv
        list_view.SelectedItems = self.crows()
        args = Args("Space", legacy.Source(self.crows()[0]))
        list_view.PreviewKeyDown.fire(list_view, args)
        self.assertTrue(args.Handled)
        self.assertEqual(self.cticked(), ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])
        self.fire("none_btn")
        self.assertEqual(self.cticked(), [])
        SharedEventReactive.raised = []
        self.fire("all_btn")
        self.assertEqual(self.cticked(), ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])
        self.assertEqual(SharedEventReactive.raised, [], "no row notifies: one refresh instead")

    def test_search_filters_the_cloud_rows(self):
        self.open_cloud(included=())
        search = legacy.FakeSearchBar.instances[0]
        search.Text = "beta"
        self.assertEqual([row.Name for row in self.window.cloud_lv.ItemsSource],
                         ["Beta-MEP.rvt"])
        search.Text = "przyk"
        self.assertEqual([row.Name for row in self.window.cloud_lv.ItemsSource], [],
                         "the project name is not searched by default")
        self.window.search_folder_cb.IsChecked = True
        self.fire("search_folder_cb")
        self.assertEqual([row.Name for row in self.window.cloud_lv.ItemsSource],
                         ["Zażółć-Konstrukcja.rvt"], "the project name is searchable on request")

    def test_models_of_unticked_projects_are_hidden_once_a_project_is_ticked(self):
        self.open_cloud(included=())
        shown = lambda: [row.Name for row in self.window.cloud_lv.ItemsSource]
        self.assertEqual(len(shown()), 3, "nothing ticked: every model is listed, greyed")
        self.pclick("Demo Tower")
        self.assertEqual(shown(), ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])
        self.pclick("Przykładowy")
        self.assertEqual(len(shown()), 3, "both projects ticked: all models")
        self.pclick("Demo Tower")
        self.assertEqual(shown(), ["Zażółć-Konstrukcja.rvt"])
        self.pclick("Przykładowy")
        self.assertEqual(len(shown()), 3, "no project ticked again: the greyed list returns")

    def test_the_folders_section_belongs_to_local_files_only(self):
        window = self.open_cloud(switch=False)
        self.assertEqual(window.folders_exp.Visibility, "Visible")
        self.assertEqual(window.cloud_header.Visibility, "Collapsed")
        self.switch("cloud")
        self.assertEqual(window.folders_exp.Visibility, "Collapsed")
        self.assertEqual(window.cloud_header.Visibility, "Visible", "the projects card, in its place")
        self.switch("local")
        self.assertEqual(window.folders_exp.Visibility, "Visible")
        self.assertEqual(window.cloud_header.Visibility, "Collapsed")

    def test_counts_and_unnamed_files(self):
        self.open_cloud()
        self.assertIn("Selected: 0 / 3", self.window.count_text.Text)
        self.assertIn("Shown: 2", self.window.count_text.Text,
                      "the other project's model is hidden once a project is ticked")
        self.assertIn("without a name: 1", self.window.count_text.Text)
        demo = [p for p in self.projects() if "Demo Tower" in p.Label][0]
        self.assertIn("Cached models without a name: 1", demo.Tip)

    def test_no_displayed_text_is_or_contains_a_guid(self):
        self.open_cloud()
        self.cclick(self.cby("Alpha-Architecture.rvt"))
        for text in displayed_texts(self.window):
            self.assertIsNone(GUID_ANYWHERE.search(text), text)
        with patch.dict(sys.modules, polish_modules()):
            self.window._refresh_state()
            for text in displayed_texts(self.window):
                self.assertIsNone(GUID_ANYWHERE.search(text), text)

    def test_the_no_journal_message_is_shown_with_the_memory_fallback(self):
        memory = cloud_memory(self.tmp, names=False)
        window = self.open(rows=[], roots=(), cloud=self.cloud(memory=memory))
        self.switch("cloud")
        self.pump()
        self.assertIn("No cloud model names were found", window.cloud_message_text.Text)
        self.assertIn("Remember cloud model", window.cloud_message_text.Text)
        self.assertEqual(self.crows(), [], "unnamed files are never listed")
        self.assertIn("without a name: 4", window.count_text.Text)

    def test_the_message_is_gone_when_names_exist_and_polish_follows_the_language(self):
        self.open_cloud()
        self.assertEqual(self.window.cloud_message_text.Text, "")
        memory = cloud_memory(self.tmp, names=False)
        with patch.dict(sys.modules, polish_modules()):
            window = self.open(rows=[], roots=(), cloud=self.cloud(memory=memory))
            self.switch("cloud")
            self.pump()
            self.assertIn("Zapamiętaj model z chmury", window.cloud_message_text.Text)
            self.assertIn("bez nazwy: 4", window.count_text.Text)
            self.assertEqual(window.Resources["models_source_cloud"], "Chmura (ACC)")

    def test_the_cloud_scan_failing_is_shown_not_raised(self):
        self.cscan = FakeCloudScan(self.files, fail=RuntimeError("boom"))
        self.open_cloud()
        self.assertIn("boom", self.window.error_text.Text)
        self.assertFalse(TIMERS[-1].IsEnabled)
        self.assertEqual(self.crows(), [])

    def test_a_missing_cache_gives_a_plain_status_not_an_error(self):
        self.files = []
        self.cscan = FakeCloudScan(self.files)
        self.open_cloud()
        self.assertEqual(self.crows(), [])
        self.assertEqual(self.window.error_text.Text, "")
        self.assertIn("No cloud models", self.window.status_text.Text)

    # -- rescan and close

    def test_rescan_in_the_cloud_source_rescans_cloud_and_keeps_ticks_by_key(self):
        self.open_cloud()
        self.cclick(self.cby("Beta-MEP.rvt"))
        self.fire("rescan_btn")
        self.assertEqual(len(self.cscan.calls), 2)
        self.pump()
        self.assertEqual(self.cticked(), ["Beta-MEP.rvt"])
        self.assertEqual(self.scan.calls, [], "the local list was not rescanned")

    def test_rescan_closes_the_running_cloud_generator(self):
        self.open_cloud(step=1.0, switch=False)
        self.switch("cloud")
        self.tick()
        self.fire("rescan_btn")
        self.assertEqual(self.cscan.closed_early, 1)
        self.assertEqual(len(self.cscan.calls), 2)

    def test_closing_the_window_closes_the_cloud_generator_and_stops_the_timer(self):
        self.open_cloud(step=1.0, switch=False)
        self.switch("cloud")
        self.tick()
        self.window.Close()
        self.assertEqual(self.cscan.closed_early, 1)
        self.assertFalse(TIMERS[-1].IsEnabled)
        self.tick()
        self.assertEqual(self.cscan.pulled, 1)

    def test_the_local_rescan_leaves_the_cloud_list_alone(self):
        self.open(rows=sample_rows(), cloud=self.cloud())
        self.switch("cloud")
        self.pump()
        self.switch("local")
        self.fire("rescan_btn")
        self.assertEqual(len(self.cscan.calls), 1)
        self.assertEqual(len(self.crows()), 3)

    # -- Export

    def tick_cloud(self, *names):
        for name in names:
            self.cclick(self.cby(name))

    def test_export_opens_the_model_in_place_even_with_stored_links_and_hands_over_a_job(self):
        self.cloud_answer = {"views_2d": [], "views_3d": [],
                             "links": [self.link("Beta-MEP", CP1, CM4),
                                       self.link("Missing-Link", CP1, CM9)]}
        self.open_cloud()
        alpha = self.cby("Alpha-Architecture.rvt")
        self.memory.store_links(logic.link_key(alpha.cloud), alpha.cloud.cache_mtime, [])
        self.tick_cloud("Alpha-Architecture.rvt")
        self.fire("export_btn")
        self.assertEqual(self.reads, [], "the cache file is not read the old way")
        self.assertEqual(len(self.cloud_opens), 1, "the stored links are no shortcut any more")
        opened = self.cloud_opens[0]
        self.assertEqual(opened["args"], (alpha.cloud.region, CP1, CM3))
        self.assertFalse(opened["timer_on"])
        self.assertEqual((opened["cursor"], opened["enabled"]), ("Wait", False))
        self.assertIsNone(MOUSE.OverrideCursor)
        self.assertTrue(self.window.IsEnabled)
        call = self.submitted[0]
        job = call["jobs"][0]
        self.assertEqual(job["model_path"], alpha.cloud.cache_path)
        self.assertEqual(job["model_name"], "Alpha-Architecture.rvt")
        self.assertEqual(job["model_key"], alpha.key)
        self.assertEqual([item["name"] for item in job["stage"]["items"]],
                         ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])
        self.assertEqual(len(job["stage"]["notes"]), 1)
        self.assertIn("Missing-Link.rvt", self.window.error_text.Text, "notes are surfaced")
        self.assertEqual(job["index"], build_index(CAPS_2022))
        self.assertTrue(plain(job))
        self.assertEqual(call["output_parent"], os.path.join("D:\\", "Out"))
        self.assertFalse(self.window.closed)
        self.assertEqual(self.cticked(), [], "queued: the tick is cleared")
        self.assertIn("queued", self.window.status_text.Text)
        stored = self.memory.links_for(logic.link_key(alpha.cloud), alpha.cloud.cache_mtime)
        self.assertEqual([link["name"] for link in stored], ["Beta-MEP", "Missing-Link"])
        # Every Export opens again.
        self.tick_cloud("Alpha-Architecture.rvt")
        self.fire("export_btn")
        self.assertEqual(len(self.cloud_opens), 2)

    def test_two_models_are_opened_one_after_the_other_with_their_status_text(self):
        self.open_cloud()
        self.tick_cloud("Alpha-Architecture.rvt", "Beta-MEP.rvt")
        self.fire("export_btn")
        self.assertEqual([o["args"][2] for o in self.cloud_opens], [CM3, CM4])
        self.assertEqual([o["status"] for o in self.cloud_opens], [
            "Opening Alpha-Architecture.rvt (1 of 2) with all worksets\u2026",
            "Opening Beta-MEP.rvt (2 of 2) with all worksets\u2026"])
        self.assertEqual([job["model_name"] for job in self.submitted[0]["jobs"]],
                         ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])
        self.assertIsNone(MOUSE.OverrideCursor)
        for opened in self.cloud_opens:
            self.assertIsNone(GUID_ANYWHERE.search(opened["status"]))

    def test_the_opening_status_is_polish_in_polish(self):
        with patch.dict(sys.modules, polish_modules()):
            self.open_cloud()
            self.tick_cloud("Alpha-Architecture.rvt")
            self.fire("export_btn")
        self.assertEqual(self.cloud_opens[0]["status"], "Otwieranie Alpha-Architecture.rvt (1 z 1) "
                         "ze wszystkimi zestawami roboczymi\u2026")

    def test_the_closed_worksets_status_is_polish_in_polish(self):
        with patch.dict(sys.modules, polish_modules()):
            self.open_cloud()
            self.tick_cloud("Alpha-Architecture.rvt")
            with patch.object(EXPORT_UI, "ViewWindow", self.views_window([], job=False)):
                self.fire("views_btn")
        self.assertIn("zamkni\u0119te zestawy", self.cloud_opens[0]["status"])
        self.assertIsNone(GUID_ANYWHERE.search(self.cloud_opens[0]["status"]))

    def values_answer(self):
        return {"views_2d": [], "views_3d": [], "links": [],
                "values": {"uid1": {"kind": "view", "id": "1", "name": "Plan", "tokens": {},
                                    "params": {"Zone": "A"}}},
                "catalog": {"views": ["Zone"], "sheets": []}}

    def test_the_values_go_into_the_job_naming_only_with_a_profile(self):
        self.cloud_answer = self.values_answer()
        window = self.names_cloud_window()
        self.tick_cloud("Alpha-Architecture.rvt")
        with patch.object(logic, "NAMED_COPIES_READY", True):
            self.fire("export_btn")
        job = self.submitted[-1]["jobs"][0]
        self.assertEqual(job["naming"]["values"], self.cloud_answer["values"])
        self.assertEqual(len(self.cloud_opens), 1)
        # No profile: the values stay out of the job.
        self.pick(window.name_profile_cb, self.entry(window, "none"))
        self.tick_cloud("Alpha-Architecture.rvt")
        with patch.object(logic, "NAMED_COPIES_READY", True):
            self.fire("export_btn")
        self.assertNotIn("naming", self.submitted[-1]["jobs"][0])

    def names_cloud_window(self):
        """A fresh-install window (file naming on, Default profile) with the cloud list shown."""
        prefs = os.path.join(self.tmp, "RevitExtractor", "preferences.json")
        if os.path.exists(prefs):
            os.remove(prefs)
        self.memory.set_included([CP1_KEY])
        with patch.object(logic, "NAMED_COPIES_READY", True):
            window = self.open(rows=[], roots=(), cloud=self.cloud())
        self.switch("cloud")
        self.pump()
        return window

    def test_the_parameter_names_are_merged_into_the_property_catalog(self):
        import rx_naming_profiles
        path = os.path.join(self.tmp, "RevitExtractor", "property-catalog.json")
        rx_naming_profiles.merge_catalog(path, {"views": ["Old"], "sheets": ["S"]})
        self.cloud_answer = self.values_answer()
        self.open_cloud()
        self.tick_cloud("Alpha-Architecture.rvt")
        self.fire("export_btn")
        self.assertEqual(rx_naming_profiles.read_catalog(path),
                         {"views": ["Old", "Zone"], "sheets": ["S"]})

    def test_a_failed_open_exports_from_the_cache_with_a_note_and_no_values(self):
        self.cloud_error = rx_reader.ReadError("open_failed", "Revit could not open the model.")
        self.cloud_answer = self.values_answer()
        self.names_cloud_window()
        self.tick_cloud("Alpha-Architecture.rvt")
        with patch.object(logic, "NAMED_COPIES_READY", True):
            self.fire("export_btn")
        self.assertEqual(len(self.submitted), 1, "still exported")
        job = self.submitted[0]["jobs"][0]
        self.assertEqual(job["model_path"], self.cby("Alpha-Architecture.rvt").cloud.cache_path)
        notes = job["stage"]["notes"]
        self.assertEqual(len(notes), 1)
        self.assertIn("Revit could not open the model.", notes[0])
        self.assertIn("own names", notes[0])
        self.assertNotIn("naming", job, "a failed open means the Extractor's own names")
        self.assertIn("Revit could not open the model.", self.window.error_text.Text)
        self.assertIsNone(GUID_ANYWHERE.search(notes[0]))
        self.assertEqual(self.cticked(), [])
        self.assertIsNone(MOUSE.OverrideCursor)
        self.assertTrue(self.window.IsEnabled)

    def alpha_and_beta_files(self):
        return (self.cby("Alpha-Architecture.rvt").cloud.cache_path,
                self.cby("Beta-MEP.rvt").cloud.cache_path)

    def test_an_open_that_rewrote_the_cache_files_does_not_fail_the_export(self):
        self.cloud_answer = {"views_2d": [], "views_3d": [], "ifc_setups": [], "ifc_error": "",
                             "links": [self.link("Beta-MEP", CP1, CM4)]}
        self.open_cloud()
        alpha, beta = self.alpha_and_beta_files()
        self.disk = {alpha: (99, CNOW), beta: (77, CNOW)}
        self.tick_cloud("Alpha-Architecture.rvt")
        self.fire("export_btn")
        items = self.submitted[0]["jobs"][0]["stage"]["items"]
        self.assertEqual([(i["size"], i["mtime"]) for i in items], [(99, CNOW), (77, CNOW)])
        self.assertEqual(self.submitted[0]["jobs"][0]["stage"]["notes"], [])

    def test_an_unreadable_link_after_the_open_is_a_missing_link_not_a_crash(self):
        self.cloud_answer = {"views_2d": [], "views_3d": [], "ifc_setups": [], "ifc_error": "",
                             "links": [self.link("Beta-MEP", CP1, CM4)]}
        self.open_cloud()
        self.unreadable = {self.alpha_and_beta_files()[1]}
        self.tick_cloud("Alpha-Architecture.rvt")
        self.fire("export_btn")
        stage = self.submitted[0]["jobs"][0]["stage"]
        self.assertEqual(len(stage["items"]), 1)
        self.assertIn("Beta-MEP.rvt", stage["notes"][0])

    def test_a_failed_open_leaves_the_scan_time_numbers_alone(self):
        self.cloud_error = RuntimeError("boom")
        self.open_cloud()
        alpha = self.cby("Alpha-Architecture.rvt").cloud
        self.disk = {alpha.cache_path: (99, CNOW)}
        self.tick_cloud("Alpha-Architecture.rvt")
        self.fire("export_btn")
        item = self.submitted[0]["jobs"][0]["stage"]["items"][0]
        self.assertEqual((item["size"], item["mtime"]), (alpha.size, alpha.cache_mtime))

    def test_choose_views_plans_from_the_refreshed_files(self):
        self.cloud_answer = {"views_2d": [], "views_3d": [], "ifc_setups": [], "ifc_error": "",
                             "links": [self.link("Beta-MEP", CP1, CM4)]}
        self.open_cloud()
        alpha, beta = self.alpha_and_beta_files()
        self.disk = {alpha: (99, CNOW), beta: (77, CNOW)}
        self.tick_cloud("Alpha-Architecture.rvt")
        with patch.object(EXPORT_UI, "ViewWindow", self.views_window([])):
            self.fire("views_btn")
        items = self.submitted[0]["jobs"][0]["stage"]["items"]
        self.assertEqual([(i["size"], i["mtime"]) for i in items], [(99, CNOW), (77, CNOW)])

    def test_a_successful_open_still_names_with_the_values(self):
        self.cloud_answer = self.values_answer()
        self.names_cloud_window()
        self.tick_cloud("Alpha-Architecture.rvt")
        with patch.object(logic, "NAMED_COPIES_READY", True):
            self.fire("export_btn")
        self.assertEqual(self.submitted[0]["jobs"][0]["naming"]["values"],
                         self.cloud_answer["values"])

    def test_a_failed_open_without_a_profile_says_only_that_it_was_not_opened(self):
        self.cloud_error = RuntimeError("boom")
        self.open_cloud()
        self.tick_cloud("Alpha-Architecture.rvt")
        self.fire("export_btn")
        note = self.submitted[0]["jobs"][0]["stage"]["notes"][0]
        self.assertIn("boom", note)
        self.assertNotIn("own names", note)

    def test_not_signed_in_shows_the_sign_in_text_and_stops_trying_the_other_models(self):
        self.cloud_error = rx_reader.ReadError("not_signed_in", "ignored long text")
        self.open_cloud()
        self.tick_cloud("Alpha-Architecture.rvt", "Beta-MEP.rvt")
        self.fire("export_btn")
        self.assertEqual(len(self.cloud_opens), 1, "the second model is not tried")
        self.assertEqual(len(self.submitted[0]["jobs"]), 2, "both are still exported")
        for job in self.submitted[0]["jobs"]:
            self.assertIn("Sign in to Autodesk in Revit first.", job["stage"]["notes"][0])
        self.assertIn("Sign in to Autodesk in Revit first.", self.window.error_text.Text)

    def test_not_signed_in_text_follows_the_language(self):
        self.cloud_error = rx_reader.ReadError("not_signed_in", "x")
        with patch.dict(sys.modules, polish_modules()):
            self.open_cloud()
            self.tick_cloud("Alpha-Architecture.rvt")
            self.fire("export_btn")
            self.assertIn("Najpierw zaloguj się do Autodesk w Revicie.",
                          self.window.error_text.Text)

    def test_a_local_read_failure_of_the_not_signed_in_kind_is_shown_as_it_is(self):
        self.open()
        self.window._read_failed(rx_reader.ReadError("not_signed_in", "Sign in please."))
        self.assertEqual(self.window.error_text.Text, "Sign in please.")

    def test_one_release_alert_per_run(self):
        self.cloud_answer = {"views_2d": [], "views_3d": [], "links": [],
                             "release_warning": "Relinquish by hand, secret-detail"}
        self.open_cloud()
        self.tick_cloud("Alpha-Architecture.rvt", "Beta-MEP.rvt")
        self.fire("export_btn")
        self.assertEqual(forms_alerts(), 1)
        message = FORMS.alert.call_args[0][0]
        self.assertIn("Relinquish All Mine", message)
        self.assertIn("Nothing was saved", message)
        self.assertNotIn("secret-detail", message)
        self.assertIsNone(GUID_ANYWHERE.search(message))
        self.assertEqual(len(self.submitted[0]["jobs"]), 2, "the export goes on")

    def test_no_alert_without_a_release_warning(self):
        self.open_cloud()
        self.tick_cloud("Alpha-Architecture.rvt")
        self.fire("export_btn")
        self.assertEqual(forms_alerts(), 0)

    def test_the_release_alert_is_polish_in_polish(self):
        self.cloud_answer = {"views_2d": [], "views_3d": [], "links": [], "release_warning": "x"}
        with patch.dict(sys.modules, polish_modules()):
            self.open_cloud()
            self.tick_cloud("Alpha-Architecture.rvt")
            self.fire("export_btn")
        self.assertIn("Nic nie zostało zapisane", FORMS.alert.call_args[0][0])

    def test_close_failed_during_the_open_closes_the_window(self):
        self.cloud_error = rx_reader.ReadError("close_failed", "Revit did not close the model.")
        self.open_cloud()
        self.tick_cloud("Alpha-Architecture.rvt")
        self.fire("export_btn")
        self.assertTrue(self.window.closed)
        self.assertEqual(self.window.fatal_error, "Revit did not close the model.")
        self.assertEqual(self.submitted, [])
        self.assertFalse(TIMERS[-1].IsEnabled)

    def test_a_greyed_cloud_row_is_never_read_or_exported(self):
        self.open_cloud()
        row = self.cby("Zażółć-Konstrukcja.rvt")
        row.set_quietly(True)
        self.window._refresh_state()
        self.fire("export_btn")
        self.fire("views_btn")
        self.assertEqual(self.cloud_opens, [])
        self.assertEqual(self.submitted, [])

    def test_export_queues_only_the_shown_source(self):
        self.open(rows=sample_rows(), cloud=self.cloud(), step=0.0)
        self.tick()
        self.memory.set_included([CP1_KEY])
        self.click(self.by_name("a.rvt"))
        self.switch("cloud")
        self.pump()
        self.tick_cloud("Alpha-Architecture.rvt")
        self.fire("export_btn")
        self.assertEqual([job["model_name"] for job in self.submitted[0]["jobs"]],
                         ["Alpha-Architecture.rvt"])
        self.assertEqual(self.ticked(), ["a.rvt"], "the local tick stays")
        self.switch("local")
        self.fire("export_btn")
        self.assertEqual([job["model_path"] for job in self.submitted[1]["jobs"]],
                         [os.path.join(ROOT_M, "a.rvt")])

    def test_a_shared_index_is_used_for_cloud_rows(self):
        path = os.path.join(self.tmp, "shared.json")
        shared = launcher_default_index()
        Path(path).write_text(json.dumps(shared), encoding="utf-8")
        self.open_cloud(shared=path)
        self.window.shared_scope_rb.IsChecked = True
        self.tick_cloud("Alpha-Architecture.rvt")
        self.fire("export_btn")
        self.assertEqual(self.submitted[0]["jobs"][0]["index"], shared)

    def test_the_summary_counts_stale_copies_and_names_the_scope(self):
        self.open_cloud()
        self.tick_cloud("Alpha-Architecture.rvt", "Beta-MEP.rvt")
        summary = self.window.summary_text.Text
        self.assertIn("Models selected: 2", summary)
        self.assertIn("older cache copies: 1", summary)
        self.assertIn("Extractor default scope", summary)
        self.assertTrue(self.window.export_btn.IsEnabled)
        self.assertFalse(self.window.views_btn.IsEnabled, "views need exactly one model")

    # -- Choose views...

    def views_window(self, made, job_index=None, job=True):
        class ViewStub(object):
            def __init__(inner, snapshot, caps, note="", save_dir=""):
                made.append((snapshot, note))
                inner.job = {"model_path": snapshot["path"],
                             "index": job_index or {"x": 1}} if job else None

            def show_dialog(inner):
                pass
        return ViewStub

    def test_choose_views_opens_once_stores_the_links_and_never_shows_a_guid(self):
        self.cloud_answer = {"title": "", "path": "", "views_2d": [], "views_3d": [],
                             "ifc_setups": [], "ifc_error": "",
                             "links": [self.link("Beta-MEP", CP1, CM4)],
                             "values": {"uid1": {"kind": "view", "id": "1", "name": "Plan",
                                                 "tokens": {}, "params": {}}}}
        made = []
        self.open_cloud()
        alpha = self.cby("Alpha-Architecture.rvt")
        self.tick_cloud("Alpha-Architecture.rvt")
        with patch.object(EXPORT_UI, "ViewWindow", self.views_window(made)):
            self.fire("views_btn")
        self.assertEqual(len(self.cloud_opens), 2, "once to read, once for the export")
        self.assertEqual(self.cloud_opens[0]["args"][1:], (CP1, CM3))
        self.assertEqual([(o["all_worksets"], o["values"]) for o in self.cloud_opens],
                         [(False, False), (True, True)])
        self.assertEqual(self.cloud_opens[0]["status"],
                         "Reading Alpha-Architecture.rvt in the background (worksets closed, "
                         "nothing is saved). This can take a few minutes…")
        self.assertEqual(self.cloud_opens[1]["status"],
                         "Opening Alpha-Architecture.rvt (1 of 1) with all worksets…")
        for opened in self.cloud_opens:
            self.assertIsNone(GUID_ANYWHERE.search(opened["status"]))
        snapshot, note = made[0]
        self.assertEqual(snapshot["title"], "Alpha-Architecture.rvt")
        self.assertIn("Alpha-Architecture.rvt", snapshot["path"])
        for text in (snapshot["title"], snapshot["path"], note):
            self.assertIsNone(GUID_ANYWHERE.search(text), text)
        stored = self.memory.links_for(logic.link_key(alpha.cloud), alpha.cloud.cache_mtime)
        self.assertEqual([link["name"] for link in stored], ["Beta-MEP"])
        job = self.submitted[0]["jobs"][0]
        self.assertEqual(job["index"], {"x": 1}, "the index of the view picker")
        self.assertEqual(job["model_path"], alpha.cloud.cache_path)
        self.assertEqual(job["model_name"], "Alpha-Architecture.rvt")
        self.assertEqual([item["name"] for item in job["stage"]["items"]],
                         ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])
        self.assertFalse(self.window.closed)
        self.assertEqual(self.cticked(), [])

    def test_back_from_the_view_picker_queues_nothing(self):
        made = []
        self.open_cloud()
        self.tick_cloud("Alpha-Architecture.rvt")
        with patch.object(EXPORT_UI, "ViewWindow", self.views_window(made, job=False)):
            self.fire("views_btn")
        self.assertEqual(self.submitted, [])
        self.assertEqual(self.cticked(), ["Alpha-Architecture.rvt"])

    def test_a_failed_views_open_of_a_cloud_row_is_shown(self):
        self.cloud_error = rx_reader.ReadError("open_failed", "Revit could not open the model.")
        self.open_cloud()
        self.tick_cloud("Alpha-Architecture.rvt")
        with patch.object(EXPORT_UI, "ViewWindow", Mock(side_effect=AssertionError("opened"))):
            self.fire("views_btn")
        self.assertIn("Revit could not open the model.", self.window.error_text.Text)
        self.assertEqual(self.submitted, [])
        self.assertIsNone(MOUSE.OverrideCursor)

    def test_a_choose_views_job_keeps_its_views_and_is_opened_again_at_export(self):
        self.cloud_answer = self.values_answer()
        self.submit_error = RuntimeError("session unreachable")
        made = []
        self.open_cloud()
        self.tick_cloud("Alpha-Architecture.rvt")
        with patch.object(EXPORT_UI, "ViewWindow", self.views_window(made, {"views": 1})):
            self.fire("views_btn")
        self.assertIn("session unreachable", self.window.error_text.Text)
        self.assertIn("views are kept", self.window.error_text.Text)
        self.assertEqual(self.cticked(), ["Alpha-Architecture.rvt"])
        self.submit_error = None
        self.fire("export_btn")
        self.assertEqual(len(self.cloud_opens), 3, "read, failed export open, retry open")
        self.assertEqual([o["all_worksets"] for o in self.cloud_opens], [False, True, True])
        retry = self.submitted[-1]["jobs"][0]
        self.assertEqual(retry["index"], {"views": 1})
        self.assertEqual(retry["model_name"], "Alpha-Architecture.rvt")
        self.assertEqual(retry["name_values"], self.cloud_answer["values"])
        self.assertEqual(self.cticked(), [])

    def test_the_cloud_texts_exist_in_both_languages(self):
        text = load_text_module()
        for key in ("models_source", "models_source_local", "models_source_cloud",
                    "cloud_projects_title", "cloud_projects_hint", "cloud_col_project",
                    "cloud_col_date"):
            english, polish_text = text.UI_TEXT[key]
            self.assertTrue(english and polish_text and english != polish_text, key)
            self.assertNotRegex(english + polish_text, r"20\d\d", key)


if __name__ == "__main__":
    unittest.main()
