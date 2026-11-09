# -*- coding: utf-8 -*-
"""Read-only facts about a cloud (ACC) model, its links, Revit's local cache and journals.

Gathers evidence for choosing how to export cloud models (Shift+click, config.py).
It never opens Revit files, copies or writes anything. The cache scan lists names, sizes and
dates only; journals are read as text to find "CLD://{project}(name)/{model}(name)" lines.
Revit API calls are passed in, so this module runs and is tested outside Revit.
"""
from __future__ import unicode_literals

import io
import os
import re
import time

from extractor_i18n import tr

try:
    text = unicode
except NameError:
    text = str

GUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
GUID_RE = re.compile(GUID)
JOURNAL_RE = re.compile(r"CLD://\{?(" + GUID + r")\}?(?:\(([^)]*)\))?/\{?(" + GUID + r")\}?(?:\(([^)]*)\))?")


def _safe(func):
    """Call func; an exception becomes an "ERROR: ..." value, so one failure never hides the rest."""
    try:
        return func()
    except Exception as error:
        return "ERROR: {0}: {1}".format(type(error).__name__, error)


def _guid(value):
    to_string = getattr(value, "ToString", None)
    return text(to_string() if to_string else value).strip("{}").lower()


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


def _describe_resources(element):
    """Every external resource of the element, with all its reference information."""
    try:
        references = list(element.GetExternalResourceReferences())
    except Exception as error:
        return {"resources": "ERROR: {0}: {1}".format(type(error).__name__, error)}
    out = {"resources_count": len(references)}
    for index, entry in enumerate(references):
        prefix = "resource{0}_".format(index)
        resource_type, reference = entry.Key, entry.Value
        out[prefix + "type"] = _safe(lambda: text(getattr(resource_type, "TypeId", resource_type)))
        out[prefix + "server_id"] = _safe(lambda: text(reference.ServerId))
        out[prefix + "in_session_path"] = _safe(lambda: text(reference.InSessionPath))
        info = _safe(lambda: [(text(item.Key), text(item.Value))
                              for item in reference.GetReferenceInformation()])
        if isinstance(info, list):
            for key, value in info:
                out[prefix + "info_" + key] = value
        else:
            out[prefix + "info"] = info
    return out


def collect(doc, link_types, get_reference, user_visible, name_of=None):
    """Describe the active model and each RevitLinkType. Read-only."""
    name_of = name_of or (lambda element: element.Name)
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
            "name": _safe(lambda: text(name_of(link_type))),
            "nested": _safe(lambda: bool(link_type.IsNestedLink)),
            "attachment": _safe(lambda: text(link_type.AttachmentType)),
            "from_local_path": _safe(lambda: bool(link_type.IsFromLocalPath())),
        }
        if get_reference is not None:
            try:
                reference = get_reference(doc, link_type.Id)
            except Exception as error:
                row["file_reference"] = "ERROR: {0}: {1}".format(type(error).__name__, error)
                reference = None
            else:
                row["file_reference"] = "ok" if reference is not None else "None"
            if reference is not None:
                row["path_type"] = _safe(lambda: text(reference.PathType))
                row["status"] = _safe(lambda: text(reference.GetLinkedFileStatus()))
                try:
                    link_path = reference.GetPath()
                except Exception as error:
                    row["path"] = "ERROR: {0}".format(error)
                else:
                    row.update(_describe_path(link_path, user_visible))
        row.update(_describe_resources(link_type))
        links.append(row)
    return {"model": model, "links": links}


def guids(data):
    """Every GUID that appears in any value of collect()'s result, lower-case, no braces."""
    found = set()
    for item in [data.get("model", {})] + list(data.get("links", [])):
        for value in item.values():
            for match in GUID_RE.findall(text(value)):
                found.add(match.lower())
    return found


def _revit_folder(revit_version, name):
    local = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local, "Autodesk", "Revit", "Autodesk Revit {0}".format(revit_version), name)


def cache_roots(revit_version):
    """Revit's per-version collaboration cache folder (layout confirmed on a real ACC model:
    <root>\\<account>\\<project GUID>\\<model GUID>.rvt plus a CentralCache copy)."""
    return [_revit_folder(revit_version, "CollaborationCache")]


def journal_roots(revit_version):
    return [_revit_folder(revit_version, "Journals")]


def _file_info(path):
    stat = os.stat(path)
    return {"path": path, "size": stat.st_size,
            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))}


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
                try:
                    found.append(_file_info(os.path.join(folder, name)))
                except OSError:
                    continue
                if len(found) >= max_entries:
                    return found
    return found


def scan_project_folders(roots, guid_values, max_entries=300):
    """Every .rvt under <root>\\<account>\\<project GUID>\\ for the given GUIDs: the models of
    those projects that this machine has cached, including links, whatever their GUID."""
    wanted = set(text(value).lower() for value in guid_values)
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for account in sorted(os.listdir(root)):
            account_dir = os.path.join(root, account)
            if not os.path.isdir(account_dir):
                continue
            for project in sorted(os.listdir(account_dir)):
                project_dir = os.path.join(account_dir, project)
                if project.lower() not in wanted or not os.path.isdir(project_dir):
                    continue
                for folder, subfolders, files in os.walk(project_dir, onerror=lambda error: None):
                    for name in sorted(files):
                        if not name.lower().endswith(".rvt"):
                            continue
                        try:
                            found.append(_file_info(os.path.join(folder, name)))
                        except OSError:
                            continue
                        if len(found) >= max_entries:
                            return found
    return found


def _read_text(path, max_bytes):
    with open(path, "rb") as handle:
        raw = handle.read(max_bytes)
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    return raw.decode(encoding, "replace")


def journal_cloud_names(roots, max_files=40, max_bytes=20 * 1024 * 1024):
    """Unique (project, model) GUID/name pairs from the newest Revit journals' CLD:// lines."""
    files = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            if name.lower().startswith("journal") and name.lower().endswith(".txt"):
                path = os.path.join(root, name)
                try:
                    files.append((os.path.getmtime(path), path))
                except OSError:
                    continue
    seen = {}
    for unused, path in sorted(files, reverse=True)[:max_files]:
        try:
            content = _read_text(path, max_bytes)
        except (IOError, OSError):
            continue
        for project_guid, project_name, model_guid, model_name in JOURNAL_RE.findall(content):
            key = (project_guid.lower(), model_guid.lower())
            entry = seen.setdefault(key, {"project_guid": key[0], "project_name": "",
                                          "model_guid": key[1], "model_name": "",
                                          "journal": os.path.basename(path)})
            entry["project_name"] = entry["project_name"] or project_name
            entry["model_name"] = entry["model_name"] or model_name
    return sorted(seen.values(), key=lambda item: (item["project_name"], item["model_name"]))


def _block(title, item):
    lines = [title]
    for key in sorted(item):
        lines.append("  {0}: {1}".format(key, text(item[key]).replace("\n", " ")))
    return "\n".join(lines)


def _files(title, items):
    lines = [title]
    if not items:
        lines.append("  " + tr("(none)", "(brak)"))
    for item in items:
        lines.append("  {0}  |  {1} B  |  {2}".format(item["path"], item["size"], item["modified"]))
    return "\n".join(lines)


def format_report(data, roots, cache_hits, project_files, journal_dirs, journal_names):
    """Plain text (pyRevit's Markdown renderer merged tables and dropped headings)."""
    links = data.get("links", [])
    parts = ["== " + tr("Cloud model check (read-only), v2", "Sprawdzenie modelu w chmurze (tylko odczyt), v2"),
             _block("[model]", data.get("model", {}))]
    for index, link in enumerate(links):
        parts.append(_block("[link {0}/{1}]".format(index + 1, len(links)), link))
    parts.append("[cache roots]\n" + "\n".join(
        "  {0} ({1})".format(root, "exists" if os.path.isdir(root) else "not found") for root in roots))
    parts.append(_files("[cache files naming a known GUID]", cache_hits))
    parts.append(_files("[every .rvt in the cached project folders]", project_files))
    parts.append("[journals]\n" + "\n".join(
        "  {0} ({1})".format(root, "exists" if os.path.isdir(root) else "not found") for root in journal_dirs))
    names = ["  {0} ({1}) / {2} ({3})  [{4}]".format(
        item.get("project_name", ""), item.get("project_guid", ""), item.get("model_name", ""),
        item.get("model_guid", ""), item.get("journal", "")) for item in journal_names]
    parts.append("[cloud names found in journals]\n" + ("\n".join(names) if names else "  (none)"))
    parts.append(tr("Nothing was opened, copied or written. This report contains client project and "
                    "file names: send it privately, never commit it to the public repository.",
                    "Niczego nie otwarto, nie skopiowano ani nie zapisano. Raport zawiera nazwy "
                    "projektów i plików klienta: wyślij go prywatnie, nigdy nie dodawaj do publicznego "
                    "repozytorium."))
    return "\n\n".join(parts)
