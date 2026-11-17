# -*- coding: utf-8 -*-
"""Tests for RememberCloudModel.pushbutton (specs/SPEC-cloud-catalog.md, fallback command).

Revit, pyRevit and the document are stubs; every GUID and name is synthetic. CPython 3 with
stubs: passing here proves nothing about IronPython, pyRevit or Revit behaviour.
"""
import ast
import json
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PANEL = Path(__file__).resolve().parents[1]
LIB = PANEL.parents[1] / "lib"
BUTTON = PANEL / "RememberCloudModel.pushbutton"
for folder in (LIB, PANEL / "tests"):
    if str(folder) not in sys.path:
        sys.path.append(str(folder))

import rx_cloud  # noqa: E402
import test_export_button  # noqa: E402
import test_status  # noqa: E402
import test_window_legacy as legacy  # noqa: E402
from wpf_fakes import polish as polish_modules  # noqa: E402

PROJECT = "11111111-1111-1111-1111-111111111111"
MODEL = "22222222-2222-2222-2222-222222222222"
LINK_PROJECT = "33333333-3333-3333-3333-333333333333"
LINK_MODEL = "44444444-4444-4444-4444-444444444444"
VISIBLE = "Autodesk Docs://Invented Project/Invented Host.rvt"


class FakeModelPath(object):
    def __init__(self, project=PROJECT, model=MODEL):
        self.project, self.model, self.disposed = project, model, 0

    def GetProjectGUID(self):
        return self.project

    def GetModelGUID(self):
        return self.model

    def Dispose(self):
        self.disposed += 1


class FakeDoc(object):
    def __init__(self, cloud=True, path=None, title="Invented Host", year="2022"):
        self.IsModelInCloud = cloud
        self.Title = title
        self.path = path or FakeModelPath()
        self.Application = types.SimpleNamespace(VersionNumber=year)
        self.calls = []

    def GetCloudModelPath(self):
        self.calls.append("GetCloudModelPath")
        return self.path

    # Anything that would write must never be called.
    def Save(self, *a):
        raise AssertionError("Save")

    def SaveAs(self, *a):
        raise AssertionError("SaveAs")

    def SynchronizeWithCentral(self, *a):
        raise AssertionError("sync")


class RememberTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rxremember-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.appdata = os.path.join(self.tmp, "Roaming")
        self.localappdata = os.path.join(self.tmp, "Local")
        self.alerts = []
        self.transactions = []
        self.visible = VISIBLE
        self.links = [{"name": "Invented Link.rvt", "project_guid": LINK_PROJECT,
                       "model_guid": LINK_MODEL, "region": "US", "nested": False}]
        self.doc = FakeDoc()
        self.module = self.load()

    def load(self):
        test = self

        class Transaction(object):
            def __init__(self, *a, **kw):
                test.transactions.append(a)

        db = types.SimpleNamespace(
            Transaction=Transaction, TransactionGroup=Transaction,
            ModelPathUtils=types.SimpleNamespace(
                ConvertModelPathToUserVisiblePath=lambda path: test.visible))
        forms = types.SimpleNamespace(alert=lambda msg, **kw: test.alerts.append(msg))
        host = types.SimpleNamespace(
            uiapp=types.SimpleNamespace(
                ActiveUIDocument=types.SimpleNamespace(Document=self.doc)))
        stubs = {"pyrevit": types.SimpleNamespace(DB=db, HOST_APP=host, forms=forms)}
        module = legacy.load("remember_script_under_test", "script.py", stubs, BUTTON)
        env = patch.dict(os.environ, {"APPDATA": self.appdata, "LOCALAPPDATA": self.localappdata})
        env.start()
        self.addCleanup(env.stop)
        patcher = patch.object(module.rx_reader, "collect_cloud_links",
                               side_effect=lambda doc, DB, name_of=None: list(self.links))
        patcher.start()
        self.addCleanup(patcher.stop)
        return module

    def set_doc(self, doc):
        self.doc = doc
        self.module.HOST_APP.uiapp.ActiveUIDocument.Document = doc

    def memory_path(self):
        return os.path.join(self.appdata, "RevitExtractor", "cloud-catalog.json")

    def memory(self):
        return rx_cloud.Memory(self.memory_path()).load()

    def put_cache(self, year="2022", place="root", model=MODEL, project=PROJECT, mtime=1700000000):
        folder = rx_cloud.revit_folders(self.localappdata, year)["cache"]
        folder = os.path.join(folder, "acct", project)
        if place == "linked":
            folder = os.path.join(folder, "LinkedModels")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, model + ".rvt")
        with open(path, "wb") as handle:
            handle.write(b"x")
        os.utime(path, (mtime, mtime))
        return path

    # -- not a cloud model

    def test_a_non_cloud_document_gets_a_message_and_writes_nothing(self):
        self.set_doc(FakeDoc(cloud=False))
        self.module.main()
        self.assertEqual(len(self.alerts), 1)
        self.assertFalse(os.path.exists(self.appdata))
        self.assertEqual(self.doc.calls, [])   # GetCloudModelPath raises on a non-cloud document

    def test_no_document_gets_a_message_and_writes_nothing(self):
        self.module.HOST_APP.uiapp.ActiveUIDocument = None
        self.module.main()
        self.assertEqual(len(self.alerts), 1)
        self.assertFalse(os.path.exists(self.appdata))

    def test_a_non_bool_flag_is_not_a_cloud_model(self):
        self.doc.IsModelInCloud = "True"
        self.module.main()
        self.assertFalse(os.path.exists(self.appdata))

    # -- cloud model

    def test_names_are_written_to_the_memory(self):
        self.module.main()
        memory = self.memory()
        self.assertEqual(memory.project_name(PROJECT), "Invented Project")
        self.assertEqual(memory.model_name(PROJECT, MODEL), "Invented Host.rvt")

    def test_links_are_stored_with_the_cache_mtime(self):
        self.put_cache(mtime=1700000000)
        self.module.main()
        key = rx_cloud.model_key(PROJECT, MODEL)
        self.assertEqual(self.memory().links_for(key, 1700000000), self.links)

    def test_the_newer_of_root_and_linked_copy_gives_the_mtime(self):
        self.put_cache(place="root", mtime=1700000000)
        self.put_cache(place="linked", mtime=1700005000)
        self.module.main()
        key = rx_cloud.model_key(PROJECT, MODEL)
        self.assertIsNotNone(self.memory().links_for(key, 1700005000))

    def test_without_a_cache_file_only_names_are_stored(self):
        self.module.main()
        memory = self.memory()
        self.assertEqual(memory.links, {})
        self.assertEqual(memory.model_name(PROJECT, MODEL), "Invented Host.rvt")

    def test_the_cache_folder_of_the_open_revit_year_is_used(self):
        self.put_cache(year="2023")           # another year: not this document's cache
        self.module.main()
        self.assertEqual(self.memory().links, {})

    def test_guids_are_normalised(self):
        self.set_doc(FakeDoc(path=FakeModelPath(PROJECT.upper(), "{" + MODEL.upper() + "}")))
        self.module.main()
        self.assertEqual(self.memory().model_name(PROJECT, MODEL), "Invented Host.rvt")

    def test_a_guid_is_never_stored_as_a_name(self):
        self.visible = "Autodesk Docs://%s/%s.rvt" % (PROJECT, MODEL)
        self.set_doc(FakeDoc(title=MODEL))
        self.module.main()
        memory = self.memory()
        self.assertIsNone(memory.project_name(PROJECT))
        self.assertIsNone(memory.model_name(PROJECT, MODEL))
        self.assertNotIn(PROJECT, json.dumps(memory.projects))
        self.assertNotIn(MODEL, json.dumps(list(memory.names.values())))

    def test_an_unparsable_visible_path_falls_back_to_the_title(self):
        for bad in ("", None, "no scheme here", "Autodesk Docs://"):
            self.visible = bad
            self.module.main()
        memory = self.memory()
        self.assertEqual(memory.model_name(PROJECT, MODEL), "Invented Host.rvt")
        self.assertIsNone(memory.project_name(PROJECT))

    def test_a_visible_path_that_raises_never_raises_out(self):
        def boom(path):
            raise RuntimeError("no")
        self.module.DB.ModelPathUtils.ConvertModelPathToUserVisiblePath = boom
        self.module.main()
        self.assertEqual(self.memory().model_name(PROJECT, MODEL), "Invented Host.rvt")

    def test_an_unreadable_guid_writes_nothing(self):
        self.set_doc(FakeDoc(path=FakeModelPath("not a guid", MODEL)))
        self.module.main()
        self.assertFalse(os.path.exists(self.appdata))
        self.assertEqual(len(self.alerts), 1)

    def test_a_second_run_keeps_the_first_and_adds(self):
        self.module.main()
        self.set_doc(FakeDoc(path=FakeModelPath(LINK_PROJECT, LINK_MODEL)))
        self.visible = "Autodesk Docs://Other Project/Other Host.rvt"
        self.module.main()
        self.assertEqual(len(self.memory().names), 2)

    def test_link_reading_failure_still_stores_names(self):
        self.put_cache()
        self.module.rx_reader.collect_cloud_links.side_effect = RuntimeError("no")
        self.module.main()
        self.assertEqual(self.memory().model_name(PROJECT, MODEL), "Invented Host.rvt")
        self.assertEqual(self.memory().links, {})

    # -- read-only

    def test_no_transaction_and_the_model_path_is_disposed(self):
        self.put_cache()
        self.module.main()
        self.assertEqual(self.transactions, [])
        self.assertEqual(self.doc.path.disposed, 1)

    def test_the_model_path_is_disposed_when_reading_fails(self):
        self.doc.path.GetProjectGUID = Mock(side_effect=RuntimeError("no"))
        self.module.main()
        self.assertEqual(self.doc.path.disposed, 1)
        self.assertEqual(len(self.alerts), 1)

    def test_the_cache_is_only_read_never_changed(self):
        path = self.put_cache()
        before = (os.path.getsize(path), os.path.getmtime(path))
        self.module.main()
        self.assertEqual((os.path.getsize(path), os.path.getmtime(path)), before)

    def test_the_source_has_no_write_calls_on_the_document(self):
        source = (BUTTON / "script.py").read_text(encoding="utf-8")
        for banned in ("Transaction", ".Save", "SynchronizeWithCentral", "OpenDocumentFile"):
            self.assertNotIn(banned, source)

    # -- messages

    def summary(self):
        self.assertEqual(len(self.alerts), 1)
        return self.alerts[0]

    def test_the_summary_has_counts_and_no_names_or_guids(self):
        self.put_cache()
        self.module.main()
        text = self.summary()
        for private in ("Invented", PROJECT, MODEL, LINK_MODEL):
            self.assertNotIn(private, text)

    def test_the_summary_counts_models_and_links(self):
        self.put_cache()
        self.links = self.links * 3
        self.module.main()
        text = self.summary()
        self.assertIn("This model was remembered.", text)
        self.assertIn("Links remembered: 3", text)

    def test_messages_are_english_by_default_and_polish_on_request(self):
        self.module.main()
        english = self.summary()
        self.assertIn("This model was remembered", english)
        for make in (lambda: FakeDoc(cloud=False), lambda: FakeDoc()):
            self.alerts[:] = []
            self.set_doc(make())
            with patch.dict(sys.modules, polish_modules()):
                self.module.main()
            self.assertTrue(re.search("[\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c]",
                                      self.summary()), self.summary())
            self.assertNotEqual(self.summary(), english)

    def test_every_message_is_a_tr_call_with_two_texts(self):
        tree = ast.parse((BUTTON / "script.py").read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "tr"]
        self.assertGreaterEqual(len(calls), 6)
        for call in calls:
            self.assertEqual(len(call.args), 2)


class BundleFiles(unittest.TestCase):
    def test_bundle_yaml_is_bilingual_and_gated(self):
        text = (BUTTON / "bundle.yaml").read_text(encoding="utf-8")
        for key in ("title", "tooltip"):
            block = re.search(r"^%s:\n((?:  .*\n?)+)" % key, text, re.M).group(1)
            self.assertIn("en_us:", block)
            self.assertIn("pl:", block)
        self.assertRegex(text, r"(?m)^min_revit_version: 2022$")
        self.assertNotIn("max_revit_version", text)
        self.assertRegex(text, r'(?m)^context:\n  rule: "doc-project"$')

    def test_readmes_exist_and_link_each_other(self):
        english = (BUTTON / "README.md").read_text(encoding="utf-8")
        polish = (BUTTON / "README.pl.md").read_text(encoding="utf-8")
        self.assertIn("README.pl.md", english)
        self.assertIn("README.md", polish)
        for text in (english, polish):
            self.assertIn("Revit", text)

    def test_files_pass_the_ironpython_guards(self):
        files = sorted(BUTTON.glob("*.py"))
        self.assertEqual([p.name for p in files], ["script.py"])
        for path in files:
            source = path.read_text(encoding="utf-8")
            self.assertEqual(test_status.ironpython_problems(source), [], path.name)
            self.assertEqual(test_export_button.extra_ironpython_problems(source), [], path.name)

    def test_no_revit_version_in_names(self):
        year = re.compile(r"(?<!\d)20[2-3]\d(?!\d)")
        self.assertIsNone(year.search(BUTTON.name))
        for path in BUTTON.rglob("*"):
            self.assertIsNone(year.search(path.name), path.name)
        self.assertIsNone(year.search(Path(__file__).name))


if __name__ == "__main__":
    unittest.main()
