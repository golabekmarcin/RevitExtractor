# -*- coding: utf-8 -*-
"""shared-ui (specs/SPEC-shared-ui.md): the window building blocks in the extension-level lib/.

1. Equality guard: every lib/ file equals its ExportSetupLegacy copy, apart from the one allowed
   import line. Delete this guard together with the old buttons.
2. The slice 1 assertions (search bar, column filters, theme) run again against the lib/ copies.
"""
from pathlib import Path
import re
import sys
import unittest

import test_window_legacy as legacy


BUNDLE = legacy.BUNDLE
LIB = Path(__file__).resolve().parents[3] / "lib"

OLD_IMPORT = b"from extractor_i18n import tr"
NEW_IMPORT = b"from rx_i18n import tr"
SAME_FILES = ("rx_theme.xaml", "rx_search_bar.xaml")
IMPORT_FILES = ("rx_search_bar.py", "rx_search_placeholder.py", "rx_column_filter_model.py",
                "rx_column_filter_ui.py")


def read(path):
    """File bytes with line endings normalised to LF, so the guard passes on any checkout."""
    return path.read_bytes().replace(b"\r\n", b"\n")


class EqualityGuardTests(unittest.TestCase):
    def test_i18n_is_identical_to_the_bundle_copy(self):
        self.assertEqual(read(BUNDLE / "extractor_i18n.py"), read(LIB / "rx_i18n.py"))

    def test_files_without_the_import_are_identical(self):
        for name in SAME_FILES:
            self.assertEqual(read(BUNDLE / name), read(LIB / name), name)

    def test_files_with_the_import_differ_only_in_that_line(self):
        for name in IMPORT_FILES:
            source = read(BUNDLE / name)
            self.assertEqual(1, source.count(OLD_IMPORT), name)
            expected = source.replace(OLD_IMPORT, NEW_IMPORT)
            actual = read(LIB / name)
            self.assertEqual(1, actual.count(NEW_IMPORT), name)
            self.assertEqual(expected, actual, name)

    def test_nothing_in_lib_imports_an_extractor_module(self):
        files = sorted(LIB.glob("*.py"))
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertEqual([], re.findall(r"^\s*(?:from|import)\s+extractor_\w*", text,
                                            re.MULTILINE), path.name)

    def test_every_expected_file_exists(self):
        for name in ("rx_i18n.py",) + SAME_FILES + IMPORT_FILES:
            self.assertTrue((LIB / name).is_file(), name)
        self.assertTrue((LIB / "rx_search_placeholder.py").is_file())


# ---------------------------------------------------------------- slice 1 assertions on lib/

LIB_KIT = legacy.Kit(LIB, pin=True)


def under_lib(function):
    return Path(function.__code__.co_filename).resolve().parent == LIB.resolve()


class LibKitTests(unittest.TestCase):
    """The lib/ run must test the lib/ copies, not same-named bundle modules on sys.path."""

    def test_every_loaded_module_comes_from_lib(self):
        for module in (LIB_KIT.SEARCH, LIB_KIT.FILTER_MODEL, LIB_KIT.POPUP):
            self.assertEqual(LIB.resolve(), Path(module.__file__).resolve().parent, module)
        # Modules the popup pulled in by bare name (they are not module attributes of the
        # loader, so check where their functions were compiled).
        for function in (LIB_KIT.SEARCH.tr, LIB_KIT.FILTER_MODEL.tr, LIB_KIT.POPUP.tr,
                         LIB_KIT.POPUP.cascading_counts, LIB_KIT.POPUP.blank_label):
            self.assertTrue(under_lib(function), function)

    def test_the_bundle_is_a_different_copy(self):
        self.assertNotEqual(Path(legacy.BUNDLE_KIT.POPUP.__file__), Path(LIB_KIT.POPUP.__file__))
        self.assertFalse(under_lib(legacy.BUNDLE_KIT.POPUP.tr))


class TextMatchTests(legacy.TextMatchCases, unittest.TestCase):
    kit = LIB_KIT


class SearchBarTests(legacy.SearchBarCases, unittest.TestCase):
    kit = LIB_KIT


class ColumnFilterModelTests(legacy.ColumnFilterModelCases, unittest.TestCase):
    kit = LIB_KIT


class ColumnFilterPopupTests(legacy.ColumnFilterPopupCases, unittest.TestCase):
    kit = LIB_KIT


class ThemeTests(legacy.ThemeCases, unittest.TestCase):
    kit = LIB_KIT
    # ui.xaml and extractor_ui.py stay in the bundle; later modules add their own window files.
    theme_xaml_files = ()
    theme_code_files = ("rx_column_filter_ui.py",)


if __name__ == "__main__":
    unittest.main()
