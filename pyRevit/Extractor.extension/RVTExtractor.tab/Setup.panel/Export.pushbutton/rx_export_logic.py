# -*- coding: utf-8 -*-
"""Pure logic of the Export button: settings, tick helpers, shared index, job planning.

No Revit, pyRevit or .NET import (a test enforces this); runs on IronPython 2.7. The windows and
script.py pass everything in. Spec: specs/SPEC-export-button.md.
"""
from __future__ import unicode_literals

import copy
import io
import json

from rx_catalog import normalize_roots
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
SETTING_NAMES = ("roots", "output_parent", "max_parallel", "shared_index_path")
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


def load_settings(config, documents_dir):
    """Settings from a config object (pyRevit's section or a stub); bad or missing values fall back.

    Returns {"roots": [...], "output_parent": text, "max_parallel": int >= 1,
    "shared_index_path": text ("" = none)}. Raises RunnerError (from rx_runner) only when the
    output folder fell back and the Documents folder is unknown.
    """
    roots = _read(config, "roots")
    if isinstance(roots, (list, tuple)):
        roots = normalize_roots([item for item in roots if isinstance(item, _TEXT_TYPES)])
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
    }


def settings_to_save(roots, output_parent, max_parallel, shared_index_path):
    """The dict to store: normalized roots, trimmed texts, a valid max_parallel. Plain values."""
    return {
        "roots": normalize_roots(roots),
        "output_parent": _text(output_parent),
        "max_parallel": _max_parallel(max_parallel),
        "shared_index_path": _text(shared_index_path),
    }


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
