# -*- coding: utf-8 -*-
"""cloud_cli.py (helper of run_extractor_integration.ps1 -Cloud): the fake cache tree, the stage
plan and the staged run, with a fake starter instead of a real Extractor.

Every GUID and name is synthetic (repeated digits, invented names). Nothing is written outside a
temp folder.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
LIB = TESTS.parents[2] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))

import cloud_cli  # noqa: E402
import rx_cloud  # noqa: E402
import rx_runner  # noqa: E402


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class FakeHandle(object):
    pid = 4242

    def has_exited(self):
        return True

    def exit_code(self):
        return 1

    def close(self):
        pass


class FakeStarter(object):
    def __init__(self):
        self.specs = []

    def start(self, spec, show_window=False):
        self.specs.append(spec)
        return FakeHandle()

    def run(self, spec):
        return 0


class CloudCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rx-cloud-cli-test-")
        self.sample = os.path.join(self.tmp, "sample.rvt")
        with open(self.sample, "wb") as handle:
            handle.write(b"synthetic model bytes " * 1000)
        self.base = os.path.join(self.tmp, "fixture")
        self.fixture = cloud_cli.build_fixture(self.base, self.sample, 2022)

    def tearDown(self):
        shutil.rmtree(self.tmp, True)

    def test_the_tree_has_the_cache_layout_and_a_journal(self):
        folders = rx_cloud.revit_folders(self.base, 2022)
        files = list(rx_cloud.scan_cache(folders["cache"]))
        self.assertEqual(sorted(f.place for f in files), ["linked", "root"])
        self.assertEqual(len(os.listdir(folders["journals"])), 1)
        for item in files:
            self.assertEqual(sha(item.path), sha(self.sample))

    def test_every_guid_is_synthetic(self):
        text = json.dumps(self.fixture)
        for guid in rx_cloud._GUID_ANYWHERE.findall(text):
            self.assertEqual(len(set(guid.replace("-", "").lower())), 1, guid)

    def test_the_catalog_names_the_host_and_the_plan_stages_it_first(self):
        stage = self.fixture["stage"]
        self.assertEqual(stage["items"][0]["name"], self.fixture["model_name"])
        self.assertEqual(len(stage["items"]), 2)
        self.assertEqual(len(stage["notes"]), 1)
        self.assertEqual(self.fixture["model_key"], "cloud:%s/%s" % (
            cloud_cli.PROJECT, cloud_cli.HOST))
        self.assertEqual(self.fixture["counts"]["named_rows"], 2)

    def test_a_staged_run_leaves_only_stage_json_and_the_cache_untouched(self):
        before = dict((p, sha(p)) for p in self.fixture["cache_files"])
        out = os.path.join(self.tmp, "exports")
        revit = os.path.join(self.tmp, "Revit X")
        os.makedirs(os.path.join(revit, "RevitExtractor"))
        open(os.path.join(revit, "RevitExtractor", "RevitExtractor.exe"), "wb").close()
        starter = FakeStarter()
        result = cloud_cli.run_staged(self.fixture, revit, 2022, out, starter=starter,
                                      tree_running=lambda: False, timeout=30)
        self.assertEqual(len(starter.specs), 1)
        self.assertTrue(starter.specs[0].env["RX_MODEL"].endswith(
            os.path.join("model", self.fixture["model_name"])))
        self.assertEqual(result["model_dir"], ["stage.json"])
        self.assertEqual(result["states"][:2], ["staging", "running"])
        self.assertEqual(before, dict((p, sha(p)) for p in self.fixture["cache_files"]))

    @unittest.skipUnless(sys.platform == "win32", "Windows PowerShell 5.1 only")
    def test_the_kit_prints_cloud_counts_and_no_name_path_or_guid(self):
        import subprocess
        appdata = os.path.join(self.tmp, "appdata")
        os.makedirs(appdata)
        done = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(TESTS / "v1_test_kit.ps1"), "-Check", "-LocalAppData", self.base,
             "-AppData", appdata], capture_output=True, text=True, encoding="utf-8",
            errors="replace")
        self.assertEqual(done.returncode, 0, done.stderr)
        out = done.stdout
        self.assertIn("journals folder 1, journals 1 (unreadable 0), named cloud models 2; "
                      "cache folder 1, cached models 2, unnamed 0", " ".join(out.split()))
        for secret in (cloud_cli.PROJECT_NAME, "Beta-MEP", "Gamma", self.base, "99999999"):
            self.assertNotIn(secret, out)
        self.assertEqual(rx_cloud._GUID_ANYWHERE.findall(out), [])

    def test_main_prints_ascii_json_and_reports_errors(self):
        # an unknown revit dir fails inside the queue: the job fails, the helper still reports
        out = os.path.join(self.tmp, "exports")
        result = cloud_cli.run_staged(self.fixture, os.path.join(self.tmp, "none"), 2022, out,
                                      starter=FakeStarter(), tree_running=lambda: False,
                                      timeout=10)
        self.assertEqual(result["state"], "failed")
        json.dumps(result, ensure_ascii=True)


if __name__ == "__main__":
    unittest.main()
