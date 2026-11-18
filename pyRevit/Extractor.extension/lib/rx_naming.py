# -*- coding: utf-8 -*-
"""File-name templates for named copies: parsing, formatting, cleaning, length budgets and clash
numbering. Pure Python: no Revit, pyRevit, System or clr import. Spec: specs/SPEC-named-copies.md.

Values reach this module as plain text. Tokens, presets and error texts exist in English and Polish.
"""
from __future__ import unicode_literals

import io
import json
import os
import re
from collections import OrderedDict, namedtuple

from rx_cloud import StageItem, StagePlan
from rx_cloud_stage import copy_steps
from rx_hardlink import make_hard_link
from rx_i18n import tr
from rx_json import dumps_ascii
from rx_naming_pdb import ExportValues

MAX_TEMPLATE = 200
_MAX_COMPONENT = 255
_MAX_FILE_PATH = 259
_MAX_DIR_PATH = 247

# name: (English label, Polish label, scope). scope: model = from the model or export,
# system = captured at submit, file = from the file being named. Two groups, in the order the
# naming window lists them: Built-in (sheet and view values), then System.
TOKENS = OrderedDict([
    ("SheetNumber", ("Sheet number", "Numer arkusza", "model")),
    ("SheetName", ("Sheet name", "Nazwa arkusza", "model")),
    ("CurrentRevision", ("Current revision", "Bieżąca rewizja", "model")),
    ("CurrentRevisionDate", ("Current revision date", "Data bieżącej rewizji", "model")),
    ("CurrentRevisionDescription",
     ("Current revision description", "Opis bieżącej rewizji", "model")),
    ("SheetIssueDate", ("Sheet issue date", "Data wydania arkusza", "model")),
    ("DrawnBy", ("Drawn by", "Rysował", "model")),
    ("CheckedBy", ("Checked by", "Sprawdził", "model")),
    ("DesignedBy", ("Designed by", "Projektował", "model")),
    ("ApprovedBy", ("Approved by", "Zatwierdził", "model")),
    ("SheetSize", ("Sheet size", "Format arkusza", "model")),
    ("ViewName", ("View name", "Nazwa widoku", "model")),
    ("ViewFamily", ("View family", "Rodzina widoku", "model")),
    ("TitleOnSheet", ("Title on sheet", "Tytuł na arkuszu", "model")),
    ("Scale", ("Scale", "Skala", "model")),
    ("DetailLevel", ("Detail level", "Poziom szczegółowości", "model")),
    ("Discipline", ("Discipline", "Branża", "model")),
    ("Phase", ("Phase", "Faza", "model")),
    ("ViewTemplate", ("View template", "Szablon widoku", "model")),
    ("ViewSheetNumber", ("Number of the sheet the view is on",
                         "Numer arkusza, na którym jest widok", "model")),
    ("ElementId", ("Element id", "Id elementu", "model")),
    ("Date", ("Date (2026-11-18)", "Data (2026-11-18)", "system")),
    ("DateShort", ("Date, short (Windows format)", "Data krótka (format Windows)", "system")),
    ("DateLong", ("Date, long (Windows format)", "Data długa (format Windows)", "system")),
    ("Time", ("Time", "Czas", "system")),
    ("ModelName", ("Model name", "Nazwa modelu", "system")),
    ("WindowsUser", ("Windows user", "Użytkownik Windows", "system")),
    ("RevitUser", ("Revit user", "Użytkownik Revita", "system")),
    ("OriginalName", ("Original name", "Oryginalna nazwa", "file")),
])
BUILT_IN_COUNT = 21   # the first 21 TOKENS are Built-in, the rest System

# Still parsed (an old saved template may hold them) but never listed for picking.
LEGACY_TOKENS = OrderedDict([
    ("Year", ("Year (4 digits)", "Rok (4 cyfry)", "system")),
    ("Year2", ("Year (2 digits)", "Rok (2 cyfry)", "system")),
    ("Month", ("Month", "Miesiąc", "system")),
    ("Day", ("Day", "Dzień", "system")),
    ("Hour", ("Hour", "Godzina", "system")),
    ("Minute", ("Minute", "Minuta", "system")),
    ("Second", ("Second", "Sekunda", "system")),
])

_SCOPES = dict((name, entry[2]) for name, entry in list(TOKENS.items()) + list(LEGACY_TOKENS.items()))

_LOWER_TOKENS = dict((name.lower(), name) for name in _SCOPES)
_SPACES = re.compile(r"\s+", re.UNICODE)
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = set(["CON", "PRN", "AUX", "NUL"] + ["COM%d" % n for n in range(1, 10)] +
                ["LPT%d" % n for n in range(1, 10)])


class NamingError(ValueError):
    """A template or naming request is unusable. The message is translated."""


def _is_text(value):
    return isinstance(value, type(""))


def parse_template(text):
    """Parse `text` into a list of ("text", s), ("token", NAME) and ("param", name) parts.
    Empty or blank text means off and gives []. Raises NamingError."""
    if not _is_text(text):
        raise NamingError(tr("The file-name template must be text.",
                             "Szablon nazw plików musi być tekstem."))
    text = text.strip()
    if len(text) > MAX_TEMPLATE:
        raise NamingError(tr("The file-name template is longer than {0} characters.",
                             "Szablon nazw plików ma więcej niż {0} znaków.").format(MAX_TEMPLATE))
    parts = []
    buf = []

    def flush():
        if buf:
            parts.append(("text", "".join(buf)))
            del buf[:]

    i = 0
    while i < len(text):
        c = text[i]
        pair = text[i:i + 2]
        if pair == "{{" or pair == "}}":
            buf.append(c)
            i += 2
        elif c == "}":
            raise NamingError(tr("Unbalanced brace in the template: use }} for a literal }.",
                                 "Niesparowany nawias w szablonie: użyj }} dla znaku }."))
        elif c == "{":
            end = text.find("}", i + 1)
            inner = text[i + 1:end] if end >= 0 else ""
            if end < 0 or "{" in inner:
                raise NamingError(tr("Unbalanced brace in the template: use {{ for a literal {.",
                                     "Niesparowany nawias w szablonie: użyj {{ dla znaku {."))
            inner = inner.strip()
            flush()
            if inner[:6].lower() == "param:":
                name = inner[6:].strip()
                if not name:
                    raise NamingError(tr("{param:} needs a parameter name.",
                                         "{param:} wymaga nazwy parametru."))
                parts.append(("param", name))
            elif inner.lower() in _LOWER_TOKENS:
                parts.append(("token", _LOWER_TOKENS[inner.lower()]))
            else:
                raise NamingError(tr("Unknown token {{{0}}} in the template.",
                                     "Nieznany znacznik {{{0}}} w szablonie.").format(inner))
            i = end + 1
        else:
            buf.append(c)
            i += 1
    flush()
    return parts


def _reserved(stem):
    return stem.split(".")[0].strip().upper() in _RESERVED


def clean_name(raw):
    """A plain Windows file-name stem from arbitrary text; "" when nothing usable is left."""
    if not _is_text(raw):
        return ""
    value = _BAD_CHARS.sub("_", _SPACES.sub(" ", raw))
    value = value.rstrip(" .").lstrip(" ")
    if value and _reserved(value):
        value = "_" + value
    return value


class Counter(object):
    """Numbers blank parts 001, 002, ... (one per model and kind, shared by all parts)."""

    def __init__(self):
        self._n = 0

    def take(self):
        self._n += 1
        return "%03d" % self._n   # widens past 999 by itself


def format_name(parsed, values, original, counter=None):
    """The stem for one file. `values` maps token names and "param:<name>" to text. A blank token
    or parameter takes the next number from `counter`. Falls back to the original name when the
    template is off or the result is empty after cleaning."""
    fallback = clean_name(original)
    if not parsed:
        return fallback
    counter = counter or Counter()
    out = []
    for kind, item in parsed:
        if kind == "text":
            out.append(item)
            continue
        if kind == "token" and item == "OriginalName":
            value = original
        else:
            value = values.get(item if kind == "token" else "param:" + item, "")
        out.append(value if _is_text(value) and value else counter.take())
    return clean_name("".join(out)) or fallback


def system_values(when, windows_user, revit_user, model_name, date_short="", date_long=""):
    """The system tokens, captured once at submit time from the datetime `when`."""
    return {
        "Year": "%04d" % when.year, "Year2": "%02d" % (when.year % 100),
        "Month": "%02d" % when.month, "Day": "%02d" % when.day,
        "Hour": "%02d" % when.hour, "Minute": "%02d" % when.minute,
        "Second": "%02d" % when.second, "Time": "%02d-%02d" % (when.hour, when.minute),
        "Date": "%04d-%02d-%02d" % (when.year, when.month, when.day),
        "DateShort": date_short, "DateLong": date_long,
        "ModelName": model_name, "WindowsUser": windows_user, "RevitUser": revit_user,
    }


def check_naming(naming):
    """Validate {"template" or "templates": {"sheet", "view"}, "system", "values"}. Returns
    {"sheet": parsed, "view": parsed} or raises NamingError. "template" serves both kinds."""
    if not isinstance(naming, dict):
        raise NamingError(tr("The naming request must be a dictionary.",
                             "Żądanie nazewnictwa musi być słownikiem."))
    templates = naming.get("templates")
    if templates is None:
        templates = {"sheet": naming.get("template"), "view": naming.get("template")}
    elif not isinstance(templates, dict):
        raise NamingError(tr("The templates must be a dictionary.",
                             "Szablony muszą być słownikiem."))
    parsed = {"sheet": parse_template(templates.get("sheet")),
              "view": parse_template(templates.get("view"))}
    system = naming.get("system")
    if not isinstance(system, dict) or not all(
            _is_text(k) and _is_text(v) for k, v in system.items()):
        raise NamingError(tr("The system values must be a dictionary of text.",
                             "Wartości systemowe muszą być słownikiem tekstów."))
    values = naming.get("values")
    if values is not None and (not isinstance(values, dict) or
                               not all(isinstance(v, dict) for v in values.values())):
        raise NamingError(tr("The model values must be empty or a dictionary of dictionaries.",
                             "Wartości z modelu muszą być puste lub słownikiem słowników."))
    return parsed


def needs_values(parsed):
    """True when either parsed template (the dict check_naming returns) uses a sheet or view
    value (a model token or {param:})."""
    return any(kind == "param" or (kind == "token" and _SCOPES[item] == "model")
               for template in parsed.values() for kind, item in template)


def file_budget(named_root, ext):
    """Most characters for a file stem under `named_root` (a path string) with extension `ext`."""
    return min(_MAX_FILE_PATH - len(named_root) - 1 - len(ext), _MAX_COMPONENT - len(ext))


def folder_budget(named_root, inner_max, inner_dir_max=0):
    """Most characters for a folder name; `inner_max` is the longest relative file path inside it
    and `inner_dir_max` the longest relative path of a folder inside it (a nested folder must stay
    under the folder limit too)."""
    budget = min(_MAX_DIR_PATH - len(named_root) - 1,
                 _MAX_FILE_PATH - len(named_root) - 2 - inner_max, _MAX_COMPONENT)
    if inner_dir_max > 0:
        budget = min(budget, _MAX_DIR_PATH - len(named_root) - 2 - inner_dir_max)
    return budget


def fit_name(stem, ext, budget):
    """`stem` cut to `budget` characters (and so that stem + ext is one valid component), never
    inside a surrogate pair, then trimmed again. None when not even one character fits."""
    limit = min(budget, _MAX_COMPONENT - len(ext))
    if limit < 1:
        return None
    cut = stem[:limit]
    if len(cut) < len(stem) and cut and 0xD800 <= ord(cut[-1]) <= 0xDBFF:
        cut = cut[:-1]  # narrow builds hold a non-BMP character as two code units
    cut = cut.rstrip(" .").lstrip(" ")
    if cut and _reserved(cut):
        cut = ("_" + cut[:limit - 1]).rstrip(" .")
    return cut or None


class Namer(object):
    """Hands out names that are unique per folder, compared without regard to case."""

    def __init__(self):
        self._taken = {}

    def unique(self, folder_key, stem, ext, budget):
        """The first free stem: `stem`, `stem (2)`, `stem (3)`, ... cut to fit `budget`. None when
        nothing fits."""
        taken = self._taken.setdefault(folder_key, set())
        n = 1
        while True:
            suffix = "" if n == 1 else " (%d)" % n
            fitted = fit_name(stem, ext, budget - len(suffix))
            if fitted is None:
                return None
            candidate = fitted + suffix
            key = (candidate + ext).lower()
            if key not in taken:
                taken.add(key)
                return candidate
            n += 1


# ---- Discovery and tying (spec: Scope, Tying a file to its sheet or view) ----

Deliverable = namedtuple(str("Deliverable"), "src rel kind viewable")

_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f-]{27,}$", re.IGNORECASE)
_FILE_KINDS = {".pdf": "pdf", ".dwg": "dwg", ".ifc": "ifc"}
_GEOMETRY = (".svf", ".f2d")


def _guid_in(parts):
    for part in parts:
        if _GUID.match(part):
            return part
    return None


class Discovery(object):
    """Lists what can be named in an export's output folder. It only lists and checks: it never
    opens a file and skips symbolic links and junctions."""

    def __init__(self, output_dir, listdir=os.listdir, isdir=os.path.isdir,
                 islink=os.path.islink):
        self.output_dir = output_dir
        self.items = []
        self.notes = []
        self._listdir = listdir
        self._isdir = isdir
        self._islink = islink
        # shortcut: junctions are only detected on a Python that has os.path.isjunction
        self._isjunction = getattr(os.path, "isjunction", None) if islink is os.path.islink else None

    def _skip(self, path):
        return self._islink(path) or bool(self._isjunction and self._isjunction(path))

    def steps(self):
        files = []   # (parts, kind)
        geometry = []  # directory parts holding one *.svf/*.f2d
        stack = [(self.output_dir, [])]
        while stack:
            path, parts = stack.pop()
            try:
                names = sorted(self._listdir(path))
            except OSError:
                self.notes.append(tr("Folder %s could not be read." % "/".join(parts or ["."]),
                                     "Nie można odczytać folderu %s." % "/".join(parts or ["."])))
                names = []
            for name in names:
                child = os.path.join(path, name)
                if self._skip(child):
                    continue
                if self._isdir(child):
                    stack.append((child, parts + [name]))
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in _GEOMETRY:
                    geometry.append(parts)
                elif ext in _FILE_KINDS:
                    files.append((parts + [name], _FILE_KINDS[ext]))
            yield
        self._finish(files, geometry)

    def _finish(self, files, geometry):
        counts = {}
        for parts in geometry:
            guid_at = [i for i, p in enumerate(parts) if _GUID.match(p)]
            holder = tuple(parts[:guid_at[0] + 1]) if guid_at else tuple(parts)
            if holder:  # geometry straight in the output folder has no folder to name
                counts[holder] = counts.get(holder, 0) + 1
        views = []
        for holder, n in counts.items():
            rel = "/".join(holder)
            if n > 1:
                self.notes.append(tr('View folder "%s" is shared by several views and was skipped.'
                                     % rel,
                                     'Folder widoku "%s" jest wspólny dla kilku widoków i został '
                                     'pominięty.' % rel))
            else:
                views.append(holder)
        everything = list(counts)  # skipped folders swallow their files too
        out = []
        for holder in views:
            out.append(Deliverable(os.path.join(self.output_dir, *holder), "/".join(holder),
                                   "view", _guid_in(holder)))
        for parts, kind in files:
            if any(tuple(parts[:len(h)]) == h for h in everything):
                continue
            out.append(Deliverable(os.path.join(self.output_dir, *parts), "/".join(parts), kind,
                                   _guid_in(parts[:-1])))
        out.sort(key=lambda d: (d.kind, d.rel.lower()))
        self.items = out


def _viewables(manifest):
    """[(id, name, group)] for every geometry node; group = nearest folder ancestor's name."""
    found = []

    def visit(node, group):
        if not isinstance(node, dict):
            return
        if node.get("type") == "geometry":
            vid = node.get("viewableID") or node.get("guid")
            if vid:
                found.append((vid, node.get("name"), group))
        for child in node.get("children") or []:
            visit(child, node.get("name") if node.get("type") == "folder" else group)
    visit(manifest, None)
    return found


def _top_folder(rel):
    dirs = rel.split("/")[:-1]
    if dirs and dirs[0].lower() == "resource":
        dirs = dirs[1:]
    return dirs[0] if dirs else None


_FOLDER_ELEMENT_ID = re.compile(r"^.* (\d+)$")
_VIEWABLE_ELEMENT_ID = re.compile(r"-([0-9a-f]{8})$", re.IGNORECASE)


def _folder_element_id(item):
    """The ElementId in the name of the nearest folder of a deliverable, or None. The Extractor
    puts every sheet and view in a folder called "<name> <ElementId in decimal>" (observed
    2026-11-18 on a real export: Resource/Sheet/A101 - Site Plan 959135/pdf/A101 - Site Plan.pdf,
    Resource/3D View/{3D} 960621/{3D}.svf), and the last 8 hex digits of the viewable's id are
    the same number."""
    parts = item.rel.split("/")
    if item.kind != "view":
        parts = parts[:-1]
    for part in reversed(parts):
        match = _FOLDER_ELEMENT_ID.match(part)
        if match:
            return int(match.group(1))
    return None


def _record_names(record):
    tokens = record.get("tokens") or {}
    if record.get("kind") == "sheet":
        if tokens.get("SheetNumber") is not None and tokens.get("SheetName") is not None:
            return "%s - %s" % (tokens["SheetNumber"], tokens["SheetName"])
    elif record.get("kind") == "view":
        return tokens.get("ViewName")
    return None


def tie(items, manifest, values):
    """Pairs each deliverable with its value record. Returns (pairs, untied count). Nothing is
    guessed beyond the spec's rules; see 'Tying a file to its sheet or view'."""
    viewables = _viewables(manifest or {})
    by_id = dict((v[0], v) for v in viewables)
    by_element = {}
    for found in viewables:
        match = _VIEWABLE_ELEMENT_ID.search("%s" % (found[0],))
        if match:
            by_element.setdefault(int(match.group(1), 16), []).append(found)
    pairs = []
    untied = 0
    for item in items:
        viewable = by_id.get(item.viewable) if item.viewable else None
        if viewable is None:
            hits = by_element.get(_folder_element_id(item)) or []
            viewable = hits[0] if len(hits) == 1 else None
        if viewable is None:
            stem = item.rel.split("/")[-1]
            if item.kind != "view":
                stem = os.path.splitext(stem)[0]
            top = _top_folder(item.rel)
            hits = [v for v in viewables if v[1] == stem and v[2] == top]
            viewable = hits[0] if len(hits) == 1 else None
        record = None
        if viewable is not None:
            if values is None:
                record = {"kind": None, "id": None, "name": viewable[1], "tokens": {},
                          "params": {}}
            elif viewable[0] in values:
                record = values[viewable[0]]
            else:
                hits = [r for r in values.values() if _record_names(r) == viewable[1]]
                record = hits[0] if len(hits) == 1 else None
        if record is None:
            untied += 1
        pairs.append((item, record))
    return pairs, untied


# ---- Writer and record (spec: Runner and session -> Writer, Record, Result note; Failure rules) ----
#
# Safety rules, each covered by tests/test_naming.py:
# - nothing under <run>\output is ever written, renamed, moved or deleted; a source is only
#   opened "rb" (bubble.json here, the rest by rx_cloud_stage.copy_steps);
# - the only writes are inside <run>\named (made new by this run) and <run>\named.json(.tmp);
# - a destination is never overwritten (hard links and O_EXCL copies fail on an existing name);
# - closing steps() early leaves complete items and named.json at "running".

RECORD_SCHEMA = "rx-named-copies"
RECORD_VERSION = 1
_COPY_CHUNK = 2 ** 20
_MB = 2 ** 20
_MTIME_TOLERANCE = 0.001
_SPLIT_FOLDERS = {"pdf": "PDF", "dwg": "DWG", "ifc": "IFC", "view": "3D"}
_TIME_TOKENS = ("Year", "Year2", "Month", "Day", "Hour", "Minute", "Second", "Date", "Time")


def _short_error(error):
    """Exception type and OS error code only (a message can hold a path). Same as
    rx_runner._short_error, kept here because rx_runner will import this module."""
    code = getattr(error, "winerror", None) or getattr(error, "errno", None)
    return type(error).__name__ + ("(%s)" % code if code else "")


def _message(error):
    return error.args[0] if error.args and _is_text(error.args[0]) else _short_error(error)


def _inside(path, folder):
    path = os.path.normcase(os.path.abspath(path))
    folder = os.path.normcase(os.path.abspath(folder))
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _unchanged(st, size, mtime):
    return st.st_size == size and abs(st.st_mtime - mtime) <= _MTIME_TOLERANCE


class _Refused(Exception):
    """The run does not start; nothing is written, not even named.json."""


class _ItemFailed(Exception):
    """One item fails; args[0] is the record's error text."""


class _NoSpace(Exception):
    """Not enough free space for the copies that are left: args = (needed, free) bytes."""


class NamedRun(object):
    """Makes <run>\\named\\ from an export's output\\ (hard links, copies when a link fails) and
    records it in <run>\\named.json. steps() does all the work and never raises; the public
    state holds plain values only."""

    def __init__(self, run_paths, naming, link=make_hard_link, copier=copy_steps,
                 free_space=None, listdir=os.listdir, now=None, values_reader=ExportValues):
        self.run_paths = run_paths
        self.naming = naming
        self.state = None
        self.done = 0
        self.total = 0
        self.counts = {"total": 0, "linked": 0, "copied": 0, "failed": 0, "untied": 0}
        self.notes = []
        self.items = []
        self._link = link
        self._copier = copier
        self._free_space = free_space
        self._listdir = listdir
        self._now = now
        self._values_reader = values_reader
        self._value_notes = []   # added at the end, so a failure's own note stays first
        self._named = os.path.join(run_paths.root, "named")
        self._record = os.path.join(run_paths.root, "named.json")
        self._started = False
        self._record_failed = False
        self._space_checked = False

    # ---- public ----

    def steps(self):
        """Generator of (done, total) files. Never raises."""
        self.state = "running"
        fatal = False
        work = self._work()
        try:
            try:
                for step in work:
                    yield step
            except _Refused as refused:
                self.notes.append(refused.args[0])
                self.state = "failed"
                return
            except Exception as error:
                fatal = True
                self.notes.append(tr("Unexpected error: {0}",
                                     "Nieoczekiwany błąd: {0}").format(_short_error(error)))
        finally:
            work.close()
        self._end(fatal)

    def result_message(self):
        """The note appended to the job's result; "" before the run ends."""
        counts = self.counts
        made = counts["linked"] + counts["copied"]
        if self.state == "failed":
            return tr("Named copies were not made: {0}",
                      "Nie utworzono kopii z nazwami: {0}").format(
                          self.notes[0] if self.notes else "")
        if self.state == "done":
            text = tr("Named copies: {0} in named\\ ({1} copied instead of linked).",
                      "Kopie z nazwami: {0} w named\\ ({1} skopiowano zamiast dowiązać).").format(
                          made, counts["copied"])
        elif self.state == "partial":
            text = tr("Named copies: {0} of {1}; {2} failed, see named.json.",
                      "Kopie z nazwami: {0} z {1}; {2} nieudanych, zobacz named.json.").format(
                          made, counts["total"], counts["failed"])
        else:
            return ""
        if counts["untied"]:
            text += " " + tr(
                "{0} files could not be tied to a sheet or view and kept their name.",
                "{0} plików nie powiązano z arkuszem ani widokiem; zachowały nazwę.").format(
                    counts["untied"])
        return text

    # ---- work ----

    def _work(self):
        try:
            parsed = check_naming(self.naming)
        except NamingError as error:
            raise _Refused(_message(error))
        if os.path.lexists(self._named):
            raise _Refused(tr("The folder named\\ already exists in this run; nothing was changed.",
                              "Folder named\\ już istnieje w tym przebiegu; niczego nie zmieniono."))
        if _inside(self._named, self.run_paths.output) or \
                _inside(self.run_paths.output, self._named):
            raise _Refused(tr("The named\\ folder would overlap the export; nothing was changed.",
                              "Folder named\\ nakładałby się na eksport; niczego nie zmieniono."))
        self._started = True
        discovery = Discovery(self.run_paths.output, listdir=self._listdir)
        for _ in discovery.steps():
            yield self.done, self.total
        self.notes.extend(discovery.notes)
        manifest = self._manifest()
        values = self.naming.get("values")
        if values is None and needs_values(parsed):
            try:   # reading only adds notes: it never fails the run
                reader = self._values_reader(os.path.join(self.run_paths.output, "Resource"),
                                             [v[0] for v in _viewables(manifest)])
                read = reader.steps()
                try:
                    for _ in read:
                        yield self.done, self.total
                finally:
                    read.close()
                self._value_notes.extend(n for n in reader.notes if _is_text(n))
                if reader.state == "done" and isinstance(reader.values, dict):
                    values = reader.values
            except Exception:
                pass
            if values is None:
                parsed = {"sheet": [], "view": []}   # no values: every file keeps its original name, as the note says
                self._value_notes.append(tr(
                    "Sheet and view values could not be read, so every file keeps its original "
                    "name.",
                    "Nie odczytano wartości arkuszy i widoków, więc każdy plik zachowuje "
                    "oryginalną nazwę."))
        pairs, self.counts["untied"] = tie(discovery.items, manifest, values)
        plan = []
        for _ in self._plan(parsed, pairs, plan):
            yield self.done, self.total
        self.counts["total"] = len(self.items)
        self.total = sum(len(files) for _, _, files in plan)
        self._write_record()
        os.makedirs(self._named)   # raises when it appeared meanwhile: never write into it
        for index, (entry, target, files) in enumerate(plan):
            result = []
            put = self._put_item(entry, target, files, plan, index, result)
            try:
                try:
                    for _ in put:
                        yield self.done, self.total
                finally:
                    put.close()   # IronPython does not close a dropped generator at once
            except _NoSpace as short:
                self.notes.append(tr(
                    "Not enough free disk space to copy the files that could not be linked: "
                    "{0} MB needed, {1} MB free.",
                    "Za mało wolnego miejsca na dysku na kopie plików, których nie dało się "
                    "dowiązać: potrzeba {0} MB, wolne {1} MB.").format(
                        -(-short.args[0] // _MB), int(short.args[1]) // _MB))
                for later, _, _ in plan[index:]:
                    self._fail(later, "not enough space")
                self.done = self.total
                yield self.done, self.total
                return
            except Exception as error:
                self._fail(entry, error.args[0] if isinstance(error, _ItemFailed)
                           else _short_error(error))
                self.done += len(files) - len(result)
                yield self.done, self.total
                continue
            entry["mode"] = "copied" if "copied" in result else "linked"
            self.counts[entry["mode"]] += 1

    def _fail(self, entry, error):
        if entry["mode"] != "failed":
            entry["mode"] = "failed"
            entry["error"] = error
            self.counts["failed"] += 1

    def _manifest(self):
        try:
            with io.open(os.path.join(self.run_paths.output, "bubble.json"), "rb") as handle:
                data = json.loads(handle.read().decode("utf-8-sig"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        # without the manifest no file can be tied to a sheet or view: refuse, change nothing
        raise _Refused(tr("bubble.json could not be read; no named copies were made.",
                          "Nie można odczytać bubble.json; nie utworzono kopii z nazwami."))

    def _system(self):
        system = dict(self.naming["system"])
        if self._now is not None:
            for key, value in system_values(self._now, "", "", "").items():
                if key in _TIME_TOKENS:
                    system.setdefault(key, value)
        return system

    def _template(self, parsed, record):
        """The parsed template for a tied record; [] (original name) for an untied file. A tied
        record of unknown kind (no values read) takes the template only when both kinds share it."""
        if record is None:
            return []
        kind = record.get("kind") if isinstance(record, dict) else None
        if kind in parsed:
            return parsed[kind]
        return parsed["sheet"] if parsed["sheet"] == parsed["view"] else []

    def _plan(self, parsed, pairs, plan):
        """Fills self.items and `plan` [(entry, target path, [(parts, src, size, mtime)])] before
        anything is written. Yields once per folder walked inside a view folder."""
        namer = Namer()
        system = self._system()
        split = self.naming.get("split") is True
        counters = {}   # one per kind, for the whole model
        for item, record in pairs:
            yield       # one step per deliverable: thousands of sheets must not block the window
            sub = _SPLIT_FOLDERS[item.kind] if split else ""
            root = os.path.join(self._named, sub) if sub else self._named
            base = item.rel.split("/")[-1]
            entry = OrderedDict([("source", item.rel), ("name", None),
                                 ("kind", "dir" if item.kind == "view" else "file"),
                                 ("mode", None), ("error", None)])
            self.items.append(entry)
            files = []
            try:
                if item.kind == "view":
                    original, ext = base, ""
                    for _ in self._tree(item.src, files):
                        yield
                    inner = max([len(os.sep.join(f[0])) for f in files] or [0])
                    inner_dirs = max([len(os.sep.join(f[0][:-1])) for f in files] or [0])
                    budget = folder_budget(root, inner, inner_dirs)
                else:
                    original, ext = os.path.splitext(base)
                    st = os.stat(item.src)
                    files.append(([], item.src, st.st_size, st.st_mtime))
                    budget = file_budget(root, ext)
            except EnvironmentError as error:
                self._fail(entry, _short_error(error))
                continue
            tokens = dict(system)
            template = self._template(parsed, record)
            counter = counters.setdefault(record.get("kind") if record else None, Counter())
            record = record if isinstance(record, dict) else {}
            if isinstance(record.get("tokens"), dict):
                tokens.update(record["tokens"])
            if isinstance(record.get("params"), dict):
                tokens.update(("param:" + k, v) for k, v in record["params"].items()
                              if _is_text(k))
            name = namer.unique(sub, format_name(template, tokens, original, counter), ext, budget)
            if name is None:
                self._fail(entry, "path too long")
                continue
            entry["name"] = (sub + "/" if sub else "") + name + ext
            plan.append((entry, os.path.join(root, name + ext), files))

    def _tree(self, top, files):
        """Every file under the view folder `top` as (relative parts, path, size, mtime);
        symbolic links and junctions are skipped. One step per folder."""
        isjunction = getattr(os.path, "isjunction", None)
        stack = [(top, [])]
        while stack:
            path, parts = stack.pop()
            for name in sorted(self._listdir(path)):
                child = os.path.join(path, name)
                if os.path.islink(child) or (isjunction is not None and isjunction(child)):
                    continue
                if os.path.isdir(child):
                    stack.append((child, parts + [name]))
                else:
                    st = os.stat(child)
                    files.append((parts + [name], child, st.st_size, st.st_mtime))
            yield

    # ---- writing ----

    def _put_item(self, entry, target, files, plan, index, result):
        parent = os.path.dirname(target)
        if not os.path.isdir(parent):
            os.makedirs(parent)   # only PDF/DWG/IFC/3D under the new named folder
        if entry["kind"] == "dir":
            os.mkdir(target)   # raises on an existing name: never merge into a folder
        for k, (parts, src, size, mtime) in enumerate(files):
            dst = os.path.join(target, *parts) if parts else target
            folder = os.path.dirname(dst)
            if not os.path.isdir(folder):
                os.makedirs(folder)

            def remaining(k=k):
                return (sum(f[2] for f in files[k:]) +
                        sum(f[2] for _, _, later in plan[index + 1:] for f in later))
            put = self._put_file(src, dst, size, mtime, remaining, result)
            try:
                for _ in put:
                    yield
            finally:
                put.close()
            self.done += 1
            yield

    def _put_file(self, src, dst, size, mtime, remaining, result):
        if not _unchanged(os.stat(src), size, mtime):
            raise _ItemFailed("source changed")
        try:
            self._link(src, dst)
            result.append("linked")
            return
        except Exception:   # other drive, no link support, no permission: copy instead
            pass
        if not self._space_checked:
            self._space_checked = True
            free = self._free()
            if free is not None and free < remaining():
                raise _NoSpace(remaining(), free)
        copy = self._copier(StagePlan([StageItem(src, os.path.basename(dst), size, mtime)], []),
                            os.path.dirname(dst), chunk=_COPY_CHUNK)
        try:
            for _ in copy:
                yield
        finally:
            copy.close()   # removes a partly written copy when closed early
        result.append("copied")

    def _free(self):
        if self._free_space is None:
            return None
        try:
            return self._free_space(self._named)
        except Exception:   # unknown: the copy goes ahead and fails on its own if the disk fills
            return None

    # ---- end and record ----

    def _end(self, fatal):
        made = self.counts["linked"] + self.counts["copied"]
        if fatal:
            self.state = "failed"
        elif not self.counts["failed"]:
            self.state = "done"
        else:
            self.state = "partial" if made else "failed"
        if self.state == "failed" and not self.notes:
            self.notes.append(tr("No named copy could be made; see named.json.",
                                 "Nie udało się utworzyć żadnej kopii z nazwą; zobacz named.json."))
        self.notes.extend(self._value_notes)
        if self._started:
            self._write_record()

    def _write_record(self):
        """named.json beside named\\: written to .tmp, then the old one removed and the new one
        renamed (IronPython 2.7 cannot overwrite through rename). A failure only adds a note."""
        temp = self._record + ".tmp"
        try:
            text = dumps_ascii(OrderedDict([
                ("schema", RECORD_SCHEMA), ("version", RECORD_VERSION),
                ("template", self.naming.get("template")),
                ("templates", self.naming.get("templates")), ("state", self.state),
                ("counts", self.counts), ("notes", self.notes), ("items", self.items)]),
                indent=1)
            with io.open(temp, "w", encoding="utf-8") as handle:
                handle.write(text)
            if os.path.exists(self._record):
                os.remove(self._record)
            os.rename(temp, self._record)
        except Exception:
            if not self._record_failed:
                self._record_failed = True
                self.notes.append(tr("named.json could not be written.",
                                     "Nie można zapisać named.json."))
