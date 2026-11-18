# -*- coding: utf-8 -*-
"""The one Export button: with no model open, pick models (and optionally views of one). Export
hands the jobs to the status window's queue at once and the model window stays open (modal, so
Revit API calls keep the command's context); closing it ends the command and hands over nothing.

Guards first, in this order: a model is open (refuse, bring up the status window if there is
one), an unsupported Revit, a missing RevitExtractor.exe. Only JSON text goes to the session:
no function, window or Revit object of this command outlives it. Button title and tooltip
(English and Polish) live in bundle.yaml. Spec: specs/SPEC-export-button.md.
"""
from __future__ import unicode_literals

import datetime
import json
import os
import re
import time

from System import AppDomain, Environment
from pyrevit import DB, HOST_APP, forms, script

import rx_dotnet

rx_dotnet.ensure_assemblies()   # .NET 8 (Revit 2025+) needs some assemblies added first

import rx_catalog
import rx_cloud
import rx_cloud_log
import rx_reader
from rx_capabilities import for_revit
from rx_export_logic import CONFIG_SECTION, load_settings, save_settings
from rx_export_ui import ModelWindow
from rx_i18n import tr
from rx_json import dumps_ascii
from rx_naming import system_values
from rx_runner import DotNetStarter, extractor_exe, find_orphan_run
from rx_status import find_session
from rx_status_ui import open_session

CACHE_FOLDER = "RevitExtractor"            # under %APPDATA% (D2); holds model paths
CACHE_FILE = "catalog-cache.json"
CLOUD_FILE = "cloud-catalog.json"          # names, project selection and link lists of the Cloud source


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


def _orphan_extractor_running(domain):
    """True when a RevitExtractor.exe runs but this Revit has no export session: a run from an
    earlier Revit session (closing Revit leaves it going). Only lists processes; any failure
    counts as false."""
    try:
        if find_session(domain) is not None:
            return False
        return bool(DotNetStarter().extractor_running())
    except Exception:
        return False


def _adopt_orphan(settings):
    """Put the export an earlier Revit session left running into this session's status window
    (watched only). True when it was found and shown; any failure is false."""
    try:
        try:
            starts = DotNetStarter().extractor_start_times()
        except Exception:
            starts = []    # unknown: nothing is adopted
        run = find_orphan_run(settings["output_parent"], time.time(), starts)
        if run is None:
            return False
        handler = open_session(settings["max_parallel"])
        answer = json.loads(handler(dumps_ascii({"op": "adopt", "run_root": run.root})))
        if not isinstance(answer, dict) or answer.get("ok") is not True:
            return False
        _show_session()
        return True
    except Exception:
        return False


def _extractor_build(revit_dir):
    """File version of ExtractorUtility.dll, or of ExtractorUtility_<year>.dll (the Extractor
    that ships with Revit 2025 names it that way), or "" when it cannot be read."""
    folder = os.path.join(revit_dir, "RevitExtractor")
    path = os.path.join(folder, "ExtractorUtility.dll")
    if not os.path.isfile(path):
        try:
            names = sorted(name for name in os.listdir(folder)
                           if re.match(r"^ExtractorUtility_\d{4}\.dll$", name))
        except OSError:
            names = []
        if names:
            path = os.path.join(folder, names[-1])
    return rx_dotnet.file_version(path)


def _failed_positions(errors):
    """0-based positions of the jobs the session refused. It numbers them "Export 2: ..." or
    "Eksport 2: ..." (rx_status); an error without a number (status window failure) fails none."""
    positions = []
    for line in errors:
        match = re.match(r"^(?:Export|Eksport) (\d+):", line)
        if match and int(match.group(1)) > 0:
            positions.append(int(match.group(1)) - 1)
    return sorted(set(positions))


def _windows_dates():
    """The short and the long date in this user's Windows regional settings (.NET current
    culture), or two empty texts when .NET cannot say."""
    try:
        from System import DateTime
        now = DateTime.Now
        return "%s" % now.ToString("d"), "%s" % now.ToString("D")
    except Exception:
        return "", ""


def _system_tokens(app, job, now=None, environ=None, dates=None):
    """The system tokens of the file-name template, captured once when the export is
    submitted: time parts, the regional dates, Windows user, Revit user and the model name
    (a cloud job: its real file name, never the GUID-named cache file)."""
    now = now or datetime.datetime.now()
    environ = os.environ if environ is None else environ
    short, long_ = (dates or _windows_dates)()
    try:
        revit_user = "%s" % (app.Username or "")
    except Exception:
        revit_user = ""
    name = job.get("model_name") or os.path.basename(job.get("model_path") or "")
    stem = os.path.splitext(name)[0]
    return system_values(now, environ.get("USERNAME") or "", revit_user, stem, short, long_)


def _job_request(job, revit_dir, output_parent, system=None):
    """One job of the submit request. A cloud job also carries its staging plan, the real file
    name of the model and the catalog key (all plain JSON values). A job with a file-name
    template carries it with the system tokens (`system(job)`; the values of sheets and
    views are not known yet: None)."""
    entry = {"model_path": job["model_path"], "index": job["index"], "revit_dir": revit_dir,
             "output_parent": output_parent}
    for name in ("stage", "model_name", "model_key"):
        if job.get(name) is not None:
            entry[name] = job[name]
    naming = job.get("naming")
    if isinstance(naming, dict) and system is not None and (
            naming.get("templates") or naming.get("template")):
        entry["naming"] = {"split": bool(naming.get("split")), "system": system(job),
                           "values": naming.get("values")}   # None: the Extractor's own names
        for key in ("templates", "template"):   # the per-kind templates of a chosen profile
            if naming.get(key):
                entry["naming"][key] = naming[key]
    return entry


def _hand_over(jobs, revit_dir, output_parent, max_parallel, system=None):
    """Hand the jobs to the status window's queue. Returns {"queued": n, "failed": [job
    positions], "warning": text}. Raises RuntimeError with a ready, translated message when the
    session cannot be reached or refuses; the model window shows it on its error line."""
    request = {"op": "submit", "jobs": [
        _job_request(job, revit_dir, output_parent, system) for job in jobs]}
    try:
        handler = open_session(max_parallel)
        answer = json.loads(handler(dumps_ascii(request)))
    except Exception as error:
        try:  # the full traceback goes to the pyRevit log; the window gets one line
            script.get_logger().exception("Could not hand the exports to the status window.")
        except Exception:
            pass
        raise RuntimeError(tr("The exports could not be handed to the status window: {0}",
                              "Nie udało się przekazać eksportów do okna statusu: {0}")
                           .format(_error_text(error)))
    if not isinstance(answer, dict) or answer.get("ok") is not True:
        reason = answer.get("error") if isinstance(answer, dict) else None
        raise RuntimeError(tr("The exports were not queued: {0}",
                              "Eksporty nie zostały dodane do kolejki: {0}").format(reason or ""))
    errors = [("%s" % item) for item in (answer.get("errors") or [])]
    added = answer.get("added")
    result = {"queued": len(added) if isinstance(added, list) else len(jobs) - len(errors),
              "failed": _failed_positions(errors), "warning": ""}
    if errors:
        result["warning"] = tr("Some exports were not queued: {0}",
                               "Niektóre eksporty nie zostały dodane do kolejki: {0}"
                               ).format("; ".join(errors))
    try:
        handler(json.dumps({"op": "show"}))
    except Exception:
        pass
    return result


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

    orphan = _orphan_extractor_running(AppDomain.CurrentDomain)

    config = script.get_config(CONFIG_SECTION)
    appdata = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData)
    try:
        settings = load_settings(
            # the profile folder, not Documents: Documents is often synced by OneDrive
            config, Environment.GetFolderPath(Environment.SpecialFolder.UserProfile))
        if not appdata:
            raise ValueError(tr("The AppData folder is unknown.",
                                "Nie znaleziono folderu AppData."))
    except Exception as error:
        _alert(_error_text(error))
        return
    if orphan and not _adopt_orphan(settings):
        # not found in the output folder: say so, the status window cannot show it
        _alert(tr("An export from an earlier Revit session is still running on this computer. "
                  "It is not listed in the status window. Exports you queue now will start when "
                  "it has finished.",
                  "Eksport z wcześniejszej sesji Revita nadal działa na tym komputerze. Nie ma "
                  "go w oknie statusu. Eksporty dodane teraz ruszą po jego zakończeniu."))
    cache = rx_catalog.Cache(os.path.join(appdata, CACHE_FOLDER, CACHE_FILE)).load()

    def read_info(path):
        return rx_catalog.read_basic_info(path, DB.BasicFileInfo)

    def read(path, workshared, links=False):
        extra = {"links": True} if links else {}
        return rx_reader.read_model(app, DB, path, caps, workshared, **extra)

    log_folder = rx_cloud_log.log_folder(appdata)   # %APPDATA%: never the run folder or the cache

    def read_cloud(region, project_guid, model_guid, all_worksets=True, values=True,
                   local_path=None):
        snapshot = rx_reader.read_cloud(
            app, DB, region, project_guid, model_guid, caps, values=values,
            all_worksets=all_worksets, local_path=local_path, uiapp=uiapp,
            diagnostics=lambda lines: rx_cloud_log.append(log_folder, lines))
        if isinstance(snapshot.get("values"), dict):
            snapshot["catalog"] = rx_reader.collect_catalog(snapshot["values"])
        return snapshot

    def save(values):
        if save_settings(config, values):
            script.save_config()

    def submit(jobs, output_parent):
        return _hand_over(jobs, revit_dir, output_parent, settings["max_parallel"],
                          system=lambda job: _system_tokens(app, job))

    cloud = None
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        cloud = {"folders": rx_cloud.revit_folders(local_appdata, caps.year),
                 "memory": rx_cloud.Memory(os.path.join(appdata, CACHE_FOLDER, CLOUD_FILE)).load()}

    try:
        window = ModelWindow(caps, settings, read_info, cache, read, save,
                             extractor_build=_extractor_build(revit_dir), scan=rx_catalog.scan,
                             submit=submit, cloud=cloud, read_cloud=read_cloud)
    except Exception as error:
        script.get_logger().exception("Could not open the export window.")
        _alert(tr("The export window could not be opened.\n\n{0}",
                  "Nie udało się otworzyć okna eksportu.\n\n{0}").format(_error_text(error)))
        return
    try:
        from System.Windows.Interop import WindowInteropHelper
        # parent the window to Revit's main window, so it stays above Revit (and goes down
        # and up with it) instead of dropping behind it
        WindowInteropHelper(window).Owner = HOST_APP.uiapp.MainWindowHandle
    except Exception:
        script.get_logger().warning("Could not parent the export window to Revit.")
    try:
        # a second line of defence: when Revit still takes the front (a cloud list loading, a
        # model opening in the background), the window takes it back
        window.keep_in_front(HOST_APP.uiapp.MainWindowHandle)
    except Exception:
        script.get_logger().warning("Could not keep the export window in front.")
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


if __name__ == "__main__":
    main()
