# -*- coding: utf-8 -*-
"""The Node.js notice: preference helpers (pure), its text table and XAML, and the dialog class.
Session behaviour is in test_status.py (WindowTest). WPF is stubbed; behaviour inside Revit is
not covered."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parent))
import test_status as ts  # noqa: E402
import rx_status  # noqa: E402

LIB = ts.LIB


class PreferenceHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rx-notice-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "RevitExtractor", "preferences.json")

    def raw(self, text):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_path_is_under_appdata_next_to_the_model_cache(self):
        self.assertEqual(rx_status.preferences_path(self.tmp), self.path)
        self.assertIsNone(rx_status.preferences_path(""))
        self.assertIsNone(rx_status.preferences_path(None))

    def test_missing_corrupt_or_wrong_shape_files_show_the_notice(self):
        self.assertFalse(rx_status.notice_hidden(self.path))
        for text in ("", "{not json", "[1, 2]", '"x"', '{"hide_node_notice": "yes"}',
                     '{"hide_node_notice": false}'):
            with self.subTest(text=text):
                self.raw(text)
                self.assertFalse(rx_status.notice_hidden(self.path))
        self.assertFalse(rx_status.notice_hidden(None))

    def test_flag_true_hides_the_notice(self):
        self.raw('{"hide_node_notice": true}')
        self.assertTrue(rx_status.notice_hidden(self.path))

    def test_write_creates_the_folder_and_round_trips(self):
        self.assertTrue(rx_status.hide_notice(self.path))
        self.assertTrue(rx_status.notice_hidden(self.path))
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"hide_node_notice": True})

    def test_write_preserves_other_keys(self):
        self.raw('{"other": {"a": 1}, "name": "Za\\u017c\\u00f3\\u0142\\u0107"}')
        self.assertTrue(rx_status.hide_notice(self.path))
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"other": {"a": 1}, "name": "Zażółć",
                                                 "hide_node_notice": True})

    def test_write_over_a_corrupt_file_replaces_it(self):
        self.raw("{broken")
        self.assertTrue(rx_status.hide_notice(self.path))
        self.assertTrue(rx_status.notice_hidden(self.path))

    def test_write_failure_is_swallowed_and_reported_as_false(self):
        def broken(path, text):
            raise IOError("read-only")
        self.assertFalse(rx_status.hide_notice(self.path, write=broken))
        self.assertFalse(rx_status.hide_notice(None))

    def test_read_failure_is_swallowed(self):
        def broken(path):
            raise IOError("denied")
        self.assertFalse(rx_status.notice_hidden(self.path, read=broken))

    def test_injected_io_is_used(self):
        store = {}
        self.assertTrue(rx_status.hide_notice("p", read=lambda path: store.get(path, ""),
                                              write=lambda path, text: store.update({path: text})))
        self.assertEqual(json.loads(store["p"]), {"hide_node_notice": True})
        self.assertTrue(rx_status.notice_hidden("p", read=lambda path: store[path]))


class NoticeText(unittest.TestCase):
    XAML_PATH = LIB / "rx_notice.xaml"

    def test_every_entry_has_english_and_polish(self):
        self.assertTrue(rx_status.NOTICE_TEXT)
        for key, (english, polish_text) in rx_status.NOTICE_TEXT.items():
            with self.subTest(key=key):
                self.assertTrue(english.strip() and polish_text.strip())
                if key != "notice_ok":
                    self.assertNotEqual(english, polish_text)
                self.assertFalse(key.startswith("Rx"))
        self.assertFalse(set(rx_status.NOTICE_TEXT) & set(rx_status.UI_TEXT))

    def test_the_text_says_what_the_user_must_do(self):
        english = " ".join(value[0] for value in rx_status.NOTICE_TEXT.values())
        polish_text = " ".join(value[1] for value in rx_status.NOTICE_TEXT.values())
        for text in (english, polish_text):
            self.assertIn("Node.js", text)
            self.assertIn("24", text)
            self.assertIn("Start-Analyzer.cmd", text)
            self.assertIn("Company Portal", text)
            self.assertIn("Revit", text)
        self.assertIn("restart revit", english.lower())

    def test_notice_resources_follow_language(self):
        self.assertEqual(rx_status.notice_resources()["notice_dont_show"], "Don't show this again")
        self.assertEqual(set(rx_status.notice_resources()), set(rx_status.NOTICE_TEXT))
        self.assertNotEqual(ts.under_polish(rx_status.notice_resources)["notice_dont_show"],
                            rx_status.notice_resources()["notice_dont_show"])

    def test_xaml_keys_and_text_table_match_both_ways(self):
        xaml = self.XAML_PATH.read_text(encoding="utf-8")
        used = set(key for key in re.findall(r"\{DynamicResource (\w+)\}", xaml)
                   if not key.startswith("Rx"))
        self.assertEqual(used, set(rx_status.NOTICE_TEXT))

    def test_no_hard_coded_label_and_theme_keys_exist(self):
        xaml = self.XAML_PATH.read_text(encoding="utf-8")
        attributes = re.findall(r'\b(Title|Text|Content|Header|ToolTip)="([^"]*)"', xaml)
        self.assertEqual({v for n, v in attributes if v and not v.startswith("{")}, set())
        for element in ET.fromstring(xaml).iter():
            if element.text and element.text.strip():
                self.fail("literal element text: " + element.text.strip())
        theme = ET.parse(str(LIB / "rx_theme.xaml")).getroot()
        keys = {e.get("{http://schemas.microsoft.com/winfx/2006/xaml}Key") for e in theme.iter()}
        self.assertEqual(set(re.findall(r"\{DynamicResource (Rx\w+)\}", xaml)) - keys, set())
        self.assertNotIn("StaticResource Rx", xaml)


class NoticeDialog(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(sys.modules, ts.ui_system_stubs())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ui = ts.load_status_ui()
        self.addCleanup(setattr, ts.FakeStatusWindowBase, "dialog_hook", None)

    def test_dialog_loads_xaml_theme_text_and_reason_and_returns_the_checkbox(self):
        seen = []

        def hook(window):
            seen.append(window)
            window.dont_show_chk.IsChecked = True
        ts.FakeStatusWindowBase.dialog_hook = hook
        self.assertTrue(self.ui.show_notice("Node.js was not found."))
        window = seen[0]
        self.assertEqual(Path(window.xaml_path).name, "rx_notice.xaml")
        self.assertEqual([Path(p).name for p in window.merged], ["rx_theme.xaml"])
        self.assertEqual(window.Resources["notice_ok"], "OK")
        self.assertEqual(window.reason_text.Text, "Node.js was not found.")
        self.assertEqual(window.dialogs, 1)

    def test_unticked_checkbox_returns_false(self):
        ts.FakeStatusWindowBase.dialog_hook = None
        self.assertFalse(self.ui.show_notice("x"))

    def test_checkbox_nullable_none_counts_as_unticked(self):
        def hook(window):
            window.dont_show_chk.IsChecked = None
        ts.FakeStatusWindowBase.dialog_hook = hook
        self.assertFalse(self.ui.show_notice("x"))


if __name__ == "__main__":
    unittest.main()
