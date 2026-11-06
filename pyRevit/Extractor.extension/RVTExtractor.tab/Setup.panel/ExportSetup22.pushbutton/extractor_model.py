# -*- coding: utf-8 -*-
"""Read the active project once, before opening the modal setup dialog."""
from __future__ import unicode_literals

from pyrevit import DB

try:
    text = unicode
except NameError:
    text = str


VIEW_KINDS = {
    "FloorPlan": "Rzuty kondygnacji",
    "CeilingPlan": "Rzuty sufitów",
    "EngineeringPlan": "Rzuty konstrukcyjne",
    "AreaPlan": "Rzuty powierzchni",
    "Section": "Przekroje",
    "Elevation": "Elewacje",
    "Detail": "Detale",
    "DraftingView": "Widoki kreślarskie",
    "Legend": "Legendy",
    "DrawingSheet": "Arkusze",
    "ThreeD": "Widoki 3D",
}


def collect_views(doc):
    """Detached records only: no Revit API objects are kept by the window."""
    rows_2d, rows_3d = [], []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if view.IsTemplate or not view.CanBePrinted:
            continue
        view_type = text(view.ViewType)
        if view_type not in VIEW_KINDS:
            # Schedules/panels/browser/internal views are not standalone drawings.
            continue
        is_sheet = isinstance(view, DB.ViewSheet)
        if is_sheet and view.IsPlaceholder:
            continue
        element_id = view.Id.IntegerValue
        name = text(view.Name)
        number = text(view.SheetNumber) if is_sheet else ""
        label = "{0} — {1}".format(number, name) if number else name
        row = {
            "id": text(element_id),
            "uid": text(view.UniqueId),
            "name": label,
            "kind": VIEW_KINDS[view_type],
        }
        row["search"] = " ".join((label, row["kind"], row["id"])).lower()
        (rows_3d if view_type == "ThreeD" else rows_2d).append(row)
    return {
        "title": text(doc.Title),
        "path": text(doc.PathName),
        "modified": bool(doc.IsModified),
        "views_2d": sorted(rows_2d, key=lambda row: (row["kind"], row["name"].lower())),
        "views_3d": sorted(rows_3d, key=lambda row: row["name"].lower()),
    }
