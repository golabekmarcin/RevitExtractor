# -*- coding: utf-8 -*-
"""Tests for lib/rx_cloud.py (specs/SPEC-cloud-catalog.md; pure Python, temporary folders only).

Every GUID and every project or file name here is synthetic (repeated digits, invented names).
"""
import ast
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import types
import unittest
import unittest.mock
from pathlib import Path

TESTS = Path(__file__).resolve().parent
LIB = TESTS.parents[2] / "lib"
FIXTURES = TESTS / "fixtures" / "cloud"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))

import rx_cloud  # noqa: E402
from rx_cloud import (CacheFile, Memory, Sighting, decode_journal, iter_journals,  # noqa: E402
                      normalize_guid, parse_journal, revit_folders, scan, scan_cache)

P1 = "11111111-1111-1111-1111-111111111111"
P2 = "22222222-2222-2222-2222-222222222222"
M3, M4, M5, M6 = ("%s-%s-%s-%s-%s" % (c * 8, c * 4, c * 4, c * 4, c * 12) for c in "3456")
ACCOUNT = "99999999"
GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
SYNTHETIC_NAMES = {"Demo Tower", "Alpha-Architecture.rvt", "Zażółć-Konstrukcja.rvt",
                   "Przykładowy Budynek Ż", "Beta-MEP.rvt", "Gamma-Browser.rvt"}


def polish():
    def get_locale_string(string_dict):
        for code in ("pl", "en_us"):
            if code in string_dict:
                return string_dict[code]
        return None
    applocales = types.SimpleNamespace(get_locale_string=get_locale_string)
    coreutils = types.SimpleNamespace(applocales=applocales)
    return {"pyrevit": types.SimpleNamespace(coreutils=coreutils),
            "pyrevit.coreutils": coreutils, "pyrevit.coreutils.applocales": applocales}


def path_line(project, pname, model, file_name, region="US", slashes="\\\\"):
    return ('ModelPath Created: Is server path = True, Region = "%s", Central server = "", '
            'Path = "CLD:%s%s%s{%s}%s%s{%s}%s"' % (region, slashes, region, slashes, project,
                                                  pname, slashes, model, file_name))


def browser_line(project, model, name):
    body = json.dumps({"projectGuid": project, "modelGuid": model, "displayName": name,
                       "region": "US"}, separators=(",", ":"))
    return 'Jrn.RibbonEvent "ModelBrowserOpenDocumentEvent:open:%s"' % body.replace('"', '""')


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rx-cloud-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def touch(self, *parts, **kw):
        path = os.path.join(self.tmp, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"x" * kw.get("size", 3))
        if "mtime" in kw:
            os.utime(path, (kw["mtime"], kw["mtime"]))
        return path


# ------------------------------------------------------------------ criterion 1

class ParseJournal(unittest.TestCase):
    def test_path_line_two_backslashes(self):
        got = list(parse_journal(path_line(P1, "Demo Tower", M3, "Alpha-Architecture.rvt")))
        self.assertEqual(got, [Sighting(P1, "Demo Tower", M3, "Alpha-Architecture.rvt", "path", "US")])

    def test_region_from_path_and_browser_lines(self):
        got = list(parse_journal(path_line(P1, "Demo Tower", M3, "A.rvt", region="EMEA")))
        self.assertEqual(got[0].region, "EMEA")
        self.assertEqual(list(parse_journal(browser_line(P1, M3, "B.rvt")))[0].region, "US")

    def test_sighting_without_region_defaults_to_empty(self):
        self.assertEqual(Sighting(P1, None, M3, "A.rvt", "button").region, "")

    def test_path_line_one_backslash(self):
        got = list(parse_journal(path_line(P1, "Demo Tower", M3, "A.rvt", slashes="\\")))
        self.assertEqual([(s.project_guid, s.model_guid, s.file_name) for s in got],
                         [(P1, M3, "A.rvt")])

    def test_url_encoded_project_name_is_decoded_as_utf8(self):
        got = list(parse_journal(path_line(P2, "Przyk\u0142adowy%20Budynek%20%C5%BB", M5, "B.rvt")))
        self.assertEqual(got[0].project_name, "Przyk\u0142adowy Budynek \u017b")

    def test_bad_percent_sequence_is_left_alone(self):
        got = list(parse_journal(path_line(P2, "Bad%FFName", M5, "B.rvt")))
        self.assertEqual(got[0].project_name, "Bad%FFName")

    def test_plain_spelling_of_the_same_project_wins(self):
        text = "\n".join([path_line(P1, "Demo%20Tower", M3, "A.rvt"),
                          path_line(P1, "Demo Tower", M4, "B.rvt")])
        self.assertEqual({s.project_name for s in parse_journal(text)}, {"Demo Tower"})

    def test_global_region_and_zero_guids_are_skipped(self):
        text = "\n".join([path_line(P1, "Demo Tower", M3, "A.rvt", region="GLOBAL"),
                          path_line("0" * 8 + "-" + "-".join(["0" * 4] * 3) + "-" + "0" * 12,
                                    "Zero", M4, "B.rvt"),
                          path_line(P1, "Demo Tower", "0" * 8 + "-" + "-".join(["0" * 4] * 3)
                                    + "-" + "0" * 12, "C.rvt")])
        self.assertEqual(list(parse_journal(text)), [])

    def test_browser_line_uppercase_and_braced_guids_are_normalised(self):
        project, model = "A" * 8 + "-" + "-".join(["A" * 4] * 3) + "-" + "A" * 12, \
            "{" + "B" * 8 + "-" + "-".join(["B" * 4] * 3) + "-" + "B" * 12 + "}"
        got = list(parse_journal(browser_line(project, model, "Gamma-Browser.rvt")))
        self.assertEqual(got, [Sighting(project.lower(), None, normalize_guid(model),
                                        "Gamma-Browser.rvt", "browser", "US")])
        self.assertEqual(got[0].model_guid, got[0].model_guid.lower())
        self.assertNotIn("{", got[0].model_guid)

    def test_broken_json_and_unrelated_lines_are_ignored(self):
        text = "\n".join(['Jrn.RibbonEvent "ModelBrowserOpenDocumentEvent:open:{""projectGuid"":"" x',
                          'Jrn.RibbonEvent "ModelBrowserOpenDocumentEvent:open:[1,2]"',
                          'Jrn.RibbonEvent "ModelBrowserOpenDocumentEvent:open:{}"',
                          "Open Cloud Model Method: open, Region: US, Model Guid: %s" % M3,
                          "' just a comment", "", "ModelPath Created: no path here"])
        self.assertEqual(list(parse_journal(text)), [])

    def test_a_guid_is_never_a_name(self):
        got = list(parse_journal(path_line(P1, M5, M3, "A.rvt")))
        self.assertEqual(got[0].project_name, None)
        # a file name that is a GUID is dropped: nothing to show
        self.assertEqual(list(parse_journal(path_line(P1, "Demo", M4, M6 + ".rvt"))), [])

    def test_never_raises_on_odd_input(self):
        self.assertEqual(list(parse_journal(None)), [])
        self.assertEqual(list(parse_journal("")), [])

    def test_fixtures_agree_in_all_three_encodings(self):
        results = []
        for name in ("journal-utf8.txt", "journal-utf16.txt", "journal-cp1250.txt"):
            text = decode_journal((FIXTURES / name).read_bytes())
            results.append(sorted(parse_journal(text)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])
        names = {(s.project_name, s.file_name) for s in results[0]}
        self.assertEqual(names, {("Demo Tower", "Alpha-Architecture.rvt"),
                                 ("Demo Tower", "Za\u017c\u00f3\u0142\u0107-Konstrukcja.rvt"),
                                 ("Przyk\u0142adowy Budynek \u017b", "Beta-MEP.rvt"),
                                 (None, "Gamma-Browser.rvt")})


# ------------------------------------------------------------------ criterion 2

class DecodeJournal(unittest.TestCase):
    TEXT = "Za\u017c\u00f3\u0142\u0107 g\u0119\u015bl\u0105 ja\u017a\u0144 \u2013 test"

    def test_utf16_with_bom(self):
        self.assertEqual(decode_journal(b"\xff\xfe" + self.TEXT.encode("utf-16-le")), self.TEXT)
        self.assertEqual(decode_journal(b"\xfe\xff" + self.TEXT.encode("utf-16-be")), self.TEXT)

    def test_utf8_with_polish_letters_and_bom(self):
        self.assertEqual(decode_journal(self.TEXT.encode("utf-8")), self.TEXT)
        self.assertEqual(decode_journal(b"\xef\xbb\xbf" + self.TEXT.encode("utf-8")), self.TEXT)

    def test_cp1250_fallback(self):
        text = "Za\u017c\u00f3\u0142\u0107 g\u0119\u015bl\u0105 ja\u017a\u0144"
        self.assertEqual(decode_journal(text.encode("cp1250")), text)

    def test_never_raises(self):
        for raw in (b"", None, b"\x81\x8d\x8f\x90\x9d", b"\xff", bytearray(b"abc"), 42):
            self.assertIsInstance(decode_journal(raw), str)


class IterJournals(TempCase):
    def test_newest_first_limit_and_only_journal_files(self):
        for n, mtime in ((1, 1000), (2, 3000), (3, 2000)):
            self.touch("journal.%04d.txt" % n, mtime=mtime)
        self.touch("notes.txt", mtime=9000)
        self.touch("journal.0009.log", mtime=9000)
        got = list(iter_journals(self.tmp))
        self.assertEqual([os.path.basename(p) for p, _ in got],
                         ["journal.0002.txt", "journal.0003.txt", "journal.0001.txt"])
        self.assertEqual([m for _, m in got], [3000, 2000, 1000])
        self.assertEqual(len(list(iter_journals(self.tmp, limit=2))), 2)
        self.assertEqual(list(iter_journals(self.tmp, limit=0)), [])

    def test_unreadable_files_are_skipped_and_counted(self):
        self.touch("journal.0001.txt", mtime=1000)
        self.touch("journal.0002.txt", mtime=2000)

        def stat(path):
            if path.endswith("0002.txt"):
                raise OSError("locked")
            return os.stat(path)
        errors = []
        got = list(iter_journals(self.tmp, stat=stat, errors=errors))
        self.assertEqual([os.path.basename(p) for p, _ in got], ["journal.0001.txt"])
        self.assertEqual(len(errors), 1)

    def test_missing_folder_is_reported_not_raised(self):
        errors = []
        self.assertEqual(list(iter_journals(os.path.join(self.tmp, "none"), errors=errors)), [])
        self.assertEqual(len(errors), 1)


class Folders(unittest.TestCase):
    def test_revit_folders(self):
        got = revit_folders("C:\\L", 2022)
        self.assertEqual(got["cache"], os.path.join("C:\\L", "Autodesk", "Revit",
                                                    "Autodesk Revit 2022", "CollaborationCache"))
        self.assertTrue(got["journals"].endswith(os.path.join("Autodesk Revit 2022", "Journals")))


# ------------------------------------------------------------------ criterion 3

class ScanCache(TempCase):
    def test_root_linked_ignored_names_and_two_accounts(self):
        a = lambda *p: self.touch("CollaborationCache", ACCOUNT, P1, *p, size=5)  # noqa: E731
        a(M3 + ".rvt")
        a("LinkedModels", M4 + ".rvt")
        a("CentralCache", M5 + ".rvt")
        a("LinkedModels", "CentralCache", M6 + ".rvt")
        a("notes.rvt")
        a(M3 + ".0001.rvt")
        a(M3 + ".rvt.txt")
        a("LinkedModels", "readme.txt")
        self.touch("CollaborationCache", ACCOUNT, "not-a-guid", M3 + ".rvt")
        self.touch("CollaborationCache", "88888888", P1, M3.upper() + ".RVT", size=7)
        self.touch("CollaborationCache", "stray.rvt")
        errors = []
        got = list(scan_cache(os.path.join(self.tmp, "CollaborationCache"), errors=errors))
        got = sorted((f.account, f.project_guid, f.model_guid, f.place, f.size) for f in got)
        self.assertEqual(got, [("88888888", P1, M3, "root", 7), (ACCOUNT, P1, M3, "root", 5),
                               (ACCOUNT, P1, M4, "linked", 5)])
        self.assertEqual(errors, [])

    def test_missing_root_is_reported_not_raised(self):
        errors = []
        self.assertEqual(list(scan_cache(os.path.join(self.tmp, "nope"), errors=errors)), [])
        self.assertTrue(errors)

    def test_stat_failure_skips_the_file(self):
        self.touch("c", ACCOUNT, P1, M3 + ".rvt")
        self.touch("c", ACCOUNT, P1, M4 + ".rvt")

        def stat(path):
            if M3 in path:
                raise OSError("gone")
            return os.stat(path)
        errors = []
        got = list(scan_cache(os.path.join(self.tmp, "c"), stat=stat, errors=errors))
        self.assertEqual([f.model_guid for f in got], [M4])
        self.assertEqual(len(errors), 1)

    def test_walk_that_raises_is_contained(self):
        def walk(*args, **kwargs):
            raise RuntimeError("boom")
        self.assertEqual(list(scan_cache(self.tmp, walk=walk)), [])


# ------------------------------------------------------------------ criterion 5

class MemoryTests(TempCase):
    def path(self):
        return os.path.join(self.tmp, "profile", "cloud-catalog.json")

    def test_round_trip_and_folder_is_created(self):
        memory = Memory(self.path()).load()
        memory.merge([Sighting(P1, "Demo Tower", M3, "Alpha-Architecture.rvt", "path")], 100.0)
        memory.set_included([ACCOUNT + "/" + P1])
        memory.store_links("k", 50.0, [{"name": "L.rvt", "model_guid": M4}])
        self.assertTrue(memory.save())
        again = Memory(self.path()).load()
        self.assertEqual(again.project_name(P1), "Demo Tower")
        self.assertEqual(again.model_name(P1, M3), "Alpha-Architecture.rvt")
        self.assertEqual(again.included, {ACCOUNT + "/" + P1})
        self.assertEqual(again.links_for("k", 50.0), [{"name": "L.rvt", "model_guid": M4}])

    def test_region_round_trip_and_old_entry_gives_empty(self):
        memory = Memory(self.path()).load()
        memory.merge([Sighting(P1, "Demo Tower", M3, "A.rvt", "path", "EMEA"),
                      Sighting(P1, None, M4, "B.rvt", "path")], 100.0)
        memory.save()
        again = Memory(self.path()).load()
        self.assertEqual(again.model_region(P1, M3), "EMEA")
        self.assertEqual(again.model_region(P1, M4), "")
        self.assertEqual(again.model_region(P1, M5), "")
        # a later sighting that does not name a region keeps the known one
        again.merge([Sighting(P1, None, M3, "A.rvt", "browser")], 200.0)
        self.assertEqual(again.model_region(P1, M3), "EMEA")

    def test_memory_file_without_region_key_loads(self):
        os.makedirs(os.path.dirname(self.path()))
        Path(self.path()).write_text(json.dumps({
            "version": rx_cloud.MEMORY_VERSION, "included": [], "projects": {}, "links": {},
            "names": {P1 + "/" + M3: {"name": "Old.rvt", "mtime": 1.0}}}), encoding="utf-8")
        memory = Memory(self.path()).load()
        self.assertEqual(memory.model_name(P1, M3), "Old.rvt")
        self.assertEqual(memory.model_region(P1, M3), "")

    def test_polish_names_survive_the_file(self):
        memory = Memory(self.path()).load()
        memory.merge([Sighting(P1, "Przyk\u0142ad", M3, "Za\u017c\u00f3\u0142\u0107.rvt", "path")], 1.0)
        memory.save()
        raw = Path(self.path()).read_bytes()
        raw.decode("ascii")  # dumps_ascii: pure ASCII on disk
        self.assertEqual(Memory(self.path()).load().model_name(P1, M3), "Za\u017c\u00f3\u0142\u0107.rvt")

    def test_missing_corrupt_and_other_version_files_give_an_empty_memory(self):
        empty = lambda m: (m.included, m.projects, m.names, m.links)  # noqa: E731
        self.assertEqual(empty(Memory(self.path()).load()), (set(), {}, {}, {}))
        os.makedirs(os.path.dirname(self.path()))
        for text in ("{not json", json.dumps({"version": 99, "included": ["a"], "projects": {},
                                              "names": {}, "links": {}}),
                     json.dumps({"version": 1, "included": "x", "projects": {}, "names": {},
                                 "links": {}}), "[]"):
            Path(self.path()).write_text(text, encoding="utf-8")
            self.assertEqual(empty(Memory(self.path()).load()), (set(), {}, {}, {}), text)

    def test_newest_journal_wins_and_older_never_overwrites(self):
        memory = Memory(self.path())
        memory.merge([Sighting(P1, "New Name", M3, "New.rvt", "path")], 200.0)
        memory.merge([Sighting(P1, "Old Name", M3, "Old.rvt", "path")], 100.0)
        self.assertEqual((memory.project_name(P1), memory.model_name(P1, M3)),
                         ("New Name", "New.rvt"))
        memory.merge([Sighting(P1, "Newer", M3, "Newer.rvt", "path")], 300.0)
        self.assertEqual(memory.model_name(P1, M3), "Newer.rvt")

    def test_within_one_journal_the_later_line_wins(self):
        memory = Memory(self.path())
        memory.merge([Sighting(P1, None, M3, "First.rvt", "path"),
                      Sighting(P1, None, M3, "Second.rvt", "browser")], 100.0)
        self.assertEqual(memory.model_name(P1, M3), "Second.rvt")

    def test_a_sighting_without_a_project_name_keeps_the_name(self):
        memory = Memory(self.path())
        memory.merge([Sighting(P1, "Demo Tower", M3, "A.rvt", "path")], 100.0)
        memory.merge([Sighting(P1, None, M4, "B.rvt", "browser")], 200.0)
        self.assertEqual(memory.project_name(P1), "Demo Tower")

    def test_a_stored_guid_like_name_is_not_returned(self):
        memory = Memory(self.path())
        memory.names[P1 + "/" + M3] = {"name": M4, "mtime": 1}
        self.assertIsNone(memory.model_name(P1, M3))

    def test_links_for_is_invalid_after_the_host_mtime_changed(self):
        memory = Memory(self.path())
        memory.store_links("k", 100.0, [{"name": "L.rvt"}])
        self.assertIsNotNone(memory.links_for("k", 100.0))
        self.assertIsNone(memory.links_for("k", 101.0))
        self.assertIsNone(memory.links_for("other", 100.0))

    def test_saves_through_a_temp_file_and_leaves_none_behind(self):
        memory = Memory(self.path())
        memory.merge([Sighting(P1, "A", M3, "A.rvt", "path")], 1.0)
        self.assertTrue(memory.save())
        self.assertTrue(memory.save())  # overwriting an existing file
        self.assertEqual(os.listdir(os.path.dirname(self.path())), ["cloud-catalog.json"])
        source = Path(rx_cloud.__file__).read_text(encoding="utf-8")
        self.assertIn('".tmp"', source)

    def test_cut_off_save_keeps_the_old_names_in_a_bak_file(self):
        memory = Memory(self.path())
        memory.merge([Sighting(P1, "A", M3, "A.rvt", "path")], 1.0)
        self.assertTrue(memory.save())
        # simulate a crash between the two renames: the file is gone, .bak holds the old one
        os.rename(self.path(), self.path() + ".bak")
        again = Memory(self.path()).load()
        self.assertEqual(again.names, memory.names)
        self.assertTrue(again.save())    # the next save puts a real file back and drops the .bak
        self.assertEqual(os.listdir(os.path.dirname(self.path())), ["cloud-catalog.json"])

    def test_failed_save_is_reported_not_raised(self):
        blocker = self.touch("file")
        memory = Memory(os.path.join(blocker, "sub", "m.json"))
        self.assertFalse(memory.save())
        self.assertEqual(memory.last_error is not None, True)
        self.assertNotIn(self.tmp, memory.last_error)  # type name only, no paths


# ------------------------------------------------------------------ criterion 4

NOW = 2_000_000_000.0
DAY = 86400.0


def folders_for(tmp):
    return {"cache": os.path.join(tmp, "cache"), "journals": os.path.join(tmp, "journals")}


class CatalogCase(TempCase):
    def journal(self, lines, name="journal.0001.txt", mtime=NOW - DAY):
        path = os.path.join(self.tmp, "journals", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write("\r\n".join(lines) + "\r\n")
        os.utime(path, (mtime, mtime))
        return path

    def cache(self, project, model, place="root", account=ACCOUNT, age_days=1.0, size=10):
        parts = ["cache", account, project] + (["LinkedModels"] if place == "linked" else [])
        return self.touch(*(parts + [model + ".rvt"]), size=size, mtime=NOW - age_days * DAY)

    def run_scan(self, memory=None, select=True, **kwargs):
        memory = memory or Memory(os.path.join(self.tmp, "mem.json"))
        if select and not memory.included:
            memory.set_included([ACCOUNT + "/" + P1, ACCOUNT + "/" + P2])
        steps, catalog = 0, None
        for item in scan(folders_for(self.tmp), memory, NOW, **kwargs):
            if item is None:
                steps += 1
            else:
                catalog = item
        self.catalog, self.steps, self.memory = catalog, steps, memory
        return catalog


class CatalogStates(CatalogCase):
    def test_row_carries_the_region_and_an_old_memory_gives_empty(self):
        self.journal([path_line(P1, "Demo Tower", M3, "A.rvt", region="EMEA")])
        self.cache(P1, M3)
        self.cache(P1, M4)
        memory = Memory(os.path.join(self.tmp, "mem.json"))
        memory.names[P1 + "/" + M4] = {"name": "Old.rvt", "mtime": 1.0}  # a pre-region entry
        by_name = {r.name: r for r in self.run_scan(memory).rows}
        self.assertEqual(by_name["A.rvt"].region, "EMEA")
        self.assertEqual(by_name["Old.rvt"].region, "")

    def test_every_state_and_the_root_rule(self):
        self.journal([path_line(P1, "Demo Tower", M3, "Alpha-Architecture.rvt"),
                      path_line(P1, "Demo Tower", M4, "Old-Model.rvt"),
                      path_line(P1, "Demo Tower", M5, "alpha-architecture.RVT"),
                      path_line(P2, "Other Site", M6, "Beta-MEP.rvt")])
        self.cache(P1, M3, "root", age_days=2.0)
        self.cache(P1, M3, "linked", age_days=0.5)        # newer, but a host row is the root file
        self.cache(P1, M4, age_days=30.0)                  # stale
        self.cache(P1, M5, age_days=9.0)                   # duplicate name (older)
        self.memory_ = Memory(os.path.join(self.tmp, "mem.json"))
        self.memory_.set_included([ACCOUNT + "/" + P1])    # P2 not selected
        self.cache(P2, M6, age_days=1.0)
        catalog = self.run_scan(self.memory_)
        by_name = {r.name: r for r in catalog.rows}
        self.assertEqual(by_name["Alpha-Architecture.rvt"].state, "ok")
        self.assertEqual(by_name["Alpha-Architecture.rvt"].place, "root")
        self.assertNotIn("LinkedModels", by_name["Alpha-Architecture.rvt"].cache_path)
        self.assertAlmostEqual(by_name["Alpha-Architecture.rvt"].cache_mtime, NOW - 2.0 * DAY)
        self.assertEqual(by_name["Old-Model.rvt"].state, "stale")
        self.assertTrue(by_name["Old-Model.rvt"].enabled)
        self.assertIn(by_name["Old-Model.rvt"].cache_date, by_name["Old-Model.rvt"].note)
        self.assertEqual(by_name["alpha-architecture.RVT"].state, "duplicate")
        self.assertFalse(by_name["alpha-architecture.RVT"].enabled)
        self.assertEqual(by_name["Beta-MEP.rvt"].state, "not_selected")
        self.assertFalse(by_name["Beta-MEP.rvt"].enabled)
        for row in catalog.rows:
            self.assertEqual(row.key, "cloud:%s/%s" % (row.project_guid, row.model_guid))
        self.assertEqual(set(r.state for r in catalog.rows),
                         {"ok", "stale", "duplicate", "not_selected"})

    def test_root_wins_a_tie_between_root_and_linked(self):
        self.journal([path_line(P1, "Demo Tower", M3, "A.rvt")])
        self.cache(P1, M3, "root", age_days=1.0)
        self.cache(P1, M3, "linked", age_days=1.0)
        self.assertEqual(self.run_scan().rows[0].place, "root")

    def test_same_project_under_two_accounts_lists_the_newest_once(self):
        self.journal([path_line(P1, "Demo Tower", M3, "A.rvt")])
        self.cache(P1, M3, account="88888888", age_days=5.0)
        self.cache(P1, M3, account=ACCOUNT, age_days=1.0)
        catalog = self.run_scan()
        self.assertEqual([(r.account, r.state) for r in catalog.rows], [(ACCOUNT, "ok")])
        self.assertEqual([p.account for p in catalog.projects], [ACCOUNT])

    def test_nothing_is_selected_by_default(self):
        self.journal([path_line(P1, "Demo Tower", M3, "A.rvt")])
        self.cache(P1, M3)
        catalog = self.run_scan(select=False)
        self.assertEqual([r.state for r in catalog.rows], ["not_selected"])
        self.assertFalse(catalog.projects[0].selected)

    def test_unnamed_files_are_counted_per_project_and_never_listed(self):
        self.journal([path_line(P1, "Demo Tower", M3, "A.rvt")])
        self.cache(P1, M3)
        self.cache(P1, M4)
        self.cache(P1, M5, "linked")
        catalog = self.run_scan()
        self.assertEqual([r.name for r in catalog.rows], ["A.rvt"])
        project = catalog.projects[0]
        self.assertEqual((project.count, project.unnamed), (1, 2))
        self.assertIn("2", project.note)
        self.assertEqual(catalog.counts["unnamed"], 2)

    def test_a_project_with_only_unnamed_files_is_still_listed_without_a_guid_name(self):
        self.cache(P2, M5)
        catalog = self.run_scan()
        self.assertEqual(catalog.rows, [])
        self.assertEqual(catalog.projects[0].name, "(project name unknown)")
        self.assertEqual(catalog.projects[0].unnamed, 1)

    def test_a_model_without_a_project_name_gets_the_placeholder(self):
        self.journal([browser_line(P1, M3, "Gamma-Browser.rvt")])
        self.cache(P1, M3)
        self.assertEqual(self.run_scan().rows[0].project, "(project name unknown)")

    def test_no_displayed_text_matches_the_guid_pattern(self):
        self.journal([path_line(P1, M5, M3, "A.rvt"), path_line(P1, "Demo Tower", M4, "B.rvt"),
                      browser_line(P2, M6, "Gamma-Browser.rvt"), path_line(P2, M6, M5, M3 + ".rvt")])
        for m in (M3, M4, M5, M6):
            self.cache(P1, m, age_days=20.0)
            self.cache(P2, m, age_days=20.0)
        for lang in ("en", "pl"):
            with unittest.mock.patch.dict(sys.modules, polish() if lang == "pl" else {}):
                catalog = self.run_scan(Memory(os.path.join(self.tmp, "m-%s.json" % lang)))
            texts = [catalog.message]
            for row in catalog.rows:
                texts += [row.name, row.project, row.note, row.cache_date, row.state]
            for project in catalog.projects:
                texts += [project.name, project.note]
            for text in texts:
                self.assertFalse(GUID_RE.search(text), text)
            self.assertTrue(catalog.rows)

    def test_notes_exist_in_both_languages(self):
        self.journal([path_line(P1, "Demo Tower", M3, "A.rvt"), path_line(P1, "Demo Tower", M4, "a.rvt"),
                      path_line(P1, "Demo Tower", M5, "C.rvt")])
        self.cache(P1, M3, age_days=1.0)
        self.cache(P1, M4, age_days=3.0)
        self.cache(P1, M5, age_days=30.0)
        self.cache(P1, M6)
        english, polish_text = {}, {}
        for store, patch in ((english, {}), (polish_text, polish())):
            with unittest.mock.patch.dict(sys.modules, patch):
                catalog = self.run_scan(Memory(os.path.join(self.tmp, "m%d.json" % len(store))))
                store.update((r.state, r.note) for r in catalog.rows)
                store["unnamed"] = catalog.projects[0].note
        self.assertEqual(set(english), set(polish_text))
        for key in english:
            self.assertTrue(english[key] and polish_text[key] or key == "ok", key)
            if english[key]:
                self.assertNotEqual(english[key], polish_text[key], key)

    def test_no_journal_data_gives_the_message_and_falls_back_to_the_memory(self):
        memory = Memory(os.path.join(self.tmp, "mem.json"))
        memory.merge([Sighting(P1, "Demo Tower", M3, "A.rvt", "path")], 1.0)
        self.cache(P1, M3)
        catalog = self.run_scan(memory)
        self.assertIn("No cloud model names", catalog.message)
        self.assertEqual([r.name for r in catalog.rows], ["A.rvt"])
        self.assertEqual(catalog.counts["journals_folder_missing"], 1)
        with unittest.mock.patch.dict(sys.modules, polish()):
            self.assertIn("dziennikach", self.run_scan(memory).message)

    def test_journal_names_reach_the_memory_file(self):
        self.journal([path_line(P1, "Demo Tower", M3, "A.rvt")])
        self.cache(P1, M3)
        self.run_scan()
        self.assertEqual(Memory(os.path.join(self.tmp, "mem.json")).load().model_name(P1, M3),
                         "A.rvt")
        self.assertEqual(self.catalog.message, "")

    def test_newest_journal_wins_across_files(self):
        self.journal([path_line(P1, "Demo Tower", M3, "Old.rvt")], "journal.0001.txt", NOW - 5 * DAY)
        self.journal([path_line(P1, "Demo Tower", M3, "New.rvt")], "journal.0002.txt", NOW - DAY)
        self.cache(P1, M3)
        self.assertEqual([r.name for r in self.run_scan().rows], ["New.rvt"])

    def test_unreadable_journal_is_counted_and_the_scan_goes_on(self):
        self.journal([path_line(P1, "Demo Tower", M3, "A.rvt")], "journal.0001.txt")
        self.journal([path_line(P1, "Demo Tower", M4, "B.rvt")], "journal.0002.txt", NOW)
        self.cache(P1, M3)
        self.cache(P1, M4)
        from rx_cloud import read_bytes

        def read(path):
            if path.endswith("0002.txt"):
                raise IOError("locked")
            return read_bytes(path)
        catalog = self.run_scan(read=read)
        self.assertEqual(catalog.counts["journals_unreadable"], 1)
        self.assertEqual(catalog.counts["journals"], 1)
        self.assertEqual(len(catalog.rows), 1)

    def test_missing_cache_folder_gives_no_rows_and_does_not_raise(self):
        self.journal([path_line(P1, "Demo Tower", M3, "A.rvt")])
        catalog = self.run_scan()
        self.assertEqual((catalog.rows, catalog.projects), ([], []))
        self.assertGreater(catalog.counts["cache_errors"], 0)

    def test_stale_threshold_is_a_parameter(self):
        self.journal([path_line(P1, "Demo Tower", M3, "A.rvt")])
        self.cache(P1, M3, age_days=3.0)
        self.assertEqual(self.run_scan().rows[0].state, "ok")
        self.assertEqual(self.run_scan(stale_days=2).rows[0].state, "stale")

    def test_scan_yields_a_step_per_journal_chunk_and_the_catalog_last(self):
        self.journal(["' filler"] * 25 + [path_line(P1, "Demo Tower", M3, "A.rvt")])
        self.cache(P1, M3)
        memory = Memory(os.path.join(self.tmp, "mem.json"))
        items = list(scan(folders_for(self.tmp), memory, NOW, budget=10))
        self.assertTrue(all(i is None for i in items[:-1]))
        self.assertIsInstance(items[-1], rx_cloud.Catalog)
        self.assertGreaterEqual(len([i for i in items if i is None]), 3 + 1)
        self.assertEqual(items[-1].counts["sightings"], 1)

    def test_closing_the_generator_early_raises_nothing(self):
        self.journal(["' filler"] * 50)
        generator = scan(folders_for(self.tmp), Memory(os.path.join(self.tmp, "m.json")), NOW,
                         budget=5)
        next(generator)
        generator.close()

    def test_failed_memory_save_does_not_stop_the_scan(self):
        self.journal([path_line(P1, "Demo Tower", M3, "A.rvt")])
        self.cache(P1, M3)
        blocker = self.touch("blocker")
        memory = Memory(os.path.join(blocker, "sub", "m.json"))
        catalog = self.run_scan(memory)
        self.assertEqual(len(catalog.rows), 1)
        self.assertIsNotNone(memory.last_error)

    def test_cache_files_are_never_modified(self):
        self.journal([path_line(P1, "Demo Tower", M3, "A.rvt")])
        path = self.cache(P1, M3)
        before = (os.stat(path).st_size, os.stat(path).st_mtime)
        self.run_scan()
        self.assertEqual(before, (os.stat(path).st_size, os.stat(path).st_mtime))
        source = Path(rx_cloud.__file__).read_text(encoding="utf-8")
        for call in ('"w"', '"a"', '"wb"', "os.remove(", "shutil"):
            if call == "os.remove(":
                self.assertEqual(source.count(call), 3)  # Memory.save only (the .bak twice + its temp)
            else:
                self.assertNotIn(call, source.replace('io.open(temp_path, "w"', ""))


class Timing(CatalogCase):
    def test_a_hundred_one_megabyte_journals_and_a_thousand_cache_files(self):
        line = "         ModelPath Created: Is server path = True, Region = \"US\", Path = " \
               "\"CLD:\\\\US\\\\{%s}Demo Tower\\\\{%s}File-%%d.rvt\"\r\n" % (P1, M3)
        noise = ("Jrn.Command \"Ribbon\" , \"synthetic noise line to fill the file\"\r\n" * 14000)
        for n in range(100):
            body = noise + "".join(line % (n * 10 + k) for k in range(10))
            path = os.path.join(self.tmp, "journals", "journal.%04d.txt" % n)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(body.encode("utf-8"))
            os.utime(path, (NOW - n, NOW - n))
        for n in range(1000):
            self.touch("cache", ACCOUNT, P1, "%08d-0000-0000-0000-%012d.rvt" % (n, n), size=1)
        memory = Memory(os.path.join(self.tmp, "mem.json"))
        started = time.time()
        slowest, last = 0.0, started
        steps, catalog = 0, None
        for item in scan(folders_for(self.tmp), memory, NOW, limit=100):
            now = time.time()
            slowest, last = max(slowest, now - last), now
            if item is None:
                steps += 1
            else:
                catalog = item
        total = time.time() - started
        print("cloud scan: 100 x ~1 MB journals + 1000 cache files: %.2f s total, "
              "slowest step %.3f s, %d steps" % (total, slowest, steps))
        self.assertEqual(catalog.counts["journals"], 100)
        self.assertEqual(catalog.counts["sightings"], 1000)
        self.assertEqual(catalog.counts["cache_files"], 1000)
        self.assertLess(total, 60.0)
        self.assertLess(slowest, 2.0)


# ------------------------------------------------------------------ criterion 6 (plan_stage)

M9 = "%s-%s-%s-%s-%s" % ("9" * 8, "9" * 4, "9" * 4, "9" * 4, "9" * 12)


def cache_file(project, model, place="root", mtime=NOW - DAY, size=10, account=ACCOUNT):
    sub = "LinkedModels\\" if place == "linked" else ""
    path = "C:\\cache\\%s\\%s\\%s%s.rvt" % (account, project, sub, model)
    return CacheFile(account, project, model, place, path, size, mtime)


def host_row(name="Alpha-Architecture.rvt", project=P1, model=M3, mtime=NOW - DAY, size=10):
    return rx_cloud.CloudRow(
        key="cloud:%s/%s" % (project, model), project="Demo Tower", name=name,
        cache_path="C:\\cache\\%s\\%s\\%s.rvt" % (ACCOUNT, project, model),
        cache_date="2026-01-01", size=size, state="ok", enabled=True, note="", account=ACCOUNT,
        project_guid=project, model_guid=model, place="root", cache_mtime=mtime)


def link(name, project, model, nested=False):
    return {"name": name, "project_guid": project, "model_guid": model, "region": "US",
            "nested": nested}


class PlanStage(unittest.TestCase):
    def setUp(self):
        self.memory = Memory(os.path.join(tempfile.gettempdir(), "rx-never-written.json"))

    def plan(self, links, files, row=None, memory=None):
        return rx_cloud.plan_stage(row or host_row(), links, files, memory or self.memory)

    def test_host_comes_first_and_keeps_its_cache_facts(self):
        row = host_row(size=123, mtime=NOW - 5)
        plan = self.plan([link("Beta-MEP.rvt", P1, M4)], [cache_file(P1, M4, size=7)], row=row)
        host = plan.items[0]
        self.assertEqual((host.src, host.name, host.size, host.mtime),
                         (row.cache_path, "Alpha-Architecture.rvt", 123, NOW - 5))
        self.assertEqual([i.name for i in plan.items], ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])
        self.assertEqual(plan.items[1].size, 7)
        self.assertEqual(plan.notes, [])

    def test_link_found_in_another_project_and_account_by_both_guids(self):
        files = [cache_file(P2, M3, size=1),                       # same model GUID, other project
                 cache_file(P2, M5, account="88888888", size=55)]
        plan = self.plan([link("Gamma-Browser.rvt", P2, M5)], files)
        self.assertEqual([(i.name, i.size) for i in plan.items[1:]], [("Gamma-Browser.rvt", 55)])
        self.assertIn("88888888", plan.items[1].src)

    def test_newer_of_root_and_linked_copy_is_used(self):
        files = [cache_file(P2, M5, "root", mtime=NOW - 9 * DAY, size=1),
                 cache_file(P2, M5, "linked", mtime=NOW - DAY, size=2)]
        plan = self.plan([link("Gamma-Browser.rvt", P2, M5)], files)
        self.assertEqual((plan.items[1].size, plan.items[1].mtime), (2, NOW - DAY))
        self.assertIn("LinkedModels", plan.items[1].src)

    def test_guids_are_normalised_for_the_lookup(self):
        plan = self.plan([link("Beta-MEP.rvt", "{%s}" % P2.upper(), M5.upper())],
                         [cache_file(P2, M5)])
        self.assertEqual([i.name for i in plan.items], ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])

    def test_missing_link_gives_a_note_and_the_export_goes_on(self):
        plan = self.plan([link("Beta-MEP.rvt", P2, M5), link("Gamma-Browser", P2, M6)],
                         [cache_file(P2, M6)])
        self.assertEqual([i.name for i in plan.items], ["Alpha-Architecture.rvt",
                                                        "Gamma-Browser.rvt"])
        self.assertEqual(plan.notes, ["Link Beta-MEP.rvt is not in the cache; exported without it."])

    def test_link_without_ids_is_missing(self):
        plan = self.plan([{"name": "Beta-MEP.rvt"}, link("Gamma-Browser.rvt", None, "")],
                         [cache_file(P2, M5)])
        self.assertEqual(len(plan.items), 1)
        self.assertEqual(len(plan.notes), 2)
        self.assertTrue(all("is not in the cache" in n for n in plan.notes))

    def test_case_insensitive_clash_skips_the_later_one(self):
        files = [cache_file(P2, M4), cache_file(P2, M5)]
        plan = self.plan([link("beta-mep.RVT", P2, M4), link("BETA-MEP", P2, M5),
                          link("ALPHA-architecture.rvt", P2, M5)], files)
        self.assertEqual([i.name for i in plan.items], ["Alpha-Architecture.rvt", "beta-mep.RVT"])
        self.assertEqual(plan.notes, [
            "Link BETA-MEP.rvt was not copied: another file in this export has the same name.",
            "Link ALPHA-architecture.rvt was not copied: another file in this export has the "
            "same name."])

    def test_the_same_link_twice_is_copied_once_without_a_note(self):
        plan = self.plan([link("Beta-MEP.rvt", P2, M5), link("Beta-MEP.rvt", P2, M5, nested=True)],
                         [cache_file(P2, M5)])
        self.assertEqual([i.name for i in plan.items], ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])
        self.assertEqual(plan.notes, [])

    def test_rvt_is_added_when_missing_and_nested_links_are_included(self):
        plan = self.plan([link("Beta-MEP", P2, M4), link("Gamma-Browser.Rvt", P2, M5, nested=True)],
                         [cache_file(P2, M4), cache_file(P2, M5)],
                         row=host_row(name="Alpha-Architecture"))
        self.assertEqual([i.name for i in plan.items],
                         ["Alpha-Architecture.rvt", "Beta-MEP.rvt", "Gamma-Browser.Rvt"])

    def test_link_list_comes_from_the_memory_when_not_given(self):
        memory = Memory(os.path.join(tempfile.gettempdir(), "rx-never-written.json"))
        memory.store_links(rx_cloud.model_key(P1, M3), NOW - DAY, [link("Beta-MEP.rvt", P2, M5)])
        plan = self.plan(None, [cache_file(P2, M5)], memory=memory)
        self.assertEqual([i.name for i in plan.items], ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])
        stale = self.plan(None, [cache_file(P2, M5)], row=host_row(mtime=NOW), memory=memory)
        self.assertEqual([i.name for i in stale.items], ["Alpha-Architecture.rvt"])

    def test_a_link_without_a_name_uses_the_memory_name_never_a_guid(self):
        memory = Memory(os.path.join(tempfile.gettempdir(), "rx-never-written.json"))
        memory.merge([Sighting(P2, None, M5, "Beta-MEP.rvt", "path")], NOW)
        plan = self.plan([link("", P2, M5), link(M6 + ".rvt", P2, M6)],
                         [cache_file(P2, M5), cache_file(P2, M6)], memory=memory)
        self.assertEqual([i.name for i in plan.items], ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])
        self.assertEqual(len(plan.notes), 1)
        for text in plan.notes + [i.name for i in plan.items]:
            self.assertFalse(GUID_RE.search(text), text)

    def test_unsafe_link_names_are_skipped_with_a_note(self):
        bad = ["..\\Beta-MEP.rvt", "sub/Beta-MEP.rvt", "C:Beta.rvt", "CON.rvt", "nul", "a\x01.rvt",
               "Beta?.rvt", "Beta<1>.rvt", "Beta|x.rvt", 'Be"ta.rvt', "Beta*.rvt", "..", ".",
               "x" * 300]
        plan = self.plan([link(n, P2, M5) for n in bad], [cache_file(P2, M5)])
        self.assertEqual([i.name for i in plan.items], ["Alpha-Architecture.rvt"])
        self.assertEqual(len(plan.notes), len(bad))

    def test_unsafe_host_name_raises_the_stage_error(self):
        for name in ("..\\Alpha.rvt", "LPT1.rvt", ""):
            with self.assertRaises(rx_cloud.StageError):
                self.plan([], [], row=host_row(name=name))

    def test_plan_stage_is_pure(self):
        files = [cache_file(P2, M5)]
        links = [link("Beta-MEP", P2, M5)]
        with unittest.mock.patch("io.open") as io_open, unittest.mock.patch("os.stat") as stat:
            self.plan(links, files)
        io_open.assert_not_called()
        stat.assert_not_called()
        self.assertEqual(links, [link("Beta-MEP", P2, M5)])
        self.assertFalse(os.path.exists(self.memory.file_path))

    def test_notes_exist_in_polish(self):
        files = [cache_file(P2, M4)]
        links = [link("Beta-MEP.rvt", P2, M5), link("alpha-architecture.rvt", P2, M4),
                 link("..\\x.rvt", P2, M4), link("", P2, M9)]
        english = self.plan(links, files).notes
        with unittest.mock.patch.dict(sys.modules, polish()):
            polish_notes = self.plan(links, files).notes
            with self.assertRaises(rx_cloud.StageError) as caught:
                self.plan([], [], row=host_row(name="..\\x.rvt"))
        self.assertEqual(len(english), 4)
        self.assertEqual(len(polish_notes), 4)
        for en, pl in zip(english, polish_notes):
            self.assertNotEqual(en, pl)
        self.assertIn("Linku Beta-MEP.rvt nie ma w pamięci podręcznej", polish_notes[0])
        self.assertIn("Nie skopiowano linku alpha-architecture.rvt", polish_notes[1])
        self.assertIn("pliku", "%s" % caught.exception)


# ------------------------------------------------------------------ criterion 12 and 13

class SourceGuards(unittest.TestCase):
    SOURCE = (LIB / "rx_cloud.py").read_text(encoding="utf-8")

    def test_no_revit_dotnet_or_clr_imports(self):
        banned = {"pyrevit", "Autodesk", "System", "clr", "rpw"}
        for node in ast.walk(ast.parse(self.SOURCE)):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                self.assertNotIn(name.split(".")[0], banned, name)

    def test_ironpython_syntax_rules(self):
        import test_export_button
        import test_status
        self.assertEqual(test_status.ironpython_problems(self.SOURCE), [])
        self.assertEqual(test_export_button.extra_ironpython_problems(self.SOURCE), [])
        self.assertFalse([n for n in ast.walk(ast.parse(self.SOURCE))
                          if isinstance(n, ast.JoinedStr)])
        for banned in ("os.replace", "scandir", "pathlib", "urllib", "\t"):
            self.assertNotIn(banned, self.SOURCE)
        self.assertIn("from __future__ import unicode_literals", self.SOURCE)
        self.assertTrue(self.SOURCE.startswith("# -*- coding: utf-8 -*-"))

    def test_no_revit_version_in_names(self):
        self.assertFalse(re.search(r"\b(rx_\w*|def \w*|class \w*)20(2\d)", self.SOURCE))

    def test_json_goes_through_dumps_ascii(self):
        self.assertNotIn("json.dumps", self.SOURCE)
        self.assertIn("dumps_ascii", self.SOURCE)


# Not client data: Autodesk schema constants and the ids of the public sample models, kept by the
# older tests, plus obviously invented sequences. Anything else under tests/ fails the guard.
KNOWN_PUBLIC = {s.lower() for s in (
    "11111111-2222-3333-4444-555555555555", "99999999-8888-7777-6666-555555555555",
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "DCB88B13-594F-44F6-8F5D-AE9477305AC3", "C2A3E6FE-CE51-4F35-8FF1-20C34567B687",
    "c8923f5e-6a14-4420-9b1d-c31d7ae067d2", "44745acb-ebea-4fb9-a091-88d28bd746c7",
    "6d3acd40-53b7-41b4-9d96-72e9eaf4bc89")}


def is_synthetic(guid):
    digits = guid.replace("-", "").lower()
    return len(set(digits)) == 1 or guid.lower() in KNOWN_PUBLIC


class PrivacyGuard(unittest.TestCase):
    def test_every_guid_under_tests_is_synthetic(self):
        checked = 0
        for path in TESTS.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            text = decode_journal(path.read_bytes())
            for guid in GUID_RE.findall(text):
                checked += 1
                self.assertTrue(is_synthetic(guid), "%s: not a synthetic GUID" % path.name)
        self.assertGreater(checked, 0)

    def test_the_guard_flags_a_realistic_guid(self):
        self.assertFalse(is_synthetic("3f2504e0-4f89-11d3-" + "9a0c-0305e82c3301"))
        self.assertTrue(is_synthetic("33333333-3333-3333-3333-333333333333"))
        self.assertTrue(is_synthetic("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))

    def test_fixture_names_are_invented(self):
        seen = set()
        for path in FIXTURES.glob("*.txt"):
            for item in parse_journal(decode_journal(path.read_bytes())):
                seen.update(n for n in (item.project_name, item.file_name) if n)
        self.assertTrue(seen)
        self.assertLessEqual(seen, SYNTHETIC_NAMES)


if __name__ == "__main__":
    unittest.main()
