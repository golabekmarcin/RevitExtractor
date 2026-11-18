# -*- coding: utf-8 -*-
"""Read one model's views in the background and leave the file untouched.

Opens detached with all worksets closed, collects the view rows, and closes with Close(False)
exactly once. Never saves, never starts a transaction, never closes a document it did not open.
No Revit import: the caller passes `app` (Autodesk.Revit.ApplicationServices.Application) and
`DB` (Autodesk.Revit.DB); a test enforces this. Compatible with pyRevit IronPython 2.7.
Spec: specs/SPEC-model-reader.md. Nothing here has been run inside Revit.
"""
from __future__ import unicode_literals

import json
import ntpath
import re

from rx_capabilities import element_id_value
from rx_i18n import tr

try:
    text = unicode  # IronPython 2.7
    _TEXT_TYPES = (basestring,)
except NameError:
    text = str
    _TEXT_TYPES = (str,)

# ViewType name -> (english, polish). Moved from ExportSetupLegacy/extractor_text.VIEW_KINDS;
# a test keeps the two equal while the old button exists.
VIEW_KINDS = {
    "FloorPlan": ("Floor plans", "Rzuty kondygnacji"),
    "CeilingPlan": ("Ceiling plans", "Rzuty sufitów"),
    "EngineeringPlan": ("Structural plans", "Rzuty konstrukcyjne"),
    "AreaPlan": ("Area plans", "Rzuty powierzchni"),
    "Section": ("Sections", "Przekroje"),
    "Elevation": ("Elevations", "Elewacje"),
    "Detail": ("Detail views", "Detale"),
    "DraftingView": ("Drafting views", "Widoki kreślarskie"),
    "Legend": ("Legends", "Legendy"),
    "DrawingSheet": ("Sheets", "Arkusze"),
    "ThreeD": ("3D views", "Widoki 3D"),
}

READ_ERROR_KINDS = ("busy", "open_failed", "close_failed")


def _is_bool(value, expected):
    """Strict bool test that does not rely on `is True` identity for .NET Boolean returns.
    1, "True", None and other look-alikes never pass."""
    return isinstance(value, bool) and bool(value) == expected


class ReadError(Exception):
    """kind: "busy" | "open_failed" | "close_failed". message: bilingual (already translated).
    detail: the original host text, if any."""

    def __init__(self, kind, message, detail=""):
        if kind not in READ_ERROR_KINDS:
            raise ValueError("Unknown ReadError kind: %r" % (kind,))
        Exception.__init__(self, message)
        self.kind = kind
        self.message = message
        self.detail = detail

    def __str__(self):
        return self.message


class IfcSetupError(ValueError):
    """The IFC setups stored in the model are inconsistent (read side only)."""


# --------------------------------------------------------------------------- views

def _kept_views(doc, DB):
    """[(view, view_type, is_sheet)] for every printable view and real sheet."""
    kept = []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if view.IsTemplate or not view.CanBePrinted:
            continue
        view_type = text(view.ViewType)
        if view_type not in VIEW_KINDS:
            # Schedules, panels, browser and internal views are not standalone drawings.
            continue
        is_sheet = isinstance(view, DB.ViewSheet)
        if is_sheet and view.IsPlaceholder:
            continue
        kept.append((view, view_type, is_sheet))
    return kept


def collect_views(doc, DB, kept=None):
    """{"views_2d": [...], "views_3d": [...]}: plain rows, no Revit object is kept.

    Same rows as ExportSetupLegacy/extractor_model.collect_views (a test checks parity).
    `kept` (from _kept_views) saves a second collector pass.
    """
    rows_2d, rows_3d = [], []
    for view, view_type, is_sheet in (_kept_views(doc, DB) if kept is None else kept):
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
        "views_2d": sorted(rows_2d, key=lambda row: (row["kind"], row["name"].lower())),
        "views_3d": sorted(rows_3d, key=lambda row: row["name"].lower()),
    }


# --------------------------------------------------------------------------- values
# Naming values (specs/SPEC-named-copies.md, Source B). ParameterTypeId members are language
# neutral; each is documented in revit-api revisions 2022 and 2026 (same member hashes). Not
# run in Revit.
_MAX_VALUE = 255
_MAX_CATALOG = 2000
_SHEET_TOKENS = (
    ("SheetNumber", "SheetNumber"), ("SheetName", "SheetName"),
    ("CurrentRevision", "SheetCurrentRevision"),
    ("CurrentRevisionDate", "SheetCurrentRevisionDate"),
    ("CurrentRevisionDescription", "SheetCurrentRevisionDescription"),
    ("SheetIssueDate", "SheetIssueDate"), ("DrawnBy", "SheetDrawnBy"),
    ("CheckedBy", "SheetCheckedBy"), ("DesignedBy", "SheetDesignedBy"),
    ("ApprovedBy", "SheetApprovedBy"))
_VIEW_TOKENS = (
    ("ViewName", "ViewName"), ("TitleOnSheet", "ViewDescription"),
    ("DetailLevel", "ViewDetailLevel"), ("Discipline", "ViewDiscipline"),
    ("Phase", "ViewPhase"), ("ViewSheetNumber", "ViewerSheetNumber"))
_ISO_SIZES = (("A0", 841, 1189), ("A1", 594, 841), ("A2", 420, 594), ("A3", 297, 420),
              ("A4", 210, 297))
_MM_PER_FOOT = 304.8


def _param_text(param):
    """Text of a parameter: AsString, else AsValueString; "" when empty or unreadable."""
    try:
        if param is None or not param.HasValue:
            return ""
        value = param.AsString()
        if value is None:
            value = param.AsValueString()
        return text(value)[:_MAX_VALUE] if value is not None else ""
    except Exception:
        return ""


def _typed(element, DB, member):
    try:
        return _param_text(element.GetParameter(getattr(DB.ParameterTypeId, member)))
    except Exception:
        return ""


def _size_mm(holder, DB, member):
    try:
        param = holder.GetParameter(getattr(DB.ParameterTypeId, member))
        return param.AsDouble() * _MM_PER_FOOT if param is not None else None
    except Exception:
        return None


def _sheet_size(doc, DB, sheet):
    """First title block on the sheet: ISO name within 1 mm (either orientation), else WxH mm."""
    try:
        blocks = list(DB.FilteredElementCollector(doc, sheet.Id).OfCategory(
            DB.BuiltInCategory.OST_TitleBlocks).WhereElementIsNotElementType())
        if not blocks:
            return ""
        holders = [blocks[0]]
        try:
            holders.append(doc.GetElement(blocks[0].GetTypeId()))  # may sit on the type
        except Exception:
            pass
        width = height = None
        for holder in holders:
            width, height = _size_mm(holder, DB, "SheetWidth"), _size_mm(holder, DB, "SheetHeight")
            if width is not None and height is not None:
                break
        if width is None or height is None:
            return ""
        for name, short, long_ in _ISO_SIZES:
            for a, b in ((width, height), (height, width)):
                if abs(a - short) <= 1 and abs(b - long_) <= 1:
                    return name
        return "%dx%d" % (round(width), round(height))
    except Exception:
        return ""


def _view_extras(doc, DB, view):
    out = {}
    try:
        out["Scale"] = text(view.Scale)
    except Exception:
        pass
    try:
        template_id = view.ViewTemplateId
        if element_id_value(template_id) != -1:
            out["ViewTemplate"] = text(element_name(doc.GetElement(template_id), DB))
    except Exception:
        pass
    try:
        out["ViewFamily"] = text(doc.GetElement(view.GetTypeId()).FamilyName)
    except Exception:
        pass
    return out


def collect_values(doc, DB, views):
    """{UniqueId: {"kind", "id", "name", "tokens", "params"}} for the given view/sheet elements.
    Plain text only; empty tokens and parameters are left out. Reads only."""
    elements = {}
    for view in views:
        is_sheet = isinstance(view, DB.ViewSheet)
        element_id = text(element_id_value(view.Id))
        name = text(view.Name)
        tokens = {}
        for token, member in (_SHEET_TOKENS if is_sheet else ()) + _VIEW_TOKENS:
            tokens[token] = _typed(view, DB, member)
        if is_sheet:
            name = "{0} - {1}".format(text(view.SheetNumber), name)
            tokens["SheetSize"] = _sheet_size(doc, DB, view)
        else:
            tokens.update(_view_extras(doc, DB, view))
        tokens["ElementId"] = element_id
        params = {}
        try:
            for param in view.Parameters:
                try:
                    key, value = text(param.Definition.Name), _param_text(param)
                except Exception:
                    continue
                if value.strip() and key not in params:
                    params[key] = value
        except Exception:
            pass
        elements[text(view.UniqueId)] = {
            "kind": "sheet" if is_sheet else "view", "id": element_id, "name": name,
            "tokens": dict((k, v) for k, v in tokens.items() if v.strip()), "params": params}
    return elements


def collect_catalog(elements):
    """{"views": [...], "sheets": [...]}: sorted unique parameter names, at most 2000 each."""
    names = {"view": set(), "sheet": set()}
    for record in elements.values():
        if record.get("kind") in names:
            names[record["kind"]].update(record.get("params") or ())
    return {"views": sorted(names["view"])[:_MAX_CATALOG],
            "sheets": sorted(names["sheet"])[:_MAX_CATALOG]}


# --------------------------------------------------------------------------- cloud links

# Read-only port of the link part of ExportSetupLegacy/extractor_cloud_probe.collect.
# revit-api 2026-11-16 (spec "API facts"): Element.GetExternalResourceReferences is declared on
# Element (RevitLinkType inherits it) and raises InvalidOperationException when the element uses
# no external resource; ExternalResourceReference.GetReferenceInformation returns a
# (String, String) map. The three Linked* keys are undocumented, observed on Revit 2022 only.
# Both maps are iterated as KeyValuePairs, the shape the probe read in the owner's Revit 2022
# session. ExternalFileUtils.GetExternalFileReference throws for cloud links: not used.
_GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_MODEL_KEY = "LinkedModelModelId"
_PROJECT_KEY = "LinkedModelProjectId"
_REGION_KEY = "LinkedModelRegion"


def _guid_text(value):
    """Lower case, braces stripped; anything that is not a GUID gives ""."""
    if value is None:
        return ""
    try:
        value = text(value).strip().strip("{}").strip().lower()
    except Exception:
        return ""
    return value if _GUID_RE.match(value) else ""


def element_name(element, DB):
    """element.Name; IronPython often cannot read Name on element types, so fall back to .NET
    reflection on Element.Name (as ExportSetupLegacy/config.element_name)."""
    try:
        return element.Name
    except Exception:
        import clr  # IronPython only; imported here so the module loads in CPython tests
        return clr.GetClrType(DB.Element).GetProperty("Name").GetValue(element, None)


def _reference_infos(link_type):
    """One plain {key: value} dict per external resource of the link, in map order."""
    try:
        references = link_type.GetExternalResourceReferences()
    except Exception:
        # InvalidOperationException: no external resource (a local link, for instance).
        return []
    infos = []
    for entry in references:
        try:
            native = entry.Value.GetReferenceInformation()
            infos.append(dict((text(pair.Key), text(pair.Value)) for pair in native))
        except Exception:
            continue
    return infos


def _link_row(link_type, DB, name_of):
    try:
        name = name_of(link_type) if name_of is not None else element_name(link_type, DB)
        name = text(name) if name is not None else ""
    except Exception:
        name = ""
    nested = False
    try:
        nested = _is_bool(link_type.IsNestedLink, True)
    except Exception:
        pass
    # The first resource with a model id; else the first one, so partial ids are still kept.
    infos = _reference_infos(link_type)
    chosen = infos[0] if infos else {}
    for info in infos:
        if _guid_text(info.get(_MODEL_KEY)):
            chosen = info
            break
    region = chosen.get(_REGION_KEY)
    return {
        "name": name,
        "project_guid": _guid_text(chosen.get(_PROJECT_KEY)),
        "model_guid": _guid_text(chosen.get(_MODEL_KEY)),
        "region": text(region).strip() if region is not None else "",
        "nested": nested,
    }


def collect_cloud_links(doc, DB, name_of=None):
    """[{"name", "project_guid", "model_guid", "region", "nested"}] for every RevitLinkType,
    nested links included. Plain text and bool only; reads only. A missing or unreadable id
    is "" (the link is then not found in the cache). `name_of(element)` replaces the default
    name reading (Name, then reflection)."""
    rows = [_link_row(link_type, DB, name_of)
            for link_type in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkType)]
    return sorted(rows, key=lambda row: (row["name"].lower(), row["name"], row["project_guid"],
                                         row["model_guid"]))


# --------------------------------------------------------------------------- open

def open_options(DB, workshared=None):
    """OpenOptions for a background open. Only workshared=False (from the catalog) gets plain
    options; anything else, including unknown, is treated as workshared."""
    options = DB.OpenOptions()
    if _is_bool(workshared, False):
        return options
    options.DetachFromCentralOption = DB.DetachFromCentralOption.DetachAndPreserveWorksets
    options.SetOpenWorksetsConfiguration(
        DB.WorksetConfiguration(DB.WorksetConfigurationOption.CloseAllWorksets))
    options.Audit = False
    options.AllowOpeningLocalByWrongUser = True
    return options


# Exception type names documented for Application.OpenDocumentFile(ModelPath, OpenOptions)
# (revit-api, revisions 2022 and 2026, member hash 06ebc3d01cc8f44d27d4f855). Matched by the
# type's own name only; any other type gets the generic message with the original text.
def _open_messages():
    central = tr("The central model is busy or access was denied. Try again later.",
                 "Model centralny jest zajęty lub odmówiono dostępu. Spróbuj ponownie później.")
    corrupt = tr("The model is corrupt and cannot be opened.",
                 "Model jest uszkodzony i nie można go otworzyć.")
    return {
        "FileNotFoundException": tr("The model file was not found.",
                                    "Nie znaleziono pliku modelu."),
        "CentralModelContentionException": central,
        "CentralModelAccessDeniedException": central,
        "CorruptModelException": corrupt,
        "ServerModelCorruptedException": corrupt,  # documented in 2026 only
        "WrongUserException": tr("The local file belongs to another user.",
                                 "Plik lokalny należy do innego użytkownika."),
        "OperationCanceledException": tr("Opening the model was cancelled.",
                                         "Otwieranie modelu zostało anulowane."),
        "InsufficientResourcesException": tr(
            "Not enough memory, disk space or other resources to open the model.",
            "Za mało pamięci, miejsca na dysku lub innych zasobów, aby otworzyć model."),
    }


def _type_names(error):
    """Candidate type names: the .NET exception IronPython wraps (clsException), the object
    itself if it is a .NET exception, then the Python type."""
    names = []
    for candidate in (getattr(error, "clsException", None), error):
        if candidate is None:
            continue
        get_type = getattr(candidate, "GetType", None)
        if get_type is None:
            continue
        try:
            names.append(text(get_type().Name))
        except Exception:
            pass
    names.append(text(type(error).__name__))
    return names


def _detail(error):
    for candidate in (getattr(error, "clsException", None), error):
        message = getattr(candidate, "Message", None) if candidate is not None else None
        if message:
            try:
                return text(message)
            except Exception:
                pass
    try:
        return text(error)
    except Exception:
        return text(repr(error))


def _open_failed(error):
    detail = _detail(error)
    messages = _open_messages()
    for name in _type_names(error):
        if name in messages:
            return ReadError("open_failed", messages[name], detail)
    return ReadError("open_failed", tr("Revit could not open the model: {0}",
                                       "Revit nie mógł otworzyć modelu: {0}").format(detail),
                     detail)


def _close_failed(detail=""):
    message = tr("Revit did not close the model opened in the background, so a document may "
                 "still be open. Nothing was saved. Restart Revit before the next read.",
                 "Revit nie zamknął modelu otwartego w tle, więc dokument może być nadal "
                 "otwarty. Niczego nie zapisano. Uruchom Revit ponownie przed kolejnym odczytem.")
    if detail:
        message = "{0} ({1})".format(message, detail)
    return ReadError("close_failed", message, detail)


def _close(doc):
    """The only Close in this module. Never raises: returns (closed, detail)."""
    try:
        result = doc.Close(False)
    except Exception as error:
        return False, _detail(error)
    return _is_bool(result, True), ""


def read_model(app, DB, path, caps, workshared=None, links=False, values=False):
    """Snapshot {"title", "path", "views_2d", "views_3d", "ifc_setups", "ifc_error"} of the
    model at `path`, read in the background. Raises ReadError.

    Call only from the button's command (modal), never from the modeless status window.
    `workshared` comes from the catalog; None (unknown) counts as workshared.
    `links=True` adds "links" (collect_cloud_links rows); otherwise no link member is read.
    `values=True` adds "values" (collect_values) from the same open and the same view list.
    """
    # Guard first: OpenDocumentFile on a file that is already open may hand back the user's
    # own document, and closing that would discard their work. Only a real True passes.
    if not _is_bool(app.Documents.IsEmpty, True):
        raise ReadError("busy", tr(
            "Close all open models before a model is read in the background. "
            "Nothing was opened.",
            "Zamknij wszystkie otwarte modele przed odczytem modelu w tle. Niczego nie otwarto."))
    if not isinstance(path, _TEXT_TYPES) or not path.strip():
        raise ReadError("open_failed", tr("No model file was given.",
                                          "Nie podano pliku modelu."))
    path = text(path)
    try:
        model_path = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(path)
        options = open_options(DB, workshared)
        doc = app.OpenDocumentFile(model_path, options)
    except Exception as error:
        raise _open_failed(error)
    if doc is None:
        raise ReadError("open_failed", tr("Revit could not open the model.",
                                          "Revit nie mógł otworzyć modelu."))

    # From here on `doc` is the document this call opened and nothing else. It is closed
    # exactly once, in `finally`; an error raised by the body wins over a close failure.
    closed, close_detail = False, ""
    link_rows = value_rows = None
    try:
        kept = _kept_views(doc, DB)
        views = collect_views(doc, DB, kept)
        if _is_bool(values, True):
            value_rows = collect_values(doc, DB, [item[0] for item in kept])
        ifc_setups, ifc_error = [], ""
        if caps.ifc_setups:
            ifc_setups, ifc_error = _read_ifc_setups(doc, DB)
        if _is_bool(links, True):
            link_rows = collect_cloud_links(doc, DB)
    finally:
        closed, close_detail = _close(doc)
    doc = None
    if not closed:
        raise _close_failed(close_detail)
    snapshot = {
        "title": text(ntpath.basename(path)),
        "path": path,
        "views_2d": views["views_2d"],
        "views_3d": views["views_3d"],
        "ifc_setups": ifc_setups,
        "ifc_error": ifc_error,
    }
    if link_rows is not None:
        snapshot["links"] = link_rows
    if value_rows is not None:
        snapshot["values"] = value_rows
    return snapshot


# --------------------------------------------------------------------------- IFC setups

# Read-only port of ExportSetup/extractor_ifc_storage._records and the name checks of its
# _validate_native_map. Constants copied from ExportSetup/extractor_ifc.py.
# revit-api 2026-11-10: Entity.Get<FieldType>(String) is documented in 2022
# (2022:b8ee0868071c9e79:6dfe12e9df552bc7b29e3f2c) and 2026 (2026:441dcbf9ce355456:
# 6dfe12e9df552bc7b29e3f2c); the type argument must match the field type exactly (IDictionary
# for maps), else ArgumentException. Not run in Revit (no Revit 2026 here).
_MAP_SCHEMA_ID = "DCB88B13-594F-44F6-8F5D-AE9477305AC3"   # IFCExportConfigurationMap
_JSON_SCHEMA_ID = "C2A3E6FE-CE51-4F35-8FF1-20C34567B687"  # current Autodesk UI (JSON)
_BUILTIN_NAMES = set("IFC " + suffix for suffix in (
    "2x3 Coordination View 2.0", "2x3 Coordination View", "2x3 GSA Concept Design BIM 2010",
    "2x3 Basic FM Handover View", "2x2 Coordination View", "2x2 Singapore BCA e-Plan Check",
    "2x3 Extended FM Handover View"))
_BUILTIN_NAMES.update(name.replace("IFC ", "IFC") for name in list(_BUILTIN_NAMES))
_BUILTIN_NAMES.update(("IFC4 Reference View", "IFC4 Design Transfer View"))


def _ifc_setups(doc, DB):
    """[{"name", "ready"}] sorted by name; ready = the setup has the map the Extractor reads.
    Raises IfcSetupError when the stored setups are inconsistent. Reads only."""
    from System import Guid, String
    from System.Collections.Generic import IDictionary

    storage_api = DB.ExtensibleStorage
    map_schema = storage_api.Schema.Lookup(Guid(_MAP_SCHEMA_ID))
    json_schema = storage_api.Schema.Lookup(Guid(_JSON_SCHEMA_ID))
    if map_schema is None and json_schema is None:
        return []
    records = []
    map_names = set()
    for storage in DB.FilteredElementCollector(doc).OfClass(storage_api.DataStorage):
        json_name, map_name = None, None
        if json_schema is not None:
            entity = storage.GetEntity(json_schema)
            if entity.IsValid():
                try:
                    source = json.loads(text(entity.Get[String]("MapField")))
                except ValueError:
                    source = None
                if not isinstance(source, dict) or not source.get("Name"):
                    raise IfcSetupError(tr("An IFC setup in the model has invalid JSON.",
                                           "Setup IFC w modelu ma nieprawidłowy JSON."))
                json_name = text(source["Name"])
        if map_schema is not None:
            entity = storage.GetEntity(map_schema)
            if entity.IsValid():
                native = entity.Get[IDictionary[String, String]]("MapField")
                data = dict((text(pair.Key), text(pair.Value)) for pair in native)
                map_name = data.get("Name")
                # A bad map can abort the Extractor's native loop over saved setups.
                if not map_name or map_name in _BUILTIN_NAMES:
                    raise IfcSetupError(tr(
                        "An older IFC setup in the model has a missing or reserved name.",
                        "Starszy setup IFC w modelu ma brakującą lub zastrzeżoną nazwę."))
                if map_name in map_names:
                    raise IfcSetupError(tr(
                        "Several older IFC setups in the model use the name {0}.",
                        "Kilka starszych setupów IFC w modelu używa nazwy {0}.").format(map_name))
                map_names.add(map_name)
        if json_name is not None and map_name is not None and json_name != map_name:
            raise IfcSetupError(tr("One data element in the model holds two different IFC setups.",
                                   "Jeden element danych w modelu zawiera dwa różne setupy IFC."))
        if json_name is not None or map_name is not None:
            records.append({"name": json_name if json_name is not None else map_name,
                            "ready": map_name is not None})
    return sorted(records, key=lambda item: (item["name"].lower(), item["name"], item["ready"]))


def _read_ifc_setups(doc, DB):
    """(setups, error text). A failure here never costs the view list: the IFC part is the
    least verified one (no Revit 2026 here), so any error is contained and reported."""
    try:
        return _ifc_setups(doc, DB), ""
    except IfcSetupError as error:
        return [], text(error)
    except Exception as error:
        return [], tr("The IFC setups could not be read: {0}",
                      "Nie udało się odczytać setupów IFC: {0}").format(_detail(error))
