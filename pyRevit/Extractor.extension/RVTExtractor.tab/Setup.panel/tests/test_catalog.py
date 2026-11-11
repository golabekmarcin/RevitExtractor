# -*- coding: utf-8 -*-
"""Tests for lib/rx_catalog.py (pure Python, no Revit; temporary folders only)."""
import ast
import io
import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[3] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))

import rx_catalog  # noqa: E402
from rx_catalog import (Cache, classify, iter_model_files, normalize_roots,  # noqa: E402
                        read_basic_info, scan)


def polish():
    """pyRevit set to Polish (same resolver shape as test_capabilities.polish)."""
    def get_locale_string(string_dict):
        for code in ("pl", "polish", "en_us", "english"):
            if code in string_dict:
                return string_dict[code]
        return None
    applocales = types.SimpleNamespace(get_locale_string=get_locale_string)
    coreutils = types.SimpleNamespace(applocales=applocales)
    return {"pyrevit": types.SimpleNamespace(coreutils=coreutils),
            "pyrevit.coreutils": coreutils, "pyrevit.coreutils.applocales": applocales}


def info(fmt="2022", later=False, local=False, created_local=False, **extra):
    data = {"format": fmt, "saved_in_later": later, "is_local": local,
            "is_created_local": created_local}
    data.update(extra)
    return data


class TempTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rxcat-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def touch(self, *parts):
        path = os.path.join(self.tmp, *parts)
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, "wb") as handle:
            handle.write(b"x")
        return path

    def rel(self, paths):
        return sorted(os.path.relpath(p, self.tmp).replace("\\", "/") for p in paths)


class NormalizeRoots(TempTree):
    def test_blank_and_trim(self):
        self.assertEqual(normalize_roots(["", "   ", None]), [])
        self.assertEqual(normalize_roots(["  " + self.tmp + "  "]), [os.path.normpath(self.tmp)])

    def test_trailing_slash(self):
        self.assertEqual(normalize_roots([self.tmp + os.sep]), [os.path.normpath(self.tmp)])

    @unittest.skipUnless(os.name == "nt", "case-insensitive paths")
    def test_duplicate_by_case(self):
        self.assertEqual(len(normalize_roots([self.tmp, self.tmp.upper(), self.tmp.lower()])), 1)

    def test_nested_collapsed(self):
        inner = os.path.join(self.tmp, "a", "b")
        other = os.path.join(self.tmp + "x", "c")
        result = normalize_roots([inner, self.tmp, other])
        self.assertEqual(result, [os.path.normpath(self.tmp), os.path.normpath(other)])

    def test_sibling_with_common_prefix_not_nested(self):
        result = normalize_roots([self.tmp, self.tmp + "2"])
        self.assertEqual(len(result), 2)

    def test_none_input(self):
        self.assertEqual(normalize_roots(None), [])


class IterModelFiles(TempTree):
    def test_nested_and_extension_case(self):
        self.touch("A.rvt")
        self.touch("sub", "deep", "B.RVT")
        self.touch("sub", "c.Rvt")
        self.touch("notes.txt")
        self.touch("family.rfa")
        self.touch("x.rvt.txt")
        self.assertEqual(self.rel(iter_model_files([self.tmp])),
                         ["A.rvt", "sub/c.Rvt", "sub/deep/B.RVT"])

    def test_sorted_and_deterministic(self):
        for name in ("b.rvt", "a.rvt", "C.rvt"):
            self.touch(name)
        self.touch("z", "q.rvt")
        self.touch("m", "q.rvt")
        first = list(iter_model_files([self.tmp]))
        self.assertEqual(first, list(iter_model_files([self.tmp])))
        self.assertEqual([os.path.basename(p).lower() for p in first[:3]],
                         ["a.rvt", "b.rvt", "c.rvt"])
        self.assertEqual([os.path.basename(os.path.dirname(p)) for p in first[3:]], ["m", "z"])

    def test_several_roots(self):
        one = os.path.join(self.tmp, "one")
        two = os.path.join(self.tmp, "two")
        self.touch("one", "a.rvt")
        self.touch("two", "b.rvt")
        self.touch("three", "c.rvt")
        self.assertEqual(self.rel(iter_model_files([one, two])), ["one/a.rvt", "two/b.rvt"])

    def test_root_inside_root_no_duplicates(self):
        self.touch("a.rvt")
        self.touch("sub", "b.rvt")
        paths = list(iter_model_files([os.path.join(self.tmp, "sub"), self.tmp, self.tmp]))
        self.assertEqual(self.rel(paths), ["a.rvt", "sub/b.rvt"])

    def test_backup_files_need_sibling(self):
        self.touch("Tower.rvt")
        self.touch("Tower.0001.rvt")
        self.touch("Tower.0002.RVT")
        self.touch("Tower.2024.rvt")          # sibling Tower.rvt exists -> backup by the rule
        self.touch("Lone.2024.rvt")           # Lone.rvt does not exist -> listed
        self.touch("Other.12345.rvt")         # five digits: not a backup name
        self.touch("Other.abcd.rvt")
        names = sorted(os.path.basename(p) for p in iter_model_files([self.tmp]))
        # Tower.2024.rvt has the sibling Tower.rvt, so by the rule it is a backup too.
        self.assertEqual(names, ["Lone.2024.rvt", "Other.12345.rvt", "Other.abcd.rvt", "Tower.rvt"])

    def test_year_named_model_without_sibling_is_listed(self):
        self.touch("Tower.2024.rvt")
        self.assertEqual(self.rel(iter_model_files([self.tmp])), ["Tower.2024.rvt"])

    @unittest.skipUnless(os.name == "nt", "case-insensitive file names")
    def test_backup_sibling_compared_case_insensitively(self):
        self.touch("TOWER.RVT")
        self.touch("tower.0003.rvt")
        self.assertEqual(self.rel(iter_model_files([self.tmp])), ["TOWER.RVT"])

    def test_backup_sibling_must_be_in_same_folder(self):
        self.touch("Tower.rvt")
        self.touch("other", "Tower.0001.rvt")
        self.assertEqual(self.rel(iter_model_files([self.tmp])),
                         ["Tower.rvt", "other/Tower.0001.rvt"])

    def test_backup_folders_not_entered(self):
        self.touch("ok.rvt")
        self.touch("Backup", "a.rvt")
        self.touch("BACKUP", "a2.rvt")
        self.touch("proj_backup", "b.rvt")
        self.touch("Proj_BACKUP", "b2.rvt")
        self.touch("sub", "backup", "c.rvt")
        self.touch("sub", "keep", "d.rvt")
        self.touch("backups", "e.rvt")        # not exactly Backup, not ending in _backup
        self.touch("mybackup", "f.rvt")
        self.assertEqual(self.rel(iter_model_files([self.tmp])),
                         ["backups/e.rvt", "mybackup/f.rvt", "ok.rvt", "sub/keep/d.rvt"])

    def test_missing_root_reported_not_raised(self):
        self.touch("a.rvt")
        missing = self.tmp + "-missing"   # a sibling, not nested under the other root
        errors = []
        paths = list(iter_model_files([missing, self.tmp], errors=errors))
        self.assertEqual(self.rel(paths), ["a.rvt"])
        self.assertEqual(len(errors), 1)
        self.assertEqual(os.path.normcase(errors[0]), os.path.normcase(os.path.normpath(missing)))

    def test_missing_root_without_errors_list(self):
        self.assertEqual(list(iter_model_files([self.tmp + "-missing"])), [])

    def test_unreadable_root_via_walk_onerror(self):
        def walk(root, onerror=None):
            if onerror:
                onerror(OSError("denied"))
            return iter(())
        errors = []
        self.assertEqual(list(iter_model_files([self.tmp], walk=walk, errors=errors)), [])
        self.assertEqual(len(errors), 1)

    def test_walk_is_injectable(self):
        def walk(root, onerror=None):
            yield root, ["Backup", "keep"], ["a.rvt", "a.0001.rvt"]
            yield os.path.join(root, "keep"), [], ["b.rvt"]
        paths = list(iter_model_files([self.tmp], walk=walk))
        self.assertEqual([os.path.basename(p) for p in paths], ["a.rvt", "b.rvt"])


class Classify(unittest.TestCase):
    def test_states(self):
        self.assertEqual(classify(info("2022"), 2022), "ok")
        self.assertEqual(classify(info("2021"), 2022), "older")
        self.assertEqual(classify(info("2023"), 2022), "newer")
        self.assertEqual(classify(info("2022", later=True), 2022), "newer")
        self.assertEqual(classify(info("", later=True), 2022), "newer")
        self.assertEqual(classify(info("garbage"), 2022), "unknown")
        self.assertEqual(classify(info(""), 2022), "unknown")
        self.assertEqual(classify(info(None), 2022), "unknown")
        self.assertEqual(classify(info("20222"), 2022), "unknown")
        self.assertEqual(classify({"error": "InvalidOperationException"}, 2022), "unknown")
        self.assertEqual(classify(info("2022", local=True), 2022), "local_copy")
        self.assertEqual(classify(info("2022", created_local=True), 2022), "local_copy")

    def test_error_wins_over_everything(self):
        self.assertEqual(classify({"error": "X", "format": "2022", "is_local": True}, 2022),
                         "unknown")

    def test_local_wins_over_version(self):
        self.assertEqual(classify(info("2030", later=True, local=True), 2022), "local_copy")

    def test_missing_keys_tolerated(self):
        self.assertEqual(classify({}, 2022), "unknown")
        self.assertEqual(classify({"format": "2022"}, 2022), "ok")

    def test_format_whitespace(self):
        self.assertEqual(classify(info(" 2022 "), 2022), "ok")


class Notes(TempTree):
    def rows_for(self, infos, year=2022):
        self.touch("m.rvt")
        cache = Cache(os.path.join(self.tmp, "c", "cache.json"))
        return list(scan([self.tmp], year, lambda p: infos, cache))

    def test_english(self):
        row = self.rows_for(info("2021"))[0]
        self.assertEqual(row.note, "Saved in Revit 2021. The export upgrades a temporary copy; "
                                   "the file is not changed.")
        row = self.rows_for(info("2024"))[0]
        self.assertEqual(row.note, "Saved in Revit 2024, newer than this Revit (2022).")
        row = self.rows_for({"error": "InvalidOperationException"})[0]
        self.assertEqual(row.note, "The Revit version could not be read.")
        self.assertEqual(self.rows_for(info("2022"))[0].note, "")

    def test_polish(self):
        saved = {k: sys.modules.get(k) for k in polish()}
        sys.modules.update(polish())
        try:
            self.assertEqual(
                self.rows_for(info("2021"))[0].note,
                "Zapisany w Revicie 2021. Eksport uaktualni tymczasową kopię; "
                "plik nie zostanie zmieniony.")
            self.assertEqual(self.rows_for(info("2024"))[0].note,
                             "Zapisany w Revicie 2024, nowszym niż ten Revit (2022).")
            self.assertEqual(self.rows_for({"error": "X"})[0].note,
                             "Nie udało się odczytać wersji Revita.")
        finally:
            for key, value in saved.items():
                if value is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value


class Rows(TempTree):
    def scan_rows(self, infos_by_name, year=2022, cache=None, **kw):
        cache = cache or Cache(os.path.join(self.tmp, "cache-dir", "cache.json"))
        return list(scan([self.tmp], year, lambda p: infos_by_name[os.path.basename(p)],
                         cache, **kw))

    def test_enabled_only_for_ok_and_older(self):
        for name in ("ok", "old", "new", "unk", "loc"):
            self.touch(name + ".rvt")
        rows = self.scan_rows({
            "ok.rvt": info("2022"), "old.rvt": info("2020"), "new.rvt": info("2023"),
            "unk.rvt": {"error": "E"}, "loc.rvt": info("2022", local=True)})
        by_state = {r.name: (r.state, r.enabled) for r in rows}
        self.assertEqual(by_state, {
            "ok.rvt": ("ok", True), "old.rvt": ("older", True), "new.rvt": ("newer", False),
            "unk.rvt": ("unknown", False), "loc.rvt": ("local_copy", False)})

    def test_row_fields(self):
        self.touch("sub", "Model.rvt")
        row = self.scan_rows({"Model.rvt": info("2021")})[0]
        self.assertEqual(row.name, "Model.rvt")
        self.assertEqual(row.folder, os.path.join(self.tmp, "sub"))
        self.assertEqual(row.path, os.path.join(self.tmp, "sub", "Model.rvt"))
        self.assertEqual(row.version, "2021")
        with self.assertRaises(AttributeError):
            row.name = "x"

    def test_unknown_version_blank(self):
        self.touch("u.rvt")
        row = self.scan_rows({"u.rvt": {"error": "E"}})[0]
        self.assertEqual(row.version, "")

    def test_workshared_true_false_and_unknown(self):
        for name in ("w", "n", "u", "e"):
            self.touch(name + ".rvt")
        rows = self.scan_rows({
            "w.rvt": info("2022", is_workshared=True),
            "n.rvt": info("2022", is_workshared=False),
            "u.rvt": info("2022"),                       # fact missing
            "e.rvt": {"error": "E"}})
        self.assertEqual({r.name: r.workshared for r in rows},
                         {"w.rvt": True, "n.rvt": False, "u.rvt": None, "e.rvt": None})

    def test_workshared_comes_from_cache_and_cache_format_is_unchanged(self):
        self.touch("models", "a.rvt")
        root = os.path.join(self.tmp, "models")
        path = os.path.join(self.tmp, "cache", "c.json")
        list(scan([root], 2022, lambda p: info("2022", is_workshared=True), Cache(path)))
        cache = Cache(path)
        cache.load()
        rows = list(scan([root], 2022, lambda p: 1 / 0, cache))
        self.assertIs(rows[0].workshared, True)
        with io.open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["version"], 1)
        entry = list(data["entries"].values())[0]
        self.assertEqual(sorted(entry), ["info", "mtime", "size"])

    def test_flag_only_newer_note(self):
        self.touch("f.rvt")
        row = self.scan_rows({"f.rvt": info("", later=True)})[0]
        self.assertEqual(row.state, "newer")
        self.assertFalse(row.enabled)
        self.assertTrue(row.note)


class CacheBehaviour(TempTree):
    def cache_path(self):
        return os.path.join(self.tmp, "cachedir", "catalog-cache.json")

    def test_hit_avoids_read(self):
        self.touch("models", "a.rvt")
        calls = []

        def read(path):
            calls.append(path)
            return info("2022")
        root = os.path.join(self.tmp, "models")
        list(scan([root], 2022, read, Cache(self.cache_path())))
        self.assertEqual(len(calls), 1)
        cache = Cache(self.cache_path())
        cache.load()
        list(scan([root], 2022, read, cache))
        self.assertEqual(len(calls), 1)

    def test_change_rereads(self):
        path = self.touch("models", "a.rvt")
        root = os.path.join(self.tmp, "models")
        calls = []

        def read(p):
            calls.append(p)
            return info("2022")
        list(scan([root], 2022, read, Cache(self.cache_path())))
        with open(path, "wb") as handle:
            handle.write(b"longer content")
        cache = Cache(self.cache_path())
        cache.load()
        list(scan([root], 2022, read, cache))
        self.assertEqual(len(calls), 2)
        # time change only
        cache = Cache(self.cache_path())
        cache.load()
        st = os.stat(path)
        os.utime(path, (st.st_atime, st.st_mtime + 100))
        list(scan([root], 2022, read, cache))
        self.assertEqual(len(calls), 3)

    def test_cache_serves_every_running_year(self):
        self.touch("models", "a.rvt")
        root = os.path.join(self.tmp, "models")
        calls = []

        def read(p):
            calls.append(p)
            return info("2023")
        cache = Cache(self.cache_path())
        self.assertEqual(list(scan([root], 2022, read, cache))[0].state, "newer")
        cache = Cache(self.cache_path())
        cache.load()
        self.assertEqual(list(scan([root], 2023, read, cache))[0].state, "ok")
        self.assertEqual(len(calls), 1)

    def test_errors_are_not_cached(self):
        self.touch("models", "a.rvt")
        root = os.path.join(self.tmp, "models")
        calls = []

        def read(p):
            calls.append(p)
            return {"error": "IOException"}
        list(scan([root], 2022, read, Cache(self.cache_path())))
        cache = Cache(self.cache_path())
        cache.load()
        list(scan([root], 2022, read, cache))
        self.assertEqual(len(calls), 2)

    def test_read_info_exception_becomes_unknown(self):
        self.touch("a.rvt")

        def read(p):
            raise RuntimeError("boom")
        rows = list(scan([self.tmp], 2022, read, Cache(self.cache_path())))
        self.assertEqual(rows[0].state, "unknown")

    def test_corrupt_wrong_version_missing(self):
        os.makedirs(os.path.dirname(self.cache_path()))
        cache = Cache(self.cache_path())
        cache.load()                                  # missing file
        self.assertIsNone(cache.lookup("x.rvt", 1, 1.0))
        for content in ("{not json", "", "[]", "null", '{"version": 999, "entries": {}}',
                        '{"version": 1, "entries": []}', '{"version": 1}'):
            with io.open(self.cache_path(), "w", encoding="utf-8") as handle:
                handle.write(content)
            cache = Cache(self.cache_path())
            cache.load()
            self.assertEqual(cache.entries, {}, content)
        with open(self.cache_path(), "wb") as handle:
            handle.write(b"\xff\xfe\x00bad")
        cache = Cache(self.cache_path())
        cache.load()
        self.assertEqual(cache.entries, {})

    def test_malformed_entry_is_a_miss(self):
        with io.open(self.tmp + os.sep + "c.json", "w", encoding="utf-8") as handle:
            json.dump({"version": rx_catalog.CACHE_VERSION,
                       "entries": {os.path.normcase("a.rvt"): "junk"}}, handle)
        cache = Cache(self.tmp + os.sep + "c.json")
        cache.load()
        self.assertIsNone(cache.lookup("a.rvt", 1, 1.0))

    def test_missing_folder_created_on_save(self):
        cache = Cache(self.cache_path())
        cache.store("a.rvt", 1, 1.0, info("2022"))
        self.assertTrue(cache.save())
        self.assertTrue(os.path.isfile(self.cache_path()))
        self.assertEqual(os.listdir(os.path.dirname(self.cache_path())),
                         ["catalog-cache.json"])        # no temp file left

    def test_save_overwrites_and_roundtrips(self):
        cache = Cache(self.cache_path())
        cache.store("A.rvt", 5, 12.5, info("2021", extra_key=True))
        cache.save()
        cache.store("B.rvt", 6, 13.5, info("2022"))
        self.assertTrue(cache.save())
        again = Cache(self.cache_path())
        again.load()
        self.assertEqual(again.lookup("a.rvt" if os.name == "nt" else "A.rvt", 5, 12.5)["format"],
                         "2021")
        self.assertIsNotNone(again.lookup("B.rvt", 6, 13.5))
        self.assertIsNone(again.lookup("B.rvt", 7, 13.5))
        self.assertEqual(os.listdir(os.path.dirname(self.cache_path())),
                         ["catalog-cache.json"])

    def test_save_through_temp_file_in_same_folder(self):
        cache = Cache(self.cache_path())
        cache.store("a.rvt", 1, 1.0, info())
        seen = []
        real_rename = os.rename

        def spy(src, dst):
            seen.append((os.path.dirname(src), os.path.dirname(dst), os.path.exists(src)))
            return real_rename(src, dst)
        os.rename = spy
        try:
            self.assertTrue(cache.save())
        finally:
            os.rename = real_rename
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], seen[0][1])
        self.assertTrue(seen[0][2])

    def test_failed_save_reported_not_raised(self):
        blocker = os.path.join(self.tmp, "file")
        with open(blocker, "wb") as handle:
            handle.write(b"x")
        cache = Cache(os.path.join(blocker, "sub", "cache.json"))
        cache.store("a.rvt", 1, 1.0, info())
        self.assertFalse(cache.save())
        self.assertTrue(cache.last_error)
        self.assertNotIn("a.rvt", cache.last_error)       # no paths in the message

    def test_failed_save_does_not_break_scan(self):
        self.touch("models", "a.rvt")
        blocker = os.path.join(self.tmp, "file")
        with open(blocker, "wb") as handle:
            handle.write(b"x")
        cache = Cache(os.path.join(blocker, "sub", "cache.json"))
        rows = list(scan([os.path.join(self.tmp, "models")], 2022, lambda p: info(), cache))
        self.assertEqual(len(rows), 1)
        self.assertTrue(cache.last_error)

    def test_prune_drops_gone_files_keeps_other_roots(self):
        one = os.path.join(self.tmp, "one")
        two = os.path.join(self.tmp, "two")
        keep = self.touch("one", "keep.rvt")
        gone = self.touch("one", "gone.rvt")
        other = self.touch("two", "other.rvt")
        cache = Cache(self.cache_path())
        list(scan([one, two], 2022, lambda p: info(), cache))
        os.remove(gone)
        list(scan([one], 2022, lambda p: info(), cache))   # only root one scanned
        st = os.stat(keep)
        self.assertIsNotNone(cache.lookup(keep, st.st_size, st.st_mtime))
        self.assertIsNotNone(cache.lookup(other, os.stat(other).st_size, os.stat(other).st_mtime))
        self.assertEqual(len(cache.entries), 2)

    def test_prune_prefix_is_a_folder_boundary(self):
        cache = Cache(self.cache_path())
        cache.store(os.path.join(self.tmp, "one2", "a.rvt"), 1, 1.0, info())
        cache.prune([os.path.join(self.tmp, "one")], [])
        self.assertEqual(len(cache.entries), 1)

    def test_prune_not_applied_to_missing_root(self):
        gone_root = os.path.join(self.tmp, "offline")
        path = os.path.join(gone_root, "a.rvt")
        cache = Cache(self.cache_path())
        cache.store(path, 1, 1.0, info())
        list(scan([gone_root], 2022, lambda p: info(), cache))
        self.assertEqual(len(cache.entries), 1)             # share offline: keep entries

    @unittest.skipUnless(os.name == "nt", "case-insensitive paths")
    def test_key_is_case_normalized(self):
        cache = Cache(self.cache_path())
        cache.store(r"C:\Models\A.rvt", 1, 1.0, info())
        self.assertIsNotNone(cache.lookup(r"c:\models\a.RVT", 1, 1.0))


class ScanGenerator(TempTree):
    def test_one_row_per_pull(self):
        for name in ("a.rvt", "b.rvt", "c.rvt"):
            self.touch(name)
        calls = []

        def read(p):
            calls.append(p)
            return info()
        gen = scan([self.tmp], 2022, read, Cache(os.path.join(self.tmp, "x", "c.json")))
        self.assertEqual(calls, [])
        next(gen)
        self.assertEqual(len(calls), 1)
        next(gen)
        self.assertEqual(len(calls), 2)

    def test_early_stop_leaves_cache_saveable(self):
        for name in ("a.rvt", "b.rvt", "c.rvt"):
            self.touch(name)
        path = os.path.join(self.tmp, "x", "c.json")
        cache = Cache(path)
        gen = scan([self.tmp], 2022, lambda p: info(), cache)
        next(gen)
        next(gen)
        gen.close()
        self.assertTrue(cache.save())
        again = Cache(path)
        again.load()
        self.assertEqual(len(again.entries), 2)

    def test_early_stop_does_not_prune(self):
        a = self.touch("a.rvt")
        b = self.touch("b.rvt")
        cache = Cache(os.path.join(self.tmp, "x", "c.json"))
        list(scan([self.tmp], 2022, lambda p: info(), cache))
        gen = scan([self.tmp], 2022, lambda p: info(), cache)
        next(gen)
        gen.close()
        self.assertEqual(len(cache.entries), 2)

    def test_completed_scan_saves_once(self):
        self.touch("a.rvt")
        path = os.path.join(self.tmp, "x", "c.json")
        cache = Cache(path)
        saves = []
        real = cache.save
        cache.save = lambda: saves.append(1) or real()
        list(scan([self.tmp], 2022, lambda p: info(), cache))
        self.assertEqual(len(saves), 1)
        self.assertTrue(os.path.isfile(path))

    def test_missing_root_reported_through_scan(self):
        errors = []
        rows = list(scan([self.tmp + "-missing"], 2022, lambda p: info(),
                         Cache(os.path.join(self.tmp, "c.json")), errors=errors))
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)

    def test_stat_is_injectable_and_failure_is_unknown(self):
        self.touch("a.rvt")

        def bad_stat(path):
            raise OSError("gone")
        rows = list(scan([self.tmp], 2022, lambda p: info(),
                         Cache(os.path.join(self.tmp, "c.json")), stat=bad_stat))
        self.assertEqual(rows[0].state, "unknown")


class StubInfo(object):
    """Stand-in for Autodesk.Revit.DB.BasicFileInfo instance."""

    def __init__(self, raises_on=None):
        self.Format = "2022"
        self.IsSavedInLaterVersion = False
        self.IsLocal = False
        self.IsCreatedLocal = True
        self.IsWorkshared = True
        self.IsCentral = False
        self.disposed = 0
        self._raises_on = raises_on

    def __getattribute__(self, name):
        if name == "_raises_on":
            return object.__getattribute__(self, name)
        if object.__getattribute__(self, "_raises_on") == name:
            raise RuntimeError("property failed")
        return object.__getattribute__(self, name)

    def Dispose(self):
        self.disposed += 1


class StubBasicFileInfo(object):
    def __init__(self, instance=None, error=None):
        self.instance = instance
        self.error = error
        self.paths = []

    def Extract(self, path):
        self.paths.append(path)
        if self.error:
            raise self.error
        return self.instance


class ReadBasicInfo(unittest.TestCase):
    def test_plain_values_and_dispose(self):
        stub = StubInfo()
        result = read_basic_info("x.rvt", StubBasicFileInfo(stub))
        self.assertEqual(result, {
            "format": "2022", "saved_in_later": False, "is_local": False,
            "is_created_local": True, "is_workshared": True, "is_central": False})
        for value in result.values():
            self.assertIn(type(value), (bool, type("")), value)
        json.dumps(result)
        self.assertEqual(stub.disposed, 1)

    def test_dispose_when_property_raises(self):
        for name in ("Format", "IsSavedInLaterVersion", "IsLocal", "IsCreatedLocal"):
            stub = StubInfo(raises_on=name)
            result = read_basic_info("x.rvt", StubBasicFileInfo(stub))
            self.assertEqual(result, {"error": "RuntimeError"}, name)
            self.assertEqual(stub.disposed, 1, name)

    def test_extract_exception_becomes_error(self):
        class InvalidOperationException(Exception):
            pass
        stub = StubBasicFileInfo(error=InvalidOperationException("old file"))
        self.assertEqual(read_basic_info("x.rvt", stub), {"error": "InvalidOperationException"})

    def test_none_format_is_blank(self):
        instance = StubInfo()
        instance.Format = None
        self.assertEqual(read_basic_info("x.rvt", StubBasicFileInfo(instance))["format"], "")

    def test_path_passed_through(self):
        stub = StubBasicFileInfo(StubInfo())
        read_basic_info("C:\\m\\a.rvt", stub)
        self.assertEqual(stub.paths, ["C:\\m\\a.rvt"])


class Timing(TempTree):
    def test_warm_scan_of_1000_files_under_two_seconds(self):
        root = os.path.join(self.tmp, "models")
        for folder in range(10):
            os.makedirs(os.path.join(root, "f%d" % folder))
            for index in range(100):
                open(os.path.join(root, "f%d" % folder, "m%03d.rvt" % index), "wb").close()
        cache_path = os.path.join(self.tmp, "cache", "c.json")
        cache = Cache(cache_path)
        cold = list(scan([root], 2022, lambda p: info(), cache))
        self.assertEqual(len(cold), 1000)

        def fail(path):
            raise AssertionError("warm scan must not read")
        warm_cache = Cache(cache_path)
        started = time.time()
        warm_cache.load()
        rows = list(scan([root], 2022, fail, warm_cache))
        elapsed = time.time() - started
        print("warm scan of 1000 files: %.3f s" % elapsed)
        self.assertEqual(len(rows), 1000)
        self.assertLess(elapsed, 2.0)


class ImportGuard(unittest.TestCase):
    def test_no_revit_imports(self):
        tree = ast.parse((LIB / "rx_catalog.py").read_text(encoding="utf-8"))
        banned = {"pyrevit", "Autodesk", "System", "clr"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                self.assertNotIn(name.split(".")[0], banned, name)

    def test_ironpython_syntax_rules(self):
        source = (LIB / "rx_catalog.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)])
        for banned in ("os.replace", "scandir", "pathlib"):
            self.assertNotIn(banned, source)
        self.assertIn("from __future__ import unicode_literals", source)


if __name__ == "__main__":
    unittest.main()
