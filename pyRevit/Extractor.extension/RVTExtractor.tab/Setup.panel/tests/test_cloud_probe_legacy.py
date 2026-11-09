"""Read-only cloud (ACC) probe of the ExportSetupLegacy bundle, tested without Revit."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

BUNDLE = Path(__file__).resolve().parents[1] / "ExportSetupLegacy.pushbutton"
sys.path.append(str(BUNDLE))  # append, never prepend (see test_config_legacy.py)


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, BUNDLE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load_module("cloud_probe_under_test", "extractor_cloud_probe.py")

MODEL_GUID = "11111111-2222-3333-4444-555555555555"
PROJECT_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
LINK_GUID = "99999999-8888-7777-6666-555555555555"


def raises(message):
    def call(*args):
        raise Exception(message)
    return call


class FakeGuid(object):
    def __init__(self, value):
        self.value = value

    def ToString(self):
        return self.value


def cloud_path(project, model):
    return types.SimpleNamespace(CloudPath=True, ServerPath=False,
                                 GetProjectGUID=lambda: FakeGuid(project),
                                 GetModelGUID=lambda: FakeGuid(model))


class CollectTests(unittest.TestCase):
    def test_cloud_model_and_link_are_described_and_errors_become_data(self):
        link_ref = types.SimpleNamespace(
            PathType="Cloud", GetPath=lambda: cloud_path(PROJECT_GUID, LINK_GUID),
            GetLinkedFileStatus=lambda: "Loaded")
        link = types.SimpleNamespace(Name="Structure.rvt", Id=7, IsNestedLink=False,
                                     AttachmentType="Overlay", IsFromLocalPath=lambda: False)
        doc = types.SimpleNamespace(
            Title="Main", PathName="Autodesk Docs://Project/Main.rvt", IsWorkshared=True,
            IsModelInCloud=True, GetCloudModelPath=lambda: cloud_path(PROJECT_GUID, MODEL_GUID),
            GetCloudModelUrn=raises("not available"),
            Application=types.SimpleNamespace(VersionNumber="2022", VersionBuild="22.1.0"))
        data = probe.collect(doc, [link], get_reference=lambda d, i: link_ref,
                             user_visible=lambda path: "Autodesk Docs://Project/x.rvt")
        self.assertEqual(data["model"]["model_guid"], MODEL_GUID)
        self.assertEqual(data["model"]["project_guid"], PROJECT_GUID)
        self.assertTrue(data["model"]["cloud_model_urn"].startswith("ERROR:"))
        self.assertEqual(data["links"][0]["name"], "Structure.rvt")
        self.assertEqual(data["links"][0]["model_guid"], LINK_GUID)
        self.assertEqual(probe.guids(data), {MODEL_GUID, PROJECT_GUID, LINK_GUID})

    def test_local_model_has_no_cloud_guids(self):
        doc = types.SimpleNamespace(
            Title="Local", PathName="C:\\P\\Local.rvt", IsWorkshared=False, IsModelInCloud=False,
            GetCloudModelPath=raises("not a cloud model"), GetCloudModelUrn=raises("no"),
            Application=types.SimpleNamespace(VersionNumber="2023", VersionBuild="23.0"))
        data = probe.collect(doc, [], get_reference=None, user_visible=lambda path: "")
        self.assertEqual(probe.guids(data), set())


class CacheScanTests(unittest.TestCase):
    def test_lists_only_files_naming_a_known_guid_and_never_writes(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, "user1", PROJECT_GUID)
            os.makedirs(folder)
            for name in (MODEL_GUID + ".rvt", LINK_GUID.replace("-", "") + ".rvt", "other.rvt"):
                with open(os.path.join(folder, name), "wb") as handle:
                    handle.write(b"x" * 10)
            before = sorted(os.listdir(folder))
            found = probe.scan_cache([root], {MODEL_GUID, LINK_GUID})
            self.assertEqual(sorted(os.listdir(folder)), before)
        names = sorted(os.path.basename(item["path"]) for item in found)
        self.assertEqual(names, sorted([MODEL_GUID + ".rvt", LINK_GUID.replace("-", "") + ".rvt"]))
        self.assertTrue(all(item["size"] == 10 for item in found))

    def test_missing_root_and_entry_limit(self):
        self.assertEqual(probe.scan_cache(["Z:\\does\\not\\exist"], {MODEL_GUID}), [])
        with tempfile.TemporaryDirectory() as root:
            for index in range(5):
                open(os.path.join(root, "{0}-{1}.rvt".format(MODEL_GUID, index)), "w").close()
            self.assertEqual(len(probe.scan_cache([root], {MODEL_GUID}, max_entries=3)), 3)

    def test_cache_roots_follow_revit_version(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:\\Users\\u\\AppData\\Local"}):
            roots = probe.cache_roots("2022")
        self.assertEqual(roots, [os.path.join("C:\\Users\\u\\AppData\\Local", "Autodesk", "Revit",
                                              "Autodesk Revit 2022", "CollaborationCache")])


class ReportTests(unittest.TestCase):
    def test_report_contains_model_links_and_cache_hits(self):
        data = {"model": {"title": "Main", "model_guid": MODEL_GUID},
                "links": [{"name": "Structure.rvt", "model_guid": LINK_GUID}]}
        cache = [{"path": "C:\\cache\\" + MODEL_GUID + ".rvt", "size": 10, "modified": "2026-11-09 10:00"}]
        text = probe.format_report(data, ["C:\\cache"], cache)
        for expected in ("Main", MODEL_GUID, "Structure.rvt", LINK_GUID, "C:\\cache"):
            self.assertIn(expected, text)


class EntryPointTests(unittest.TestCase):
    def test_shift_click_prints_report_and_handles_missing_document(self):
        for doc in (None, types.SimpleNamespace(IsFamilyDocument=True)):
            with self.subTest(doc=doc):
                output = Mock()
                pyrevit = types.SimpleNamespace(forms=Mock(), revit=types.SimpleNamespace(doc=doc),
                                                script=types.SimpleNamespace(get_output=lambda: output),
                                                DB=Mock())
                with patch.dict(sys.modules, {"pyrevit": pyrevit}):
                    command = load_module("probe_command_under_test", "config.py")
                    command.main()
                self.assertTrue(pyrevit.forms.alert.called)
                self.assertFalse(output.print_md.called)


if __name__ == "__main__":
    unittest.main()
