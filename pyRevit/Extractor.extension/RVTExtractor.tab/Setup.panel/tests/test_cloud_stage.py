# -*- coding: utf-8 -*-
"""Tests for lib/rx_cloud_stage.py (specs/SPEC-cloud-catalog.md, criterion 7; temporary folders only).

The "cache" here is a temporary folder of synthetic files. Every GUID is synthetic (repeated
digits) and every name invented.
"""
import ast
import hashlib
import io
import os
import re
import shutil
import stat as stat_module
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

TESTS = Path(__file__).resolve().parent
LIB = TESTS.parents[2] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))

import rx_cloud  # noqa: E402
import rx_cloud_stage  # noqa: E402
from rx_cloud import StageItem, StagePlan  # noqa: E402
from rx_cloud_stage import StageError, check_space, copy_steps  # noqa: E402
from test_cloud import polish  # noqa: E402

P1 = "11111111-1111-1111-1111-111111111111"
M3 = "33333333-3333-3333-3333-333333333333"
M4 = "44444444-4444-4444-4444-444444444444"
CHUNK = 1024
REAL_IO_OPEN = io.open
REAL_OS_OPEN = os.open
REAL_OS_REMOVE = os.remove
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


def sha256(path):
    with REAL_IO_OPEN(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def facts(path):
    st = os.stat(path)
    return st.st_size, st.st_mtime, sha256(path)


class StageCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rx-cloud-stage-test-")
        self.addCleanup(self._remove_tmp)
        self.cache = os.path.join(self.tmp, "cache", "99999999", P1)
        self.dest = os.path.join(self.tmp, "run", "model")
        os.makedirs(self.cache)

    def _remove_tmp(self):
        for folder, _dirs, files in os.walk(self.tmp):
            for name in files:
                os.chmod(os.path.join(folder, name), stat_module.S_IREAD | stat_module.S_IWRITE)
        shutil.rmtree(self.tmp, True)

    def source(self, model, size, read_only=True, mtime=1900000000.0, sub=""):
        folder = os.path.join(self.cache, sub) if sub else self.cache
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, model + ".rvt")
        if os.path.exists(path):
            os.chmod(path, stat_module.S_IREAD | stat_module.S_IWRITE)
        with REAL_IO_OPEN(path, "wb") as handle:
            handle.write(os.urandom(size))
        os.utime(path, (mtime, mtime))
        if read_only:
            os.chmod(path, stat_module.S_IREAD)
        return path

    def item(self, path, name):
        st = os.stat(path)
        return StageItem(path, name, st.st_size, st.st_mtime)

    def two_item_plan(self, host_size=3 * CHUNK + 5, link_size=CHUNK):
        host = self.source(M3, host_size)
        linked = self.source(M4, link_size, sub="LinkedModels")
        return StagePlan([self.item(host, "Alpha-Architecture.rvt"),
                          self.item(linked, "Beta-MEP.rvt")], [])

    def run_all(self, plan, dest=None, **kwargs):
        kwargs.setdefault("chunk", CHUNK)
        return list(copy_steps(plan, dest or self.dest, **kwargs))

    def dest_files(self):
        return sorted(os.listdir(self.dest)) if os.path.isdir(self.dest) else []


# ------------------------------------------------------------------ copy_steps

class CopySteps(StageCase):
    def test_identical_bytes_and_progress(self):
        plan = self.two_item_plan()
        before = [facts(i.src) for i in plan.items]
        steps = self.run_all(plan)
        total = sum(i.size for i in plan.items)
        self.assertEqual(self.dest_files(), ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])
        for item in plan.items:
            self.assertEqual(sha256(os.path.join(self.dest, item.name)), sha256(item.src))
        done = [s[0] for s in steps]
        self.assertEqual(done, sorted(done))
        self.assertEqual(steps[-1][0], total)
        self.assertTrue(all(s[1] == total for s in steps))
        self.assertEqual({s[2].name for s in steps}, {"Alpha-Architecture.rvt", "Beta-MEP.rvt"})
        self.assertGreaterEqual(len(steps), 5)  # time-sliced: one step per chunk
        self.assertEqual(steps[0][2].name, "Alpha-Architecture.rvt")  # host first
        self.assertEqual(before, [facts(i.src) for i in plan.items])

    def test_read_only_sources_keep_size_mtime_and_sha256(self):
        plan = self.two_item_plan()
        before = [facts(i.src) for i in plan.items]
        modes = [os.stat(i.src).st_mode for i in plan.items]
        self.run_all(plan)
        self.assertEqual(before, [facts(i.src) for i in plan.items])
        self.assertEqual(modes, [os.stat(i.src).st_mode for i in plan.items])
        self.assertTrue(all(not os.access(i.src, os.W_OK) for i in plan.items))

    def test_zero_byte_file_is_copied_and_reported(self):
        empty = self.source(M3, 0)
        steps = self.run_all(StagePlan([self.item(empty, "Alpha-Architecture.rvt")], []))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0][:2], (0, 0))
        self.assertEqual(os.path.getsize(os.path.join(self.dest, "Alpha-Architecture.rvt")), 0)

    def test_destination_folder_is_created_when_missing(self):
        plan = self.two_item_plan()
        self.assertFalse(os.path.exists(self.dest))
        self.run_all(plan)
        self.assertEqual(len(self.dest_files()), 2)

    def test_plain_dict_items_are_accepted(self):
        plan = self.two_item_plan()
        as_dicts = {"items": [dict(i._asdict()) for i in plan.items], "notes": []}
        self.run_all(as_dicts)
        self.assertEqual(self.dest_files(), ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])

    def test_existing_destination_raises_and_is_never_overwritten(self):
        plan = self.two_item_plan()
        os.makedirs(self.dest)
        existing = os.path.join(self.dest, "Beta-MEP.rvt")
        with REAL_IO_OPEN(existing, "wb") as handle:
            handle.write(b"keep me")
        before = [facts(i.src) for i in plan.items]
        with self.assertRaises(StageError) as caught:
            self.run_all(plan)
        self.assertIn("Beta-MEP.rvt", "%s" % caught.exception)
        with REAL_IO_OPEN(existing, "rb") as handle:
            self.assertEqual(handle.read(), b"keep me")
        self.assertEqual(before, [facts(i.src) for i in plan.items])
        # the host was copied before the clash was reached and is complete
        host = os.path.join(self.dest, "Alpha-Architecture.rvt")
        self.assertEqual(sha256(host), sha256(plan.items[0].src))

    def test_destination_on_the_source_itself_never_touches_the_source(self):
        src = self.source(M3, CHUNK, read_only=False)
        before = facts(src)
        plan = StagePlan([StageItem(src, os.path.basename(src), before[0], before[1])], [])
        with unittest.mock.patch("os.remove", side_effect=AssertionError("remove")) as remove:
            with self.assertRaises(StageError):
                self.run_all(plan, dest=self.cache)
        remove.assert_not_called()
        self.assertEqual(before, facts(src))

    def test_destination_on_another_plan_source_is_refused_before_copying(self):
        first = self.source(M3, CHUNK)
        second = self.source(M4, CHUNK, read_only=False)
        before = facts(second)
        plan = StagePlan([self.item(first, os.path.basename(second)),
                          self.item(second, "Beta-MEP.rvt")], [])
        with self.assertRaises(StageError):
            self.run_all(plan, dest=self.cache)
        self.assertEqual(before, facts(second))

    def test_destination_folder_inside_the_cache_is_refused(self):
        plan = self.two_item_plan()
        cache_like = os.path.join(self.tmp, "Autodesk Revit X", "collaborationCACHE", "run")
        for dest in (os.path.join(self.cache, "run", "model"), cache_like,
                     os.path.join(self.cache, "LinkedModels")):
            with self.assertRaises(StageError):
                self.run_all(plan, dest=dest)
            self.assertFalse(os.path.exists(os.path.join(dest, "Alpha-Architecture.rvt")))
        self.assertFalse(os.path.exists(os.path.join(self.cache, "run")))
        self.assertFalse(os.path.exists(cache_like))

    def test_source_changed_since_planning_fails_before_writing(self):
        plan = self.two_item_plan()
        os.utime(plan.items[0].src, (1900000500.0, 1900000500.0))
        with self.assertRaises(StageError) as caught:
            self.run_all(plan)
        self.assertIn("The cache file changed while it was copied. Export again.",
                      "%s" % caught.exception)
        self.assertEqual(self.dest_files(), [])

    def test_source_changed_during_the_copy_fails_and_leaves_no_partial_file(self):
        host = self.source(M3, 4 * CHUNK, read_only=False)
        plan = StagePlan([self.item(host, "Alpha-Architecture.rvt")], [])
        steps = copy_steps(plan, self.dest, chunk=CHUNK)
        next(steps)
        with REAL_IO_OPEN(host, "ab") as handle:  # Revit syncs the cache under our feet
            handle.write(b"more")
        with self.assertRaises(StageError) as caught:
            list(steps)
        self.assertIn("cache file changed", "%s" % caught.exception)
        self.assertEqual(self.dest_files(), [])
        self.assertTrue(os.path.exists(host))

    def test_source_mtime_changed_during_the_copy_fails(self):
        plan = self.two_item_plan(link_size=10)
        calls = []

        def stat(path):
            st = os.stat(path)
            calls.append(path)
            if path == plan.items[1].src and calls.count(path) > 1:
                return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid,
                                       st.st_gid, st.st_size, st.st_atime, st.st_mtime + 2,
                                       st.st_ctime))
            return st
        with self.assertRaises(StageError):
            self.run_all(plan, stat=stat)
        self.assertEqual(self.dest_files(), ["Alpha-Architecture.rvt"])

    def test_destination_size_mismatch_fails(self):
        plan = self.two_item_plan()
        dest_host = os.path.join(self.dest, "Alpha-Architecture.rvt")

        def stat(path):
            st = os.stat(path)
            if path == dest_host:
                return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid,
                                       st.st_gid, st.st_size - 1, st.st_atime, st.st_mtime,
                                       st.st_ctime))
            return st
        with self.assertRaises(StageError):
            self.run_all(plan, stat=stat)
        self.assertEqual(self.dest_files(), [])

    def test_source_shorter_than_planned_fails(self):
        host = self.source(M3, CHUNK)
        st = os.stat(host)
        plan = StagePlan([StageItem(host, "Alpha-Architecture.rvt", st.st_size + 1, st.st_mtime)],
                         [])

        def stat(path):  # the stat still claims the planned size; the bytes are fewer
            real = os.stat(path)
            if path != host:
                return real
            return os.stat_result((real.st_mode, real.st_ino, real.st_dev, real.st_nlink,
                                   real.st_uid, real.st_gid, real.st_size + 1, real.st_atime,
                                   real.st_mtime, real.st_ctime))
        with self.assertRaises(StageError):
            self.run_all(plan, stat=stat)
        self.assertEqual(self.dest_files(), [])

    def test_closing_early_raises_nothing_and_removes_only_the_partial_copy(self):
        plan = self.two_item_plan()
        before = [facts(i.src) for i in plan.items]
        steps = copy_steps(plan, self.dest, chunk=CHUNK)
        next(steps)
        self.assertEqual(self.dest_files(), ["Alpha-Architecture.rvt"])
        steps.close()
        self.assertEqual(self.dest_files(), [])
        self.assertEqual(before, [facts(i.src) for i in plan.items])

    def test_closing_after_an_item_finished_keeps_that_complete_copy(self):
        plan = self.two_item_plan(host_size=10, link_size=3 * CHUNK)
        steps = copy_steps(plan, self.dest, chunk=CHUNK)
        done, total, item = next(steps)
        self.assertEqual((done, item.name), (10, "Alpha-Architecture.rvt"))
        next(steps)  # first chunk of the link
        steps.close()
        self.assertEqual(self.dest_files(), ["Alpha-Architecture.rvt"])
        self.assertEqual(sha256(os.path.join(self.dest, "Alpha-Architecture.rvt")),
                         sha256(plan.items[0].src))

    def test_closing_before_the_first_step_does_nothing(self):
        plan = self.two_item_plan()
        copy_steps(plan, self.dest).close()
        self.assertFalse(os.path.exists(self.dest))

    def test_unsafe_item_name_from_a_hand_built_plan_is_refused(self):
        host = self.source(M3, 10)
        st = os.stat(host)
        for name in ("..\\escape.rvt", "../escape.rvt", "sub\\x.rvt", "C:x.rvt", "CON.rvt", "",
                     None, 5):
            plan = {"items": [{"src": host, "name": name, "size": st.st_size,
                               "mtime": st.st_mtime}]}
            with self.assertRaises(StageError):
                self.run_all(plan)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "run", "escape.rvt")))
        self.assertEqual(self.dest_files(), [])

    def test_errors_exist_in_polish(self):
        plan = self.two_item_plan()
        os.utime(plan.items[0].src, (1900000500.0, 1900000500.0))
        with unittest.mock.patch.dict(sys.modules, polish()):
            with self.assertRaises(StageError) as changed:
                self.run_all(plan)
            plan = self.two_item_plan()
            os.makedirs(self.dest, exist_ok=True)
            with REAL_IO_OPEN(os.path.join(self.dest, "Alpha-Architecture.rvt"), "wb"):
                pass
            with self.assertRaises(StageError) as exists:
                self.run_all(plan)
        self.assertIn("Plik w pamięci podręcznej zmienił się podczas kopiowania. "
                      "Wyeksportuj ponownie.", "%s" % changed.exception)
        self.assertIn("Alpha-Architecture.rvt", "%s" % exists.exception)
        self.assertNotIn("already exists", "%s" % exists.exception)


# ------------------------------------------------------------------ no write on a source

class NeverWritesASource(StageCase):
    def recorded(self, scenario):
        """Run `scenario` with io.open, os.open and os.remove recorded; return the calls."""
        opened, created, removed = [], [], []

        def rec_io_open(path, mode="r", *args, **kwargs):
            opened.append(("%s" % path, mode))
            return REAL_IO_OPEN(path, mode, *args, **kwargs)

        def rec_os_open(path, flags, *args):
            created.append(("%s" % path, flags))
            return REAL_OS_OPEN(path, flags, *args)

        def rec_remove(path):
            removed.append("%s" % path)
            return REAL_OS_REMOVE(path)
        with unittest.mock.patch("os.open", rec_os_open), \
                unittest.mock.patch("os.remove", rec_remove), \
                unittest.mock.patch("os.unlink", rec_remove), \
                unittest.mock.patch("os.rename", side_effect=AssertionError("rename")), \
                unittest.mock.patch("shutil.move", side_effect=AssertionError("move")):
            scenario(rec_io_open)
        return opened, created, removed

    def assert_sources_only_read(self, sources, calls):
        opened, created, removed = calls
        sources = {os.path.normcase(os.path.abspath(s)) for s in sources}
        for path, mode in opened:
            self.assertEqual(mode, "rb", path)
            self.assertIn(os.path.normcase(os.path.abspath(path)), sources)
        dest_root = os.path.normcase(os.path.abspath(self.dest)) + os.sep
        for path, flags in created + [(p, 0) for p in removed]:
            path = os.path.normcase(os.path.abspath(path))
            self.assertNotIn(path, sources)
            self.assertTrue(path.startswith(dest_root), path)
        for path, flags in created:
            if flags & WRITE_FLAGS:
                self.assertTrue(flags & os.O_EXCL, "destination must be created exclusively")

    def test_every_path_opens_sources_read_only(self):
        def normal(opener):
            plan = self.two_item_plan()
            self.sources = [i.src for i in plan.items]
            self.run_all(plan, open=opener)

        def changed(opener):
            for name in self.dest_files():
                os.remove(os.path.join(self.dest, name))
            plan = StagePlan([self.item(self.sources[0], "Alpha-Architecture.rvt")._replace(
                size=1)], [])
            with self.assertRaises(StageError):
                self.run_all(plan, open=opener)

        def early_close(opener):
            plan = StagePlan([self.item(self.sources[0], "Alpha-Architecture.rvt")], [])
            steps = copy_steps(plan, self.dest, chunk=CHUNK, open=opener)
            next(steps)
            steps.close()

        def existing(opener):
            plan = StagePlan([self.item(self.sources[0], "Alpha-Architecture.rvt")], [])
            os.makedirs(self.dest, exist_ok=True)
            with REAL_IO_OPEN(os.path.join(self.dest, "Alpha-Architecture.rvt"), "wb"):
                pass
            with self.assertRaises(StageError):
                self.run_all(plan, open=opener)
            os.remove(os.path.join(self.dest, "Alpha-Architecture.rvt"))

        before = None
        for scenario in (normal, changed, early_close, existing):
            calls = self.recorded(scenario)
            if before is None:
                before = [facts(s) for s in self.sources]
                self.assertEqual([p for p, _m in calls[0]], self.sources)  # normal run read both
                self.assertTrue(calls[1])  # and created both destinations
            self.assert_sources_only_read(self.sources, calls)
        for path in self.sources:
            self.assertFalse(os.access(path, os.W_OK))
        self.assertEqual(before, [facts(s) for s in self.sources])

    def test_default_open_is_io_open(self):
        names = copy_steps.__code__.co_varnames[:copy_steps.__code__.co_argcount]
        defaults = dict(zip(names[-len(copy_steps.__defaults__):], copy_steps.__defaults__))
        self.assertIs(defaults["open"], io.open)
        self.assertIs(defaults["stat"], os.stat)
        self.assertEqual(defaults["chunk"], 8 * 2 ** 20)

    def test_source_text_writes_only_through_the_exclusive_create(self):
        source = (LIB / "rx_cloud_stage.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        modes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for arg in list(node.args) + [k.value for k in node.keywords]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and \
                            re.match(r"^[rwabxt+]{1,3}$", arg.value):
                        modes.append(arg.value)
        self.assertEqual(set(modes), {"rb"})
        self.assertIn("O_EXCL", source)
        self.assertNotIn("O_TRUNC", source)
        self.assertNotIn("O_APPEND", source)
        for banned in ("shutil", "os.rename", "os.replace", "os.unlink", "rmtree", "os.chmod",
                       "os.utime"):
            self.assertNotIn(banned, source)
        self.assertEqual(source.count("os.remove("), 1)


# ------------------------------------------------------------------ check_space

class CheckSpace(StageCase):
    def plan(self, *sizes):
        return StagePlan([StageItem("C:\\cache\\%d.rvt" % n, "M%d.rvt" % n, size, 1.0)
                          for n, size in enumerate(sizes)], [])

    def test_budget_is_the_copies_plus_the_extractors_own_copy(self):
        plan = self.plan(300 * 2 ** 20, 100 * 2 ** 20)
        self.assertEqual(rx_cloud_stage.needed_bytes(plan), 800 * 2 ** 20)
        self.assertEqual(check_space(plan, 800 * 2 ** 20), 800 * 2 ** 20)

    def test_refuses_when_space_is_short(self):
        plan = self.plan(300 * 2 ** 20, 100 * 2 ** 20)
        with self.assertRaises(StageError) as caught:
            check_space(plan, 800 * 2 ** 20 - 1)
        text = "%s" % caught.exception
        self.assertIn("800", text)
        self.assertIn("799", text)
        self.assertIn("disk space", text)
        with unittest.mock.patch.dict(sys.modules, polish()):
            with self.assertRaises(StageError) as polish_error:
                check_space(plan, 10)
        self.assertIn("miejsca", "%s" % polish_error.exception)
        self.assertIsInstance(caught.exception, ValueError)

    def test_links_budget_only_the_files_that_cannot_be_linked(self):
        plan = self.plan(300 * 2 ** 20, 100 * 2 ** 20)
        with unittest.mock.patch.object(rx_cloud_stage, "_linkable",
                                        lambda item, dest: item.size == 300 * 2 ** 20):
            names, copy_bytes = rx_cloud_stage.split_by_link(plan, True, "D:\out")
            self.assertEqual((names, copy_bytes), (["M0.rvt"], 100 * 2 ** 20))
            self.assertEqual(check_space(plan, 200 * 2 ** 20, links=True, dest="D:\out"),
                             200 * 2 ** 20)
            self.assertEqual(rx_cloud_stage.split_by_link(plan, False)[1], 400 * 2 ** 20)

    def test_unknown_free_space_does_not_block(self):
        self.assertEqual(check_space(self.plan(5), None), 10)

    def test_dict_plan_and_bad_input(self):
        self.assertEqual(check_space({"items": [{"src": "x", "name": "a.rvt", "size": 3,
                                                 "mtime": 1.0}]}, 6), 6)
        for bad in (-1, "lots", True):
            with self.assertRaises(StageError):
                check_space(self.plan(5), bad)


# ------------------------------------------------------------------ source guards

class SourceGuards(unittest.TestCase):
    SOURCE = (LIB / "rx_cloud_stage.py").read_text(encoding="utf-8")

    def test_no_revit_dotnet_or_clr_imports(self):
        banned = {"pyrevit", "Autodesk", "System", "clr", "rpw", "rx_runner"}
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
        for banned in ("os.replace", "scandir", "pathlib", "\t", "threading"):
            self.assertNotIn(banned, self.SOURCE)
        self.assertIn("from __future__ import unicode_literals", self.SOURCE)
        self.assertTrue(self.SOURCE.startswith("# -*- coding: utf-8 -*-"))
        self.assertNotIn('"xb"', self.SOURCE)  # io.open has no "x" mode on IronPython 2.7

    def test_no_revit_version_in_names(self):
        self.assertFalse(re.search(r"\b(rx_\w*|def \w*|class \w*)20(2\d)", self.SOURCE))

    def test_stage_error_is_shared_with_the_pure_module(self):
        self.assertIs(StageError, rx_cloud.StageError)
        self.assertTrue(issubclass(StageError, ValueError))


if __name__ == "__main__":
    unittest.main()
