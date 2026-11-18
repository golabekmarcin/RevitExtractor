# -*- coding: utf-8 -*-
"""Naming profiles for named copies: what a profile holds, validation, the files it is kept in,
the list of parts the user can pick and the remembered choice. Pure Python: no Revit, pyRevit,
System or clr import; reading and writing are injected. Spec: specs/SPEC-named-copies.md.

A profile is {"name", "views": [part], "sheets": [part], "separator", "split_by_format"}; a part is
a token name from rx_naming.TOKENS or "param:<name>". to_template() turns the parts of one tab
into the {Token} template string rx_naming already parses, so the user never sees braces.
"""
from __future__ import unicode_literals

import io
import json
import os
from collections import OrderedDict

from rx_i18n import tr
from rx_json import dumps_ascii
from rx_naming import (BUILT_IN_COUNT, MAX_TEMPLATE, TOKENS, Counter, NamingError, format_name,
                       parse_template)
from rx_status import _write_text, read_preferences

SCHEMA = "rx-naming-profile"
VERSION = 1
SUFFIX = ".rx-naming.json"
SEPARATORS = (" - ", " ", "_", "-")
CATALOG_SCHEMA = "rx-property-catalog"
NAMING_KEY = "naming"

DEFAULT = OrderedDict([
    ("name", "Default"), ("views", ["ViewFamily", "ViewName"]),
    ("sheets", ["SheetNumber", "SheetName"]), ("separator", " - "), ("split_by_format", False)])

_SHEET_ONLY = ("SheetNumber", "SheetName", "CurrentRevision", "CurrentRevisionDate",
               "CurrentRevisionDescription", "SheetIssueDate", "DrawnBy", "CheckedBy",
               "DesignedBy", "ApprovedBy", "SheetSize")
_VIEW_ONLY = ("ViewName", "ViewFamily", "TitleOnSheet", "Scale", "DetailLevel", "Discipline",
              "Phase", "ViewTemplate", "ViewSheetNumber")
_SYSTEM = tuple(list(TOKENS)[BUILT_IN_COUNT:])
# Which tokens each tab offers: its own built-in ones, ElementId, then all the system ones.
TAB_TOKENS = {"sheets": _SHEET_ONLY + ("ElementId",) + _SYSTEM,
              "views": _VIEW_ONLY + ("ElementId",) + _SYSTEM}
_GROUPS = {"builtin": 0, "custom": 1, "system": 2}


def _text(value):
    return isinstance(value, type(""))


def to_template(parts, separator):
    """The {Token} template for a list of parts joined by `separator`."""
    return separator.join("{param:%s}" % p[6:] if p.startswith("param:") else "{%s}" % p
                          for p in parts)


def _check_parts(tab, parts, separator):
    if not isinstance(parts, list) or not parts:
        raise NamingError(tr("The {0} list of a naming profile must not be empty.",
                             "Lista {0} profilu nazewnictwa nie może być pusta.").format(tab))
    for part in parts:
        if not _text(part):
            raise NamingError(tr("A naming profile part must be text.",
                                 "Część profilu nazewnictwa musi być tekstem."))
        if part.startswith("param:"):
            name = part[6:]
            if not name.strip() or "{" in name or "}" in name:
                raise NamingError(tr("A parameter name in a naming profile is empty or holds a "
                                     "brace.", "Nazwa parametru w profilu jest pusta albo "
                                     "zawiera nawias klamrowy."))
        elif part not in TAB_TOKENS[tab]:
            raise NamingError(tr("Unknown part {0} in a naming profile.",
                                 "Nieznana część {0} w profilu nazewnictwa.").format(part))
    template = to_template(parts, separator)
    if len(template) > MAX_TEMPLATE:
        raise NamingError(tr("The file-name template is longer than {0} characters.",
                             "Szablon nazw plików ma więcej niż {0} znaków.").format(MAX_TEMPLATE))
    parse_template(template)   # the same parser the run uses
    return list(parts)


def validate(data):
    """The profile as a clean dict, or NamingError."""
    if not isinstance(data, dict):
        raise NamingError(tr("A naming profile must be a dictionary.",
                             "Profil nazewnictwa musi być słownikiem."))
    separator = data.get("separator")
    if separator not in SEPARATORS:
        raise NamingError(tr("The separator of a naming profile is not one of the allowed ones.",
                             "Separator profilu nazewnictwa nie jest jednym z dozwolonych."))
    name = data.get("name")
    return OrderedDict([
        ("name", name.strip() if _text(name) else ""),
        ("views", _check_parts("views", data.get("views"), separator)),
        ("sheets", _check_parts("sheets", data.get("sheets"), separator)),
        ("separator", separator), ("split_by_format", data.get("split_by_format") is True)])


def default_profile():
    return validate(DEFAULT)


def load_profile(path):
    """The validated profile in the file; NamingError when it is missing, unreadable or wrong."""
    try:
        with io.open(path, "r", encoding="utf-8") as handle:
            data = json.loads(handle.read().lstrip("﻿"))
    except Exception:
        raise NamingError(tr("The naming profile file could not be read.",
                             "Nie można odczytać pliku profilu nazewnictwa."))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("version") != VERSION:
        raise NamingError(tr("The file is not a naming profile.",
                             "Ten plik nie jest profilem nazewnictwa."))
    return validate(data)


def profile_path(chosen):
    """`chosen` with the suffix .rx-naming.json (a trailing .json is replaced)."""
    if chosen.lower().endswith(SUFFIX):
        return chosen
    if chosen.lower().endswith(".json"):
        chosen = chosen[:-5]
    return chosen + SUFFIX


def save_profile(path, profile):
    """Writes the validated profile to .tmp, removes the old file and renames (IronPython 2.7
    cannot overwrite through rename). Raises NamingError (bad profile) or EnvironmentError."""
    clean = validate(profile)
    out = OrderedDict([("schema", SCHEMA), ("version", VERSION)])
    out.update(clean)
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    temp = path + ".tmp"
    with io.open(temp, "w", encoding="utf-8") as handle:
        handle.write(dumps_ascii(out, indent=2))
    if os.path.exists(path):
        os.remove(path)
    os.rename(temp, path)


def read_catalog(path, read=None):
    """{"views": [names], "sheets": [names]} from property-catalog.json; empty lists when the
    file is missing or wrong."""
    empty = {"views": [], "sheets": []}
    try:
        if read is None:
            with io.open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        else:
            text = read(path)
        data = json.loads(text.lstrip("﻿"))
    except Exception:
        return empty
    if not isinstance(data, dict) or data.get("schema") != CATALOG_SCHEMA:
        return empty
    for tab in empty:
        names = data.get(tab)
        if isinstance(names, list):
            empty[tab] = sorted(set(n.strip() for n in names if _text(n) and n.strip()))
    return empty


CATALOG_MAX = 2000


def merge_catalog(path, found):
    """Union the parameter names in `found` ({"views": [...], "sheets": [...]}) into the
    property catalog file at `path` (sorted, at most CATALOG_MAX each; written to .tmp, then the
    old file removed and renamed). False, never an exception, when it could not be written."""
    try:
        old = read_catalog(path)
        out = OrderedDict([("schema", CATALOG_SCHEMA), ("version", 1)])
        for tab in ("views", "sheets"):
            names = set(old[tab]) | set(n.strip() for n in (found or {}).get(tab) or []
                                        if _text(n) and n.strip())
            out[tab] = sorted(names)[:CATALOG_MAX]
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        temp = path + ".tmp"
        with io.open(temp, "w", encoding="utf-8") as handle:
            handle.write(dumps_ascii(out, indent=2))
        if os.path.exists(path):
            os.remove(path)
        os.rename(temp, path)
        return True
    except Exception:
        return False


def available(tab, catalog, query, lang):
    """[(part, label, cls)] the user can pick on `tab` ("views" or "sheets"): Built-in, then
    Custom, then System, each by label; only labels holding `query` (case-insensitive). `lang`
    is "pl" for Polish, anything else English. cls is "builtin", "custom" or "system"."""
    pl = lang == "pl"
    items = []
    for name in TAB_TOKENS[tab]:
        english, polish, _scope = TOKENS[name]
        cls = "builtin" if list(TOKENS).index(name) < BUILT_IN_COUNT else "system"
        items.append((name, polish if pl else english, cls))
    for name in (catalog or {}).get(tab) or []:
        items.append(("param:" + name, name, "custom"))
    query = (query or "").strip().lower()
    items = [i for i in items if query in i[1].lower()]
    items.sort(key=lambda i: (_GROUPS[i[2]], i[1].lower()))
    return items


def preview(profile, tab, sample):
    """An example file stem for `profile` on `tab` from `sample` (token and "param:" values);
    "" when the profile is unusable. Blank parts show their numbers."""
    try:
        clean = validate(profile)
    except NamingError:
        return ""
    parsed = parse_template(to_template(clean[tab], clean["separator"]))
    original = sample.get("OriginalName", "")
    return format_name(parsed, sample, original, Counter())


def read_choice(prefs):
    """The remembered choice from the preferences dict: {"selected": "none" | "default" | path,
    "profile": profile dict or None (none), "profiles": [{"name", "path"}], "note": text}. A
    missing or unusable file falls back to Default and says so in "note". Nothing chosen yet
    means "none"."""
    block = prefs.get(NAMING_KEY) if isinstance(prefs, dict) else None
    block = block if isinstance(block, dict) else {}
    profiles = [{"name": p["name"], "path": p["path"]} for p in block.get("profiles") or []
                if isinstance(p, dict) and _text(p.get("name")) and _text(p.get("path"))]
    selected = block.get("selected")
    note = ""
    profile = None
    if not _text(selected) or selected == "none":
        selected = "none"
    elif selected == "default":
        profile = default_profile()
    else:
        try:
            profile = load_profile(selected)
        except NamingError:
            label = next((p["name"] for p in profiles if p["path"] == selected),
                         os.path.basename(selected))
            note = tr('The naming profile "{0}" could not be read; the Default profile is '
                      'used.', 'Nie można odczytać profilu nazewnictwa "{0}"; użyto profilu '
                      'Domyślnego.').format(label)
            selected, profile = "default", default_profile()
    return {"selected": selected, "profile": profile, "profiles": profiles, "note": note}


def remember(prefs_path, selected, profiles=None):
    """Stores the choice (and the profile list when given) under "naming" in the preferences
    file, keeping every other key. False (never raises) on any failure."""
    if not prefs_path:
        return False
    try:
        prefs = read_preferences(prefs_path)
        block = prefs.get(NAMING_KEY)
        block = dict(block) if isinstance(block, dict) else {}
        block["selected"] = selected
        if profiles is not None:
            block["profiles"] = [{"name": p["name"], "path": p["path"]} for p in profiles]
        prefs[NAMING_KEY] = block
        _write_text(prefs_path, dumps_ascii(prefs, indent=2, sort_keys=True))
        return True
    except Exception:
        return False
