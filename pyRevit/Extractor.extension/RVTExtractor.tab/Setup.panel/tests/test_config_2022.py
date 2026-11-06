"""Regression coverage for the isolated Revit 2022 bundle."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


BUNDLE = Path(__file__).resolve().parents[1] / "ExportSetup22.pushbutton"


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, BUNDLE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config = load_module("config_2022_under_test", "extractor_config.py")


class Config2022Tests(unittest.TestCase):
    def test_default_and_database_only_preserve_native_branch_semantics(self):
        self.assertEqual(config.build_index()["metadata"]["parameters"], {
            "derivative_type": {"2dviewing": {}, "3dviewing": {},
                                "properties_data": {"pdb": True}}})
        self.assertEqual(config.build_index({"enable_2d": False, "enable_3d": False})
                         ["metadata"]["parameters"]["derivative_type"],
                         {"properties_data": {"pdb": True}})
        with self.assertRaises(config.SetupError):
            config.build_index({"enable_2d": False, "enable_3d": False, "pdb": False})

    def test_selections_are_separate_numeric_int32_arrays(self):
        payload = config.build_index({"scope_2d": "selected", "scope_3d": "selected"},
                                     ["100", "20", 100], ["2147483647"])
        result = json.loads(config.to_json(payload))["metadata"]["parameters"]["derivative_type"]
        self.assertEqual(result["2dviewing"], {"view_ids": [20, 100]})
        self.assertEqual(result["3dviewing"], {"view_ids": [2147483647]})
        self.assertTrue(all(type(value) is int for value in result["2dviewing"]["view_ids"]))

    def test_invalid_ids_and_empty_selections_cannot_broaden_export(self):
        for dimension in ("2d", "3d"):
            for selection in ([], [None], [True], [1.5], ["1.5"], ["view-uid"],
                              [0], [-1], [2147483648], [""], ["²"], ["10", None]):
                with self.subTest(dimension=dimension, selection=selection):
                    args = {"selected_" + dimension: selection}
                    with self.assertRaises(config.SetupError):
                        config.build_index({"scope_" + dimension: "selected"}, **args)

    def test_inactive_selections_are_ignored(self):
        result = config.build_index({"enable_2d": False, "scope_2d": "selected"},
                                    ["stale-uid"], ["stale-uid"])
        derivative = result["metadata"]["parameters"]["derivative_type"]
        self.assertNotIn("2dviewing", derivative)
        self.assertEqual(derivative["3dviewing"], {})

    def test_unsupported_exports_are_rejected_even_with_viewing_enabled(self):
        for options in ({"ifc": True}, {"dwg": True}, {"ifc_setup_name": "Setup"},
                        {"extended_properties": True}, {"topology_metadata": True}):
            with self.subTest(options=options), self.assertRaises(config.SetupError):
                config.build_index(options)

    def test_advanced_options_keep_native_paths(self):
        result = config.build_index({
            "aec_model_data": False, "design_description": False,
            "generate_master_views": True, "f2d": True})["metadata"]["parameters"]["derivative_type"]
        self.assertEqual(result["3dviewing"], {
            "aec_model_data": False, "design_description": False,
            "generate_master_views": True})
        self.assertEqual(result["2dviewing"], {"f2d": True})
        self.assertNotIn("metadata", result)
        result = config.build_index({"enable_3d": False, "pdb": False})["metadata"]["parameters"]["derivative_type"]
        self.assertNotIn("metadata", result)
        self.assertNotIn("3dviewing", result)
        self.assertEqual(result["properties_data"], {"pdb": False})


class Host2022Tests(unittest.TestCase):
    def test_collect_views_uses_integer_value_and_keeps_model_read_only(self):
        class View:
            def __init__(self, eid, kind="FloorPlan", **changes):
                self.Id = types.SimpleNamespace(IntegerValue=eid)
                self.UniqueId = "uid-" + str(eid)
                self.Name = "View " + str(eid)
                self.ViewType = kind
                self.IsTemplate = False
                self.CanBePrinted = True
                self.__dict__.update(changes)

        class Sheet(View):
            SheetNumber = "A-101"
            IsPlaceholder = False

        views = [View(10), View(20, "ThreeD"), Sheet(30, "DrawingSheet"),
                 View(40, IsTemplate=True), View(50, CanBePrinted=False),
                 Sheet(60, "DrawingSheet", IsPlaceholder=True), View(70, "Schedule")]
        collector = Mock()
        collector.OfClass.return_value = views
        db = types.SimpleNamespace(View=View, ViewSheet=Sheet,
                                   FilteredElementCollector=Mock(return_value=collector))
        with patch.dict(sys.modules, {"pyrevit": types.SimpleNamespace(DB=db)}):
            model = load_module("model_2022_under_test", "extractor_model.py")
        doc = types.SimpleNamespace(Title="Test", PathName="", IsModified=True)
        snapshot = model.collect_views(doc)
        self.assertEqual({row["id"] for row in snapshot["views_2d"]}, {"10", "30"})
        self.assertEqual([row["id"] for row in snapshot["views_3d"]], ["20"])
        self.assertIn("a-101", snapshot["views_2d"][0]["search"])
        self.assertTrue(snapshot["modified"])

    def test_entry_point_opens_only_a_revit_2022_project(self):
        for year, family, opened in (("2022", False, True), ("2026", False, False),
                                     ("2022", True, False), (None, False, False)):
            with self.subTest(year=year, family=family):
                doc = (types.SimpleNamespace(Application=types.SimpleNamespace(VersionNumber=year),
                                             IsFamilyDocument=family) if year else None)
                pyrevit = types.SimpleNamespace(forms=Mock(), revit=types.SimpleNamespace(doc=doc),
                                                script=Mock())
                model, ui = Mock(), Mock()
                with patch.dict(sys.modules, {"pyrevit": pyrevit, "extractor_model": model,
                                              "extractor_ui": ui}):
                    command = load_module("command_2022_under_test", "script.py")
                    command.main()
                self.assertEqual(model.collect_views.called, opened)
                self.assertEqual(ui.ExportSetupWindow.return_value.ShowDialog.called, opened)
                self.assertEqual(pyrevit.forms.alert.called, not opened)


if __name__ == "__main__":
    unittest.main()
