# -*- coding: utf-8 -*-
"""rx_reader.collect_values / collect_catalog / read_model(values=True) with plain stubs.
Nothing here runs in Revit."""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

LIB = Path(__file__).resolve().parents[3] / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

import rx_reader  # noqa: E402
from rx_capabilities import for_revit  # noqa: E402
from rx_reader import collect_catalog, collect_values  # noqa: E402

NS = types.SimpleNamespace


class Param(object):
    def __init__(self, name, text=None, value_text=None, has_value=True):
        self.Definition = NS(Name=name)
        self.HasValue = has_value
        self._text, self._value_text = text, value_text

    def AsString(self):
        return self._text

    def AsValueString(self):
        return self._value_text

    def AsDouble(self):
        return self._text


class SheetClass(object):
    pass


class Element(object):
    def __init__(self, eid, uid, name, by_id=None, params=(), id_shape="2022", type_id=None,
                 **members):
        self.Id = NS(IntegerValue=eid) if id_shape == "2022" else NS(Value=eid)
        self.UniqueId, self.Name = uid, name
        self._by_id, self.Parameters = by_id or {}, list(params)
        self._type_id = type_id
        self.__dict__.update(members)

    def GetParameter(self, forge_id):
        return self._by_id.get(forge_id)

    def GetTypeId(self):
        return self._type_id


class Sheet(Element, SheetClass):
    pass


class Collector(object):
    def __init__(self, items):
        self.items = items

    def OfCategory(self, category):
        assert category == "OST_TitleBlocks"
        return self

    def WhereElementIsNotElementType(self):
        return list(self.items)


class Fixture(object):
    def __init__(self, elements=None, title_blocks=None):
        self.elements = elements or {}          # ElementId value -> element
        self.title_blocks = title_blocks or {}  # sheet ElementId value -> [element]
        self.doc = NS(GetElement=self._get)
        self.DB = NS(
            ViewSheet=SheetClass,
            ParameterTypeId=NS(**dict((n, "ptid:" + n) for n in (
                "SheetNumber SheetName SheetCurrentRevision SheetCurrentRevisionDate "
                "SheetCurrentRevisionDescription SheetIssueDate SheetDrawnBy SheetCheckedBy "
                "SheetDesignedBy SheetApprovedBy ViewName ViewDescription ViewDetailLevel "
                "ViewDiscipline ViewPhase ViewerSheetNumber SheetWidth SheetHeight").split())),
            BuiltInCategory=NS(OST_TitleBlocks="OST_TitleBlocks"),
            FilteredElementCollector=self._collector)

    def _get(self, element_id):
        return self.elements.get(rx_reader.element_id_value(element_id))

    def _collector(self, doc, sheet_id):
        assert doc is self.doc
        return Collector(self.title_blocks.get(rx_reader.element_id_value(sheet_id), []))


def P(token, text=None, value_text=None):
    return "ptid:" + token, Param(token, text, value_text)


class CollectValues(unittest.TestCase):
    def test_sheet_tokens_and_params(self):
        sheet = Sheet(5, "uid-5", "Plans", SheetNumber="A-101",
                      by_id=dict([P("SheetNumber", "A-101"), P("SheetName", "Plans"),
                                  P("SheetCurrentRevision", "B"), P("SheetDrawnBy", "Zażółć"),
                                  P("SheetIssueDate", "2026-01-02")]),
                      params=[Param("Sheet Number", "A-101"), Param("Nazwa projektu", "Wieża"),
                              Param("Empty", ""), Param("None", None, None),
                              Param("NoValue", "x", has_value=False),
                              Param("Count", None, "7 szt.")])
        fx = Fixture()
        out = collect_values(fx.doc, fx.DB, [sheet])
        self.assertEqual(list(out), ["uid-5"])
        rec = out["uid-5"]
        self.assertEqual((rec["kind"], rec["id"], rec["name"]), ("sheet", "5", "A-101 - Plans"))
        self.assertEqual(rec["tokens"], {
            "SheetNumber": "A-101", "SheetName": "Plans", "CurrentRevision": "B",
            "DrawnBy": "Zażółć", "SheetIssueDate": "2026-01-02", "ElementId": "5"})
        self.assertEqual(rec["params"], {"Sheet Number": "A-101", "Nazwa projektu": "Wieża",
                                         "Count": "7 szt."})

    def test_view_tokens(self):
        template = Element(90, "uid-90", "Plan template")
        family = NS(FamilyName="Floor Plan")
        view = Element(
            11, "uid-11", "Level 1", id_shape="2026", Scale=100,
            ViewTemplateId=NS(Value=90), type_id=NS(Value=70),
            by_id=dict([P("ViewName", "Level 1"), P("ViewDescription", "Parter"),
                        P("ViewDetailLevel", None, "Fine"), P("ViewDiscipline", None, "Arch"),
                        P("ViewPhase", None, "New"), P("ViewerSheetNumber", "A-101")]))
        fx = Fixture({90: template, 70: family})
        rec = collect_values(fx.doc, fx.DB, [view])["uid-11"]
        self.assertEqual((rec["kind"], rec["id"], rec["name"]), ("view", "11", "Level 1"))
        self.assertEqual(rec["tokens"], {
            "ViewName": "Level 1", "TitleOnSheet": "Parter", "DetailLevel": "Fine",
            "Discipline": "Arch", "Phase": "New", "ViewSheetNumber": "A-101", "Scale": "100",
            "ViewTemplate": "Plan template", "ViewFamily": "Floor Plan", "ElementId": "11"})

    def test_view_without_template_and_big_2026_id(self):
        view = Element(2 ** 40, "u", "V", id_shape="2026", Scale=50,
                       ViewTemplateId=NS(IntegerValue=-1, Value=-1), type_id=NS(Value=1))
        fx = Fixture()
        rec = collect_values(fx.doc, fx.DB, [view])["u"]
        self.assertEqual(rec["id"], str(2 ** 40))
        self.assertNotIn("ViewTemplate", rec["tokens"])
        self.assertNotIn("ViewFamily", rec["tokens"])

    def test_cut_to_255_and_blank_omitted(self):
        view = Element(1, "u", "V", Scale=1, ViewTemplateId=NS(IntegerValue=-1),
                       params=[Param("Long", "x" * 300), Param("Blank", "   ")])
        fx = Fixture()
        rec = collect_values(fx.doc, fx.DB, [view])["u"]
        self.assertEqual(rec["params"], {"Long": "x" * 255})

    def test_a_failing_parameter_read_is_skipped(self):
        class Boom(Param):
            def AsString(self):
                raise RuntimeError("x")
        view = Element(1, "u", "V", Scale=1, ViewTemplateId=NS(IntegerValue=-1),
                       params=[Boom("Bad", "x"), Param("Good", "y")])
        fx = Fixture()
        self.assertEqual(collect_values(fx.doc, fx.DB, [view])["u"]["params"], {"Good": "y"})

    def test_sheet_size_iso_and_other(self):
        def block(width_ft, height_ft):
            return Element(1, "t", "T", by_id={
                "ptid:SheetWidth": Param("w", width_ft), "ptid:SheetHeight": Param("h", height_ft)})
        mm = 1 / 304.8
        for blocks, expected in (([block(420 * mm, 297 * mm)], "A3"),
                                 ([block(297 * mm, 420.6 * mm)], "A3"),
                                 ([block(500 * mm, 300 * mm)], "500x300"),
                                 ([], None)):
            sheet = Sheet(5, "s", "S", SheetNumber="1")
            fx = Fixture(title_blocks={5: blocks})
            tokens = collect_values(fx.doc, fx.DB, [sheet])["s"]["tokens"]
            self.assertEqual(tokens.get("SheetSize"), expected)

    def test_sheet_size_falls_back_to_the_title_block_type(self):
        mm = 1 / 304.8
        type_el = Element(7, "ty", "Ty", by_id={
            "ptid:SheetWidth": Param("w", 841 * mm), "ptid:SheetHeight": Param("h", 1189 * mm)})
        tb = Element(1, "t", "T", type_id=NS(IntegerValue=7))
        fx = Fixture({7: type_el}, {5: [tb]})
        sheet = Sheet(5, "s", "S", SheetNumber="1")
        self.assertEqual(collect_values(fx.doc, fx.DB, [sheet])["s"]["tokens"]["SheetSize"], "A0")


class CollectCatalog(unittest.TestCase):
    def test_union_sorted_per_kind(self):
        elements = {
            "a": {"kind": "view", "params": {"Zeta": "1", "Alfa": "2"}},
            "b": {"kind": "view", "params": {"Alfa": "3", "Ł": "4"}},
            "c": {"kind": "sheet", "params": {"Approved": "x"}},
        }
        self.assertEqual(collect_catalog(elements), {
            "views": ["Alfa", "Zeta", "Ł"], "sheets": ["Approved"]})

    def test_cap_2000_and_empty(self):
        elements = {"v": {"kind": "view", "params": dict(("P%05d" % n, "x") for n in range(2500))}}
        out = collect_catalog(elements)
        self.assertEqual(len(out["views"]), 2000)
        self.assertEqual(out["views"][0], "P00000")
        self.assertEqual(collect_catalog({}), {"views": [], "sheets": []})


class ReadModelValues(unittest.TestCase):
    def _host(self):
        from test_reader import Host
        return Host(self, views=[])

    def test_values_in_same_open_before_close(self):
        host = self._host()
        sentinel = {"u": {"kind": "view"}}
        seen = []

        def fake(doc, DB, views):
            seen.append(host.close_calls)
            return sentinel
        with patch.object(rx_reader, "collect_values", fake):
            snap = rx_reader.read_model(host.app, host.DB, "D:\\A.rvt", for_revit(2022),
                                        values=True)
        self.assertEqual(snap["values"], sentinel)
        self.assertEqual(seen, [0])
        self.assertEqual(host.close_calls, 1)
        self.assertEqual(host.events().count("open"), 1)

    def test_not_asked_means_no_values_key_and_no_call(self):
        host = self._host()
        with patch.object(rx_reader, "collect_values", side_effect=AssertionError):
            snap = rx_reader.read_model(host.app, host.DB, "D:\\A.rvt", for_revit(2022))
        self.assertNotIn("values", snap)

    def test_values_error_still_closes_once(self):
        host = self._host()
        with patch.object(rx_reader, "collect_values", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                rx_reader.read_model(host.app, host.DB, "D:\\A.rvt", for_revit(2022), values=True)
        self.assertEqual(host.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
