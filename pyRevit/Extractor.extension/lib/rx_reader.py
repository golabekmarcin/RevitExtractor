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

def collect_views(doc, DB):
    """{"views_2d": [...], "views_3d": [...]}: plain rows, no Revit object is kept.

    Same rows as ExportSetupLegacy/extractor_model.collect_views (a test checks parity).
    """
    rows_2d, rows_3d = [], []
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


def read_model(app, DB, path, caps, workshared=None):
    """Snapshot {"title", "path", "views_2d", "views_3d", "ifc_setups", "ifc_error"} of the
    model at `path`, read in the background. Raises ReadError.

    Call only from the button's command (modal), never from the modeless status window.
    `workshared` comes from the catalog; None (unknown) counts as workshared.
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
    try:
        views = collect_views(doc, DB)
        ifc_setups, ifc_error = [], ""
        if caps.ifc_setups:
            ifc_setups, ifc_error = _read_ifc_setups(doc, DB)
    finally:
        closed, close_detail = _close(doc)
    doc = None
    if not closed:
        raise _close_failed(close_detail)
    return {
        "title": text(ntpath.basename(path)),
        "path": path,
        "views_2d": views["views_2d"],
        "views_3d": views["views_3d"],
        "ifc_setups": ifc_setups,
        "ifc_error": ifc_error,
    }


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
