# -*- coding: utf-8 -*-
"""Revit 2022-2025 index builder; compatible with pyRevit IronPython 2.7."""
from __future__ import unicode_literals

import json

from extractor_i18n import tr

try:
    integer_types = (int, long)
    string_types = (basestring,)
except NameError:
    integer_types = (int,)
    string_types = (str,)


DEFAULTS = {
    "enable_2d": True,
    "enable_3d": True,
    "pdb": True,
    "scope_2d": "default",
    "scope_3d": "default",
    "aec_model_data": True,
    "design_description": True,
    "generate_master_views": False,
    "f2d": False,
}


class SetupError(ValueError):
    pass


def _view_options(settings, dimension, selected_ids):
    scope = settings["scope_" + dimension]
    if scope not in ("default", "selected"):
        raise SetupError(tr("Unknown view selection mode: {0}",
                            "Nieznany tryb wyboru widoków: {0}").format(scope))
    if scope == "default":
        return {}
    # Only a list/tuple of IDs: a string would be iterated per character ("123" -> 1, 2, 3).
    if not isinstance(selected_ids, (list, tuple)):
        raise SetupError(tr("The view selection must be a list of ElementIds.",
                            "Wybór widoków musi być listą ElementId."))
    # A missing/empty selection must never silently fall back to a broad export.
    ids = set()
    for value in selected_ids:
        # Extractor 2024.0.x reads view_ids as Int32 (reflection); 2025.3 was checked up to the
        # Int32 maximum. Revit 2024+ ElementId is Int64, so larger IDs are rejected, never
        # truncated. Never truncate a float or accept a UID:
        # an invalid selection could otherwise turn into a default/broad export.
        if (isinstance(value, bool)
                or not isinstance(value, integer_types + string_types)
                or (isinstance(value, string_types)
                    and (not value or any(char not in "0123456789" for char in value)))):
            raise SetupError(tr("Selected views need a numeric ElementId.",
                                "Wybrane widoki wymagają liczbowego ElementId."))
        element_id = int(value)
        if not 0 < element_id <= 2147483647:
            raise SetupError(tr("View ElementId is outside the range the Extractor accepts.",
                                "ElementId widoku jest poza zakresem obsługiwanym przez Extractor."))
        ids.add(element_id)
    if not ids:
        raise SetupError(
            tr("Select at least one {0} view or choose the default scope.",
               "Zaznacz co najmniej jeden widok {0} lub wybierz domyślny zakres.")
            .format(dimension.upper()))
    return {"view_ids": sorted(ids)}


def build_index(settings=None, selected_2d=None, selected_3d=None):
    """Omit disabled viewing branches; their mere presence enables them."""
    options = dict(DEFAULTS)
    if settings:
        options.update(settings)
    if options.get("dwg") or options.get("ifc") or options.get("ifc_setup_name"):
        raise SetupError(tr("This Extractor profile (Revit 2022-2025) does not support DWG or IFC "
                            "export. Use the Export command in Revit.",
                            "Ten profil Extractora (Revit 2022-2025) nie obsługuje eksportu DWG "
                            "ani IFC. Użyj polecenia eksportu w Revicie."))
    if options.get("extended_properties") or options.get("topology_metadata"):
        raise SetupError(tr("This Extractor profile (Revit 2022-2025) does not support extended "
                            "properties or topology metadata.",
                            "Ten profil Extractora (Revit 2022-2025) nie obsługuje rozszerzonych "
                            "właściwości ani metadanych topologii."))
    if not any(options[key] for key in ("enable_2d", "enable_3d", "pdb")):
        raise SetupError(tr("Enable 2D views, 3D views or the database.",
                            "Włącz widoki 2D, widoki 3D lub bazę danych."))

    derivative = {}
    if options["enable_3d"]:
        view3d = _view_options(options, "3d", selected_3d or [])
        for key in ("aec_model_data", "design_description", "generate_master_views"):
            if bool(options[key]) != DEFAULTS[key]:
                view3d[key] = bool(options[key])
        if not options["pdb"]:
            # Extractor 2024.0.x ignores properties_data.pdb and reads this key (default true).
            # Without 3D there is no way to tell it, since writing 3dviewing enables 3D.
            view3d["db_export"] = False
        derivative["3dviewing"] = view3d
    if options["enable_2d"]:
        view2d = _view_options(options, "2d", selected_2d or [])
        if options["f2d"]:
            view2d["f2d"] = True
        derivative["2dviewing"] = view2d

    # Always explicit: an empty derivative_type enables both viewing branches.
    derivative["properties_data"] = {"pdb": bool(options["pdb"])}
    parameters = {"derivative_type": derivative}
    return {"metadata": {"parameters": parameters}}


def database_warning(settings=None):
    """Text to show when the index cannot switch the DB off for every Extractor build, else "".

    Extractor 2024.0.x only reads 3dviewing.db_export, and its PropDbTask runs whenever that is
    not false, so with 3D off it still builds the database.
    """
    options = dict(DEFAULTS)
    if settings:
        options.update(settings)
    if options["pdb"] or options["enable_3d"]:
        return ""
    return tr("Note: with 3D views off, older Extractor builds (2024.0.x, e.g. Revit 2023 "
              "without updates) still create the SQLite database.",
              "Uwaga: przy wyłączonych widokach 3D starsze kompilacje Extractora (2024.0.x, "
              "np. Revit 2023 bez aktualizacji) i tak utworzą bazę SQLite.")


def to_json(index):
    return json.dumps(index, ensure_ascii=False, indent=2) + "\n"


def filter_records(records, search="", kind=None):
    words = search.lower().split()
    return [row for row in records
            if (not kind or row["kind"] == kind)
            and all(word in row["search"] for word in words)]
