# -*- coding: utf-8 -*-
"""One index.json builder for every Revit version, driven by rx_capabilities.

Pure Python, no Revit import (a test enforces this); runs on IronPython 2.7. It writes what the
two old buttons write, proven equal by tests that run both. The row flags of `caps` decide the
form; this module never reads the Revit year. Spec: specs/SPEC-index-builder.md.
"""
from __future__ import unicode_literals

import json

from rx_i18n import tr

try:
    _INTEGER_TYPES = (int, long)  # IronPython 2.7 / CPython 2
    _TEXT_TYPES = (basestring,)
except NameError:
    _INTEGER_TYPES = (int,)
    _TEXT_TYPES = (str,)

_COMMON_DEFAULTS = {
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
_EXTENDED_DEFAULTS = {"extended_properties": False, "topology_metadata": False}
_FORMAT_DEFAULTS = {"dwg": False, "ifc": False}

_INT32_MAX = 2147483647


class SetupError(ValueError):
    """The settings or the selection cannot produce a safe index."""


def defaults(caps):
    """The settings defaults of the table row (a new dict each call)."""
    options = dict(_COMMON_DEFAULTS)
    if caps.extended_properties:
        options["extended_properties"] = _EXTENDED_DEFAULTS["extended_properties"]
    if caps.topology_metadata:
        options["topology_metadata"] = _EXTENDED_DEFAULTS["topology_metadata"]
    for name in caps.formats:
        options[name] = _FORMAT_DEFAULTS[name]
    return options


def _numeric_ids(selected, dimension):
    ids = set()
    for value in selected:
        # Extractor 2024.0.x reads view_ids as Int32 (reflection); 2025.3 was checked up to the
        # Int32 maximum. Revit 2024+ ElementId is Int64, so larger IDs are rejected, never
        # truncated. Never truncate a float or accept a UID: an invalid selection could
        # otherwise turn into a default/broad export.
        if (isinstance(value, bool)
                or not isinstance(value, _INTEGER_TYPES + _TEXT_TYPES)
                or (isinstance(value, _TEXT_TYPES)
                    and (not value or any(char not in "0123456789" for char in value)))):
            raise SetupError(tr("Selected views need a numeric ElementId.",
                                "Wybrane widoki wymagają liczbowego ElementId."))
        element_id = int(value)
        if not 0 < element_id <= _INT32_MAX:
            raise SetupError(tr(
                "View ElementId is outside the range the Extractor accepts.",
                "ElementId widoku jest poza zakresem obsługiwanym przez Extractor."))
        ids.add(element_id)
    return sorted(ids)


def _unique_ids(selected, dimension):
    uids = set()
    for value in selected:
        if not value:
            continue  # empty entries are dropped, as in the 2026 button
        if not isinstance(value, _TEXT_TYPES):
            raise SetupError(tr("Selected views need a text UniqueId.",
                                "Wybrane widoki wymagają tekstowego UniqueId."))
        uids.add(value)
    return sorted(uids)


def _view_options(caps, settings, dimension, selected):
    scope = settings["scope_" + dimension]
    if not isinstance(scope, _TEXT_TYPES) or scope not in ("default", "selected"):
        raise SetupError(tr("Unknown view selection mode: {0}",
                            "Nieznany tryb wyboru widoków: {0}").format(scope))
    if scope == "default":
        return {}
    # Only a list/tuple of IDs: a string would be iterated per character ("123" -> 1, 2, 3).
    if not isinstance(selected, (list, tuple)):
        if caps.view_key == "view_ids":
            raise SetupError(tr("The view selection must be a list of ElementIds.",
                                "Wybór widoków musi być listą ElementId."))
        raise SetupError(tr("The view selection must be a list of UniqueIds.",
                            "Wybór widoków musi być listą UniqueId."))
    # A missing/empty selection must never silently fall back to a broad export.
    if caps.view_key == "view_ids":
        ids = _numeric_ids(selected, dimension)
    else:
        ids = _unique_ids(selected, dimension)
    if not ids:
        raise SetupError(
            tr("Select at least one {0} view or choose the default scope.",
               "Zaznacz co najmniej jeden widok {0} lub wybierz domyślny zakres.")
            .format(dimension.upper()))
    return {caps.view_key: ids}


def _check_supported(caps, options):
    if not caps.formats and (options.get("dwg") or options.get("ifc")
                             or options.get("ifc_setup_name")):
        raise SetupError(tr("This Extractor profile (Revit 2022-2025) does not support DWG or IFC "
                            "export. Use the Export command in Revit.",
                            "Ten profil Extractora (Revit 2022-2025) nie obsługuje eksportu DWG "
                            "ani IFC. Użyj polecenia eksportu w Revicie."))
    if (not caps.extended_properties and options.get("extended_properties")) or \
            (not caps.topology_metadata and options.get("topology_metadata")):
        raise SetupError(tr("This Extractor profile (Revit 2022-2025) does not support extended "
                            "properties or topology metadata.",
                            "Ten profil Extractora (Revit 2022-2025) nie obsługuje rozszerzonych "
                            "właściwości ani metadanych topologii."))
    switches = ("enable_2d", "enable_3d", "pdb") + tuple(caps.formats)
    if not any(options[key] for key in switches):
        if caps.formats:
            raise SetupError(tr("Enable 2D views, 3D views, the database or an additional format.",
                                "Włącz widoki 2D, widoki 3D, bazę danych lub dodatkowy format."))
        raise SetupError(tr("Enable 2D views, 3D views or the database.",
                            "Włącz widoki 2D, widoki 3D lub bazę danych."))


def build_index(caps, settings=None, selected_2d=None, selected_3d=None):
    """Omit disabled viewing branches; their mere presence enables them. Raises SetupError."""
    base = defaults(caps)
    options = dict(base)
    if settings:
        options.update(settings)
    _check_supported(caps, options)

    derivative = {}
    if options["enable_3d"]:
        view3d = _view_options(caps, options, "3d", selected_3d or [])
        flags = ["aec_model_data", "design_description", "generate_master_views"]
        if caps.topology_metadata:
            flags.append("topology_metadata")
        for key in flags:
            if bool(options[key]) != base[key]:
                view3d[key] = bool(options[key])
        if caps.db_export_key and not options["pdb"]:
            # Extractor 2024.0.x ignores properties_data.pdb and reads this key (default true).
            # Without 3D there is no way to tell it, since writing 3dviewing enables 3D.
            view3d["db_export"] = False
        derivative["3dviewing"] = view3d
    if options["enable_2d"]:
        view2d = _view_options(caps, options, "2d", selected_2d or [])
        if options["f2d"]:
            view2d["f2d"] = True
        derivative["2dviewing"] = view2d

    # Always explicit: an empty derivative_type enables both viewing branches.
    derivative["properties_data"] = {"pdb": bool(options["pdb"])}
    if caps.extended_properties and options["pdb"] and options["extended_properties"]:
        derivative["metadata"] = {"extended_properties": True}
    formats = [name for name in caps.formats if options[name]]
    if formats:
        derivative["export"] = {"to": formats}
    parameters = {"derivative_type": derivative}
    if "ifc" in caps.formats and options["ifc"] and options.get("ifc_setup_name"):
        parameters["direct_params"] = {"IFCExportOption": options["ifc_setup_name"]}
    return {"metadata": {"parameters": parameters}}


def database_warning(caps, settings=None):
    """Text to show when the index cannot switch the DB off for every Extractor build, else "".

    Extractor 2024.0.x only reads 3dviewing.db_export, and its PropDbTask runs whenever that is
    not false, so with 3D off it still builds the database. Rows without db_export_key never warn.
    """
    options = defaults(caps)
    if settings:
        options.update(settings)
    if not caps.db_export_key or options["pdb"] or options["enable_3d"]:
        return ""
    return tr("Note: with 3D views off, older Extractor builds (2024.0.x, e.g. Revit 2023 "
              "without updates) still create the SQLite database.",
              "Uwaga: przy wyłączonych widokach 3D starsze kompilacje Extractora (2024.0.x, "
              "np. Revit 2023 bez aktualizacji) i tak utworzą bazę SQLite.")


def to_json(index):
    return json.dumps(index, ensure_ascii=False, indent=2) + "\n"


def require_index_shape(data):
    """The shared index.json shape (Q18): metadata.parameters.derivative_type. Returns data."""
    level = data
    for key in ("metadata", "parameters", "derivative_type"):
        if not isinstance(level, dict) or not isinstance(level.get(key), dict):
            raise SetupError(tr(
                "index.json must contain metadata.parameters.derivative_type.",
                "index.json musi zawierać metadata.parameters.derivative_type."))
        level = level[key]
    return data
