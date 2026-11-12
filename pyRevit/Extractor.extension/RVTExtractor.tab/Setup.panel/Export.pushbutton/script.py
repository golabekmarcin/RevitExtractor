# -*- coding: utf-8 -*-
"""The one Export button: with no model open, pick models (and optionally views of one), then
hand the exports to the status window's queue and return at once.

Guards first, in this order: a model is open (refuse, bring up the status window if there is
one), an unsupported Revit, a missing RevitExtractor.exe. Only JSON text goes to the session:
no function, window or Revit object of this command outlives it. Button title and tooltip
(English and Polish) live in bundle.yaml. Spec: specs/SPEC-export-button.md.
"""
from __future__ import unicode_literals

import json
import os

from System import AppDomain, Environment
from System.Diagnostics import FileVersionInfo
from pyrevit import DB, HOST_APP, forms, script

import rx_catalog
import rx_reader
from rx_capabilities import for_revit
from rx_export_logic import CONFIG_SECTION, load_settings, save_settings
from rx_export_ui import ModelWindow
from rx_i18n import tr
from rx_runner import extractor_exe
from rx_status import find_session
from rx_status_ui import open_session

CACHE_FOLDER = "RevitExtractor"            # under %APPDATA% (D2); holds model paths
CACHE_FILE = "catalog-cache.json"


def _error_text(error):
    if getattr(error, "args", None):
        try:
            return "%s" % (error.args[0],)
        except Exception:
            pass
    return type(error).__name__


def _alert(message):
    forms.alert(message, title=tr("Export", "Eksport"))


def _documents_open(uiapp):
    """True unless Revit says for sure that no document is open. Anything that cannot be asked
    counts as open; only a real True from IsEmpty passes (never 1, "True" or None)."""
    try:
        if uiapp.ActiveUIDocument is not None:
            return True
        empty = uiapp.Application.Documents.IsEmpty
    except Exception:
        return True
    return not (isinstance(empty, bool) and empty)


def _show_session():
    """Bring up the status window of a session that already exists; never create one."""
    try:
        handler = find_session(AppDomain.CurrentDomain)
        if handler is not None:
            handler(json.dumps({"op": "show"}))
    except Exception:
        pass


def _extractor_build(revit_dir):
    """File version of ExtractorUtility.dll, or "" when it cannot be read."""
    path = os.path.join(revit_dir, "RevitExtractor", "ExtractorUtility.dll")
    try:
        version = FileVersionInfo.GetVersionInfo(path).FileVersion
    except Exception:
        return ""
    return ("%s" % version).strip() if version else ""


def _hand_over(jobs, revit_dir, output_parent, max_parallel):
    request = {"op": "submit", "jobs": [
        {"model_path": job["model_path"], "index": job["index"], "revit_dir": revit_dir,
         "output_parent": output_parent} for job in jobs]}
    try:
        handler = open_session(max_parallel)
        answer = json.loads(handler(json.dumps(request, ensure_ascii=True)))
    except Exception as error:
        try:
            script.get_logger().exception("Could not hand the exports to the status window.")
        except Exception:
            pass
        _alert(tr("The exports could not be handed to the status window.\n\n{0}",
                  "Nie udało się przekazać eksportów do okna statusu.\n\n{0}")
               .format(_error_text(error)))
        return
    if not isinstance(answer, dict) or answer.get("ok") is not True:
        reason = answer.get("error") if isinstance(answer, dict) else None
        _alert(tr("The exports were not queued.\n\n{0}",
                  "Eksporty nie zostały dodane do kolejki.\n\n{0}").format(reason or ""))
        return
    errors = [("%s" % item) for item in (answer.get("errors") or [])]
    if errors:
        _alert(tr("Some exports were not queued:\n\n{0}",
                  "Niektóre eksporty nie zostały dodane do kolejki:\n\n{0}")
               .format("\n".join(errors)))
    try:
        handler(json.dumps({"op": "show"}))
    except Exception:
        pass


def main():
    uiapp = HOST_APP.uiapp
    if _documents_open(uiapp):
        _alert(tr("Close all open models first. The Export button reads model files in the "
                  "background and works only when no model is open.",
                  "Najpierw zamknij wszystkie otwarte modele. Przycisk Eksport odczytuje pliki "
                  "modeli w tle i działa tylko wtedy, gdy żaden model nie jest otwarty."))
        _show_session()
        return
    app = uiapp.Application
    try:
        caps = for_revit(app.VersionNumber)
    except Exception as error:
        _alert(_error_text(error))
        return
    try:
        revit_dir = os.path.dirname(HOST_APP.proc_path)
        extractor_exe(revit_dir)
    except Exception as error:
        _alert(tr("The Revit Extractor of this Revit was not found.\n\n{0}",
                  "Nie znaleziono Revit Extractora tego Revita.\n\n{0}")
               .format(_error_text(error)))
        return

    config = script.get_config(CONFIG_SECTION)
    appdata = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData)
    try:
        settings = load_settings(
            config, Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments))
        if not appdata:
            raise ValueError(tr("The AppData folder is unknown.",
                                "Nie znaleziono folderu AppData."))
    except Exception as error:
        _alert(_error_text(error))
        return
    cache = rx_catalog.Cache(os.path.join(appdata, CACHE_FOLDER, CACHE_FILE)).load()

    def read_info(path):
        return rx_catalog.read_basic_info(path, DB.BasicFileInfo)

    def read(path, workshared):
        return rx_reader.read_model(app, DB, path, caps, workshared)

    def save(values):
        if save_settings(config, values):
            script.save_config()

    try:
        window = ModelWindow(caps, settings, read_info, cache, read, save,
                             extractor_build=_extractor_build(revit_dir), scan=rx_catalog.scan)
    except Exception as error:
        script.get_logger().exception("Could not open the export window.")
        _alert(tr("The export window could not be opened.\n\n{0}",
                  "Nie udało się otworzyć okna eksportu.\n\n{0}").format(_error_text(error)))
        return
    try:
        window.show_dialog()
    except Exception as error:
        _alert(tr("The export window failed.\n\n{0}",
                  "Błąd okna eksportu.\n\n{0}").format(_error_text(error)))
        return
    finally:
        window.stop_scan()

    if window.fatal_error:
        _alert(tr("Revit could not close the model it read in the background, so nothing was "
                  "exported. Close it in Revit, or restart Revit, before the next export.\n\n{0}",
                  "Revit nie zamknął modelu odczytanego w tle, więc nic nie zostało "
                  "wyeksportowane. Zamknij go w Revicie albo uruchom Revit ponownie przed "
                  "kolejnym eksportem.\n\n{0}").format(window.fatal_error))
        return
    if not window.jobs:
        return
    _hand_over(window.jobs, revit_dir, window.output_parent, settings["max_parallel"])


if __name__ == "__main__":
    main()
