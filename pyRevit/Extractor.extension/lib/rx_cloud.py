# -*- coding: utf-8 -*-
"""Cloud (ACC) model list from Revit's CollaborationCache and journals, without opening a model.

Pure Python, no Revit, .NET or clr import (a test enforces this). Compatible with pyRevit
IronPython 2.7 (io.open, os.walk, os.stat, json, re only). Spec: specs/SPEC-cloud-catalog.md.

Journals name the models (project name and file name, keyed by a GUID pair); the cache holds the
files under GUID names. They are joined only by the GUID pair. Nothing here writes to the cache or
the journals. The name memory holds client project and file names: it lives in the user's profile,
never in the repo, and nothing here logs its content. A GUID is never returned as a name.
"""
from __future__ import unicode_literals

import io
import json
import os
import re
from collections import namedtuple

from rx_i18n import tr
from rx_json import dumps_ascii

MEMORY_VERSION = 1
STALE_DAYS = 7
JOURNAL_LIMIT = 100
LINES_PER_STEP = 5000       # journal lines parsed per step of scan()
FILES_PER_STEP = 200        # cache files stat'ed per step of scan()
_MTIME_TOLERANCE = 0.001    # seconds; JSON round trip and filesystem timestamp precision

STATES = ("ok", "stale", "not_selected", "duplicate")

_GUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_GUID_RE = re.compile(r"^" + _GUID + r"$")
_GUID_ANYWHERE = re.compile(_GUID)
_PATH_LINE = re.compile(
    r'Path\s*=\s*"CLD:\\{1,2}(?P<region>[^\\"]+)\\{1,2}\{(?P<project>' + _GUID +
    r')\}(?P<pname>[^\\"]*)\\{1,2}\{(?P<model>' + _GUID + r')\}(?P<file>[^\\"]*)"')
_REGION_ATTR = re.compile(r'Region\s*=\s*"(?P<region>[^"]*)"')
_BROWSER_MARK = "ModelBrowserOpenDocumentEvent:open:"
_PERCENT = re.compile(r"(?:%[0-9A-Fa-f]{2})+")

Sighting = namedtuple(str("Sighting"),
                      str("project_guid project_name model_guid file_name source"))
CacheFile = namedtuple(str("CacheFile"),
                       str("account project_guid model_guid place path size mtime"))
CloudRow = namedtuple(str("CloudRow"),
                      str("key project name cache_path cache_date size state enabled note "
                          "account project_guid model_guid place cache_mtime"))
Project = namedtuple(str("Project"), str("key account guid name selected count unnamed note"))
Catalog = namedtuple(str("Catalog"), str("rows projects counts message"))
StageItem = namedtuple(str("StageItem"), str("src name size mtime"))
StagePlan = namedtuple(str("StagePlan"), str("items notes"))

_BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = set(["CON", "PRN", "AUX", "NUL"] + ["COM%d" % n for n in range(1, 10)] +
                      ["LPT%d" % n for n in range(1, 10)])
_MAX_NAME = 255


class StageError(ValueError):
    """Staging a cloud model cannot be planned or copied. The message is translated."""


# ---------------------------------------------------------------- helpers

def normalize_guid(text):
    """Lower case, braces stripped; None when the text is not a GUID."""
    if text is None:
        return None
    try:
        value = ("%s" % text).strip().strip("{}").strip().lower()
    except Exception:
        return None
    return value if _GUID_RE.match(value) else None


def _is_zero_guid(guid):
    return guid.replace("-", "").strip("0") == ""


def _has_guid(text):
    return bool(text) and bool(_GUID_ANYWHERE.search(text))


def _has_percent(text):
    return bool(_PERCENT.search(text))


def _unquote(text):
    """%XX sequences decoded as UTF-8; a sequence that is not valid UTF-8 is left as written."""
    def replace(match):
        raw = match.group(0)
        try:
            data = bytearray(int(part, 16) for part in raw.split("%")[1:])
            return bytes(data).decode("utf-8")
        except Exception:
            return raw
    return _PERCENT.sub(replace, text)


def _clean_name(text):
    """A usable display name or None: trimmed, never empty, never carrying a GUID."""
    if text is None:
        return None
    value = ("%s" % text).strip()
    if not value or _has_guid(value):
        return None
    return value


def project_key(account, project_guid):
    return "%s/%s" % (account, project_guid)


def model_key(project_guid, model_guid):
    return "%s/%s" % (project_guid, model_guid)


def revit_folders(localappdata, year):
    base = os.path.join(localappdata, "Autodesk", "Revit", "Autodesk Revit %s" % year)
    return {"cache": os.path.join(base, "CollaborationCache"),
            "journals": os.path.join(base, "Journals")}


# ---------------------------------------------------------------- journals

def iter_journals(folder, limit=JOURNAL_LIMIT, listdir=os.listdir, stat=os.stat, errors=None):
    """Yield (path, mtime) of journal*.txt, newest first, at most `limit`.

    A folder that cannot be listed or a file that cannot be stat'ed is skipped and appended to
    `errors` (the path, when given); nothing is raised.
    """
    problems = errors if errors is not None else []
    try:
        names = listdir(folder)
    except Exception:
        problems.append(folder)
        return
    found = []
    for name in names:
        lowered = name.lower()
        if not (lowered.startswith("journal") and lowered.endswith(".txt")):
            continue
        path = os.path.join(folder, name)
        try:
            found.append((stat(path).st_mtime, name, path))
        except Exception:
            problems.append(path)
    found.sort(key=lambda item: (item[0], item[1].lower()), reverse=True)
    for mtime, _name, path in found[:max(0, limit)]:
        yield path, mtime


def decode_journal(raw):
    """Text from journal bytes: UTF-16 with BOM (or clearly UTF-16 without), UTF-8 (strict), else
    Windows-1250. Never raises."""
    try:
        if raw is None:
            return ""
        if not isinstance(raw, (bytes, bytearray)):
            return "%s" % raw
        raw = bytes(raw)
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return raw.decode("utf-16", "replace")
        if raw[:3] == b"\xef\xbb\xbf":
            return raw[3:].decode("utf-8", "replace")
        if len(raw) >= 4 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00" and b"\x00" not in raw[0:1]:
            return raw.decode("utf-16-le", "replace")  # no BOM, ASCII-range letters
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp1250", "replace")
    except Exception:
        return ""


def _line_sightings(line):
    """Sightings of one journal line (empty list for any other line). Never raises."""
    try:
        if _BROWSER_MARK in line:
            return _browser_sightings(line)
        if "ModelPath Created" in line and "CLD:" in line:
            return _path_sightings(line)
    except Exception:
        pass
    return []


def _path_sightings(line):
    match = _PATH_LINE.search(line)
    if not match:
        return []
    region_attr = _REGION_ATTR.search(line)
    for region in (match.group("region"), region_attr.group("region") if region_attr else ""):
        if region.strip().upper() == "GLOBAL":
            return []
    project = normalize_guid(match.group("project"))
    model = normalize_guid(match.group("model"))
    if not project or not model or _is_zero_guid(project) or _is_zero_guid(model):
        return []
    file_name = _clean_name(match.group("file"))
    if not file_name:
        return []
    pname = match.group("pname")
    if _has_percent(pname):
        pname = _unquote(pname)
    return [Sighting(project, _clean_name(pname), model, file_name, "path")]


def _browser_sightings(line):
    text = line.split(_BROWSER_MARK, 1)[1]
    start = text.find("{")
    if start < 0:
        return []
    body = text[start:].replace('""', '"')
    try:
        data, _end = json.JSONDecoder().raw_decode(body)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    region = data.get("region")
    if isinstance(region, type("")) and region.strip().upper() == "GLOBAL":
        return []
    project = normalize_guid(data.get("projectGuid"))
    model = normalize_guid(data.get("modelGuid"))
    if not project or not model or _is_zero_guid(project) or _is_zero_guid(model):
        return []
    name = data.get("displayName")
    file_name = _clean_name(name) if isinstance(name, type("")) else None
    if not file_name:
        return []
    return [Sighting(project, None, model, file_name, "browser")]


def _parse_lines(lines):
    found = []
    for line in lines:
        if _BROWSER_MARK in line or "ModelPath Created" in line:
            found.extend(_line_sightings(line))
    return found


def _prefer_plain(sightings):
    """A project name spelled with %XX is replaced by a plain spelling of the same project GUID."""
    plain = {}
    for item in sightings:
        if item.project_name and item.source == "path" and not _has_percent(item.project_name):
            plain[item.project_guid] = item.project_name
    return list(sightings) if not plain else [
        item._replace(project_name=plain.get(item.project_guid, item.project_name))
        if item.project_name else item for item in sightings]


def parse_journal(text):
    """Generator of Sighting for every cloud model named in the journal text.

    Sees both the `ModelPath Created ... Path = "CLD:\\\\..."` lines (project and file name) and
    the `ModelBrowserOpenDocumentEvent:open:` lines (file name only). Everything else is ignored.
    """
    # A plain spelling of a project name wins over a %XX one, so the whole text is read first.
    for item in _prefer_plain(_parse_lines((text or "").splitlines())):
        yield item


# ---------------------------------------------------------------- cache

def _is_guid_rvt(name):
    if not name.lower().endswith(".rvt"):
        return None
    return normalize_guid(name[:-4]) if _GUID_RE.match(name[:-4]) else None


def scan_cache(cache_root, walk=os.walk, stat=os.stat, errors=None):
    """Yield CacheFile for <account>\\<project GUID>\\<model GUID>.rvt (place "root") and
    ...\\LinkedModels\\<model GUID>.rvt (place "linked").

    CentralCache folders and other names are ignored. A missing or unreadable folder is appended
    to `errors` (when given) and never raised.
    """
    problems = errors if errors is not None else []

    def on_error(exc):
        problems.append(getattr(exc, "filename", None) or cache_root)

    try:
        for folder, dirs, files in walk(cache_root, onerror=on_error):
            rel = os.path.relpath(folder, cache_root)
            parts = [] if rel == os.curdir else rel.split(os.sep)
            depth = len(parts)
            if depth == 0:
                dirs[:] = sorted(dirs, key=lambda d: d.lower())
                continue
            if depth == 1:
                dirs[:] = sorted((d for d in dirs if normalize_guid(d)), key=lambda d: d.lower())
                continue
            if depth == 2:
                dirs[:] = [d for d in dirs if d.lower() == "linkedmodels"]
                place = "root"
            elif depth == 3 and parts[2].lower() == "linkedmodels":
                dirs[:] = []
                place = "linked"
            else:
                dirs[:] = []
                continue
            project = normalize_guid(parts[1])
            for name in sorted(files, key=lambda n: n.lower()):
                model = _is_guid_rvt(name)
                if not model:
                    continue
                path = os.path.join(folder, name)
                try:
                    st = stat(path)
                    yield CacheFile(parts[0], project, model, place, path,
                                    st.st_size, st.st_mtime)
                except Exception:
                    problems.append(path)
    except Exception:
        problems.append(cache_root)


# ---------------------------------------------------------------- memory

class Memory(object):
    """Selection, remembered names and link lists, in the user's profile.

    A missing, corrupt or other-version file gives an empty memory and never raises. Holds client
    names: never in the repo, never in logs.
    """

    def __init__(self, file_path):
        self.file_path = file_path
        self.included = set()   # project keys "<account>/<project GUID>" the user ticked
        self.projects = {}      # project GUID -> {"name", "mtime"}
        self.names = {}         # "<project>/<model>" -> {"name", "mtime"}
        self.links = {}         # "<project>/<model>" -> {"cache_mtime", "links"}
        self.last_error = None
        self.dirty = False

    def _clear(self):
        self.included, self.projects, self.names, self.links = set(), {}, {}, {}

    def load(self):
        self._clear()
        self.dirty = False
        try:
            with io.open(self.file_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not (isinstance(data, dict) and data.get("version") == MEMORY_VERSION):
                return self
            included = data.get("included")
            projects, names, links = data.get("projects"), data.get("names"), data.get("links")
            if not (isinstance(included, list) and isinstance(projects, dict)
                    and isinstance(names, dict) and isinstance(links, dict)):
                return self
            self.included = set(item for item in included if isinstance(item, type("")))
            self.projects, self.names, self.links = projects, names, links
        except Exception:
            self._clear()
        return self

    def merge(self, sightings, journal_mtime):
        """Remember names. A name from a journal older than the stored one is ignored, so the
        newest journal wins; within one journal the later line wins. A sighting without a project
        name never overwrites one."""
        for item in sightings:
            if item.project_name:
                self._remember(self.projects, item.project_guid, item.project_name, journal_mtime)
            if item.file_name:
                self._remember(self.names, model_key(item.project_guid, item.model_guid),
                               item.file_name, journal_mtime)

    def _remember(self, table, key, name, mtime):
        entry = table.get(key)
        try:
            if isinstance(entry, dict) and float(entry.get("mtime", 0)) > float(mtime):
                return
        except (TypeError, ValueError):
            pass
        if not (isinstance(entry, dict) and entry.get("name") == name
                and entry.get("mtime") == mtime):
            table[key] = {"name": name, "mtime": mtime}
            self.dirty = True

    def project_name(self, project_guid):
        return self._name(self.projects.get(project_guid))

    def model_name(self, project_guid, model_guid):
        return self._name(self.names.get(model_key(project_guid, model_guid)))

    @staticmethod
    def _name(entry):
        if isinstance(entry, dict):
            return _clean_name(entry.get("name"))
        return None

    def set_included(self, keys):
        self.included = set(keys)
        self.dirty = True

    def links_for(self, key, mtime):
        """The stored link list while the host copy's mtime is unchanged, else None."""
        entry = self.links.get(key)
        try:
            if (isinstance(entry, dict) and isinstance(entry.get("links"), list)
                    and abs(float(entry["cache_mtime"]) - float(mtime)) <= _MTIME_TOLERANCE):
                return [dict(item) if isinstance(item, dict) else item for item in entry["links"]]
        except (KeyError, TypeError, ValueError):
            pass
        return None

    def store_links(self, key, mtime, links):
        self.links[key] = {"cache_mtime": mtime, "links": list(links)}
        self.dirty = True

    def save(self):
        """Write through a temporary file in the same folder. True on success.

        A failure is kept in last_error (the exception type name, no paths) and never raised.
        IronPython 2.7 cannot overwrite through rename, so the old file is removed first.
        """
        temp_path = self.file_path + ".tmp"
        try:
            folder = os.path.dirname(self.file_path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            text = dumps_ascii({"version": MEMORY_VERSION, "included": sorted(self.included),
                                "projects": self.projects, "names": self.names,
                                "links": self.links}, sort_keys=True)
            with io.open(temp_path, "w", encoding="utf-8") as handle:
                handle.write(text)
            if os.path.exists(self.file_path):
                os.remove(self.file_path)
            os.rename(temp_path, self.file_path)
            self.last_error = None
            self.dirty = False
            return True
        except Exception as exc:
            self.last_error = type(exc).__name__
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            return False


# ---------------------------------------------------------------- catalog

def _unknown_project():
    return tr("(project name unknown)", "(nazwa projektu nieznana)")


def _date_text(mtime):
    import time
    return time.strftime("%Y-%m-%d", time.localtime(mtime))


def _note(state, date_text):
    if state == "stale":
        return tr("Cache copy from {0}; it is as current as the last time this model was "
                  "opened on this computer.",
                  "Kopia z pamięci podręcznej z {0}; jest tak aktualna, jak ostatnie "
                  "otwarcie tego modelu na tym komputerze.").format(date_text)
    if state == "not_selected":
        return tr("Not in the selected projects.", "Poza wybranymi projektami.")
    if state == "duplicate":
        return tr("Another model in this project has the same name; the newer cache copy is "
                  "listed.",
                  "Inny model w tym projekcie ma tę samą nazwę; na liście "
                  "jest nowsza kopia.")
    return ""


def _unnamed_note(count):
    return tr("Cached models without a name: {0}. Open them once in Revit to add them.",
              "Modele w pamięci podręcznej bez nazwy: {0}. Otwórz je raz w "
              "Revicie, aby je dodać.").format(count) if count else ""


def _no_journal_message():
    return tr("No cloud model names were found in the Revit journals. Open the model in Revit "
              "and click Remember cloud model.",
              "W dziennikach Revita nie znaleziono nazw modeli z chmury. Otwórz model w "
              "Revicie i kliknij Zapamiętaj model z chmury.")


def _newest_copies(cache_files):
    """(project, model) -> the newer of root and linked, over every account; root wins a tie."""
    best = {}
    for item in cache_files:
        key = (item.project_guid, item.model_guid)
        rank = (item.mtime, 1 if item.place == "root" else 0)
        if key not in best or rank > best[key][0]:
            best[key] = (rank, item)
    return dict((key, value[1]) for key, value in best.items())


def build_catalog(cache_files, memory, now, stale_days=STALE_DAYS, counts=None, message=""):
    """Rows, projects and counts from the cache files and the name memory. Pure."""
    counts = dict(counts or {})
    copies = _newest_copies(cache_files)
    rows, unnamed, project_accounts = [], {}, {}
    for (project, model), item in sorted(copies.items()):
        pkey = project_key(item.account, project)
        project_accounts[pkey] = (item.account, project)
        name = memory.model_name(project, model)
        if name is None:
            unnamed[pkey] = unnamed.get(pkey, 0) + 1
            continue
        pname = memory.project_name(project) or _unknown_project()
        rows.append(CloudRow(
            key="cloud:%s/%s" % (project, model), project=pname, name=name, cache_path=item.path,
            cache_date=_date_text(item.mtime), size=item.size, state="ok", enabled=True,
            note="", account=item.account, project_guid=project, model_guid=model,
            place=item.place, cache_mtime=item.mtime))
    # duplicates: same project and file name (case-insensitive); the newer copy stays
    newest = {}
    for row in rows:
        ident = (row.project_guid, row.name.lower())
        if ident not in newest or (row.cache_mtime, row.key) > (newest[ident].cache_mtime,
                                                                newest[ident].key):
            newest[ident] = row
    final = []
    for row in rows:
        selected = project_key(row.account, row.project_guid) in memory.included
        if not selected:
            state = "not_selected"
        elif newest[(row.project_guid, row.name.lower())] is not row:
            state = "duplicate"
        elif now - row.cache_mtime > stale_days * 86400:
            state = "stale"
        else:
            state = "ok"
        final.append(row._replace(state=state, enabled=state in ("ok", "stale"),
                                  note=_note(state, row.cache_date)))
    final.sort(key=lambda r: (r.project.lower(), r.name.lower(), r.key))
    per_project = {}
    for row in final:
        pkey = project_key(row.account, row.project_guid)
        per_project[pkey] = per_project.get(pkey, 0) + 1
    projects = []
    for pkey, (account, guid) in project_accounts.items():
        count, missing = per_project.get(pkey, 0), unnamed.get(pkey, 0)
        if not count and not missing:
            continue
        projects.append(Project(key=pkey, account=account, guid=guid,
                                name=memory.project_name(guid) or _unknown_project(),
                                selected=pkey in memory.included, count=count,
                                unnamed=missing, note=_unnamed_note(missing)))
    projects.sort(key=lambda p: (p.name.lower(), p.key))
    counts.update({"rows": len(final), "projects": len(projects),
                   "unnamed": sum(unnamed.values()), "cache_files": len(cache_files)})
    return Catalog(rows=final, projects=projects, counts=counts, message=message)


def read_bytes(path):
    with io.open(path, "rb") as handle:
        return handle.read()


def scan(folders, memory, now, read=read_bytes, budget=LINES_PER_STEP, stale_days=STALE_DAYS,
         limit=JOURNAL_LIMIT, listdir=os.listdir, stat=os.stat, walk=os.walk):
    """Yield None once per journal chunk (`budget` lines) and per group of cache files, then one
    Catalog, so the window can time-slice. Journal names are merged into `memory` (saved at the
    end when anything changed; a failed save sets memory.last_error). Never raises: an unreadable
    journal is counted in counts["journals_unreadable"]; a missing cache folder gives no rows and
    counts["cache_errors"] > 0.
    """
    budget = max(1, int(budget))
    problems = []
    journals = list(iter_journals(folders["journals"], limit, listdir, stat, problems))
    counts = {"journals": 0, "journals_unreadable": 0, "sightings": 0}
    for path, mtime in journals:
        try:
            text = decode_journal(read(path))
        except Exception:
            counts["journals_unreadable"] += 1
            yield None
            continue
        counts["journals"] += 1
        lines = text.splitlines()
        found = []
        for start in range(0, max(1, len(lines)), budget):
            found.extend(_parse_lines(lines[start:start + budget]))
            yield None
        found = _prefer_plain(found)
        counts["sightings"] += len(found)
        memory.merge(found, mtime)
    counts["journals_unreadable"] += len([p for p in problems if p != folders["journals"]])
    counts["journals_folder_missing"] = 1 if folders["journals"] in problems else 0
    cache_errors = []
    cache_files = []
    last_project = None
    for item in scan_cache(folders["cache"], walk, stat, cache_errors):
        cache_files.append(item)
        if item.project_guid != last_project or len(cache_files) % FILES_PER_STEP == 0:
            last_project = item.project_guid
            yield None
    counts["cache_errors"] = len(cache_errors)
    if memory.dirty:
        memory.save()
    message = _no_journal_message() if not counts["sightings"] else ""
    yield build_catalog(cache_files, memory, now, stale_days, counts, message)


# ---------------------------------------------------------------- staging plan

def safe_file_name(name):
    """True when `name` is one plain Windows file name: no folder part, drive, wildcard, control
    character, reserved device name or trailing dot/space. Used before anything is joined to the
    staging folder, so a link name can never point outside it."""
    if not isinstance(name, type("")) or not name or len(name) > _MAX_NAME:
        return False
    if name in (".", "..") or name != name.strip() or name.endswith("."):
        return False
    if _BAD_NAME_CHARS.search(name):
        return False
    return name.split(".")[0].strip().upper() not in _RESERVED_NAMES


def _rvt_name(name):
    """The staging file name: trimmed, ".rvt" added when missing; None when unusable."""
    value = _clean_name(name) if isinstance(name, type("")) else None
    if value is None or value in (".", ".."):
        return None
    if not value.lower().endswith(".rvt"):
        value += ".rvt"
    return value if safe_file_name(value) else None


def _note_missing(name):
    return tr("Link {0} is not in the cache; exported without it.",
              "Linku {0} nie ma w pamięci podręcznej; wyeksportowano bez niego.").format(name)


def _note_clash(name):
    return tr("Link {0} was not copied: another file in this export has the same name.",
              "Nie skopiowano linku {0}: inny plik w tym eksporcie ma tę samą nazwę.").format(name)


def _note_bad_name(name):
    return tr("Link {0} was not copied: its name cannot be used as a file name.",
              "Nie skopiowano linku {0}: jego nazwy nie można użyć jako nazwy "
              "pliku.").format(name)


def _note_unnamed():
    return tr("A link without a usable name was not copied.",
              "Nie skopiowano linku bez użytecznej nazwy.")


def _shown_name(name):
    """A link name for a note: never a GUID, line breaks flattened."""
    value = _clean_name(name) if isinstance(name, type("")) else None
    if value is None:
        return None
    return value.replace("\r", " ").replace("\n", " ")


def plan_stage(row, link_refs, cache_files, memory):
    """StagePlan for exporting `row` (a CloudRow) from copies: the host first, then its links.

    `link_refs` is the host's link list ([{"name", "project_guid", "model_guid", ...}], as
    rx_reader.collect_cloud_links gives it); None takes it from `memory` while the host copy's
    mtime is unchanged. Each link is found by project GUID + model GUID across all of
    `cache_files` (the newer of root and linked copy, any account) and staged under its link
    name with ".rvt" added when missing. Names are unique without regard to case: a later clash
    is skipped with a note. A link missing from the cache gives a note and the export goes on.
    Pure: nothing is opened, stat'ed or written. StageError when the host name is unusable.
    """
    host_name = _rvt_name(row.name)
    if host_name is None:
        raise StageError(tr("The model name cannot be used as a file name: {0}",
                            "Nazwy modelu nie można użyć jako nazwy pliku: {0}").format(
            _shown_name(row.name) or ""))
    items = [StageItem(row.cache_path, host_name, row.size, row.cache_mtime)]
    notes = []
    taken = {host_name.lower(): (row.project_guid, row.model_guid)}
    if link_refs is None:
        link_refs = memory.links_for(model_key(row.project_guid, row.model_guid),
                                     row.cache_mtime) or []
    copies = _newest_copies(cache_files)
    for ref in link_refs:
        if not isinstance(ref, dict):
            continue
        project = normalize_guid(ref.get("project_guid"))
        model = normalize_guid(ref.get("model_guid"))
        raw = ref.get("name")
        if _shown_name(raw) is None and project and model:
            raw = memory.model_name(project, model)
        shown = _shown_name(raw)
        if shown is None:
            notes.append(_note_unnamed())
            continue
        name = _rvt_name(raw)
        if name is None:
            notes.append(_note_bad_name(shown))
            continue
        if taken.get(name.lower()) == (project, model):
            continue    # the same file under the same name, e.g. a nested and a direct link
        found = copies.get((project, model)) if project and model else None
        if found is None:
            notes.append(_note_missing(name))
            continue
        if name.lower() in taken:
            notes.append(_note_clash(name))
            continue
        taken[name.lower()] = (project, model)
        items.append(StageItem(found.path, name, found.size, found.mtime))
    return StagePlan(items, notes)
