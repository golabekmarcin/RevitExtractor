# -*- coding: utf-8 -*-
"""File-name templates for named copies: parsing, formatting, cleaning, length budgets and clash
numbering. Pure Python: no Revit, pyRevit, System or clr import. Spec: specs/SPEC-named-copies.md.

Values reach this module as plain text. Tokens, presets and error texts exist in English and Polish.
"""
from __future__ import unicode_literals

import re
from collections import OrderedDict

from rx_i18n import tr

MAX_TEMPLATE = 200
_MAX_COMPONENT = 255
_MAX_FILE_PATH = 259
_MAX_DIR_PATH = 247

# name: (English label, Polish label, scope). scope: model = from the model or export,
# system = captured at submit, file = from the file being named.
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
    ("TitleOnSheet", ("Title on sheet", "Tytuł na arkuszu", "model")),
    ("Scale", ("Scale", "Skala", "model")),
    ("DetailLevel", ("Detail level", "Poziom szczegółowości", "model")),
    ("Discipline", ("Discipline", "Branża", "model")),
    ("Phase", ("Phase", "Faza", "model")),
    ("ViewTemplate", ("View template", "Szablon widoku", "model")),
    ("ViewSheetNumber", ("Number of the sheet the view is on",
                         "Numer arkusza, na którym jest widok", "model")),
    ("ElementId", ("Element id", "Id elementu", "model")),
    ("Year", ("Year (4 digits)", "Rok (4 cyfry)", "system")),
    ("Year2", ("Year (2 digits)", "Rok (2 cyfry)", "system")),
    ("Month", ("Month", "Miesiąc", "system")),
    ("Day", ("Day", "Dzień", "system")),
    ("Hour", ("Hour", "Godzina", "system")),
    ("Minute", ("Minute", "Minuta", "system")),
    ("Second", ("Second", "Sekunda", "system")),
    ("Date", ("Date (2026-11-18)", "Data (2026-11-18)", "system")),
    ("DateShort", ("Date, short (Windows format)", "Data krótka (format Windows)", "system")),
    ("DateLong", ("Date, long (Windows format)", "Data długa (format Windows)", "system")),
    ("ModelName", ("Model name", "Nazwa modelu", "system")),
    ("WindowsUser", ("Windows user", "Użytkownik Windows", "system")),
    ("RevitUser", ("Revit user", "Użytkownik Revita", "system")),
    ("OriginalName", ("Original name", "Oryginalna nazwa", "file")),
])

PRESETS = [
    "{SheetNumber}",
    "{SheetNumber} - {SheetName}",
    "{SheetNumber}_{CurrentRevision}",
    "{ModelName} - {SheetNumber} - {SheetName}",
    "{Date} {OriginalName}",
]

_LOWER_TOKENS = dict((name.lower(), name) for name in TOKENS)
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


def format_name(parsed, values, original):
    """The stem for one file. `values` maps token names and "param:<name>" to text. Falls back to
    the original name when the template is off, every token is empty or the result is empty."""
    fallback = clean_name(original)
    if not parsed:
        return fallback
    out = []
    filled = False
    has_tokens = False
    for kind, item in parsed:
        if kind == "text":
            out.append(item)
            continue
        has_tokens = True
        if kind == "token" and item == "OriginalName":
            value = original
        else:
            value = values.get(item if kind == "token" else "param:" + item, "")
        value = value if _is_text(value) else ""
        filled = filled or bool(value)
        out.append(value)
    if has_tokens and not filled:
        return fallback
    return clean_name("".join(out)) or fallback


def system_values(when, windows_user, revit_user, model_name, date_short="", date_long=""):
    """The system tokens, captured once at submit time from the datetime `when`."""
    return {
        "Year": "%04d" % when.year, "Year2": "%02d" % (when.year % 100),
        "Month": "%02d" % when.month, "Day": "%02d" % when.day,
        "Hour": "%02d" % when.hour, "Minute": "%02d" % when.minute,
        "Second": "%02d" % when.second,
        "Date": "%04d-%02d-%02d" % (when.year, when.month, when.day),
        "DateShort": date_short, "DateLong": date_long,
        "ModelName": model_name, "WindowsUser": windows_user, "RevitUser": revit_user,
    }


def check_naming(naming):
    """Validate {"template", "system", "values"}; returns the parsed template or raises NamingError."""
    if not isinstance(naming, dict):
        raise NamingError(tr("The naming request must be a dictionary.",
                             "Żądanie nazewnictwa musi być słownikiem."))
    parsed = parse_template(naming.get("template"))
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


def file_budget(named_root, ext):
    """Most characters for a file stem under `named_root` (a path string) with extension `ext`."""
    return min(_MAX_FILE_PATH - len(named_root) - 1 - len(ext), _MAX_COMPONENT - len(ext))


def folder_budget(named_root, inner_max):
    """Most characters for a folder name; `inner_max` is the longest relative path inside it."""
    return min(_MAX_DIR_PATH - len(named_root) - 1,
               _MAX_FILE_PATH - len(named_root) - 2 - inner_max, _MAX_COMPONENT)


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
