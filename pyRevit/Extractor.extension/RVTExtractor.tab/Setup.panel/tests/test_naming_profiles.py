# -*- coding: utf-8 -*-
"""Tests for lib/rx_naming_profiles.py: profile validation, files, the part list, the remembered
choice, and the blank-value counter. Names and values are invented."""
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

TESTS = Path(__file__).resolve().parent
LIB = TESTS.parents[2] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))

import rx_naming  # noqa: E402
import rx_naming_profiles as P  # noqa: E402
from rx_naming import NamingError  # noqa: E402


def polish():
    def get_locale_string(string_dict):
        return string_dict.get("pl")
    applocales = types.SimpleNamespace(get_locale_string=get_locale_string)
    coreutils = types.SimpleNamespace(applocales=applocales)
    return {"pyrevit": types.SimpleNamespace(coreutils=coreutils),
            "pyrevit.coreutils": coreutils, "pyrevit.coreutils.applocales": applocales}


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="rxnp-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def path(self, name):
        return os.path.join(self.dir, name)


class Profiles(Case):
    def test_default_and_template(self):
        d = P.default_profile()
        self.assertEqual(P.to_template(d["views"], d["separator"]), "{ViewFamily} - {ViewName}")
        self.assertEqual(P.to_template(d["sheets"], d["separator"]),
                         "{SheetNumber} - {SheetName}")
        self.assertEqual(P.to_template(["SheetNumber", "param:Project code"], "_"),
                         "{SheetNumber}_{param:Project code}")

    def test_round_trip(self):
        profile = {"name": "Mine ł", "views": ["ViewName", "param:Zone"], "sheets": ["Date"],
                   "separator": "_", "split_by_format": True}
        path = self.path("a.rx-naming.json")
        P.save_profile(path, profile)
        P.save_profile(path, profile)   # replaces the old file
        self.assertEqual(sorted(os.listdir(self.dir)), ["a.rx-naming.json"])
        self.assertEqual(P.load_profile(path), profile)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        raw = json.loads(text)
        self.assertEqual((raw["schema"], raw["version"]), ("rx-naming-profile", 1))
        self.assertIn("\\u0142", text)

    def test_suffix_rule(self):
        self.assertEqual(P.profile_path("x"), "x.rx-naming.json")
        self.assertEqual(P.profile_path("x.json"), "x.rx-naming.json")
        self.assertEqual(P.profile_path("x.rx-naming.json"), "x.rx-naming.json")
        self.assertEqual(P.profile_path("X.RX-NAMING.JSON"), "X.RX-NAMING.JSON")

    def test_validate_rejects(self):
        good = dict(P.DEFAULT)
        bad = [None, [], dict(good, separator="::"), dict(good, views=[]), dict(good, sheets=None),
               dict(good, views=["Nope"]), dict(good, views=["SheetNumber"]),
               dict(good, views=["Year"]), dict(good, sheets=["param:a}b"]),
               dict(good, sheets=["param:a{b"]), dict(good, sheets=["param:  "]),
               dict(good, sheets=[5]),
               dict(good, sheets=["param:" + "x" * 150, "param:" + "y" * 150])]
        for item in bad:
            with self.assertRaises(NamingError, msg=repr(item)):
                P.validate(item)
        for sep in P.SEPARATORS:
            P.validate(dict(good, separator=sep))

    def test_load_rejects_a_wrong_or_missing_file(self):
        with self.assertRaises(NamingError):
            P.load_profile(self.path("missing.rx-naming.json"))
        for text in ("{bad", "[]", json.dumps({"schema": "x", "version": 1}),
                     json.dumps(dict(P.DEFAULT, schema=P.SCHEMA, version=2))):
            with open(self.path("w.json"), "w") as handle:
                handle.write(text)
            with self.assertRaises(NamingError, msg=text):
                P.load_profile(self.path("w.json"))


class Available(unittest.TestCase):
    CATALOG = {"views": ["Zone", "alpha"], "sheets": ["Project code"]}

    def test_order_groups_and_labels(self):
        items = P.available("sheets", self.CATALOG, "", "en")
        rank = {"builtin": 0, "custom": 1, "system": 2}
        classes = [c for _, _, c in items]
        self.assertEqual(classes, sorted(classes, key=rank.get))
        labels = {c: [l for _, l, k in items if k == c] for c in rank}
        for group in labels.values():
            self.assertEqual(group, sorted(group, key=str.lower))
        self.assertEqual(labels["custom"], ["Project code"])
        self.assertIn(("param:Project code", "Project code", "custom"), items)
        self.assertIn(("SheetNumber", "Sheet number", "builtin"), items)
        self.assertIn(("Time", "Time", "system"), items)
        self.assertNotIn("Year", [p for p, _, _ in items])
        self.assertNotIn("ViewName", [p for p, _, _ in items])

    def test_view_tab_and_custom_sorting(self):
        items = P.available("views", self.CATALOG, "", "en")
        self.assertEqual([l for _, l, c in items if c == "custom"], ["alpha", "Zone"])
        self.assertIn("ViewFamily", [p for p, _, _ in items])

    def test_search_is_a_case_insensitive_substring(self):
        items = P.available("sheets", self.CATALOG, " NUMBER ", "en")
        self.assertEqual([l for _, l, _ in items], ["Sheet number"])
        self.assertEqual(P.available("sheets", self.CATALOG, "zzzz", "en"), [])
        self.assertEqual([p for p, _, _ in P.available("sheets", self.CATALOG, "code", "en")],
                         ["param:Project code"])

    def test_polish_labels(self):
        items = P.available("views", {}, "rodzina", "pl")
        self.assertEqual(items, [("ViewFamily", "Rodzina widoku", "builtin")])
        self.assertEqual([l for p, l, _ in P.available("sheets", {}, "czas", "pl")], ["Czas"])


class Catalog(Case):
    def test_read(self):
        path = self.path("property-catalog.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"schema": "rx-property-catalog", "version": 1,
                       "views": ["B", "A", "A", 5, " "], "sheets": ["Ł"]}, handle)
        self.assertEqual(P.read_catalog(path), {"views": ["A", "B"], "sheets": ["Ł"]})

    def test_missing_or_bad_gives_empty_lists(self):
        empty = {"views": [], "sheets": []}
        self.assertEqual(P.read_catalog(self.path("nope.json")), empty)
        with open(self.path("b.json"), "w") as handle:
            handle.write("{bad")
        self.assertEqual(P.read_catalog(self.path("b.json")), empty)
        with open(self.path("c.json"), "w") as handle:
            handle.write(json.dumps({"schema": "other", "views": ["A"]}))
        self.assertEqual(P.read_catalog(self.path("c.json")), empty)

    def test_merge_unions_sorts_caps_and_keeps_the_schema(self):
        path = self.path("property-catalog.json")
        self.assertTrue(P.merge_catalog(path, {"views": ["B"], "sheets": ["S"]}))
        self.assertTrue(P.merge_catalog(path, {"views": ["A", "B", " "], "sheets": []}))
        self.assertEqual(P.read_catalog(path), {"views": ["A", "B"], "sheets": ["S"]})
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual((data["schema"], data["version"]), ("rx-property-catalog", 1))
        names = ["P%04d" % n for n in range(2500)]
        self.assertTrue(P.merge_catalog(path, {"views": names, "sheets": []}))
        self.assertEqual(len(P.read_catalog(path)["views"]), 2000)

    def test_merge_is_atomic_and_never_raises(self):
        path = self.path("property-catalog.json")
        P.merge_catalog(path, {"views": ["A"], "sheets": []})
        self.assertFalse(os.path.exists(path + ".tmp"), "the temp file is renamed away")
        os.mkdir(self.path("blocked.json"))     # a folder where the file should be
        self.assertFalse(P.merge_catalog(self.path("blocked.json"), {"views": ["A"], "sheets": []}))
        self.assertEqual(P.read_catalog(path), {"views": ["A"], "sheets": []})


class Choice(Case):
    def test_nothing_chosen_means_none(self):
        got = P.read_choice({})
        self.assertEqual((got["selected"], got["profile"], got["note"]), ("none", None, ""))
        self.assertEqual(P.read_choice(None)["selected"], "none")

    def test_default(self):
        got = P.read_choice({"naming": {"selected": "default"}})
        self.assertEqual(got["profile"], P.default_profile())

    def test_a_chosen_file(self):
        path = self.path("a.rx-naming.json")
        P.save_profile(path, dict(P.DEFAULT, name="Mine"))
        got = P.read_choice({"naming": {"selected": path, "profiles": [
            {"name": "Mine", "path": path}, {"name": 5}, "x"]}})
        self.assertEqual((got["selected"], got["profile"]["name"], got["note"]), (path, "Mine", ""))
        self.assertEqual(got["profiles"], [{"name": "Mine", "path": path}])

    def test_missing_file_falls_back_to_default_with_a_note(self):
        path = self.path("gone.rx-naming.json")
        prefs = {"naming": {"selected": path, "profiles": [{"name": "Gone", "path": path}]}}
        got = P.read_choice(prefs)
        self.assertEqual((got["selected"], got["profile"]), ("default", P.default_profile()))
        self.assertIn('"Gone"', got["note"])
        with unittest.mock.patch.dict(sys.modules, polish()):
            note = P.read_choice(prefs)["note"]
        self.assertIn("Nie można odczytać profilu", note)
        self.assertIn('"Gone"', note)

    def test_remember_keeps_other_keys(self):
        prefs = self.path("preferences.json")
        with open(prefs, "w") as handle:
            json.dump({"hide_node_notice": True, "naming": {"extra": 1}}, handle)
        entries = [{"name": "A", "path": "p"}]
        self.assertTrue(P.remember(prefs, "default", entries))
        with open(prefs) as handle:
            data = json.load(handle)
        self.assertEqual(data, {"hide_node_notice": True, "naming": {
            "extra": 1, "selected": "default", "profiles": entries}})
        self.assertTrue(P.remember(prefs, "none"))   # the profile list stays
        with open(prefs) as handle:
            self.assertEqual(json.load(handle)["naming"]["profiles"], entries)

    def test_remember_creates_the_file_and_never_raises(self):
        prefs = self.path("sub/preferences.json")
        self.assertTrue(P.remember(prefs, "default"))
        with open(prefs) as handle:
            self.assertEqual(json.load(handle), {"naming": {"selected": "default"}})
        self.assertFalse(P.remember("", "default"))
        self.assertFalse(P.remember(self.path("x"), "default", [None]))


class Preview(unittest.TestCase):
    SAMPLE = {"ViewFamily": "Floor Plan", "ViewName": "Level 1", "SheetNumber": "A101"}

    def test_default_profile(self):
        d = P.default_profile()
        self.assertEqual(P.preview(d, "views", self.SAMPLE), "Floor Plan - Level 1")
        self.assertEqual(P.preview(d, "sheets", self.SAMPLE), "A101 - 001")   # blank name

    def test_unusable_profile_gives_empty_text(self):
        self.assertEqual(P.preview({}, "views", {}), "")


class BlankCounter(unittest.TestCase):
    def test_001_002_and_1000(self):
        counter = rx_naming.Counter()
        parsed = rx_naming.parse_template("{SheetNumber}")
        names = [rx_naming.format_name(parsed, {}, "o", counter) for _ in range(1000)]
        self.assertEqual((names[0], names[1], names[998], names[999]),
                         ("001", "002", "999", "1000"))

    def test_counters_are_independent(self):
        # the restart per kind in a run is covered by test_naming.WriterTests
        a, b = rx_naming.Counter(), rx_naming.Counter()
        self.assertEqual((a.take(), a.take(), b.take()), ("001", "002", "001"))


if __name__ == "__main__":
    unittest.main()
