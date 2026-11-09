"""Regression coverage for the isolated ExportSetupLegacy bundle (Revit 2022-2025)."""
import importlib.util
import json
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import Mock, patch


BUNDLE = Path(__file__).resolve().parents[1] / "ExportSetupLegacy.pushbutton"
# The bundle imports extractor_i18n by bare name, as pyRevit does. Append, never prepend:
# the 2026 bundle's tests import same-named modules (extractor_config) by bare name.
sys.path.append(str(BUNDLE))
import extractor_i18n as i18n  # noqa: E402  (needs the path above)


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, BUNDLE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config = load_module("config_legacy_under_test", "extractor_config.py")


def fake_pyrevit_locale(user_codes, get_locale_string=None):
    """Mirrors pyrevit.coreutils.applocales.get_locale_string: the user's locale codes,
    then English (DEFAULT_LOCALE) codes, first key present in the dict wins."""
    def default_get_locale_string(string_dict):
        for code in list(user_codes) + ["en_us", "english"]:
            if code in string_dict:
                return string_dict[code]
        return None
    applocales = types.SimpleNamespace(
        get_locale_string=get_locale_string or default_get_locale_string)
    coreutils = types.SimpleNamespace(applocales=applocales)
    return {"pyrevit": types.SimpleNamespace(coreutils=coreutils),
            "pyrevit.coreutils": coreutils, "pyrevit.coreutils.applocales": applocales}


class LanguageTests(unittest.TestCase):
    def test_english_is_default_without_pyrevit(self):
        self.assertEqual(i18n.tr("Save", "Zapisz"), "Save")

    def test_same_resolution_as_bundle_yaml_maps(self):
        for codes, expected in ((["pl", "polish"], "Zapisz"), (["en_us", "english"], "Save"),
                                (["de_de"], "Save"), ([], "Save")):
            with self.subTest(codes=codes), patch.dict(sys.modules, fake_pyrevit_locale(codes)):
                self.assertEqual(i18n.tr("Save", "Zapisz"), expected)

    def test_pyrevit_failure_or_empty_result_falls_back_to_english(self):
        def broken(string_dict):
            raise AttributeError("no applocale for ''")
        for resolver in (broken, lambda string_dict: None, lambda string_dict: ""):
            with self.subTest(resolver=resolver), \
                    patch.dict(sys.modules, fake_pyrevit_locale(["pl"], resolver)):
                self.assertEqual(i18n.tr("Save", "Zapisz"), "Save")

    def test_config_errors_follow_language(self):
        with self.assertRaisesRegex(config.SetupError, "^Enable 2D views"):
            config.build_index({"enable_2d": False, "enable_3d": False, "pdb": False})
        with patch.dict(sys.modules, fake_pyrevit_locale(["pl"])):
            with self.assertRaisesRegex(config.SetupError, "^Włącz widoki 2D"):
                config.build_index({"enable_2d": False, "enable_3d": False, "pdb": False})


class LegacyConfigTests(unittest.TestCase):
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

    def test_selection_must_be_a_list_and_scope_must_be_known(self):
        # A string would be iterated per character: "123" -> view_ids [1, 2, 3].
        for selection in ("123", 123, None, {"1": 1}, b"12"):
            with self.subTest(selection=selection), self.assertRaises(config.SetupError):
                config.build_index({"scope_2d": "selected"}, selection, [])
        for scope in (None, 1, "everything"):
            with self.subTest(scope=scope), self.assertRaises(config.SetupError):
                config.build_index({"scope_2d": scope})
        # Tuples are fine.
        self.assertEqual(config.build_index({"scope_3d": "selected"}, [], ("5",))
                         ["metadata"]["parameters"]["derivative_type"]["3dviewing"], {"view_ids": [5]})

    def test_database_warning_only_when_older_parsers_cannot_honour_it(self):
        self.assertTrue(config.database_warning({"enable_3d": False, "pdb": False}))
        for settings in ({}, {"pdb": False}, {"enable_3d": False}, None):
            with self.subTest(settings=settings):
                self.assertEqual(config.database_warning(settings), "")

    def test_tick_applies_to_whole_selection_only_when_row_is_part_of_it(self):
        a, b, c = object(), object(), object()
        self.assertEqual(config.tick_targets([a, b], a), [a, b])
        self.assertEqual(config.tick_targets([a, b], c), [c])      # outside the selection
        self.assertEqual(config.tick_targets([a], a), [a])         # single selection
        self.assertEqual(config.tick_targets([], a), [a])

    def test_space_ticks_all_unless_all_already_ticked(self):
        self.assertTrue(config.toggled_state([False, True]))
        self.assertTrue(config.toggled_state([False]))
        self.assertFalse(config.toggled_state([True, True]))

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

    def test_disabled_database_is_written_for_both_parser_shapes(self):
        # Extractor 2024.0.x reads 3dviewing.db_export (default true); 2025.3+ reads properties_data.pdb.
        derivative = config.build_index({"pdb": False})["metadata"]["parameters"]["derivative_type"]
        self.assertEqual(derivative["properties_data"], {"pdb": False})
        self.assertEqual(derivative["3dviewing"], {"db_export": False})
        # Enabled database keeps the index identical to the one verified on Revit 2022.
        derivative = config.build_index()["metadata"]["parameters"]["derivative_type"]
        self.assertEqual(derivative["3dviewing"], {})
        # Without 3D the older key cannot be written without enabling 3D viewing.
        derivative = config.build_index({"enable_3d": False, "pdb": False})["metadata"]["parameters"]["derivative_type"]
        self.assertNotIn("3dviewing", derivative)


class WindowTextTests(unittest.TestCase):
    """ui.xaml takes every static label from extractor_text.UI_TEXT via {DynamicResource key}."""
    XAML = (BUNDLE / "ui.xaml").read_text(encoding="utf-8")
    # Attribute values that are the same in every language.
    LANGUAGE_NEUTRAL = {"✓", "ElementId"}

    def setUp(self):
        self.text = load_module("text_legacy_under_test", "extractor_text.py")

    def test_xaml_keys_and_text_table_match_both_ways(self):
        # Rx* keys are the theme (rx_theme.xaml, checked in test_window_legacy.py).
        used = set(key for key in re.findall(r"\{DynamicResource (\w+)\}", self.XAML)
                   if not key.startswith("Rx"))
        self.assertEqual(used, set(self.text.UI_TEXT))
        self.assertFalse([key for key in self.text.UI_TEXT if key.startswith("Rx")])

    def test_no_hard_coded_label_left_in_xaml(self):
        attributes = re.findall(r'\b(Title|Text|Content|Header|ToolTip)="([^"]*)"', self.XAML)
        literals = {value for name, value in attributes
                    if value and not value.startswith("{")}
        self.assertEqual(literals - self.LANGUAGE_NEUTRAL, set())

    def test_every_entry_has_english_and_polish(self):
        for table in (self.text.UI_TEXT, self.text.VIEW_KINDS):
            for key, (english, polish) in table.items():
                with self.subTest(key=key):
                    self.assertTrue(english.strip() and polish.strip())
                    self.assertNotEqual(english, polish)

    def test_resources_follow_language(self):
        self.assertEqual(self.text.resources()["close"], "Close")
        with patch.dict(sys.modules, fake_pyrevit_locale(["pl"])):
            self.assertEqual(self.text.resources()["close"], "Zamknij")


class LegacyHostTests(unittest.TestCase):
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
            model = load_module("model_legacy_under_test", "extractor_model.py")
        doc = types.SimpleNamespace(Title="Test", PathName="", IsModified=True)
        snapshot = model.collect_views(doc)
        self.assertEqual({row["id"] for row in snapshot["views_2d"]}, {"10", "30"})
        self.assertEqual([row["id"] for row in snapshot["views_3d"]], ["20"])
        sheet = [row for row in snapshot["views_2d"] if row["id"] == "30"][0]
        self.assertIn("a-101", sheet["search"])
        # Displayed type follows the language (English by default); search matches both.
        self.assertEqual(sheet["kind"], "Sheets")
        self.assertIn("sheets", sheet["search"])
        self.assertIn("arkusze", sheet["search"])
        self.assertTrue(snapshot["modified"])
        with patch.dict(sys.modules, fake_pyrevit_locale(["pl"])):
            polish = model.collect_views(doc)
        self.assertEqual([row["kind"] for row in polish["views_2d"] if row["id"] == "30"], ["Arkusze"])

    def test_element_id_prefers_value_and_falls_back_to_integer_value(self):
        with patch.dict(sys.modules, {"pyrevit": types.SimpleNamespace(DB=None)}):
            model = load_module("model_ids_under_test", "extractor_model.py")
        # 2022-2023: IntegerValue only. 2024-2025: both. 2026: Value only.
        self.assertEqual(model.element_id_value(types.SimpleNamespace(IntegerValue=7)), 7)
        self.assertEqual(model.element_id_value(types.SimpleNamespace(IntegerValue=7, Value=7)), 7)
        self.assertEqual(model.element_id_value(types.SimpleNamespace(Value=2 ** 40)), 2 ** 40)

    def test_entry_point_opens_only_revit_2022_to_2025_projects(self):
        for year, family, opened in (("2022", False, True), ("2023", False, True),
                                     ("2024", False, True), ("2025", False, True),
                                     ("2021", False, False), ("2026", False, False),
                                     ("x", False, False), ("2022", True, False),
                                     (None, False, False)):
            with self.subTest(year=year, family=family):
                doc = (types.SimpleNamespace(Application=types.SimpleNamespace(VersionNumber=year),
                                             IsFamilyDocument=family) if year else None)
                pyrevit = types.SimpleNamespace(forms=Mock(), revit=types.SimpleNamespace(doc=doc),
                                                script=Mock())
                model, ui = Mock(), Mock()
                with patch.dict(sys.modules, {"pyrevit": pyrevit, "extractor_model": model,
                                              "extractor_ui": ui}):
                    command = load_module("command_legacy_under_test", "script.py")
                    command.main()
                self.assertEqual(model.collect_views.called, opened)
                self.assertEqual(ui.ExportSetupWindow.return_value.ShowDialog.called, opened)
                self.assertEqual(pyrevit.forms.alert.called, not opened)


if __name__ == "__main__":
    unittest.main()
