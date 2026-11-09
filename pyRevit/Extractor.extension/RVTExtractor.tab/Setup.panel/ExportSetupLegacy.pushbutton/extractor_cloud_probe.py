# -*- coding: utf-8 -*-
"""Read-only facts about a cloud (ACC) model, its links and Revit's local cache.

Gathers evidence for choosing how to export cloud models (see Shift+click, config.py).
It never opens, copies or writes files: the cache scan lists names, sizes and dates only.
Revit API calls are passed in, so this module runs and is tested outside Revit.
"""
from __future__ import unicode_literals

import os
import time

from extractor_i18n import tr

try:
    text = unicode
except NameError:
    text = str


def _safe(func):
    """Call func; an exception becomes an "ERROR: ..." value, so one failure never hides the rest."""
    try:
        return func()
    except Exception as error:
        return "ERROR: {0}".format(error)


def _guid(value):
    to_string = getattr(value, "ToString", None)
    return text(to_string() if to_string else value).lower()


def _describe_path(model_path, user_visible):
    info = {
        "user_visible_path": _safe(lambda: text(user_visible(model_path))),
        "cloud_path": _safe(lambda: bool(model_path.CloudPath)),
        "server_path": _safe(lambda: bool(model_path.ServerPath)),
    }
    if info["cloud_path"] is True:
        info["project_guid"] = _safe(lambda: _guid(model_path.GetProjectGUID()))
        info["model_guid"] = _safe(lambda: _guid(model_path.GetModelGUID()))
    return info


def collect(doc, link_types, get_reference, user_visible):
    """Describe the active model and each RevitLinkType. Read-only."""
    app = doc.Application
    model = {
        "title": _safe(lambda: text(doc.Title)),
        "path_name": _safe(lambda: text(doc.PathName)),
        "revit_version": _safe(lambda: text(app.VersionNumber)),
        "revit_build": _safe(lambda: text(app.VersionBuild)),
        "workshared": _safe(lambda: bool(doc.IsWorkshared)),
        "in_cloud": _safe(lambda: bool(doc.IsModelInCloud)),
    }
    if model["in_cloud"] is True:
        try:
            cloud_path = doc.GetCloudModelPath()
        except Exception as error:
            model["cloud_model_path"] = "ERROR: {0}".format(error)
        else:
            model.update(_describe_path(cloud_path, user_visible))
        model["cloud_model_urn"] = _safe(lambda: text(doc.GetCloudModelUrn()))

    links = []
    for link_type in link_types:
        row = {
            "name": _safe(lambda: text(link_type.Name)),
            "nested": _safe(lambda: bool(link_type.IsNestedLink)),
            "attachment": _safe(lambda: text(link_type.AttachmentType)),
            "from_local_path": _safe(lambda: bool(link_type.IsFromLocalPath())),
        }
        if get_reference is not None:
            try:
                reference = get_reference(doc, link_type.Id)
            except Exception as error:
                row["reference"] = "ERROR: {0}".format(error)
            else:
                row["path_type"] = _safe(lambda: text(reference.PathType))
                row["status"] = _safe(lambda: text(reference.GetLinkedFileStatus()))
                try:
                    link_path = reference.GetPath()
                except Exception as error:
                    row["path"] = "ERROR: {0}".format(error)
                else:
                    row.update(_describe_path(link_path, user_visible))
        links.append(row)
    return {"model": model, "links": links}


def guids(data):
    """Every project/model GUID found in collect()'s result."""
    found = set()
    for item in [data.get("model", {})] + list(data.get("links", [])):
        for key in ("project_guid", "model_guid"):
            value = item.get(key)
            if value and not text(value).startswith("ERROR"):
                found.add(text(value).lower())
    return found


def cache_roots(revit_version):
    """Revit's per-version collaboration cache folder (an undocumented convention, hence probed)."""
    local = os.environ.get("LOCALAPPDATA", "")
    return [os.path.join(local, "Autodesk", "Revit", "Autodesk Revit {0}".format(revit_version),
                         "CollaborationCache")]


def scan_cache(roots, guid_values, max_entries=200, max_depth=6):
    """Files under roots whose *file name* contains one of the GUIDs (with or without dashes).

    Lists name, size and modification time only; never opens a file.
    """
    needles = set()
    for value in guid_values:
        value = text(value).lower()
        needles.add(value)
        needles.add(value.replace("-", ""))
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip("\\/").count(os.sep)
        for folder, subfolders, files in os.walk(root, onerror=lambda error: None):
            if folder.rstrip("\\/").count(os.sep) - base_depth >= max_depth:
                del subfolders[:]
            for name in sorted(files):
                lowered = name.lower()
                if not any(needle and needle in lowered for needle in needles):
                    continue
                path = os.path.join(folder, name)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                found.append({"path": path, "size": stat.st_size,
                              "modified": time.strftime("%Y-%m-%d %H:%M",
                                                        time.localtime(stat.st_mtime))})
                if len(found) >= max_entries:
                    return found
    return found


def _cell(value):
    return text(value).replace("|", "\\|").replace("\n", " ")


def _table(item):
    lines = ["| | |", "|---|---|"]
    for key in sorted(item):
        lines.append("| {0} | {1} |".format(key, _cell(item[key])))
    return "\n".join(lines)


def format_report(data, roots, cache):
    """Markdown for pyRevit's output window."""
    parts = ["# " + tr("Cloud model check (read-only)", "Sprawdzenie modelu w chmurze (tylko odczyt)"),
             "## " + tr("Model", "Model"), _table(data.get("model", {})),
             "## " + tr("Links", "Linki") + " ({0})".format(len(data.get("links", [])))]
    for link in data.get("links", []):
        parts.append("### " + _cell(link.get("name", "?")))
        parts.append(_table(link))
    parts.append("## " + tr("Local cache", "Lokalna pamięć podręczna"))
    for root in roots:
        parts.append("- `{0}` ({1})".format(root, tr("exists", "istnieje") if os.path.isdir(root)
                                            else tr("not found", "nie znaleziono")))
    if cache:
        parts.append("| path | size | modified |\n|---|---|---|")
        parts.append("\n".join("| {0} | {1} | {2} |".format(_cell(item["path"]), item["size"],
                                                           item["modified"]) for item in cache))
    else:
        parts.append(tr("No cached file names contain these GUIDs.",
                        "Żadna nazwa pliku w pamięci podręcznej nie zawiera tych GUID."))
    parts.append(tr("Nothing was opened, copied or written. Copy this report for the developer; "
                    "it contains project and file names.",
                    "Niczego nie otwarto, nie skopiowano ani nie zapisano. Skopiuj ten raport dla "
                    "autora narzędzia; zawiera nazwy projektu i plików."))
    return "\n\n".join(parts)
