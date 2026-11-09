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


def pair(key, value):
    return types.SimpleNamespace(Key=key, Value=value)


def cloud_doc():
    return types.SimpleNamespace(
        Title="Main", PathName="Autodesk Docs://Project/Main.rvt", IsWorkshared=True,
        IsModelInCloud=True, GetCloudModelPath=lambda: cloud_path(PROJECT_GUID, MODEL_GUID),
        GetCloudModelUrn=raises("not available"),
        Application=types.SimpleNamespace(VersionNumber="2022", VersionBuild="22.1.0"))


class CollectTests(unittest.TestCase):
    def test_cloud_model_and_link_are_described_and_errors_become_data(self):
        link_ref = types.SimpleNamespace(
            PathType="Cloud", GetPath=lambda: cloud_path(PROJECT_GUID, LINK_GUID),
            GetLinkedFileStatus=lambda: "Loaded")
        link = types.SimpleNamespace(Name="Structure.rvt", Id=7, IsNestedLink=False,
                                     AttachmentType="Overlay", IsFromLocalPath=lambda: False,
                                     GetExternalResourceReferences=lambda: [])
        data = probe.collect(cloud_doc(), [link], get_reference=lambda d, i: link_ref,
                             user_visible=lambda path: "Autodesk Docs://Project/x.rvt")
        self.assertEqual(data["model"]["model_guid"], MODEL_GUID)
        self.assertEqual(data["model"]["project_guid"], PROJECT_GUID)
        self.assertTrue(data["model"]["cloud_model_urn"].startswith("ERROR:"))
        self.assertEqual(data["links"][0]["name"], "Structure.rvt")
        self.assertEqual(data["links"][0]["file_reference"], "ok")
        self.assertEqual(data["links"][0]["model_guid"], LINK_GUID)
        self.assertEqual(probe.guids(data), {MODEL_GUID, PROJECT_GUID, LINK_GUID})

    def test_name_falls_back_and_missing_reference_is_reported(self):
        class NoName(object):
            Id = 8
            IsNestedLink = False
            AttachmentType = "Overlay"

            @property
            def Name(self):
                raise AttributeError("Name")

            def IsFromLocalPath(self):
                return False

            def GetExternalResourceReferences(self):
                return []

        data = probe.collect(cloud_doc(), [NoName()], get_reference=lambda d, i: None,
                             user_visible=lambda path: "", name_of=lambda element: "Fallback.rvt")
        self.assertEqual(data["links"][0]["name"], "Fallback.rvt")
        self.assertEqual(data["links"][0]["file_reference"], "None")

    def test_external_resources_are_dumped_and_their_guids_collected(self):
        info = [pair("ProjectGuid", PROJECT_GUID), pair("ModelGuid", "{" + LINK_GUID.upper() + "}")]
        resource = types.SimpleNamespace(ServerId="srv", InSessionPath="cloud://x",
                                         GetReferenceInformation=lambda: info)
        link = types.SimpleNamespace(
            Name="Arch.rvt", Id=9, IsNestedLink=False, AttachmentType="Overlay",
            IsFromLocalPath=lambda: False,
            GetExternalResourceReferences=lambda: [pair(types.SimpleNamespace(TypeId="RevitLink"), resource)])
        data = probe.collect(cloud_doc(), [link], get_reference=raises("not a file reference"),
                             user_visible=lambda path: "")
        row = data["links"][0]
        self.assertTrue(row["file_reference"].startswith("ERROR:"))
        self.assertEqual(row["resources_count"], 1)
        self.assertEqual(row["resource0_info_ModelGuid"], "{" + LINK_GUID.upper() + "}")
        self.assertIn(LINK_GUID, probe.guids(data))

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

    def test_project_folders_list_every_cached_model(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, "ACCOUNT", PROJECT_GUID)
            os.makedirs(os.path.join(folder, "CentralCache"))
            for relative in ("a.rvt", os.path.join("CentralCache", "a.rvt"), "notes.txt"):
                open(os.path.join(folder, relative), "w").close()
            os.makedirs(os.path.join(root, "ACCOUNT", "other-project"))
            open(os.path.join(root, "ACCOUNT", "other-project", "b.rvt"), "w").close()
            found = probe.scan_project_folders([root], {PROJECT_GUID, MODEL_GUID})
        relative = sorted(os.path.relpath(item["path"], root) for item in found)
        self.assertEqual(relative, sorted([os.path.join("ACCOUNT", PROJECT_GUID, "a.rvt"),
                                           os.path.join("ACCOUNT", PROJECT_GUID, "CentralCache", "a.rvt")]))

    def test_missing_root_and_entry_limit(self):
        self.assertEqual(probe.scan_cache(["Z:\\does\\not\\exist"], {MODEL_GUID}), [])
        with tempfile.TemporaryDirectory() as root:
            for index in range(5):
                open(os.path.join(root, "{0}-{1}.rvt".format(MODEL_GUID, index)), "w").close()
            self.assertEqual(len(probe.scan_cache([root], {MODEL_GUID}, max_entries=3)), 3)

    def test_cache_and_journal_roots_follow_revit_version(self):
        local = "C:\\Users\\u\\AppData\\Local"
        with patch.dict(os.environ, {"LOCALAPPDATA": local}):
            self.assertEqual(probe.cache_roots("2022"), [os.path.join(
                local, "Autodesk", "Revit", "Autodesk Revit 2022", "CollaborationCache")])
            self.assertEqual(probe.journal_roots("2022"), [os.path.join(
                local, "Autodesk", "Revit", "Autodesk Revit 2022", "Journals")])


class JournalTests(unittest.TestCase):
    def test_cloud_names_are_read_from_journal_lines(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "journal.0001.txt"), "w", encoding="utf-8") as handle:
                handle.write("noise\n' [Jrn.Data] CLD://{0}(My Project)/{1}(Structure.rvt) more\n"
                             .format("{" + PROJECT_GUID + "}", "{" + LINK_GUID + "}"))
                handle.write("' CLD://{0}(My Project)/{1}(Structure.rvt) again\n"
                             .format(PROJECT_GUID, LINK_GUID))
            open(os.path.join(root, "not-a-journal.log"), "w").close()
            found = probe.journal_cloud_names([root])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["project_guid"], PROJECT_GUID)
        self.assertEqual(found[0]["project_name"], "My Project")
        self.assertEqual(found[0]["model_guid"], LINK_GUID)
        self.assertEqual(found[0]["model_name"], "Structure.rvt")

    def test_missing_journal_folder(self):
        self.assertEqual(probe.journal_cloud_names(["Z:\\nope"]), [])


class ReportTests(unittest.TestCase):
    def test_plain_text_report_contains_everything(self):
        data = {"model": {"title": "Main", "model_guid": MODEL_GUID},
                "links": [{"name": "Structure.rvt", "model_guid": LINK_GUID}]}
        cache = [{"path": "C:\\cache\\" + MODEL_GUID + ".rvt", "size": 10, "modified": "2026-11-09 10:00"}]
        names = [{"project_guid": PROJECT_GUID, "project_name": "P", "model_guid": LINK_GUID,
                  "model_name": "Structure.rvt"}]
        text = probe.format_report(data, ["C:\\cache"], cache, cache, ["C:\\journals"], names)
        for expected in ("Main", MODEL_GUID, "Structure.rvt", LINK_GUID, "C:\\cache", PROJECT_GUID,
                         "C:\\journals"):
            self.assertIn(expected, text)
        self.assertNotIn("|---", text)  # plain text, not Markdown tables


class EntryPointTests(unittest.TestCase):
    def test_shift_click_handles_missing_document(self):
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
                self.assertFalse(output.print_code.called)


if __name__ == "__main__":
    unittest.main()
