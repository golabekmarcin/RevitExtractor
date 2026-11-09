# -*- coding: utf-8 -*-
"""Revit 2022 index builder; compatible with pyRevit IronPython 2.7."""
from __future__ import unicode_literals

import json

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
        raise SetupError("Nieznany tryb wyboru widoków: " + scope)
    if scope == "default":
        return {}
    # A missing/empty selection must never silently fall back to a broad export.
    ids = set()
    for value in selected_ids:
        # Revit 2022 ElementId is Int32. Never truncate a float or accept a UID:
        # an invalid selection could otherwise turn into a default/broad export.
        if (isinstance(value, bool)
                or not isinstance(value, integer_types + string_types)
                or (isinstance(value, string_types)
                    and (not value or any(char not in "0123456789" for char in value)))):
            raise SetupError("Widoki dla Revita 2022 wymagają liczbowego ElementId.")
        element_id = int(value)
        if not 0 < element_id <= 2147483647:
            raise SetupError("ElementId widoku jest poza zakresem Revita 2022.")
        ids.add(element_id)
    if not ids:
        raise SetupError(
            "Zaznacz co najmniej jeden widok {0} lub wybierz domyślny zakres."
            .format(dimension.upper()))
    return {"view_ids": sorted(ids)}


def build_index(settings=None, selected_2d=None, selected_3d=None):
    """Omit disabled viewing branches; their mere presence enables them."""
    options = dict(DEFAULTS)
    if settings:
        options.update(settings)
    if options.get("dwg") or options.get("ifc") or options.get("ifc_setup_name"):
        raise SetupError("Ten profil Extractora 2022 nie obsługuje eksportu DWG ani IFC. "
                         "Użyj polecenia eksportu w Revicie.")
    if options.get("extended_properties") or options.get("topology_metadata"):
        raise SetupError("Ten profil Extractora 2022 nie obsługuje rozszerzonych "
                         "właściwości ani metadanych topologii.")
    if not any(options[key] for key in ("enable_2d", "enable_3d", "pdb")):
        raise SetupError("Włącz widoki 2D, widoki 3D lub bazę danych.")

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


def to_json(index):
    return json.dumps(index, ensure_ascii=False, indent=2) + "\n"


def filter_records(records, search="", kind=None):
    words = search.lower().split()
    return [row for row in records
            if (not kind or row["kind"] == kind)
            and all(word in row["search"] for word in words)]
