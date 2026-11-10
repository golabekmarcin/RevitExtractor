# -*- coding: utf-8 -*-
"""Tests for lib/rx_reader.py with strict host stubs (CPython; no Revit, no pyRevit).

Every stub (app, doc, DB, views, IFC storage) answers only the members listed in
SPEC-model-reader.md "Revit API members". Anything else is recorded as a violation and raises
StubViolation, a BaseException, so `except Exception` in the module cannot swallow it; tearDown
also fails on any recorded violation. Save, SaveAs, Close(), Close(True) and DB.Transaction are
therefore test failures by construction (proved in StrictStubSelfTests).
"""
import ast
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
LIB = HERE.parents[2] / "lib"
LEGACY = HERE.parent / "ExportSetupLegacy.pushbutton"
# Append, never insert: other tests import same-named bundle modules by bare name.
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))

import rx_reader  # noqa: E402
from rx_capabilities import for_revit  # noqa: E402
from rx_reader import ReadError, collect_views, open_options, read_model  # noqa: E402


def fake_pyrevit_locale(user_codes):
    """Same resolver shape as test_config_legacy.fake_pyrevit_locale."""
    def get_locale_string(string_dict):
        for code in list(user_codes) + ["en_us", "english"]:
            if code in string_dict:
                return string_dict[code]
        return None
    applocales = types.SimpleNamespace(get_locale_string=get_locale_string)
    coreutils = types.SimpleNamespace(applocales=applocales)
    return {"pyrevit": types.SimpleNamespace(coreutils=coreutils),
            "pyrevit.coreutils": coreutils, "pyrevit.coreutils.applocales": applocales}


POLISH = fake_pyrevit_locale(["pl", "polish"])


# --------------------------------------------------------------------------- strict stubs

class StubViolation(BaseException):
    """Not an Exception: `except Exception` in the module under test cannot hide it."""


class Recorder(object):
    def __init__(self):
        self.calls = []
        self.violations = []

    def log(self, event):
        self.calls.append(event)

    def violate(self, what):
        self.violations.append(what)
        raise StubViolation(what)


class Strict(object):
    """Answers only `members`; accepts writes only to `settable`. Everything is logged."""

    def __init__(self, rec, label, members=None, settable=()):
        object.__setattr__(self, "_rec", rec)
        object.__setattr__(self, "_label", label)
        object.__setattr__(self, "_members", dict(members or {}))
        object.__setattr__(self, "_settable", frozenset(settable))
        object.__setattr__(self, "_values", {})

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        rec = object.__getattribute__(self, "_rec")
        label = object.__getattribute__(self, "_label")
        members = object.__getattribute__(self, "_members")
        values = object.__getattribute__(self, "_values")
        if name in values:
            return values[name]
        if name in members:
            rec.log("%s.%s" % (label, name))
            return members[name]
        rec.violate("%s.%s" % (label, name))

    def __setattr__(self, name, value):
        rec = object.__getattribute__(self, "_rec")
        label = object.__getattribute__(self, "_label")
        if name not in object.__getattribute__(self, "_settable"):
            rec.violate("set %s.%s" % (label, name))
        rec.log(("set", "%s.%s" % (label, name), value))
        object.__getattribute__(self, "_values")[name] = value


VIEW_MEMBERS = ("IsTemplate", "CanBePrinted", "ViewType", "Name", "UniqueId", "Id")
SHEET_MEMBERS = VIEW_MEMBERS + ("IsPlaceholder", "SheetNumber")


class StubView(Strict):
    def __init__(self, rec, eid, kind="FloorPlan", name=None, id_shape="2022", **changes):
        element_id = (types.SimpleNamespace(IntegerValue=eid) if id_shape == "2022"
                      else types.SimpleNamespace(Value=eid))
        members = dict(IsTemplate=False, CanBePrinted=True, ViewType=kind,
                       Name=name or ("View %d" % eid), UniqueId="uid-%d" % eid, Id=element_id)
        members.update(changes)
        allowed = SHEET_MEMBERS if isinstance(self, StubSheet) else VIEW_MEMBERS
        members = dict((key, value) for key, value in members.items() if key in allowed)
        Strict.__init__(self, rec, "view%d" % eid, members)


class StubSheet(StubView):
    def __init__(self, rec, eid, kind="DrawingSheet", number="A-101", placeholder=False, **changes):
        changes.setdefault("SheetNumber", number)
        changes.setdefault("IsPlaceholder", placeholder)
        StubView.__init__(self, rec, eid, kind, **changes)


def sample_views(rec):
    return [
        StubView(rec, 10, "FloorPlan", "Level 1"),
        StubView(rec, 11, "Section", "Section B", id_shape="2026"),
        StubView(rec, 12, "Section", "section a"),
        StubView(rec, 20, "ThreeD", "{3D}"),
        StubView(rec, 21, "ThreeD", "Axo", id_shape="2026"),
        StubSheet(rec, 30, number="A-101", Name="Plans"),
        StubSheet(rec, 31, number="", Name="Unnumbered"),
        StubView(rec, 40, IsTemplate=True),
        StubView(rec, 50, CanBePrinted=False),
        StubSheet(rec, 60, placeholder=True),
        StubView(rec, 70, "Schedule"),
        StubView(rec, 80, "Legend", "Legenda ł"),
        StubView(rec, 2 ** 40, "DraftingView", "Big id", id_shape="2026"),
    ]


class Host(object):
    """One strict Revit session: app, DB and the document OpenDocumentFile hands back."""

    def __init__(self, test, views=None, is_empty=True, open_error=None, close_result=True,
                 close_error=None, collect_error=None, storage=None):
        self.rec = rec = Recorder()
        test.addCleanup(self.assert_clean, test)
        self.views = sample_views(rec) if views is None else views
        self.close_result = close_result
        self.close_error = close_error
        self.collect_error = collect_error
        self.open_error = open_error
        self.close_calls = 0
        self.model_path = object()
        self.storage = storage  # IfcStorage or None (= DB has no ExtensibleStorage member)
        self.doc = Strict(rec, "doc", {"Close": self._close})
        self.options = []

        db_members = dict(
            FilteredElementCollector=self._collector,
            View=StubView, ViewSheet=StubSheet,
            OpenOptions=self._open_options,
            DetachFromCentralOption=Strict(rec, "DetachFromCentralOption", {
                "DetachAndPreserveWorksets": "DetachAndPreserveWorksets"}),
            WorksetConfiguration=self._workset_configuration,
            WorksetConfigurationOption=Strict(rec, "WorksetConfigurationOption", {
                "CloseAllWorksets": "CloseAllWorksets"}),
            ModelPathUtils=Strict(rec, "ModelPathUtils", {
                "ConvertUserVisiblePathToModelPath": self._convert}),
        )
        if storage is not None:
            db_members["ExtensibleStorage"] = storage.namespace(rec)
        self.DB = Strict(rec, "DB", db_members)
        self.app = Strict(rec, "app", {
            "Documents": Strict(rec, "Documents", {"IsEmpty": is_empty}),
            "OpenDocumentFile": self._open,
        })

    # -- DB
    def _open_options(self, *args):
        if args:
            self.rec.violate("OpenOptions%r" % (args,))
        options = Strict(self.rec, "options", {
            "SetOpenWorksetsConfiguration": self._set_worksets},
            settable=("DetachFromCentralOption", "Audit", "AllowOpeningLocalByWrongUser"))
        self.options.append(options)
        self.rec.log("OpenOptions()")
        return options

    def _set_worksets(self, *args):
        if len(args) != 1 or not isinstance(args[0], tuple) or args[0][0] != "WorksetConfiguration":
            self.rec.violate("SetOpenWorksetsConfiguration%r" % (args,))
        self.rec.log(("SetOpenWorksetsConfiguration", args[0][1]))

    def _workset_configuration(self, *args):
        if len(args) != 1:
            self.rec.violate("WorksetConfiguration%r" % (args,))
        return ("WorksetConfiguration", args[0])

    def _convert(self, *args):
        if len(args) != 1 or not isinstance(args[0], str):
            self.rec.violate("Convert%r" % (args,))
        self.rec.log(("convert", args[0]))
        return self.model_path

    def _collector(self, *args):
        if len(args) != 1 or args[0] is not self.doc:
            self.rec.violate("FilteredElementCollector%r" % (args,))
        self.rec.log("collector")
        if self.collect_error is not None:
            raise self.collect_error

        def of_class(*cls):
            if cls == (StubView,):
                self.rec.log("OfClass(View)")
                return list(self.views)
            if self.storage is not None and cls == (self.storage.DataStorage,):
                self.rec.log("OfClass(DataStorage)")
                return self.storage.storages(self.rec)
            self.rec.violate("OfClass%r" % (cls,))
        return Strict(self.rec, "collector", {"OfClass": of_class})

    # -- app / doc
    def _open(self, *args, **kwargs):
        if (len(args) != 2 or kwargs or args[0] is not self.model_path
                or not self.options or args[1] is not self.options[-1]):
            self.rec.violate("OpenDocumentFile%r%r" % (args, kwargs))
        self.rec.log("open")
        if self.open_error is not None:
            raise self.open_error
        return self.doc

    def _close(self, *args, **kwargs):
        if kwargs or len(args) != 1 or args[0] is not False:
            self.rec.violate("doc.Close%r%r" % (args, kwargs))
        self.close_calls += 1
        self.rec.log("Close(False)")
        if self.close_error is not None:
            raise self.close_error
        return self.close_result

    # -- checks
    def events(self):
        """Ordered key events (not member reads)."""
        keep = ("Documents.IsEmpty", "convert", "open", "collector", "OfClass(View)",
                "OfClass(DataStorage)", "Close(False)")
        out = []
        for call in self.rec.calls:
            name = call[0] if isinstance(call, tuple) else call
            if name in keep:
                out.append(name)
        return out

    def assert_clean(self, test):
        test.assertEqual(self.rec.violations, [], "strict stub violations")


# --------------------------------------------------------------------------- legacy loader

def load_legacy_model(db):
    """Legacy extractor_model.py by file path, its bare-name siblings pinned from its own bundle."""
    def load(name, filename):
        spec = importlib.util.spec_from_file_location(name, LEGACY / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    with patch.dict(sys.modules, {"pyrevit": types.SimpleNamespace(DB=db)}):
        i18n = load("i18n_legacy_for_reader", "extractor_i18n.py")
        sys.modules["extractor_i18n"] = i18n
        text = load("text_legacy_for_reader", "extractor_text.py")
        sys.modules["extractor_text"] = text
        model = load("model_legacy_for_reader", "extractor_model.py")
    return model, text


# --------------------------------------------------------------------------- tests

class StrictStubSelfTests(unittest.TestCase):
    """The stubs themselves reject what the module must never do."""

    def test_forbidden_calls_raise(self):
        host = Host(self)
        for action in (lambda: host.doc.Save(), lambda: host.doc.SaveAs("x"),
                       lambda: host.doc.Close(), lambda: host.doc.Close(True),
                       lambda: host.doc.Close(0), lambda: host.DB.Transaction(host.doc, "x"),
                       lambda: host.doc.Title, lambda: host.doc.PathName,
                       lambda: host.app.OpenAndActivateDocument("x"),
                       lambda: host.app.OpenDocumentFile("x")):
            with self.assertRaises(StubViolation):
                action()
        self.assertEqual(len(host.rec.violations), 10)
        host.rec.violations[:] = []  # expected here; cleanup asserts the rest stay clean


class ViewKinds(unittest.TestCase):
    def test_equals_legacy_bundle(self):
        unused, text = load_legacy_model(None)
        self.assertEqual(rx_reader.VIEW_KINDS, text.VIEW_KINDS)

    def test_every_kind_has_english_and_polish(self):
        for key, (english, polish) in rx_reader.VIEW_KINDS.items():
            self.assertTrue(english.strip() and polish.strip(), key)
            self.assertNotEqual(english, polish, key)


class CollectViews(unittest.TestCase):
    def legacy_rows(self, host, locale=None):
        db = types.SimpleNamespace(View=StubView, ViewSheet=StubSheet,
                                   FilteredElementCollector=lambda doc: types.SimpleNamespace(
                                       OfClass=lambda cls: list(host.views)))
        model, unused = load_legacy_model(db)
        legacy_doc = types.SimpleNamespace(Title="T", PathName="", IsModified=False)
        with patch.dict(sys.modules, locale or {}):
            snapshot = model.collect_views(legacy_doc)
        return {"views_2d": snapshot["views_2d"], "views_3d": snapshot["views_3d"]}

    def test_same_rows_as_legacy_in_english_and_polish(self):
        for locale in (None, POLISH):
            with self.subTest(polish=bool(locale)):
                host = Host(self)
                expected = self.legacy_rows(host, locale)
                with patch.dict(sys.modules, locale or {}):
                    result = collect_views(host.doc, host.DB)
                self.assertEqual(result, expected)
                self.assertEqual(set(result), {"views_2d", "views_3d"})

    def test_rows_shape_and_filters(self):
        host = Host(self)
        result = collect_views(host.doc, host.DB)
        ids_2d = [row["id"] for row in result["views_2d"]]
        self.assertEqual(sorted(ids_2d), sorted(["10", "11", "12", "30", "31", "80",
                                                 str(2 ** 40)]))
        self.assertEqual([row["id"] for row in result["views_3d"]], ["21", "20"])
        sheet = [row for row in result["views_2d"] if row["id"] == "30"][0]
        self.assertEqual(sheet, {"id": "30", "uid": "uid-30", "name": "A-101 — Plans",
                                 "kind": "Sheets",
                                 "search": "a-101 — plans sheets arkusze 30"})
        unnumbered = [row for row in result["views_2d"] if row["id"] == "31"][0]
        self.assertEqual(unnumbered["name"], "Unnumbered")
        for row in result["views_2d"] + result["views_3d"]:
            self.assertEqual(set(row), {"id", "uid", "name", "kind", "search"})

    def test_polish_kind(self):
        host = Host(self)
        with patch.dict(sys.modules, POLISH):
            result = collect_views(host.doc, host.DB)
        sheet = [row for row in result["views_2d"] if row["id"] == "30"][0]
        self.assertEqual(sheet["kind"], "Arkusze")


class OpenOptionsTests(unittest.TestCase):
    def sets(self, host):
        return [call for call in host.rec.calls if isinstance(call, tuple)]

    def test_workshared_or_unknown_sets_the_four_options(self):
        for workshared in (True, None):
            with self.subTest(workshared=workshared):
                host = Host(self)
                options = open_options(host.DB, workshared)
                self.assertIs(options, host.options[-1])
                self.assertEqual(sorted(self.sets(host), key=repr), sorted([
                    ("set", "options.DetachFromCentralOption", "DetachAndPreserveWorksets"),
                    ("SetOpenWorksetsConfiguration", "CloseAllWorksets"),
                    ("set", "options.Audit", False),
                    ("set", "options.AllowOpeningLocalByWrongUser", True)], key=repr))
                self.assertIs(options.Audit, False)
                self.assertIs(options.AllowOpeningLocalByWrongUser, True)

    def test_unknown_counts_as_workshared(self):
        # Only a real False means "not workshared"; 0, "" and other falsy values do not.
        for workshared in (0, "", [], "False"):
            with self.subTest(workshared=workshared):
                host = Host(self)
                open_options(host.DB, workshared)
                self.assertEqual(len(self.sets(host)), 4)

    def test_not_workshared_sets_nothing(self):
        host = Host(self)
        options = open_options(host.DB, False)
        self.assertIs(options, host.options[-1])
        self.assertEqual(self.sets(host), [])

    def test_default_is_workshared(self):
        host = Host(self)
        open_options(host.DB)
        self.assertEqual(len(self.sets(host)), 4)


class ReadModelHappyPath(unittest.TestCase):
    PATH = "D:\\Projects\\Tower\\Tower_Central.rvt"

    def test_call_order_and_single_close_false(self):
        host = Host(self)
        snapshot = read_model(host.app, host.DB, self.PATH, for_revit(2022))
        self.assertEqual(host.events(), ["Documents.IsEmpty", "convert", "open", "collector",
                                         "OfClass(View)", "Close(False)"])
        self.assertEqual(host.close_calls, 1)
        self.assertIn(("convert", self.PATH), host.rec.calls)

    def test_snapshot_shape_title_and_path_from_argument(self):
        host = Host(self)
        snapshot = read_model(host.app, host.DB, self.PATH, for_revit(2022))
        self.assertEqual(set(snapshot), {"title", "path", "views_2d", "views_3d",
                                         "ifc_setups", "ifc_error"})
        self.assertEqual(snapshot["path"], self.PATH)
        self.assertEqual(snapshot["title"], "Tower_Central.rvt")
        self.assertEqual(snapshot["ifc_setups"], [])
        self.assertEqual(snapshot["ifc_error"], "")
        reference = Host(self)
        expected = collect_views(reference.doc, reference.DB)
        self.assertEqual(snapshot["views_2d"], expected["views_2d"])
        self.assertEqual(snapshot["views_3d"], expected["views_3d"])

    def test_title_from_forward_slash_and_unc_paths(self):
        for path, title in (("//server/share/A.rvt", "A.rvt"),
                            ("\\\\server\\share\\dir\\B.rvt", "B.rvt"),
                            ("C:/x/y/Ł ó.rvt", "Ł ó.rvt")):
            with self.subTest(path=path):
                host = Host(self)
                self.assertEqual(read_model(host.app, host.DB, path, for_revit(2022))["title"],
                                 title)

    def test_snapshot_is_plain_data(self):
        host = Host(self)
        snapshot = read_model(host.app, host.DB, self.PATH, for_revit(2022))

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertIsInstance(key, str)
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            else:
                self.assertIsInstance(value, (str, bool))
        walk(snapshot)

    def test_workshared_flag_reaches_options(self):
        host = Host(self)
        read_model(host.app, host.DB, self.PATH, for_revit(2022), workshared=False)
        self.assertFalse([c for c in host.rec.calls if isinstance(c, tuple) and c[0] == "set"])
        host = Host(self)
        read_model(host.app, host.DB, self.PATH, for_revit(2022))
        self.assertEqual(len([c for c in host.rec.calls
                              if isinstance(c, tuple) and c[0] == "set"]), 3)

    def test_collect_error_still_closes_once_and_is_reported(self):
        error = RuntimeError("collector broke")
        host = Host(self, collect_error=error)
        with self.assertRaises(RuntimeError) as ctx:
            read_model(host.app, host.DB, self.PATH, for_revit(2022))
        self.assertIs(ctx.exception, error)
        self.assertEqual(host.close_calls, 1)
        self.assertEqual(host.events()[-1], "Close(False)")

    def test_first_error_wins_over_close_failure(self):
        for close_kwargs in ({"close_result": False}, {"close_error": RuntimeError("close")}):
            with self.subTest(close=close_kwargs):
                error = RuntimeError("collector broke")
                host = Host(self, collect_error=error, **close_kwargs)
                with self.assertRaises(RuntimeError) as ctx:
                    read_model(host.app, host.DB, self.PATH, for_revit(2022))
                self.assertIs(ctx.exception, error)
                self.assertEqual(host.close_calls, 1)


class Exc(Exception):
    """Base for named stand-ins of Autodesk.Revit.Exceptions types."""


def named_exception(name, message="native text"):
    return type(str(name), (Exc,), {})(message)


class ReadModelGuardsAndErrors(unittest.TestCase):
    PATH = "D:\\P\\Model.rvt"

    def test_busy_when_a_document_is_open(self):
        for is_empty in (False, None, 0, 1, "True"):
            with self.subTest(is_empty=is_empty):
                host = Host(self, is_empty=is_empty)
                with self.assertRaises(ReadError) as ctx:
                    read_model(host.app, host.DB, self.PATH, for_revit(2022))
                self.assertEqual(ctx.exception.kind, "busy")
                self.assertEqual(host.events(), ["Documents.IsEmpty"])
                self.assertEqual(host.close_calls, 0)
                self.assertNotIn("open", host.rec.calls)

    def test_busy_message_bilingual(self):
        host = Host(self, is_empty=False)
        with self.assertRaises(ReadError) as ctx:
            read_model(host.app, host.DB, self.PATH, for_revit(2022))
        english = str(ctx.exception)
        self.assertIn("Close", english)
        host = Host(self, is_empty=False)
        with patch.dict(sys.modules, POLISH), self.assertRaises(ReadError) as ctx:
            read_model(host.app, host.DB, self.PATH, for_revit(2022))
        self.assertIn("Zamknij", str(ctx.exception))
        self.assertNotEqual(str(ctx.exception), english)

    def test_invalid_path_opens_nothing(self):
        for path in ("", "   ", None, 5, b"D:\\x.rvt"):
            with self.subTest(path=path):
                host = Host(self)
                with self.assertRaises(ReadError) as ctx:
                    read_model(host.app, host.DB, path, for_revit(2022))
                self.assertEqual(ctx.exception.kind, "open_failed")
                self.assertEqual(host.events(), ["Documents.IsEmpty"])

    def test_close_false_return_is_close_failed(self):
        host = Host(self, close_result=False)
        with self.assertRaises(ReadError) as ctx:
            read_model(host.app, host.DB, self.PATH, for_revit(2022))
        self.assertEqual(ctx.exception.kind, "close_failed")
        self.assertIn("still be open", str(ctx.exception))
        self.assertEqual(host.close_calls, 1)
        host = Host(self, close_result=False)
        with patch.dict(sys.modules, POLISH), self.assertRaises(ReadError) as ctx:
            read_model(host.app, host.DB, self.PATH, for_revit(2022))
        self.assertIn("nadal otwarty", str(ctx.exception))

    def test_close_exception_is_close_failed(self):
        host = Host(self, close_error=named_exception("InvalidOperationException", "in use"))
        with self.assertRaises(ReadError) as ctx:
            read_model(host.app, host.DB, self.PATH, for_revit(2022))
        self.assertEqual(ctx.exception.kind, "close_failed")
        self.assertIn("in use", str(ctx.exception))
        self.assertEqual(host.close_calls, 1)

    def test_close_returning_non_bool_true_is_close_failed(self):
        # Fail closed: only a real True means the document is gone.
        for result in (None, 1, "True"):
            with self.subTest(result=result):
                host = Host(self, close_result=result)
                with self.assertRaises(ReadError) as ctx:
                    read_model(host.app, host.DB, self.PATH, for_revit(2022))
                self.assertEqual(ctx.exception.kind, "close_failed")

    TABLE = {
        "FileNotFoundException": ("not found", "Nie znaleziono"),
        "CentralModelContentionException": ("busy or", "zajęty lub"),
        "CentralModelAccessDeniedException": ("busy or", "zajęty lub"),
        "CorruptModelException": ("corrupt", "uszkodzony"),
        "ServerModelCorruptedException": ("corrupt", "uszkodzony"),
        "WrongUserException": ("another user", "innego użytkownika"),
        "OperationCanceledException": ("cancelled", "anulowane"),
        "InsufficientResourcesException": ("Not enough", "Za mało"),
    }

    def open_error(self, error, locale=None):
        host = Host(self, open_error=error)
        with patch.dict(sys.modules, locale or {}), self.assertRaises(ReadError) as ctx:
            read_model(host.app, host.DB, self.PATH, for_revit(2022))
        self.assertEqual(ctx.exception.kind, "open_failed")
        self.assertEqual(host.close_calls, 0)
        self.assertEqual(host.events(), ["Documents.IsEmpty", "convert", "open"])
        return str(ctx.exception)

    def test_documented_open_exceptions_by_type_name(self):
        for name, (english, polish) in self.TABLE.items():
            with self.subTest(name=name):
                message = self.open_error(named_exception(name))
                self.assertIn(english, message)
                self.assertIn(polish, self.open_error(named_exception(name), POLISH))

    def test_messages_are_distinct_per_language(self):
        seen_en, seen_pl = set(), set()
        for name in self.TABLE:
            seen_en.add(self.open_error(named_exception(name, "x")))
            seen_pl.add(self.open_error(named_exception(name, "x"), POLISH))
        self.assertFalse(seen_en & seen_pl)

    def test_other_exception_is_generic_with_original_text(self):
        for error in (named_exception("CentralModelException", "native ąę text"),
                      named_exception("FileAccessException", "bad extension"),
                      RuntimeError("boom 42")):
            with self.subTest(error=type(error).__name__):
                original = str(error)
                self.assertIn(original, self.open_error(error))
                polish = self.open_error(error, POLISH)
                self.assertIn(original, polish)
                self.assertIn("nie mógł otworzyć", polish)

    def test_dotnet_wrapped_exception_uses_cls_exception_type_and_message(self):
        # IronPython exposes the .NET exception as .clsException on the Python one.
        net_type = types.SimpleNamespace(Name="WrongUserException")
        native = types.SimpleNamespace(GetType=lambda: net_type, Message="owned by bob")
        error = Exception("wrapper text")
        error.clsException = native
        self.assertIn("another user", self.open_error(error))
        native_generic = types.SimpleNamespace(
            GetType=lambda: types.SimpleNamespace(Name="RevitServerInternalException"),
            Message="server said no")
        error = Exception("wrapper text")
        error.clsException = native_generic
        self.assertIn("server said no", self.open_error(error))

    def test_open_returning_none_is_open_failed(self):
        host = Host(self)
        checked_open = host._open

        def open_none(*args, **kwargs):
            checked_open(*args, **kwargs)
            return None
        object.__getattribute__(host.app, "_members")["OpenDocumentFile"] = open_none
        with self.assertRaises(ReadError) as ctx:
            read_model(host.app, host.DB, self.PATH, for_revit(2022))
        self.assertEqual(ctx.exception.kind, "open_failed")
        self.assertEqual(host.close_calls, 0)

    def test_convert_failure_is_open_failed(self):
        host = Host(self)

        def bad_convert(*args):
            raise named_exception("ArgumentException", "bad path text")
        object.__getattribute__(host.DB.ModelPathUtils, "_members")[
            "ConvertUserVisiblePathToModelPath"] = bad_convert
        with self.assertRaises(ReadError) as ctx:
            read_model(host.app, host.DB, self.PATH, for_revit(2022))
        self.assertEqual(ctx.exception.kind, "open_failed")
        self.assertIn("bad path text", str(ctx.exception))
        self.assertNotIn("open", host.rec.calls)

    def test_read_error_attributes(self):
        error = ReadError("busy", "message text", detail="d")
        self.assertEqual(error.kind, "busy")
        self.assertEqual(error.message, "message text")
        self.assertEqual(error.detail, "d")
        self.assertEqual(str(error), "message text")
        with self.assertRaises(ValueError):
            ReadError("unknown-kind", "x")


# --------------------------------------------------------------------------- IFC setups

LEGACY_SCHEMA = "DCB88B13-594F-44F6-8F5D-AE9477305AC3"
JSON_SCHEMA = "C2A3E6FE-CE51-4F35-8FF1-20C34567B687"


class GenericType(object):
    def __init__(self, name):
        self.name = name

    def __getitem__(self, args):
        return (self.name,) + (args if isinstance(args, tuple) else (args,))


def system_modules():
    system = types.ModuleType("System")
    system.Guid = lambda value: ("Guid", value)
    system.String = "String"
    generic = types.ModuleType("System.Collections.Generic")
    generic.IDictionary = GenericType("IDictionary")
    collections_module = types.ModuleType("System.Collections")
    collections_module.Generic = generic
    system.Collections = collections_module
    return {"System": system, "System.Collections": collections_module,
            "System.Collections.Generic": generic}


class IfcStorage(object):
    """Stub DataStorage elements carrying the modern JSON and/or the legacy map entity."""

    DataStorage = type(str("DataStorage"), (object,), {})

    def __init__(self, test, records, legacy_schema=True, modern_schema=True, get_error=None):
        self.test = test
        self.records = records  # list of (json_text or None, legacy dict or None)
        self.legacy_schema = legacy_schema
        self.modern_schema = modern_schema
        self.get_error = get_error

    def namespace(self, rec):
        def lookup(*args):
            self.test.assertEqual(len(args), 1)
            kind, value = args[0]
            self.test.assertEqual(kind, "Guid")
            rec.log(("Lookup", value))
            if value == LEGACY_SCHEMA:
                return "legacy-schema" if self.legacy_schema else None
            if value == JSON_SCHEMA:
                return "modern-schema" if self.modern_schema else None
            rec.violate("Schema.Lookup(%r)" % (value,))
        schema = Strict(rec, "Schema", {"Lookup": lookup})
        return Strict(rec, "ExtensibleStorage", {"Schema": schema, "DataStorage": self.DataStorage})

    def storages(self, rec):
        out = []
        for index, (raw, legacy) in enumerate(self.records):
            out.append(self._storage(rec, index, raw, legacy))
        return out

    def _storage(self, rec, index, raw, legacy):
        test = self.test
        get_error = self.get_error

        def entity(payload, expected_type):
            class Getter(object):
                def __getitem__(self, type_arg):
                    test.assertEqual(type_arg, expected_type)

                    def get(*args):
                        test.assertEqual(args, ("MapField",))
                        if get_error is not None:
                            raise get_error
                        rec.log(("Get", expected_type))
                        return payload
                    return get
            return Strict(rec, "entity", {"IsValid": lambda: payload is not None,
                                          "Get": Getter()})

        def get_entity(*args):
            test.assertEqual(len(args), 1)
            if args[0] == "modern-schema":
                return entity(raw, "String")
            if args[0] == "legacy-schema":
                pairs = None if legacy is None else [
                    types.SimpleNamespace(Key=k, Value=v) for k, v in legacy.items()]
                return entity(pairs, ("IDictionary", "String", "String"))
            rec.violate("GetEntity(%r)" % (args,))
        return Strict(rec, "storage%d" % index, {"GetEntity": get_entity})


def json_text(name, **extra):
    import json
    data = dict(Name=name, IFCVersion=29)
    data.update(extra)
    return json.dumps(data, ensure_ascii=False)


class IfcSetups(unittest.TestCase):
    PATH = "D:\\P\\Model.rvt"

    def read(self, records, caps=None, locale=None, **storage_kwargs):
        storage = IfcStorage(self, records, **storage_kwargs)
        host = Host(self, storage=storage)
        with patch.dict(sys.modules, system_modules()), patch.dict(sys.modules, locale or {}):
            snapshot = read_model(host.app, host.DB, self.PATH, caps or for_revit(2026))
        self.assertEqual(host.close_calls, 1)
        self.assertEqual(len(snapshot["views_2d"]), 7)  # views survive any IFC outcome
        return snapshot, host

    def test_names_sorted_with_ready(self):
        snapshot, host = self.read([
            (json_text("zeta"), None),                             # JSON only: not ready
            (json_text("Alpha"), {"Name": "Alpha", "Version": "IFC4RV"}),  # both: one record
            (None, {"Name": "beta", "Extra": "keep"}),             # legacy only
        ])
        self.assertEqual(snapshot["ifc_error"], "")
        self.assertEqual(snapshot["ifc_setups"], [
            {"name": "Alpha", "ready": True},
            {"name": "beta", "ready": True},
            {"name": "zeta", "ready": False}])
        self.assertEqual(host.events(), ["Documents.IsEmpty", "convert", "open", "collector",
                                         "OfClass(View)", "collector", "OfClass(DataStorage)",
                                         "Close(False)"])

    def test_json_and_map_on_same_storage_read_as_one_record(self):
        snapshot, unused = self.read([(json_text("PiKej"), {"Name": "PiKej"})])
        self.assertEqual(snapshot["ifc_setups"], [{"name": "PiKej", "ready": True}])

    def test_json_only_is_listed_not_ready(self):
        snapshot, unused = self.read([(json_text("PiKej"), None)])
        self.assertEqual(snapshot["ifc_setups"], [{"name": "PiKej", "ready": False}])

    def test_no_schemas_registered(self):
        snapshot, host = self.read([(json_text("x"), None)], legacy_schema=False,
                                   modern_schema=False)
        self.assertEqual(snapshot["ifc_setups"], [])
        self.assertEqual(snapshot["ifc_error"], "")

    def test_only_legacy_schema_registered(self):
        snapshot, unused = self.read([(json_text("x"), {"Name": "Old"})], modern_schema=False)
        self.assertEqual(snapshot["ifc_setups"], [{"name": "Old", "ready": True}])

    def test_inconsistent_storage_is_reported_and_lists_nothing(self):
        cases = (
            [(None, {"Name": "Dup"}), (None, {"Name": "Dup"})],          # two legacy, same name
            [(json_text("One"), {"Name": "Other"})],                     # mismatching names
            [(None, {"Version": "IFC4RV"})],                             # legacy without a name
            [(None, {"Name": "IFC4 Reference View"})],                   # reserved built-in name
            [(None, {"Name": "IFC 2x3 Coordination View 2.0"})],
            [("not json", None)],                                         # invalid JSON
            [('["list"]', None)],                                         # JSON that is no dict
            [(json_text(""), None)],                                      # JSON without a name
        )
        for records in cases:
            with self.subTest(records=records):
                snapshot, unused = self.read(records)
                self.assertEqual(snapshot["ifc_setups"], [])
                self.assertTrue(snapshot["ifc_error"])
                with_pl, unused = self.read(records, locale=POLISH)
                self.assertTrue(with_pl["ifc_error"])
                self.assertNotEqual(with_pl["ifc_error"], snapshot["ifc_error"])

    def test_unexpected_host_error_is_contained(self):
        snapshot, host = self.read([(json_text("a"), None)],
                                   get_error=named_exception("ArgumentException", "type clash"))
        self.assertEqual(snapshot["ifc_setups"], [])
        self.assertIn("type clash", snapshot["ifc_error"])

    def test_disabled_touches_no_storage_member(self):
        # DB has no ExtensibleStorage member and System is not importable: any touch fails.
        host = Host(self, storage=None)
        with patch.dict(sys.modules, {"System": None}):
            snapshot = read_model(host.app, host.DB, self.PATH, for_revit(2022))
        self.assertEqual(snapshot["ifc_setups"], [])
        self.assertEqual(snapshot["ifc_error"], "")
        self.assertFalse([c for c in host.rec.calls if "ExtensibleStorage" in repr(c)])

    def test_direct_port_matches_storage_reading_cases(self):
        # Mirrors test_ifc_storage.ReadRecordsTests against the port (names and ready only).
        storage = IfcStorage(self, [(None, {"Name": "Old", "Version": "IFC4RV",
                                            "Extra": "preserve"})])
        host = Host(self, storage=storage)
        with patch.dict(sys.modules, system_modules()):
            self.assertEqual(rx_reader._ifc_setups(host.doc, host.DB),
                             [{"name": "Old", "ready": True}])
            storage.records = [(None, {"Name": "Dup"}), (None, {"Name": "Dup"})]
            with self.assertRaises(rx_reader.IfcSetupError):
                rx_reader._ifc_setups(host.doc, host.DB)


# --------------------------------------------------------------------------- source rules

class SourceRules(unittest.TestCase):
    SOURCE = (LIB / "rx_reader.py").read_text(encoding="utf-8")
    TREE = ast.parse(SOURCE)

    def test_no_module_level_host_imports(self):
        banned = {"pyrevit", "Autodesk", "System", "clr"}

        def top_level(nodes):
            for node in nodes:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                    continue
                yield node
                for child in ast.iter_child_nodes(node):
                    for item in top_level([child]):
                        yield item
        for node in top_level(self.TREE.body):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                self.assertNotIn(name.split(".")[0], banned, name)

    def test_header_and_future_import(self):
        self.assertTrue(self.SOURCE.startswith("# -*- coding: utf-8 -*-\n"))
        self.assertIn("from __future__ import unicode_literals", self.SOURCE)

    def test_ironpython_syntax_subset(self):
        for node in ast.walk(self.TREE):
            self.assertNotIsInstance(node, (ast.JoinedStr, ast.AnnAssign, ast.AsyncFunctionDef,
                                            ast.Await, ast.YieldFrom, ast.NamedExpr,
                                            ast.Nonlocal), ast.dump(node)[:80])
            if isinstance(node, ast.arguments):
                self.assertFalse(node.kwonlyargs)
                self.assertFalse(getattr(node, "posonlyargs", []))
                for arg in node.args:
                    self.assertIsNone(arg.annotation)
            if isinstance(node, ast.FunctionDef):
                self.assertIsNone(node.returns)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                         else [node.module or ""])
                for name in names:
                    self.assertNotIn(name.split(".")[0], {"pathlib", "typing", "enum"}, name)

    def test_uses_shared_element_id_value(self):
        self.assertIn("from rx_capabilities import element_id_value", self.SOURCE)
        defined = [node.name for node in ast.walk(self.TREE) if isinstance(node, ast.FunctionDef)]
        self.assertNotIn("element_id_value", defined)

    def test_close_only_once_with_literal_false_and_no_write_members(self):
        forbidden = {"Save", "SaveAs", "Transaction", "SubTransaction", "TransactionGroup",
                     "OpenAndActivateDocument", "SynchronizeWithCentral", "SetEntity",
                     "DeleteEntity", "Delete"}
        closes = 0
        for node in ast.walk(self.TREE):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, forbidden)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Close"):
                closes += 1
                self.assertEqual(len(node.args), 1)
                self.assertFalse(node.keywords)
                self.assertIsInstance(node.args[0], ast.Constant)
                self.assertIs(node.args[0].value, False)
        self.assertEqual(closes, 1)


if __name__ == "__main__":
    unittest.main()
