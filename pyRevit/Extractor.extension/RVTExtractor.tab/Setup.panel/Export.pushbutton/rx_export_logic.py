# -*- coding: utf-8 -*-
"""Pure logic of the Export button: settings, tick helpers, shared index, job planning.

No Revit, pyRevit or .NET import (a test enforces this); runs on IronPython 2.7. The windows and
script.py pass everything in. Spec: specs/SPEC-export-button.md.
"""
from __future__ import unicode_literals

import copy
import io
import json
import os

from rx_catalog import normalize_roots
from rx_cloud import model_key, plan_stage
from rx_i18n import tr
from rx_index import SetupError, build_index, require_index_shape
from rx_runner import default_output_parent

try:
    _INTEGER_TYPES = (int, long)  # IronPython 2.7 / CPython 2
    _TEXT_TYPES = (basestring,)
except NameError:
    _INTEGER_TYPES = (int,)
    _TEXT_TYPES = (str,)

CONFIG_SECTION = "RevitExtractorExport"
SETTING_NAMES = ("roots", "output_parent", "max_parallel", "shared_index_path", "subfolders")
_VIEW_ID_KEYS = ("view_ids", "view_unique_ids")


# --- settings ---------------------------------------------------------------------------------

def _read(config, name):
    try:
        return getattr(config, name)
    except Exception:
        return None


def _text(value):
    return value.strip() if isinstance(value, _TEXT_TYPES) else ""


def _max_parallel(value):
    if isinstance(value, bool):
        return 1
    if isinstance(value, _TEXT_TYPES):
        value = value.strip()
        if not value or any(char not in "0123456789" for char in value):
            return 1
    elif not isinstance(value, _INTEGER_TYPES):
        return 1
    number = int(value)
    return number if number >= 1 else 1


_ONEDRIVE_VARIABLES = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")


def inside_onedrive(path, environ=None):
    """True when `path` lies in a OneDrive folder: under a folder named by the OneDrive
    environment variables, or under any folder whose name starts with "OneDrive" (company
    accounts are named "OneDrive - <company>"). Pure text; touches no disk."""
    if not isinstance(path, _TEXT_TYPES) or not path.strip():
        return False
    environ = os.environ if environ is None else environ
    here = os.path.normcase(os.path.normpath(path))
    for name in _ONEDRIVE_VARIABLES:
        root = environ.get(name)
        if root and isinstance(root, _TEXT_TYPES) and root.strip():
            root = os.path.normcase(os.path.normpath(root))
            if here == root or here.startswith(root.rstrip("\\/") + os.sep):
                return True
    parts = here.replace("/", os.sep).split(os.sep)
    return any(part.startswith("onedrive") for part in parts[1:])


def load_settings(config, documents_dir):
    """Settings from a config object (pyRevit's section or a stub); bad or missing values fall back.

    Returns {"roots": [...], "output_parent": text, "max_parallel": int >= 1,
    "shared_index_path": text ("" = none)}. Raises RunnerError (from rx_runner) only when the
    output folder fell back and the base folder is unknown. `documents_dir` is the folder the
    default <base>\\RevitExtractor is made in: script.py passes the user profile folder, outside
    OneDrive (Documents is often synced by it).
    """
    roots = _read(config, "roots")
    if isinstance(roots, (list, tuple)):
        roots = normalize_roots([item for item in roots if isinstance(item, _TEXT_TYPES)],
                                nested=True)
    else:
        roots = []
    output_parent = _text(_read(config, "output_parent"))
    if not output_parent:
        output_parent = default_output_parent(documents_dir)
    return {
        "roots": roots,
        "output_parent": output_parent,
        "max_parallel": _max_parallel(_read(config, "max_parallel")),
        "shared_index_path": _text(_read(config, "shared_index_path")),
        "subfolders": _read(config, "subfolders") is not False,
    }


def settings_to_save(roots, output_parent, max_parallel, shared_index_path, subfolders=True):
    """The dict to store: normalized roots, trimmed texts, a valid max_parallel. Plain values."""
    return {
        "roots": normalize_roots(roots, nested=True),
        "output_parent": _text(output_parent),
        "max_parallel": _max_parallel(max_parallel),
        "shared_index_path": _text(shared_index_path),
        "subfolders": subfolders is not False,
    }


def has_nested_roots(roots):
    """True when a root lies inside another one (searching subfolders makes it redundant)."""
    roots = normalize_roots(roots, nested=True)
    return normalize_roots(roots) != roots


def save_settings(config, values):
    """Write the changed settings onto the config object. True when something changed, so the
    caller (script.py) calls script.save_config() only then."""
    changed = False
    for name in SETTING_NAMES:
        if name not in values:
            continue
        if _read(config, name) != values[name]:
            setattr(config, name, values[name])
            changed = True
    return changed


# --- tick helpers (same behaviour as ExportSetupLegacy/extractor_config.py) --------------------

def tick_targets(selected, source):
    """Rows a checkbox change applies to: the whole selection when the clicked row is part of
    a multi-row selection (Ctrl/Shift/Ctrl+A), otherwise just that row."""
    selected = list(selected)
    if len(selected) > 1 and any(row is source for row in selected):
        return selected
    return [source]


def toggled_state(checked_states):
    """Space on selected rows: tick them all, unless they are all ticked already."""
    return not all(checked_states)


# --- shared index -----------------------------------------------------------------------------

def load_shared_index(path):
    """Read a shared index.json (UTF-8, BOM allowed) and check its shape. Raises SetupError."""
    try:
        with io.open(path, "rb") as handle:
            raw = handle.read()
    except Exception:
        raise SetupError(tr("The shared index.json could not be read.",
                            "Nie udało się odczytać wspólnego pliku index.json."))
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        raise SetupError(tr("The shared index.json is not valid JSON.",
                            "Wspólny plik index.json nie jest poprawnym JSON-em."))
    return require_index_shape(data)


def index_has_view_ids(index):
    """True when the index holds view_ids or view_unique_ids anywhere."""
    if isinstance(index, dict):
        for key, value in index.items():
            if key in _VIEW_ID_KEYS or index_has_view_ids(value):
                return True
    elif isinstance(index, (list, tuple)):
        return any(index_has_view_ids(item) for item in index)
    return False


# --- job planning -----------------------------------------------------------------------------

def _model_path(model):
    path = model if isinstance(model, _TEXT_TYPES) else getattr(model, "path", None)
    if not isinstance(path, _TEXT_TYPES) or not path.strip():
        raise SetupError(tr("A selected model has no file path.",
                            "Zaznaczony model nie ma ścieżki pliku."))
    return path


def plan_jobs(models, caps, shared_index=None):
    """One job per model, in the given order: [{"model_path": text, "index": dict}].

    `models` are catalog rows (or paths). Default scope (shared_index None): each job gets its own
    build_index(caps). A shared index is copied into every job as given. Raises SetupError for no
    model, a greyed-out row (enabled False), or a shared index with view ids and more than one
    model (those ids belong to one model, D11). script.py adds revit_dir and output_parent.
    """
    models = list(models or ())
    if not models:
        raise SetupError(tr("Select at least one model.", "Zaznacz co najmniej jeden model."))
    paths = []
    for model in models:
        if getattr(model, "enabled", True) is False:
            raise SetupError(tr("A model that cannot be exported is selected.",
                                "Zaznaczono model, którego nie można wyeksportować."))
        paths.append(_model_path(model))
    if shared_index is not None and len(paths) > 1 and index_has_view_ids(shared_index):
        raise SetupError(tr(
            "This index.json selects views, and view ids belong to one model. Select one model "
            "or use an index.json without views.",
            "Ten index.json wskazuje widoki, a identyfikatory widoków należą do jednego modelu. "
            "Zaznacz jeden model albo użyj pliku index.json bez widoków."))
    jobs = []
    for path in paths:
        index = build_index(caps) if shared_index is None else copy.deepcopy(shared_index)
        jobs.append({"model_path": path, "index": index})
    return jobs


# --- cloud jobs -------------------------------------------------------------------------------

def link_key(row):
    """The key of a cloud row's link list in rx_cloud.Memory (not the row key)."""
    return model_key(row.project_guid, row.model_guid)


def stage_dict(plan):
    """A StagePlan as plain dicts, the form Job.stage and the status session take:
    {"items": [{"src", "name", "size", "mtime"}], "notes": [text]}."""
    return {"items": [{"src": item.src, "name": item.name, "size": item.size,
                       "mtime": item.mtime} for item in plan.items],
            "notes": list(plan.notes)}


def _host_only_note():
    return tr("The links of this model were not read; it is exported without them.",
              "Linków tego modelu nie odczytano; model wyeksportowano bez nich.")


def plan_cloud_job(row, index, cache_files, memory, links=None, host_only=False):
    """One job for a cloud row (a rx_cloud.CloudRow): the cache copy of the model is the job's
    model_path, `stage` lists what the runner copies into the run folder (host first), and
    `model_name` is the real file name (never the GUID-named cache file). `links` is the host's
    link list (None: from `memory` while the host copy is unchanged); `host_only` stages the host
    alone, with a note. Raises SetupError for a greyed row, rx_cloud.StageError when the model
    name cannot be a file name."""
    if getattr(row, "enabled", True) is not True:
        raise SetupError(tr("A model that cannot be exported is selected.",
                            "Zaznaczono model, którego nie można wyeksportować."))
    plan = plan_stage(row, [] if host_only else links, cache_files, memory)
    stage = stage_dict(plan)
    if host_only:
        stage["notes"].append(_host_only_note())
    return {"model_path": row.cache_path, "model_name": stage["items"][0]["name"],
            "model_key": row.key, "index": index, "stage": stage}


def plan_cloud_jobs(rows, caps, cache_files, memory, link_lists=None, host_only=(),
                    shared_index=None):
    """One cloud job per ticked, enabled CloudRow, in the given order: the shape of plan_jobs plus
    "model_name", "model_key" and "stage" (see plan_cloud_job).

    `link_lists` maps a row's key to its link list; a row without an entry takes the list from
    `memory`. `host_only` holds the keys of rows exported without their links. The index rules are
    plan_jobs's: default scope gives each job build_index(caps), a shared index is copied, and a
    shared index with view ids needs exactly one model. Raises SetupError, StageError.
    """
    rows = list(rows or ())
    if not rows:
        raise SetupError(tr("Select at least one model.", "Zaznacz co najmniej jeden model."))
    for row in rows:
        if getattr(row, "enabled", True) is not True:
            raise SetupError(tr("A model that cannot be exported is selected.",
                                "Zaznaczono model, którego nie można wyeksportować."))
    if shared_index is not None and len(rows) > 1 and index_has_view_ids(shared_index):
        raise SetupError(tr(
            "This index.json selects views, and view ids belong to one model. Select one model "
            "or use an index.json without views.",
            "Ten index.json wskazuje widoki, a identyfikatory widoków należą do jednego modelu. "
            "Zaznacz jeden model albo użyj pliku index.json bez widoków."))
    link_lists = link_lists or {}
    jobs = []
    for row in rows:
        index = build_index(caps) if shared_index is None else copy.deepcopy(shared_index)
        jobs.append(plan_cloud_job(row, index, cache_files, memory, link_lists.get(row.key),
                                   row.key in host_only))
    return jobs
