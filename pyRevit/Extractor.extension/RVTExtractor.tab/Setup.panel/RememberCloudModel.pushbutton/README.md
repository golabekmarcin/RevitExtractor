# Remember cloud model (Revit 2022 and later)

English · [Polski](README.pl.md)

A pyRevit button for the fallback case of the Export button's cloud list: with a cloud (ACC) model open, it remembers that model's project name, file name and its Revit links in your per-user memory (`%APPDATA%\RevitExtractor\cloud-catalog.json`). The Export button reads that memory when the Revit journals do not name a model.

**Status: built and unit-tested outside Revit. Not yet run in Revit.** See Validation.

## Use

1. Open a cloud model (Autodesk Docs / ACC) in Revit. The button is greyed when no project is open.
2. Click **Remember cloud model**.
3. A short message gives counts only: the models remembered and the links remembered for this model. Names and ids are never shown.

If the open model is not a cloud model, you get a message and nothing is written.

## What it does

- Reads `Document.IsModelInCloud`, the cloud model path (project and model ids, then disposed), the user-visible path (`Autodesk Docs://<project>/<file>.rvt`, parsed defensively) and the link list.
- Writes names to the memory. The links are stored together with the date of this model's copy in `%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit <year>\CollaborationCache`; when no such copy exists only the names are stored and the message says so.
- **Read-only on the model:** no transaction, no save, no synchronise. The cache copy is only listed (names and times), never opened or changed.
- The memory holds client project and file names. It stays in your profile; do not share it or commit it.

All text is English and Polish, following pyRevit's language setting (English by default).

## Validation

Unit tests with a stubbed document and pyRevit (`tests/test_remember_cloud.py`, CPython 3): non-cloud document writes nothing, cloud document writes the memory, no transaction, model path disposed, English and Polish text, IronPython syntax guards.

**Not verified:** IronPython 2.7, pyRevit (greying of the button, `doc-project` for a cloud model), and everything inside Revit: the real shape of the user-visible path, `GetCloudModelPath` on a real cloud model, the link list and the cache folder of a real session. Owner's checklist: `specs/v1-revit-test.md` (Part H).
