# -*- coding: utf-8 -*-
"""ExportSetupLegacy window, slice 1 (HANDOVER §3a): the ported search bar, column filters
and theme, and the view window's behaviour with WPF and pyRevit stubbed.

Cannot prove WPF/IronPython behaviour or speed inside Revit; it checks the logic and the
wiring (no per-row PropertyChanged subscriptions, lazy JSON, ticks only on shown rows).
"""
import importlib.util
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET


BUNDLE = Path(__file__).resolve().parents[1] / "ExportSetupLegacy.pushbutton"
# Append, never prepend (see test_config_legacy.py).
sys.path.append(str(BUNDLE))
XNAME = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
XKEY = "{http://schemas.microsoft.com/winfx/2006/xaml}Key"

from wpf_fakes import (  # noqa: E402,F401  moved unchanged (status-window plan, Task 5)
    POPUP_EVENTS, POPUP_STUBS, SEARCH_BAR_STUBS, CONTROL_EVENTS, AnyModule, Args, BarRoot, Box,
    Changes, Check, Children, Collection, Control, Event, Fake, FakePopupSearchBar, FakeView, Host,
    Items, Part, SharedEventReactive, any_module, polish, reactive, stub_module)


def load(name, filename, stubs=None, folder=BUNDLE):
    """Load a module from `folder` (the bundle by default) with stubbed imports; sys.modules is
    restored afterwards."""
    saved = dict(sys.modules)
    try:
        sys.modules.update(stubs or {})
        spec = importlib.util.spec_from_file_location(name, str(folder / filename))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for key in list(sys.modules):
            if key not in saved:
                del sys.modules[key]
        sys.modules.update(saved)
    return module


# ---------------------------------------------------------------- search bar


class TextMatchCases(object):
    def test_plain_search_needs_every_word_in_any_order_and_case(self):
        self.assertTrue(self.kit.SEARCH.text_matches("  101 a- ", False, "A-101 — Ground floor"))
        self.assertTrue(self.kit.SEARCH.text_matches("FLOOR ground", False, "a-101 — ground floor"))
        self.assertFalse(self.kit.SEARCH.text_matches("floor roof", False, "a-101 — ground floor"))
        self.assertTrue(self.kit.SEARCH.text_matches("", False, "anything"))
        self.assertFalse(self.kit.SEARCH.text_matches("x", False, None))

    def test_regex_any_case_and_invalid_pattern_matches_nothing(self):
        self.assertTrue(self.kit.SEARCH.text_matches("^a-1\\d\\d", True, "A-101 — Ground floor"))
        self.assertFalse(self.kit.SEARCH.text_matches("^101", True, "A-101"))
        self.assertFalse(self.kit.SEARCH.text_matches("(a", True, "(a"))
        self.assertIsNotNone(self.kit.SEARCH.regex_error("(a"))
        self.assertIsNone(self.kit.SEARCH.regex_error("a|b"))


class SearchBarCases(object):
    def setUp(self):
        self.changes = Changes()

    def parts(self, bar):
        return bar.Root.parts

    def test_placed_in_its_host_with_only_the_box_shown(self):
        host = Host()
        bar = self.kit.SearchBar(host, self.changes, tooltip="Find")
        self.assertIs(bar.Root, host.Content)
        for name in ("ClearSearch", "SearchRegex", "ClearFilters"):
            self.assertEqual("Collapsed", self.parts(bar)[name].Visibility, name)
        self.assertEqual("Find", self.parts(bar)["SearchText"].ToolTip)
        self.assertEqual([], self.changes.calls)

    def test_text_changes_notify_and_show_the_clear_button(self):
        bar = self.kit.SearchBar(None, self.changes)
        bar.Text = "door"
        self.assertEqual("Visible", self.parts(bar)["ClearSearch"].Visibility)
        self.assertEqual([(bar, None)], self.changes.calls)
        self.parts(bar)["ClearSearch"].Click.fire(None, None)
        self.assertEqual("", bar.Text)
        self.assertTrue(self.parts(bar)["SearchText"].focused)
        self.assertEqual("Collapsed", self.parts(bar)["ClearSearch"].Visibility)

    def test_escape_clears_a_filled_box_only(self):
        bar = self.kit.SearchBar(None, self.changes, text="door")
        args = Args("Escape")
        self.parts(bar)["SearchText"].KeyDown.fire(None, args)
        self.assertEqual("", bar.Text)
        self.assertTrue(args.Handled)
        args = Args("Escape")
        self.parts(bar)["SearchText"].KeyDown.fire(None, args)
        self.assertFalse(args.Handled)
        bar.Text = "door"
        args = Args("A")
        self.parts(bar)["SearchText"].KeyDown.fire(None, args)
        self.assertEqual("door", bar.Text)
        self.assertFalse(args.Handled)

    def test_regex_only_where_offered(self):
        bar = self.kit.SearchBar(None, self.changes, text="^d.*r$")
        self.assertFalse(bar.matches("door"))
        bar = self.kit.SearchBar(None, self.changes, regex=True, text="^d.*r$")
        self.assertEqual("Visible", self.parts(bar)["SearchRegex"].Visibility)
        self.assertFalse(bar.IsRegex)
        bar.IsRegex = True
        self.assertTrue(bar.matches("DOOR"))
        self.assertFalse(bar.matches("doors"))

    def test_invalid_regex_matches_nothing_and_marks_the_box(self):
        bar = self.kit.SearchBar(None, self.changes, tooltip="Find", regex=True)
        bar.IsRegex = True
        bar.Text = "(door"
        box = self.parts(bar)["SearchText"]
        self.assertFalse(bar.matches("(door"))
        self.assertIsNotNone(bar.Error)
        self.assertIsNotNone(box.BorderBrush)
        self.assertTrue(box.ToolTip.startswith("Invalid regular expression: "))
        bar.Text = "door"
        self.assertIsNone(bar.Error)
        self.assertIsNone(box.BorderBrush)
        self.assertEqual("Find", box.ToolTip)

    def test_regex_click_notifies(self):
        bar = self.kit.SearchBar(None, self.changes, regex=True)
        self.parts(bar)["SearchRegex"].Click.fire(None, None)
        self.assertEqual(1, len(self.changes.calls))

    def test_clear_all_filters_follows_the_controller(self):
        class Controller(object):
            IsActive = False
            cleared = 0
            listeners = []

            def clear_all(self):
                Controller.cleared += 1

            def on_active_changed(self, callback):
                self.listeners.append(callback)
                callback(self.IsActive)

        controller = Controller()
        bar = self.kit.SearchBar(None, self.changes, text="door")
        bar.bind_filters(controller)
        button = self.parts(bar)["ClearFilters"]
        self.assertEqual("Collapsed", button.Visibility)
        controller.listeners[0](True)
        self.assertEqual("Visible", button.Visibility)
        button.Click.fire(None, None)
        self.assertEqual(1, Controller.cleared)
        self.assertEqual("door", bar.Text)

    def test_clear_all_filters_needs_an_action(self):
        bar = self.kit.SearchBar(None, self.changes)
        bar.show_clear_filters(True)
        self.assertEqual("Collapsed", self.parts(bar)["ClearFilters"].Visibility)
        bar = self.kit.SearchBar(None, self.changes, clear_filters=lambda: None)
        bar.show_clear_filters(True)
        self.assertEqual("Visible", self.parts(bar)["ClearFilters"].Visibility)

    def test_part_texts_follow_language(self):
        bar = self.kit.SearchBar(None, self.changes, regex=True)
        self.assertEqual("Clear all filters", self.parts(bar)["ClearFilters"].Content)
        self.assertTrue(self.parts(bar)["ClearSearch"].ToolTip)
        with patch.dict(sys.modules, polish()):
            bar = self.kit.SearchBar(None, self.changes, regex=True)
            bar.IsRegex = True
            bar.Text = "(x"
        self.assertEqual("Wyczyść wszystkie filtry", self.parts(bar)["ClearFilters"].Content)
        self.assertTrue(self.parts(bar)["SearchText"].ToolTip.startswith(
            "Nieprawidłowe wyrażenie regularne: "))


# ---------------------------------------------------------------- column filters

def frow(kind, name="", element_id=""):
    return types.SimpleNamespace(Kind=kind, Name=name, ElementId=element_id)


class ColumnFilterModelCases(object):
    def test_exact_filters_combine_and_one_column_can_be_excluded(self):
        item = frow("Sheets", "A")
        filters = {"Kind": {"Sheets"}, "Name": {"B"}}
        self.assertFalse(self.kit.FILTER_MODEL.row_matches_filters(item, filters))
        self.assertTrue(self.kit.FILTER_MODEL.row_matches_filters(item, filters, exclude="Name"))
        self.assertTrue(self.kit.FILTER_MODEL.row_matches_filters(item, {"Kind": None}))

    def test_cascading_counts_apply_every_other_filter_and_base_rule(self):
        rows = [frow("Sheets", "A"), frow("Sheets", "B"), frow("Sections", "A"),
                frow("Sheets", "C")]
        counts = self.kit.FILTER_MODEL.cascading_counts(
            rows, "Kind", {"Name": {"A", "C"}, "Kind": set()},
            base_visible=lambda item: item.Name != "C")
        self.assertEqual({"Sheets": 1, "Sections": 1}, counts)

    def test_rebuild_preserves_survivors_and_excludes_new_values(self):
        rows = [frow("Sheets"), frow("Sections")]
        result = self.kit.FILTER_MODEL.reconcile_filters(rows, {"Kind": {"Sheets", "Gone"}, "Name": None})
        self.assertEqual({"Sheets"}, result["Kind"])
        self.assertIsNone(result["Name"])

    def test_blank_label_follows_language(self):
        self.assertEqual("(Blanks)", self.kit.FILTER_MODEL.blank_label())
        with patch.dict(sys.modules, polish()):
            self.assertEqual("(Puste)", self.kit.FILTER_MODEL.blank_label())

    def test_order_is_yes_no_numbers_then_text(self):
        values = ["b", 10, "No", 2, "A", "Yes"]
        ordered = sorted(values, key=lambda value: self.kit.FILTER_MODEL.value_sort_key(value, str(value)))
        self.assertEqual(["Yes", "No", 2, 10, "A", "b"], ordered)


class Kit(object):
    """The modules under test, loaded from one folder: the bundle, or lib/ (test_shared_ui.py).

    `pin` makes the folder's own rx_i18n / rx_column_filter_model win over same-named bundle
    modules that are on sys.path, so a lib/ run cannot silently test the bundle copies.
    """

    def __init__(self, folder, pin=False):
        self.folder = folder
        pinned = {}
        if pin:
            pinned["rx_i18n"] = load("rx_i18n", "rx_i18n.py", folder=folder)
        stubs = dict(SEARCH_BAR_STUBS, **pinned)
        self.SEARCH = load("rx_search_bar_under_test", "rx_search_bar.py", stubs, folder)
        self.SearchBar = self.SEARCH.SearchBar
        self.FILTER_MODEL = load("rx_column_filter_model_under_test", "rx_column_filter_model.py",
                                 pinned, folder)
        if pin:
            pinned["rx_column_filter_model"] = self.FILTER_MODEL
        self.POPUP = load("rx_column_filter_ui_under_test", "rx_column_filter_ui.py",
                          dict(POPUP_STUBS, **pinned), folder)


def popup_values(controller):
    viewer = controller._popup.Child.Child.Children[3]
    return viewer, list(viewer.Content.Children)


def labels(boxes):
    return [box.Content.Text for box in boxes]


class ColumnFilterPopupCases(object):
    def test_values_with_counts_and_clicks_filter_and_refresh(self):
        rows = [frow("Sheets"), frow("Sections"), frow("Sheets")]
        refreshed = []
        controller = self.kit.POPUP.ColumnFilterController(lambda: rows, lambda: refreshed.append(1))
        controller.open(Fake(), "Kind")
        viewer, boxes = popup_values(controller)
        self.assertEqual(["Sections (1)", "Sheets (2)"], labels(boxes))
        boxes[0].IsChecked = False
        boxes[0].Click.fire(boxes[0], None)
        viewer, boxes = popup_values(controller)
        self.assertEqual([False, True], [box.IsChecked for box in boxes])
        self.assertEqual({"Sheets"}, controller.Filters["Kind"])
        self.assertTrue(controller.IsActive)
        self.assertEqual([1], refreshed)
        # Scroll position and the clicked value's focus are kept.
        self.assertEqual(7, viewer.scrolled_to)
        self.assertTrue(boxes[0].focused)

    def test_base_visible_limits_the_counts(self):
        rows = [frow("Sheets", "A"), frow("Sections", "B")]
        controller = self.kit.POPUP.ColumnFilterController(
            lambda: rows, lambda: None, base_visible=lambda row: row.Name == "A")
        controller.open(Fake(), "Kind")
        unused_viewer, boxes = popup_values(controller)
        self.assertEqual(["Sheets (1)"], labels(boxes))

    def test_clear_all_resets_and_notifies(self):
        rows = [frow("Sheets")]
        seen = []
        controller = self.kit.POPUP.ColumnFilterController(lambda: rows, lambda: None)
        controller.Filters["Kind"] = set()
        controller.on_active_changed(seen.append)
        controller.clear_all()
        self.assertEqual([True, False], seen)
        self.assertIsNone(controller.Filters["Kind"])

    def test_header_uses_theme_keys_only(self):
        source = (self.kit.folder / "rx_column_filter_ui.py").read_text(encoding="utf-8")
        self.assertNotIn('"Fs', source)
        self.assertIn('"RxAccent"', source)


# ---------------------------------------------------------------- theme and XAML

def theme_keys(folder):
    root = ET.parse(str(folder / "rx_theme.xaml")).getroot()
    return {element.get(XKEY) for element in root.iter() if element.get(XKEY)}


class ThemeCases(object):
    def test_theme_is_renamed_and_complete(self):
        keys = theme_keys(self.kit.folder)
        self.assertFalse([key for key in keys if key.startswith("Fs")])
        for key in ("RxWindow", "RxPrimaryButton", "RxCard", "RxAccent", "RxCardBackground",
                    "RxBorder", "RxError", "RxMuted", "RxWindowTitle"):
            self.assertIn(key, keys)
        self.assertNotRegex((self.kit.folder / "rx_theme.xaml").read_text(encoding="utf-8"), r"\bFs[A-Z]")

    def test_every_theme_key_the_code_uses_exists(self):
        keys = theme_keys(self.kit.folder)
        used = set()
        for name in self.theme_xaml_files:
            used |= set(re.findall(r"\{DynamicResource (Rx\w+)\}",
                                   (self.kit.folder / name).read_text(encoding="utf-8")))
        for name in self.theme_code_files:
            used |= set(re.findall(r'"(Rx[A-Z]\w+)"', (self.kit.folder / name).read_text(encoding="utf-8")))
        self.assertTrue(used)
        self.assertEqual(set(), used - keys)

    def test_search_bar_template_has_no_text_or_window_resources(self):
        text = (self.kit.folder / "rx_search_bar.xaml").read_text(encoding="utf-8")
        self.assertNotIn("DynamicResource", text)
        attributes = re.findall(r'\b(Text|Content|Header|ToolTip)="([^"]*)"', text)
        literals = {value for name, value in attributes if value and not value.startswith("{")}
        self.assertEqual({"&#x2715;"}, literals)
        root = ET.fromstring(text)
        names = {element.get(XNAME) for element in root.iter() if element.get(XNAME)}
        self.assertLessEqual({"SearchText", "ClearSearch", "SearchRegex", "ClearFilters"}, names)
        # Search box first, then Regex, then "Clear all filters".
        columns = dict((element.get(XNAME), element.get("Grid.Column")) for element in root.iter())
        self.assertEqual(("1", "2"), (columns["SearchRegex"], columns["ClearFilters"]))


# ---------------------------------------------------------------- bundle runs

BUNDLE_KIT = Kit(BUNDLE)
FILTER_MODEL = BUNDLE_KIT.FILTER_MODEL


class TextMatchTests(TextMatchCases, unittest.TestCase):
    kit = BUNDLE_KIT


class SearchBarTests(SearchBarCases, unittest.TestCase):
    kit = BUNDLE_KIT


class ColumnFilterModelTests(ColumnFilterModelCases, unittest.TestCase):
    kit = BUNDLE_KIT


class ColumnFilterPopupTests(ColumnFilterPopupCases, unittest.TestCase):
    kit = BUNDLE_KIT


class ThemeTests(ThemeCases, unittest.TestCase):
    kit = BUNDLE_KIT
    theme_xaml_files = ("ui.xaml",)
    theme_code_files = ("rx_column_filter_ui.py", "extractor_ui.py")


# ---------------------------------------------------------------- window


XAML_NAMES = dict(
    (element.get(XNAME), element.get("Tag"))
    for element in ET.parse(str(BUNDLE / "ui.xaml")).getroot().iter() if element.get(XNAME))


class FakeWPFWindow(object):
    def __init__(self, xaml_path, handle_esc=True):
        self.xaml_path = xaml_path
        self.handle_esc = handle_esc
        self.Resources = {}
        self.merged = []
        self.closed = False
        for name, tag in XAML_NAMES.items():
            setattr(self, name, Control(name, tag))

    def merge_resource_dict(self, path):
        self.merged.append(path)

    def FindResource(self, key):
        raise KeyError(key)

    def Close(self):
        self.closed = True


class FakeSearchBar(object):
    instances = []

    def __init__(self, host, changed=None, tooltip=None, regex=False, **unused):
        self.host = host
        self.changed = changed
        self.tooltip = tooltip
        self.regex = regex
        self.bound = None
        self._text = ""
        FakeSearchBar.instances.append(self)

    @property
    def Text(self):
        return self._text

    @Text.setter
    def Text(self, value):
        self._text = value
        if self.changed:
            self.changed(self, None)

    def matches(self, value):
        return all(word in value.lower() for word in self._text.lower().split())

    def bind_filters(self, controller):
        self.bound = controller


class FakeFilters(object):
    def __init__(self, rows, refresh, base_visible=None, **unused):
        self.rows = rows
        self.refresh = refresh
        self.base_visible = base_visible
        self.Filters = {}
        self.registered = []

    def register(self, column, title, attribute):
        self.Filters.setdefault(attribute, None)
        self.registered.append((column, title, attribute))

    def matches(self, row):
        return FILTER_MODEL.row_matches_filters(row, self.Filters)

    def clear_all(self):
        for key in self.Filters:
            self.Filters[key] = None
        self.refresh()


def load_window_module():
    config = load("config_for_window_test", "extractor_config.py")
    forms = types.SimpleNamespace(WPFWindow=FakeWPFWindow, Reactive=SharedEventReactive,
                                  reactive=reactive, save_file=Mock(return_value=None),
                                  alert=Mock())
    stubs = {
        "System": stub_module("System", Environment=Mock(), Predicate={object: lambda fn: fn}),
        "System.Collections": stub_module("System.Collections"),
        "System.Collections.ObjectModel": stub_module("System.Collections.ObjectModel",
                                                      ObservableCollection={object: Collection}),
        "System.IO": stub_module("System.IO", File=Mock()),
        "System.Text": stub_module("System.Text", UTF8Encoding=Mock()),
        "System.Windows": stub_module("System.Windows", RoutedEventHandler=lambda fn: fn),
        "System.Windows.Controls": stub_module("System.Windows.Controls"),
        "System.Windows.Controls.Primitives": stub_module(
            "System.Windows.Controls.Primitives",
            ButtonBase=types.SimpleNamespace(ClickEvent="ButtonBase.Click")),
        "System.Windows.Data": stub_module(
            "System.Windows.Data", CollectionViewSource=types.SimpleNamespace(
                GetDefaultView=FakeView)),
        "System.Windows.Input": stub_module("System.Windows.Input",
                                            Key=types.SimpleNamespace(Space="Space", A="A")),
        "pyrevit": types.SimpleNamespace(forms=forms),
        # Pin the legacy modules: the 2026 tests put a same-named extractor_config first.
        "extractor_config": config,
        "rx_search_bar": stub_module("rx_search_bar", SearchBar=FakeSearchBar),
        "rx_column_filter_ui": stub_module("rx_column_filter_ui",
                                           ColumnFilterController=FakeFilters),
    }
    return load("ui_legacy_under_test", "extractor_ui.py", stubs)


UI = load_window_module()


def record(element_id, name, kind="Floor plans"):
    return {"id": str(element_id), "uid": "uid-" + str(element_id), "name": name, "kind": kind,
            "search": " ".join((name, kind, str(element_id))).lower()}


def snapshot():
    return {
        "title": "Model", "path": "C:\\P\\Model.rvt", "modified": False,
        "views_2d": [record(10, "Level 1"), record(11, "Level 2"),
                     record(30, "A-101 — Ground", "Sheets"), record(31, "A-102 — Roof", "Sheets")],
        "views_3d": [record(20, "{3D}", "3D views"), record(21, "Facade", "3D views")],
    }


class Source(object):
    def __init__(self, row):
        self.DataContext = row


class WindowTests(unittest.TestCase):
    def setUp(self):
        SharedEventReactive.PropertyChanged = Event()
        SharedEventReactive.raised = []
        FakeSearchBar.instances = []
        self.window = UI.ExportSetupWindow(snapshot())
        self.search2d, self.search3d = FakeSearchBar.instances

    def rows(self, dimension):
        return list(self.window._rows[dimension])

    def ticked(self, dimension):
        return [row.ElementId for row in self.rows(dimension) if row.Checked]

    def click_checkbox(self, list_view, row):
        row.Checked = not row.Checked            # what the TwoWay binding does first
        event, handler = list_view.routed[0]
        self.assertEqual("ButtonBase.Click", event)
        handler(list_view, Args(source=Source(row)))

    def choose_selected_scope(self, dimension):
        getattr(self.window, "default" + dimension + "_rb").IsChecked = False
        getattr(self.window, "selected" + dimension + "_rb").IsChecked = True
        self.window._on_settings_changed(None, None)

    def test_theme_merged_and_pyrevit_escape_hook_off(self):
        self.assertEqual(["rx_theme.xaml"], [Path(path).name for path in self.window.merged])
        # Esc belongs to the search bar first, then the Close button (IsCancel).
        self.assertFalse(self.window.handle_esc)
        self.assertEqual(self.window.Resources["close"], "Close")

    def test_rows_are_plain_reactive_objects_without_window_subscriptions(self):
        row = self.rows("2d")[0]
        self.assertEqual(("Level 1", "Floor plans", "10"), (row.Name, row.Kind, row.ElementId))
        self.click_checkbox(self.window.views2d_lv, row)
        self.window.all3d_btn.Click.fire(self.window.all3d_btn, None)
        # pyRevit shares one PropertyChanged list between all rows, so a per-row window
        # handler runs once per row on every tick (the 1000+ sheet lag).
        self.assertEqual([], SharedEventReactive.PropertyChanged.handlers)
        self.assertEqual([(row, "Checked")], SharedEventReactive.raised)

    def test_each_list_is_one_filtered_view_that_search_refreshes(self):
        view = self.window.views2d_lv.ItemsSource
        self.assertIsInstance(view, FakeView)
        self.search2d.Text = "a-10"
        self.assertIs(view, self.window.views2d_lv.ItemsSource)
        self.assertEqual(["30", "31"], [row.ElementId for row in view])
        self.assertIn("Shown in the list: 2", self.window.count2d_text.Text)
        self.assertTrue(self.search2d.regex and self.search3d.regex)
        self.assertIs(self.window.search2d_host, self.search2d.host)

    def test_select_all_shown_ticks_only_the_filtered_rows_with_one_refresh(self):
        self.search2d.Text = "roof"
        before = self.window.views2d_lv.Items.refreshes
        self.window.all2d_btn.Click.fire(self.window.all2d_btn, None)
        self.assertEqual(["31"], self.ticked("2d"))
        self.assertEqual(before + 1, self.window.views2d_lv.Items.refreshes)
        self.assertEqual([], SharedEventReactive.raised)
        self.search2d.Text = ""
        self.window.none2d_btn.Click.fire(self.window.none2d_btn, None)
        self.assertEqual([], self.ticked("2d"))
        self.assertIn("Selected: 0 / 4", self.window.count2d_text.Text)

    def test_type_column_filter_replaces_the_type_combo(self):
        filters = self.search2d.bound
        self.assertIsInstance(filters, FakeFilters)
        column, title, attribute = filters.registered[0]
        self.assertIs(self.window.views2d_lv.View.Columns[2], column)
        self.assertEqual(("Type", "Kind"), (title, attribute))
        filters.Filters["Kind"] = {"Sheets"}
        filters.refresh()
        self.assertEqual(["30", "31"], [row.ElementId for row in self.window.views2d_lv.ItemsSource])
        # The popup counts follow the search box.
        self.search2d.Text = "roof"
        self.assertEqual([False, False, False, True],
                         [filters.base_visible(row) for row in self.rows("2d")])
        self.assertNotIn("kind2d_cb", XAML_NAMES)

    def test_checkbox_on_a_highlighted_row_ticks_every_highlighted_row(self):
        rows = self.rows("2d")
        list_view = self.window.views2d_lv
        list_view.SelectedItems = [rows[0], rows[2]]
        self.click_checkbox(list_view, rows[2])
        self.assertEqual(["10", "30"], self.ticked("2d"))
        self.click_checkbox(list_view, rows[1])      # outside the highlight: only that row
        self.assertEqual(["10", "11", "30"], self.ticked("2d"))
        # A header filter button bubbles the same Click; it has no row and is ignored.
        list_view.routed[0][1](list_view, Args(source=Source(None)))
        self.assertEqual(["10", "11", "30"], self.ticked("2d"))

    def test_space_toggles_highlighted_rows_but_not_inside_popups(self):
        rows = self.rows("3d")
        list_view = self.window.views3d_lv
        list_view.SelectedItems = rows
        args = Args("Space", Source(rows[0]))
        list_view.PreviewKeyDown.fire(list_view, args)
        self.assertTrue(args.Handled)
        self.assertEqual(["20", "21"], self.ticked("3d"))
        list_view.PreviewKeyDown.fire(list_view, Args("Space", Source(rows[0])))
        self.assertEqual([], self.ticked("3d"))
        # Focus on the list itself (no focused row) works too.
        list_view.PreviewKeyDown.fire(list_view, Args("Space", list_view))
        self.assertEqual(["20", "21"], self.ticked("3d"))
        list_view.PreviewKeyDown.fire(list_view, Args("Space", list_view))
        self.assertEqual([], self.ticked("3d"))
        # A filter popup's search box or value checkbox routes its keys through the header.
        args = Args("Space", Source(None))
        list_view.PreviewKeyDown.fire(list_view, args)
        self.assertFalse(args.Handled)
        self.assertEqual([], self.ticked("3d"))

    def test_json_preview_is_built_only_while_its_tab_is_open(self):
        self.choose_selected_scope("2d")
        self.window.all2d_btn.Click.fire(self.window.all2d_btn, None)
        self.assertEqual("", self.window.json_tb.Text)
        self.window.preview_tab.IsSelected = True
        self.window.tabs.SelectionChanged.fire(self.window.tabs, None)
        self.assertIn('"view_ids": [\n', self.window.json_tb.Text)
        self.assertIn("31", self.window.json_tb.Text)
        # Options above the tabs stay live while the preview is open.
        self.window.pdb_cb.IsChecked = False
        self.window._on_settings_changed(None, None)
        self.assertIn('"pdb": false', self.window.json_tb.Text)

    def test_invalid_selection_disables_save_and_shows_the_error_line(self):
        self.choose_selected_scope("3d")
        self.assertFalse(self.window.save_btn.IsEnabled)
        self.assertIn("3D", self.window.error_text.Text)
        self.click_checkbox(self.window.views3d_lv, self.rows("3d")[1])
        self.assertTrue(self.window.save_btn.IsEnabled)
        self.assertEqual("", self.window.error_text.Text)
        self.assertIn("3D: selected: 1", self.window.summary_text.Text)

    def test_reset_clears_ticks_search_and_filters(self):
        self.window.all2d_btn.Click.fire(self.window.all2d_btn, None)
        self.search3d.Text = "facade"
        self.search2d.bound.Filters["Kind"] = {"Sheets"}
        self.window.reset_btn.Click.fire(self.window.reset_btn, None)
        self.assertEqual([], self.ticked("2d"))
        self.assertEqual("", self.search3d.Text)
        self.assertIsNone(self.search2d.bound.Filters["Kind"])
        self.assertEqual(4, len(list(self.window.views2d_lv.ItemsSource)))
        self.assertTrue(self.window.default2d_rb.IsChecked)

    def test_footer_keys(self):
        xaml = (BUNDLE / "ui.xaml").read_text(encoding="utf-8")
        self.assertRegex(xaml, r'<Button x:Name="close_btn"[^>]*IsCancel="True"')
        self.assertRegex(xaml, r'<Button x:Name="save_btn"[^>]*IsDefault="True"')
        self.assertRegex(xaml, r'<ContentControl x:Name="search2d_host"')
        self.assertRegex(xaml, r'<ContentControl x:Name="search3d_host"')
        self.assertNotIn("PropertyChanged +=", (BUNDLE / "extractor_ui.py").read_text(
            encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
