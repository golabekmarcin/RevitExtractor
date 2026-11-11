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
                         {"rx_export_logic.py", "rx_export_text.py", "rx_export_ui.py", "script.py"})
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
        for path in (MODELS_XAML, VIEWS_XAML):
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
                     "status_text", "caps_text", "output_text", "shared_path_text"):
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
        self.pulled = 0
        self.finished = 0
        self.closed_early = 0

    def __call__(self, roots, running_year, read_info, cache, errors=None):
        self.calls.append((list(roots), running_year, read_info, cache))

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


@unittest.skipIf(EXPORT_UI is None, "rx_export_ui.py not built yet")
class ModelWindowTests(unittest.TestCase):
    def setUp(self):
        reset_fakes()
        self.tmp = tempfile.mkdtemp(prefix="rxexp-ui-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.reads = []
        self.read_answer = None
        self.read_error = None
        self.saved = []
        self.cache = object()
        self.read_info = Mock(name="read_info")

    def read(self, path, workshared):
        self.reads.append((path, workshared, TIMERS[-1].IsEnabled, MOUSE.OverrideCursor,
                           self.window.IsEnabled))
        if self.read_error is not None:
            raise self.read_error
        return self.read_answer

    def open(self, rows=None, roots=(ROOT_M, ROOT_N), step=0.0, shared="", build="2025.3.0.12",
             caps=CAPS_2022, show=True):
        self.scan = FakeScan(sample_rows() if rows is None else rows)
        settings = {"roots": list(roots), "output_parent": os.path.join("D:\\", "Out"),
                    "max_parallel": 1, "shared_index_path": shared}
        self.window = EXPORT_UI.ModelWindow(caps, settings, self.read_info, self.cache, self.read,
                                            self.saved.append, extractor_build=build,
                                            scan=self.scan, clock=StepClock(step))
        if show:
            self.window.show_dialog()
        return self.window

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
        self.assertIsNone(window.jobs)

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
        self.assertTrue(self.window.closed)
        self.assertEqual([job["model_path"] for job in self.window.jobs],
                         [os.path.join(ROOT_M, "b.rvt"), os.path.join(ROOT_N, "e.rvt")])
        for job in self.window.jobs:
            self.assertEqual(job["index"], build_index(CAPS_2022))
        self.assertEqual(self.window.output_parent, os.path.join("D:\\", "Out"))
        self.assertEqual(self.reads, [], "a default-scope export reads no model")
        self.assertIn("1", self.window.summary_text.Text)

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
        self.assertEqual([job["index"] for job in self.window.jobs], [default, default])

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
        self.assertIsNone(self.window.jobs)
        self.assertFalse(self.window.closed)
        self.assertIn("view", self.window.error_text.Text)
        self.click(self.by_name("e.rvt"))
        self.fire("export_btn")
        self.assertEqual(len(self.window.jobs), 1)

    def test_shared_scope_without_a_file_or_a_broken_file_is_refused(self):
        self.open()
        self.tick()
        self.window.default_scope_rb.IsChecked = False
        self.window.shared_scope_rb.IsChecked = True
        self.window._on_scope_changed(None, None)
        self.click(self.by_name("a.rvt"))
        self.fire("export_btn")
        self.assertIsNone(self.window.jobs)
        self.assertTrue(self.window.error_text.Text)
        broken = os.path.join(self.tmp, "broken.json")
        with open(broken, "w") as handle:
            handle.write("{broken")
        FORMS.pick_file.return_value = broken
        self.fire("shared_choose_btn")
        self.assertIn("JSON", self.window.error_text.Text)
        self.assertEqual(self.saved, [], "a broken file is not remembered")

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
        self.assertEqual(self.window.jobs, [{"model_path": os.path.join(ROOT_M, "b.rvt"),
                                             "index": {"x": 1}}])
        self.assertTrue(self.window.closed)
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
        self.assertIsNone(self.window.jobs)
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
        self.assertIsNone(self.window.jobs)
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
        self.assertIsNone(self.window.jobs)
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
        self.assertIsNone(self.window.jobs)

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
    made = []
    jobs = None
    fatal_error = None
    raise_on_show = None

    def __init__(self, caps, settings, read_info, cache, read, save_settings, extractor_build="",
                 scan=None):
        self.caps, self.settings, self.read_info = caps, settings, read_info
        self.cache, self.read, self.save_settings = cache, read, save_settings
        self.extractor_build = extractor_build
        self.scan = scan
        self.output_parent = settings["output_parent"]
        self.shown = 0
        self.stopped = 0
        FakeModelWindow.made.append(self)

    def show_dialog(self):
        self.shown += 1
        if FakeModelWindow.raise_on_show is not None:
            raise FakeModelWindow.raise_on_show
        self.jobs = FakeModelWindow.jobs
        self.fatal_error = FakeModelWindow.fatal_error

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
        FakeModelWindow.made = []
        FakeModelWindow.jobs = None
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
        return {"ApplicationData": self.appdata, "MyDocuments": self.documents}[which]

    def load(self):
        test = self
        special = types.SimpleNamespace(ApplicationData="ApplicationData",
                                        MyDocuments="MyDocuments")

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
            "System.Diagnostics": stub_module("System.Diagnostics", FileVersionInfo=types.SimpleNamespace(
                GetVersionInfo=file_version)),
            "rx_export_ui": stub_module("rx_export_ui", ModelWindow=FakeModelWindow),
            "rx_status_ui": stub_module("rx_status_ui", open_session=self.open_session),
        }
        module = legacy.load("export_script_under_test", "script.py", stubs, BUTTON)
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
                         os.path.join(self.documents, "RevitExtractor"))
        self.assertEqual(window.extractor_build, "2025.3.0.12")
        self.assertEqual(window.cache.file_path,
                         os.path.join(self.appdata, "RevitExtractor", "catalog-cache.json"))
        self.script_stub.get_config.assert_called_with("RevitExtractorExport")
        # The UI module imports no rx_catalog: script.py hands it the scan.
        self.assertIs(window.scan, rx_catalog.scan)
        self.assertEqual(window.shown, 1)
        self.assertEqual(window.stopped, 1, "the scan timer is stopped after the dialog")

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

    # -- hand-over (criterion 9)

    def test_jobs_go_to_the_session_as_json_then_show(self):
        FakeModelWindow.jobs = [self.job("a.rvt"), self.job("b.rvt")]
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
            self.assertEqual(job["output_parent"], os.path.join(self.documents, "RevitExtractor"))
            self.assertEqual(job["index"], build_index(CAPS_2022))
        self.assertEqual(self.alerts, [])

    def test_errors_in_the_answer_are_shown(self):
        FakeModelWindow.jobs = [self.job()]
        self.handler.answer = {"ok": True, "added": [], "errors": ["Export 1: bad path"]}
        self.run_main()
        self.assertEqual(len(self.alerts), 1)
        self.assertIn("Export 1: bad path", self.alerts[0][0])

    def test_a_refused_request_is_shown(self):
        FakeModelWindow.jobs = [self.job()]
        self.handler.answer = {"ok": False, "error": "Nothing to export"}
        self.run_main()
        self.assertIn("Nothing to export", self.alerts[0][0])

    def test_a_broken_answer_is_shown(self):
        FakeModelWindow.jobs = [self.job()]
        self.handler = lambda text: "not json"
        self.run_main()
        self.assertEqual(len(self.alerts), 1)

    def test_nothing_ticked_creates_no_session(self):
        self.run_main()
        self.assertEqual(self.sessions, [])
        self.assertEqual(self.alerts, [])

    def test_close_failed_is_shown_and_nothing_is_queued(self):
        FakeModelWindow.fatal_error = "Revit did not close the model."
        FakeModelWindow.jobs = [self.job()]
        self.run_main()
        self.assertEqual(self.sessions, [])
        self.assertIn("Revit did not close the model.", self.alerts[0][0])

    def test_a_window_error_is_shown_and_the_scan_stopped(self):
        FakeModelWindow.raise_on_show = RuntimeError("xaml broke")
        self.run_main()
        self.assertIn("xaml broke", self.alerts[0][0])
        self.assertEqual(FakeModelWindow.made[0].stopped, 1)
        self.assertEqual(self.sessions, [])


if __name__ == "__main__":
    unittest.main()
