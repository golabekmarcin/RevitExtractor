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
import re
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


RevitLinkTypeClass = type(str("RevitLinkType"), (object,), {})
ElementClass = type(str("Element"), (object,), {})


class StrictMap(Strict):
    """A .NET IDictionary as IronPython iterates it (KeyValuePair objects, the shape the legacy
    probe read in the owner's Revit 2022 session). Every member (.Values, .Keys, .get, .Count,
    indexing by key) is a violation."""

    def __init__(self, rec, label, pairs):
        Strict.__init__(self, rec, label)
        object.__setattr__(self, "_pairs", list(pairs))

    def __iter__(self):
        object.__getattribute__(self, "_rec").log(
            "iter " + object.__getattribute__(self, "_label"))
        return iter(object.__getattribute__(self, "_pairs"))


def stub_link(rec, index, name="Structure.rvt", nested=False, references=(), refs_error=None,
              info_error=None, members=None):
    """RevitLinkType stub. `references`: one reference-information dict per external resource.
    Outer pairs answer only Value (the ExternalResourceType key is never needed)."""
    label = "link%d" % index

    def info_map(ref_index, info):
        def get_information(*args):
            if args:
                rec.violate("GetReferenceInformation%r" % (args,))
            if info_error is not None:
                raise info_error
            pairs = [Strict(rec, "%s.info%d.pair" % (label, ref_index),
                            {"Key": key, "Value": value}) for key, value in info.items()]
            return StrictMap(rec, "%s.info%d" % (label, ref_index), pairs)
        return Strict(rec, "%s.reference%d" % (label, ref_index),
                      {"GetReferenceInformation": get_information})

    def get_references(*args):
        if args:
            rec.violate("GetExternalResourceReferences%r" % (args,))
        if refs_error is not None:
            raise refs_error
        pairs = [Strict(rec, "%s.refpair%d" % (label, ref_index),
                        {"Value": info_map(ref_index, info)})
                 for ref_index, info in enumerate(references)]
        return StrictMap(rec, label + ".references", pairs)

    if members is None:
        members = {"Name": name, "IsNestedLink": nested}
    members = dict(members)
    members["GetExternalResourceReferences"] = get_references
    return Strict(rec, label, members)


class NamelessLink(Strict):
    """IronPython often cannot read Name on element types: the property itself raises."""

    @property
    def Name(self):
        object.__getattribute__(self, "_rec").log("nameless.Name")
        raise Exception("Name")


def nameless_link(rec, index, **kwargs):
    template = stub_link(rec, index, **kwargs)
    members = dict(object.__getattribute__(template, "_members"))
    members.pop("Name", None)
    return NamelessLink(rec, "link%d" % index, members)


def clr_stub(test, rec, value="Fallback.rvt", error=None):
    """clr.GetClrType(DB.Element).GetProperty("Name").GetValue(element, None)."""
    def get_value(*args):
        test.assertEqual(len(args), 2)
        test.assertIsInstance(args[0], NamelessLink)
        test.assertIsNone(args[1])
        rec.log("reflection GetValue")
        return value

    def get_property(*args):
        test.assertEqual(args, ("Name",))
        return types.SimpleNamespace(GetValue=get_value)

    def get_clr_type(*args):
        test.assertEqual(args, (ElementClass,))
        if error is not None:
            raise error
        return types.SimpleNamespace(GetProperty=get_property)
    module = types.ModuleType("clr")
    module.GetClrType = get_clr_type
    return {"clr": module}


G1 = "11111111-1111-1111-1111-111111111111"
G2 = "22222222-2222-2222-2222-222222222222"
GA = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
GB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def link_info(model=None, project=None, region=None, **extra):
    info = {}
    if model is not None:
        info["LinkedModelModelId"] = model
    if project is not None:
        info["LinkedModelProjectId"] = project
    if region is not None:
        info["LinkedModelRegion"] = region
    info.update(extra)
    return info


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
                 close_error=None, collect_error=None, storage=None, link_types=None,
                 link_collect_error=None, element_member=False):
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
        # link_types: None = DB has no RevitLinkType member at all (any touch is a violation).
        self.link_types = link_types
        self.link_collect_error = link_collect_error
        if link_types is not None:
            db_members["RevitLinkType"] = RevitLinkTypeClass
        if element_member:
            db_members["Element"] = ElementClass
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
            if self.link_types is not None and cls == (RevitLinkTypeClass,):
                self.rec.log("OfClass(RevitLinkType)")
                if self.link_collect_error is not None:
                    raise self.link_collect_error
                return list(self.link_types)
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
                "OfClass(DataStorage)", "OfClass(RevitLinkType)", "Close(False)")
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


# --------------------------------------------------------------------------- cloud links

def link_calls(host):
    """Every recorded event that touches a link, a link member or the link class."""
    return [call for call in host.rec.calls
            if "link" in repr(call).lower() or "reflection" in repr(call)]


class CollectCloudLinks(unittest.TestCase):
    def collect(self, links, name_of=None, modules=None, **host_kwargs):
        host = Host(self, link_types=links if links is not None else [], **host_kwargs)
        with patch.dict(sys.modules, modules or {}):
            rows = rx_reader.collect_cloud_links(host.doc, host.DB, name_of)
        return rows, host

    def test_rows_from_reference_information_sorted_and_normalised(self):
        host = Host(self, link_types=[])
        rec = host.rec
        host.link_types.extend([
            stub_link(rec, 0, "Structure.rvt", references=[link_info(
                "{" + GA.upper() + "}", GB.upper(), "US", ForgeDmItemUrn="urn:synthetic")]),
            stub_link(rec, 1, "Arch", nested=True, references=[link_info(
                " " + G1 + " ", "{" + G2 + "}", "EMEA")]),
        ])
        rows = rx_reader.collect_cloud_links(host.doc, host.DB)
        self.assertEqual(rows, [
            {"name": "Arch", "project_guid": G2, "model_guid": G1, "region": "EMEA",
             "nested": True},
            {"name": "Structure.rvt", "project_guid": GB, "model_guid": GA, "region": "US",
             "nested": False},
        ])
        self.assertIn("OfClass(RevitLinkType)", host.events())

    def test_only_allowed_members_are_touched(self):
        host = Host(self, link_types=[])
        rec = host.rec
        host.link_types.extend([
            stub_link(rec, 0, references=[link_info(G1, G2, "US"), link_info()]),
            stub_link(rec, 1, refs_error=named_exception("InvalidOperationException")),
        ])
        rx_reader.collect_cloud_links(host.doc, host.DB)
        touched = set()
        for call in rec.calls:
            if isinstance(call, str) and call.startswith("link") and "." in call:
                touched.add(re.sub(r"\d", "", call.split(".", 1)[1]))
        self.assertTrue(touched <= {"Name", "IsNestedLink", "GetExternalResourceReferences",
                                    "refpair.Value", "reference.GetReferenceInformation",
                                    "info.pair.Key", "info.pair.Value"}, touched)
        self.assertEqual(rec.violations, [])

    def test_missing_keys_are_tolerated(self):
        host = Host(self, link_types=[])
        rec = host.rec
        host.link_types.extend([
            stub_link(rec, 0, "A.rvt", references=[link_info()]),
            stub_link(rec, 1, "B.rvt", references=[link_info(model=G1)]),
            stub_link(rec, 2, "C.rvt", references=[link_info(project=G2, region="US")]),
            stub_link(rec, 3, "D.rvt", references=[]),
        ])
        rows = rx_reader.collect_cloud_links(host.doc, host.DB)
        self.assertEqual([(r["name"], r["project_guid"], r["model_guid"], r["region"])
                          for r in rows], [
            ("A.rvt", "", "", ""), ("B.rvt", "", G1, ""), ("C.rvt", G2, "", "US"),
            ("D.rvt", "", "", "")])

    def test_no_external_resource_or_unreadable_information_gives_empty_ids(self):
        host = Host(self, link_types=[])
        rec = host.rec
        host.link_types.extend([
            stub_link(rec, 0, "Local.rvt",
                      refs_error=named_exception("InvalidOperationException", "no resource")),
            stub_link(rec, 1, "Odd.rvt", references=[link_info(G1, G2)],
                      info_error=RuntimeError("copy failed")),
        ])
        rows = rx_reader.collect_cloud_links(host.doc, host.DB)
        self.assertEqual(rows, [
            {"name": "Local.rvt", "project_guid": "", "model_guid": "", "region": "",
             "nested": False},
            {"name": "Odd.rvt", "project_guid": "", "model_guid": "", "region": "",
             "nested": False}])

    def test_first_reference_with_a_model_id_wins(self):
        host = Host(self, link_types=[])
        rec = host.rec
        host.link_types.extend([
            stub_link(rec, 0, "A.rvt", references=[
                link_info(region="US"), link_info(G1, G2, "EMEA"), link_info(GA, GB, "US")]),
        ])
        rows = rx_reader.collect_cloud_links(host.doc, host.DB)
        self.assertEqual((rows[0]["model_guid"], rows[0]["project_guid"], rows[0]["region"]),
                         (G1, G2, "EMEA"))

    def test_values_that_are_not_guids_become_empty(self):
        for bad in ("", "{}", "not-a-guid", G1 + "0", "urn:adsk.wipprod:dm.lineage:x", None):
            with self.subTest(bad=bad):
                host = Host(self, link_types=[])
                info = {"LinkedModelModelId": bad, "LinkedModelProjectId": bad}
                host.link_types.append(stub_link(host.rec, 0, "A.rvt", references=[info]))
                rows = rx_reader.collect_cloud_links(host.doc, host.DB)
                self.assertEqual((rows[0]["model_guid"], rows[0]["project_guid"]), ("", ""))

    def test_name_reflection_fallback(self):
        host = Host(self, link_types=[], element_member=True)
        host.link_types.append(nameless_link(host.rec, 0, references=[link_info(G1, G2)]))
        with patch.dict(sys.modules, clr_stub(self, host.rec)):
            rows = rx_reader.collect_cloud_links(host.doc, host.DB)
        self.assertEqual(rows[0]["name"], "Fallback.rvt")
        self.assertIn("reflection GetValue", host.rec.calls)
        self.assertIn("DB.Element", host.rec.calls)

    def test_unreadable_name_keeps_the_row_with_an_empty_name(self):
        host = Host(self, link_types=[], element_member=True)
        host.link_types.append(nameless_link(host.rec, 0, references=[link_info(G1, G2)]))
        with patch.dict(sys.modules, clr_stub(self, host.rec, error=RuntimeError("no clr"))):
            rows = rx_reader.collect_cloud_links(host.doc, host.DB)
        self.assertEqual(rows, [{"name": "", "project_guid": G2, "model_guid": G1,
                                 "region": "", "nested": False}])

    def test_name_of_argument_replaces_name_reading(self):
        host = Host(self, link_types=[])
        # No Name member at all: reading .Name would be a violation.
        host.link_types.append(stub_link(host.rec, 0, members={"IsNestedLink": False},
                                         references=[link_info(G1, G2)]))
        seen = []

        def name_of(element):
            seen.append(element)
            return "Given.rvt"
        rows = rx_reader.collect_cloud_links(host.doc, host.DB, name_of)
        self.assertEqual(rows[0]["name"], "Given.rvt")
        self.assertIs(seen[0], host.link_types[0])

    def test_nested_is_a_strict_bool(self):
        for value, expected in ((True, True), (False, False), (1, False), ("True", False),
                                (None, False)):
            with self.subTest(value=value):
                host = Host(self, link_types=[])
                host.link_types.append(stub_link(host.rec, 0, nested=value))
                self.assertIs(rx_reader.collect_cloud_links(host.doc, host.DB)[0]["nested"],
                              expected)

    def test_rows_hold_plain_text_and_bool_only(self):
        host = Host(self, link_types=[])
        host.link_types.append(stub_link(host.rec, 0, "Ł ó.rvt", nested=True,
                                         references=[link_info(G1, G2, "US")]))
        rows = rx_reader.collect_cloud_links(host.doc, host.DB)
        self.assertEqual(set(rows[0]), {"name", "project_guid", "model_guid", "region",
                                        "nested"})
        for key, value in rows[0].items():
            self.assertIs(type(value), bool if key == "nested" else str, key)

    def test_no_links(self):
        rows, host = self.collect([])
        self.assertEqual(rows, [])

    def test_collector_error_propagates(self):
        host = Host(self, link_types=[], link_collect_error=RuntimeError("collector broke"))
        with self.assertRaises(RuntimeError):
            rx_reader.collect_cloud_links(host.doc, host.DB)


class ReadModelLinks(unittest.TestCase):
    PATH = "D:\\P\\Host.rvt"

    def host(self, **kwargs):
        host = Host(self, link_types=[], **kwargs)
        host.link_types.append(stub_link(host.rec, 0, "Structure.rvt",
                                         references=[link_info(G1, G2, "US")]))
        return host

    def test_links_true_adds_links_and_closes_once(self):
        host = self.host()
        snapshot = read_model(host.app, host.DB, self.PATH, for_revit(2022), links=True)
        self.assertEqual(snapshot["links"], [{"name": "Structure.rvt", "project_guid": G2,
                                              "model_guid": G1, "region": "US",
                                              "nested": False}])
        self.assertEqual(set(snapshot), {"title", "path", "views_2d", "views_3d",
                                         "ifc_setups", "ifc_error", "links"})
        self.assertEqual(host.events(), ["Documents.IsEmpty", "convert", "open", "collector",
                                         "OfClass(View)", "collector", "OfClass(RevitLinkType)",
                                         "Close(False)"])
        self.assertEqual(host.close_calls, 1)

    def test_links_true_keeps_background_open_rules(self):
        host = self.host()
        read_model(host.app, host.DB, self.PATH, for_revit(2022), links=True)
        sets = [c for c in host.rec.calls if isinstance(c, tuple) and c[0] == "set"]
        self.assertIn(("set", "options.DetachFromCentralOption", "DetachAndPreserveWorksets"),
                      sets)
        self.assertIn(("SetOpenWorksetsConfiguration", "CloseAllWorksets"), host.rec.calls)

    def test_links_false_touches_no_link_member(self):
        for kwargs in ({}, {"links": False}):
            with self.subTest(kwargs=kwargs):
                host = self.host()
                snapshot = read_model(host.app, host.DB, self.PATH, for_revit(2022), **kwargs)
                self.assertNotIn("links", snapshot)
                self.assertEqual(link_calls(host), [])
                self.assertNotIn("DB.RevitLinkType", host.rec.calls)
                self.assertEqual(host.close_calls, 1)

    def test_links_false_without_link_class_in_db(self):
        host = Host(self)  # DB has no RevitLinkType member: any touch is a violation
        snapshot = read_model(host.app, host.DB, self.PATH, for_revit(2022), links=False)
        self.assertNotIn("links", snapshot)

    def test_link_error_still_closes_once_and_first_error_wins(self):
        for close_kwargs in ({}, {"close_result": False}, {"close_error": RuntimeError("c")}):
            with self.subTest(close=close_kwargs):
                error = RuntimeError("link collector broke")
                host = self.host(link_collect_error=error, **close_kwargs)
                with self.assertRaises(RuntimeError) as ctx:
                    read_model(host.app, host.DB, self.PATH, for_revit(2022), links=True)
                self.assertIs(ctx.exception, error)
                self.assertEqual(host.close_calls, 1)
                self.assertEqual(host.events()[-1], "Close(False)")

    def test_links_true_close_failure_is_close_failed(self):
        host = self.host(close_result=False)
        with self.assertRaises(ReadError) as ctx:
            read_model(host.app, host.DB, self.PATH, for_revit(2022), links=True)
        self.assertEqual(ctx.exception.kind, "close_failed")
        self.assertEqual(host.close_calls, 1)

    def test_busy_guard_opens_nothing_with_links(self):
        host = self.host(is_empty=False)
        with self.assertRaises(ReadError) as ctx:
            read_model(host.app, host.DB, self.PATH, for_revit(2022), links=True)
        self.assertEqual(ctx.exception.kind, "busy")
        self.assertEqual(host.events(), ["Documents.IsEmpty"])

    def test_links_snapshot_is_plain_data(self):
        host = self.host()
        snapshot = read_model(host.app, host.DB, self.PATH, for_revit(2022), links=True)

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertIs(type(key), str)
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            else:
                self.assertIn(type(value), (str, bool))
        walk(snapshot)


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

    def test_cloud_links_avoid_file_reference_api(self):
        # ExternalFileUtils.GetExternalFileReference throws for cloud links on 2022 (spec).
        banned = {"ExternalFileUtils", "GetExternalFileReference", "GetLinkedFileStatus",
                  "ExternalResourceType", "Values", "Keys"}
        for node in ast.walk(self.TREE):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, banned)
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, banned)

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
