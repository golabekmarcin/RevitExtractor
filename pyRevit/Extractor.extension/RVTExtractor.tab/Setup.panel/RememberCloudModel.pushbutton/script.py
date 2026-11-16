# -*- coding: utf-8 -*-
"""Remember the open cloud (ACC) model: its names and its link list go into the per-user memory
(%APPDATA%\\RevitExtractor\\cloud-catalog.json) that the Export button's cloud catalog reads.

This is the fallback for when the journals do not name a model. It only reads: no transaction,
no save, no sync, and the cache copy is never opened or changed. Only counts are shown, never a
name or a GUID. Spec: specs/SPEC-cloud-catalog.md (Fallback command).
"""
from __future__ import unicode_literals

import os
import re
import time

from pyrevit import DB, HOST_APP, forms

import rx_cloud
import rx_reader
from rx_i18n import tr

MEMORY_FOLDER = "RevitExtractor"
MEMORY_FILE = "cloud-catalog.json"
_GUID_ANYWHERE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                            r"-[0-9a-fA-F]{12}")


def _alert(message):
    forms.alert(message, title=tr("Remember cloud model", "Zapamiętaj model z chmury"))


def _name_or_none(text):
    """A trimmed name that carries no GUID, else None. Never raises."""
    try:
        value = ("%s" % text).strip() if text is not None else ""
    except Exception:
        return None
    if not value or _GUID_ANYWHERE.search(value):
        return None
    return value


def parse_visible_path(visible):
    """(project name, file name) from 'Autodesk Docs://<project>/<file>.rvt'; each is None when
    it cannot be read or would be a GUID. The shape is observed, not documented: never raises."""
    try:
        text = ("%s" % visible).strip() if visible is not None else ""
        if "://" not in text:
            return None, None
        parts = [part for part in text.split("://", 1)[1].replace("\\", "/").split("/") if part]
        if len(parts) < 2:
            return None, None
        file_name = _name_or_none(parts[-1])
        if file_name is not None and not file_name.lower().endswith(".rvt"):
            file_name = None
        return _name_or_none(parts[0]), file_name
    except Exception:
        return None, None


def _is_cloud(doc):
    try:
        return doc.IsModelInCloud is True
    except Exception:
        return False


def _read_ids_and_name(doc):
    """(project GUID, model GUID, project name, file name); GUIDs are None when unreadable.
    The ModelPath is read and disposed here."""
    path = doc.GetCloudModelPath()
    try:
        project = rx_cloud.normalize_guid(str(path.GetProjectGUID()))
        model = rx_cloud.normalize_guid(str(path.GetModelGUID()))
        visible = None
        try:
            visible = DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(path)
        except Exception:
            pass
    finally:
        try:
            path.Dispose()
        except Exception:
            pass
    project_name, file_name = parse_visible_path(visible)
    if file_name is None:
        title = _name_or_none(getattr(doc, "Title", None))
        if title is not None:
            file_name = title if title.lower().endswith(".rvt") else title + ".rvt"
    return project, model, project_name, file_name


def _cache_mtime(doc, project, model):
    """Newest mtime of this model's copies in the CollaborationCache of the running Revit, or
    None. Reads folder listings and file times only."""
    try:
        year = ("%s" % doc.Application.VersionNumber).strip()
        local = os.environ.get("LOCALAPPDATA")
        if not year or not local:
            return None
        cache = rx_cloud.revit_folders(local, year)["cache"]
        times = [item.mtime for item in rx_cloud.scan_cache(cache)
                 if item.project_guid == project and item.model_guid == model]
        return max(times) if times else None
    except Exception:
        return None


def _links(doc):
    try:
        return rx_reader.collect_cloud_links(doc, DB)
    except Exception:
        return None


def _memory_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, MEMORY_FOLDER, MEMORY_FILE)


def main():
    try:
        doc = HOST_APP.uiapp.ActiveUIDocument.Document
    except Exception:
        doc = None
    if doc is None:
        _alert(tr("Open a cloud model first.", "Najpierw otwórz model z chmury."))
        return
    if not _is_cloud(doc):
        _alert(tr("The open model is not a cloud (ACC) model. Nothing was remembered.",
                  "Otwarty model nie jest modelem z chmury (ACC). Nic nie zostało "
                  "zapamiętane."))
        return
    try:
        project, model, project_name, file_name = _read_ids_and_name(doc)
    except Exception:
        _alert(tr("The cloud model could not be read. Nothing was remembered.",
                  "Nie można odczytać modelu z chmury. Nic nie zostało "
                  "zapamiętane."))
        return
    if not project or not model:
        _alert(tr("The cloud model's ids could not be read. Nothing was remembered.",
                  "Nie można odczytać identyfikatorów modelu z chmury. Nic nie "
                  "zostało zapamiętane."))
        return

    memory = rx_cloud.Memory(_memory_path()).load()
    memory.merge([rx_cloud.Sighting(project, project_name, model, file_name, "button")],
                 time.time())
    links_remembered = 0
    mtime = _cache_mtime(doc, project, model)
    if mtime is not None:
        links = _links(doc)
        if links is not None:
            memory.store_links(rx_cloud.model_key(project, model), mtime, links)
            links_remembered = len(links)
    if not memory.save():
        _alert(tr("The memory file could not be saved. Nothing was remembered.",
                  "Nie można zapisać pliku pamięci. Nic nie zostało "
                  "zapamiętane."))
        return

    lines = [tr("This model was remembered.", "Zapamiętano ten model."),
             tr("Links remembered: {0}", "Zapamiętane łącza: {0}").format(links_remembered)]
    if mtime is None:
        lines.append(tr("No cache copy of this model was found, so its links were not stored.",
                        "Nie znaleziono kopii tego modelu w pamięci podręcznej, więc "
                        "jego łącza nie zostały zapisane."))
    _alert("\n".join(lines))


if __name__ == "__main__":
    main()
