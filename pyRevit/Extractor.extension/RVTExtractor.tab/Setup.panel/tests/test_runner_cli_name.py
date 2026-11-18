# -*- coding: utf-8 -*-
"""runner_cli.py name on a synthetic run folder (named-copies Task 9, the integration helper)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "runner_cli.py")
G1 = "11111111-1111-1111-1111-111111111111"
G3 = "33333333-3333-3333-3333-333333333333"
KEYS = {"state", "counts", "items_by_kind", "named_entries_on_disk", "linked_files_checked",
        "links_verified", "longest_named_path", "output_unchanged", "output_files_compared",
        "notes"}


def touch(root, rel, data=b"x"):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


class RunnerCliNameTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="rxcli-name-")
        self.addCleanup(shutil.rmtree, self.root, True)
        manifest = {"type": "folder", "name": "root", "children": [
            {"type": "folder", "name": "Sheets", "children": [
                {"type": "geometry", "name": "Zebra sheet", "viewableID": G1}]},
            {"type": "folder", "name": "3D", "children": [
                {"type": "geometry", "name": "Quokka view", "viewableID": G3}]}]}
        touch(self.root, "index.json", b"{}")
        touch(self.root, "output/bubble.json", json.dumps(manifest).encode("utf-8"))
        touch(self.root, "output/Resource/%s/Zebra sheet.pdf" % G1, b"pdf" * 40)
        touch(self.root, "output/Resource/3D/%s/0/quokka.svf" % G3, b"svf" * 20)
        touch(self.root, "output/Resource/3D/%s/0/sub/quokka.bin" % G3, b"bin" * 10)

    def run_cli(self, *args):
        done = subprocess.run([sys.executable, "-B", CLI, "name"] + list(args),
                              capture_output=True, text=True, timeout=120)
        return done.returncode, done.stdout

    def test_names_counts_only(self):
        code, out = self.run_cli(os.path.join(self.root, "output"))   # the output\ form
        self.assertEqual(code, 0, out)
        data = json.loads(out)
        self.assertEqual(set(data), KEYS)
        self.assertEqual(data["state"], "done")
        self.assertTrue(data["output_unchanged"])
        self.assertEqual(data["output_files_compared"], 4)
        self.assertEqual(data["counts"]["linked"] + data["counts"]["copied"], 2)
        self.assertEqual(data["items_by_kind"], {"pdf": 1, "view": 1})
        if data["counts"]["copied"] == 0:
            self.assertTrue(data["links_verified"])
        self.assertTrue(os.path.isdir(os.path.join(self.root, "named")))
        for text in ("Zebra", "Quokka", "quokka", G1, G3, "rxcli-name", self.root,
                     self.root.replace("\\", "\\\\"), "Users"):
            self.assertNotIn(text, out)

    def test_second_run_is_refused(self):
        self.assertEqual(self.run_cli(self.root)[0], 0)
        code, out = self.run_cli(self.root)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["state"], "failed")

    def test_not_a_run_folder(self):
        code, out = self.run_cli(os.path.join(self.root, "output", "Resource"))
        self.assertEqual(code, 2)
        self.assertNotIn(self.root, out)


if __name__ == "__main__":
    unittest.main()
