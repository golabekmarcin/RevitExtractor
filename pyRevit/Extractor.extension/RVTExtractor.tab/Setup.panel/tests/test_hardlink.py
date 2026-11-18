# -*- coding: utf-8 -*-
"""Tests for lib/rx_hardlink.py and the hard-link route of rx_cloud_stage.copy_steps
(temporary folders and synthetic files only; no Revit)."""
import ast
import json
import os
import stat
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
LIB = TESTS.parents[2] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))

import rx_hardlink  # noqa: E402
import rx_status  # noqa: E402
from rx_cloud import StageItem, StagePlan  # noqa: E402
from rx_cloud_stage import copy_steps  # noqa: E402
from test_cloud_stage import CHUNK, StageCase, facts  # noqa: E402


class MakeHardLink(unittest.TestCase):
    def test_enabled_unless_exactly_false(self):
        self.assertFalse(rx_hardlink.hardlinks_enabled({"cloud_hardlinks": False}))
        for on in ({}, {"cloud_hardlinks": True}, {"cloud_hardlinks": 0}, {"cloud_hardlinks": "false"},
                   None, [], "x"):
            self.assertTrue(rx_hardlink.hardlinks_enabled(on), on)

    def test_uses_os_link_when_present(self):
        calls = []
        rx_hardlink.make_hard_link("a", "b", os_link=lambda s, d: calls.append((s, d)))
        self.assertEqual(calls, [("a", "b")])

    def test_falls_back_to_createhardlinkw_without_os_link(self):
        seen = []

        class Kernel(object):
            def CreateHardLinkW(self, link_path, source, security):
                seen.append((link_path, source, security))
                return 1

        rx_hardlink.make_hard_link("src", "dst", os_link=None, kernel32=Kernel())
        self.assertEqual(seen, [("dst", "src", None)])    # new name first, existing file second

    def test_failed_createhardlinkw_raises_oserror(self):
        class Kernel(object):
            def CreateHardLinkW(self, *args):
                return 0

        with self.assertRaises(OSError):
            rx_hardlink.make_hard_link("src", "dst", os_link=None, kernel32=Kernel())

    def test_source_guards(self):
        source = (LIB / "rx_hardlink.py").read_text(encoding="utf-8")
        self.assertIn("from __future__ import unicode_literals", source)
        self.assertNotIn("\t", source)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) \
                    else [node.module or ""]
                for name in names:
                    self.assertNotIn(name.split(".")[0], {"clr", "System", "pyrevit", "Autodesk"})
        for banned in ("os.remove", "os.unlink", "shutil", "os.chmod", "os.rename"):
            self.assertNotIn(banned, source)



class WritablePlan(object):
    def writable_plan(self):
        """Sources without the read-only attribute: only those are ever linked."""
        plan = self.two_item_plan()
        for item in plan.items:
            os.chmod(item.src, stat.S_IREAD | stat.S_IWRITE)
        return plan


class LinkRoute(WritablePlan, StageCase):
    def test_link_is_used_instead_of_a_copy(self):
        plan = self.writable_plan()
        before = [facts(i.src) for i in plan.items]
        steps = list(copy_steps(plan, self.dest, chunk=CHUNK, link=os.link))
        self.assertEqual([s[2].name for s in steps], ["Alpha-Architecture.rvt", "Beta-MEP.rvt"])
        self.assertEqual(steps[-1][0], sum(i.size for i in plan.items))
        for item in plan.items:
            target = os.path.join(self.dest, item.name)
            self.assertTrue(os.path.samefile(target, item.src))
            self.assertEqual(os.stat(target).st_nlink, 2)
        self.assertEqual(before, [facts(i.src) for i in plan.items])

    def test_failing_link_falls_back_to_a_copy_per_item(self):
        plan = self.writable_plan()

        def link(source, target):
            if target.endswith("Beta-MEP.rvt"):
                raise OSError("different drive")
            os.link(source, target)

        list(copy_steps(plan, self.dest, chunk=CHUNK, link=link))
        alpha, beta = [os.path.join(self.dest, i.name) for i in plan.items]
        self.assertTrue(os.path.samefile(alpha, plan.items[0].src))
        self.assertFalse(os.path.samefile(beta, plan.items[1].src))
        self.assertEqual(facts(beta)[2], facts(plan.items[1].src)[2])

    def test_existing_target_is_never_replaced_by_a_link(self):
        plan = self.two_item_plan()
        os.makedirs(self.dest)
        existing = os.path.join(self.dest, "Alpha-Architecture.rvt")
        with open(existing, "wb") as handle:
            handle.write(b"mine")
        calls = []
        with self.assertRaises(ValueError):    # StageError
            list(copy_steps(plan, self.dest, chunk=CHUNK, link=lambda s, t: calls.append(t)))
        self.assertEqual(calls, [])
        with open(existing, "rb") as handle:
            self.assertEqual(handle.read(), b"mine")

    def test_source_changed_after_planning_removes_only_the_link(self):
        plan = self.two_item_plan()
        stale = StagePlan([plan.items[0]._replace(size=plan.items[0].size + 1)], [])
        with self.assertRaises(ValueError):
            list(copy_steps(stale, self.dest, chunk=CHUNK, link=os.link))
        self.assertTrue(os.path.exists(plan.items[0].src))
        self.assertEqual(self.dest_files(), [])

    def test_read_only_source_is_copied_not_linked(self):
        plan = self.two_item_plan()    # read-only like the real cache
        modes = {}
        list(copy_steps(plan, self.dest, chunk=CHUNK, link=os.link,
                        report=lambda item, mode: modes.update({item.name: mode})))
        self.assertEqual(modes, {"Alpha-Architecture.rvt": "copied", "Beta-MEP.rvt": "copied"})
        self.assertEqual(os.stat(plan.items[0].src).st_nlink, 1)

    def test_report_says_linked(self):
        plan = self.writable_plan()
        modes = {}
        list(copy_steps(plan, self.dest, chunk=CHUNK, link=os.link,
                        report=lambda item, mode: modes.update({item.name: mode})))
        self.assertEqual(set(modes.values()), {"linked"})

    def test_without_link_argument_nothing_is_linked(self):
        plan = self.two_item_plan()
        list(copy_steps(plan, self.dest, chunk=CHUNK))
        self.assertEqual(os.stat(plan.items[0].src).st_nlink, 1)


class CloudCopier(WritablePlan, StageCase):
    def prefs(self, data):
        path = os.path.join(self.tmp, "preferences.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return path

    def test_preference_true_links(self):
        plan = self.writable_plan()
        copier = rx_status.cloud_copier(self.prefs({"cloud_hardlinks": True}))
        list(copier(plan, self.dest, CHUNK))
        self.assertEqual(os.stat(plan.items[0].src).st_nlink, 2)

    def test_preference_false_copies(self):
        plan = self.writable_plan()
        copier = rx_status.cloud_copier(self.prefs({"cloud_hardlinks": False}))
        list(copier(plan, self.dest, CHUNK))
        self.assertEqual(os.stat(plan.items[0].src).st_nlink, 1)
        self.assertFalse(copier.linking())

    def test_missing_or_other_preference_links_by_default(self):
        for number, data in enumerate(({}, {"cloud_hardlinks": "no"}, {"other": 1})):
            plan = self.writable_plan()
            copier = rx_status.cloud_copier(self.prefs(data))
            dest = os.path.join(self.tmp, "run-%d" % number, "model")
            list(copier(plan, dest, CHUNK))
            self.assertEqual(os.stat(plan.items[0].src).st_nlink, 2, data)
            self.assertTrue(copier.linking())
            for item in plan.items:     # reset the file for the next round
                os.remove(os.path.join(dest, item.name))

    def test_missing_preferences_file_links(self):
        plan = self.writable_plan()
        list(rx_status.cloud_copier(os.path.join(self.tmp, "nope.json"))(plan, self.dest, CHUNK))
        self.assertEqual(os.stat(plan.items[0].src).st_nlink, 2)

    def test_preference_is_read_for_every_job(self):
        path = self.prefs({"cloud_hardlinks": False})
        copier = rx_status.cloud_copier(path)
        plan = self.writable_plan()
        list(copier(plan, os.path.join(self.tmp, "run-a", "model"), CHUNK))
        self.assertEqual(os.stat(plan.items[0].src).st_nlink, 1)
        self.prefs({})
        list(copier(plan, os.path.join(self.tmp, "run-b", "model"), CHUNK))
        self.assertEqual(os.stat(plan.items[0].src).st_nlink, 2)


if __name__ == "__main__":
    unittest.main()
