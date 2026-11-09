# -*- coding: utf-8 -*-
"""Read the active project once, before opening the modal setup dialog."""
from __future__ import unicode_literals

from pyrevit import DB

from extractor_i18n import tr
from extractor_text import VIEW_KINDS

try:
    text = unicode
except NameError:
    text = str


def element_id_value(element_id):
    """Numeric ElementId across Revit 2022-2025, picked by feature, not by version.

    RevitAPI docs (RevitRAG): ElementId.Value (Int64) is documented from 2024; IntegerValue
    is documented 2022-2025.3 and not in 2026. On 2022-2023 only IntegerValue exists.
    The caller turns the value into text, so an Int64 never reaches the index's Int32 checks.
    """
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


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
        element_id = element_id_value(view.Id)
        name = text(view.Name)
        number = text(view.SheetNumber) if is_sheet else ""
        label = "{0} — {1}".format(number, name) if number else name
        english, polish = VIEW_KINDS[view_type]
        row = {
            "id": text(element_id),
            "uid": text(view.UniqueId),
            "name": label,
            "kind": tr(english, polish),
        }
        # Search matches the type in both languages, whatever the UI shows.
        row["search"] = " ".join((label, english, polish, row["id"])).lower()
        (rows_3d if view_type == "ThreeD" else rows_2d).append(row)
    return {
        "title": text(doc.Title),
        "path": text(doc.PathName),
        "modified": bool(doc.IsModified),
        "views_2d": sorted(rows_2d, key=lambda row: (row["kind"], row["name"].lower())),
        "views_3d": sorted(rows_3d, key=lambda row: row["name"].lower()),
    }
