# -*- coding: utf-8 -*-
"""Pure logic of the status window: progress parsing, row texts, the Analyzer plan, and the
JSON session protocol that crosses between pyRevit script engines.

No pyrevit, Autodesk, System or clr import, so CPython tests cover all of it; the WPF side is
rx_status_ui.py. Runs on IronPython 2.7. Spec: specs/SPEC-status-window.md.

Why JSON text: every button click may run in a new IronPython engine (`engine: clean: true`, a
pyRevit reload). Classes, exceptions and isinstance checks of one engine do not match another
engine's copy, so the session publishes one Func[String, String] in AppDomain data and only
text crosses (find_session / publish_session / SessionCore.handle).
"""
from __future__ import unicode_literals

import json
import os
import re

from rx_i18n import tr
from rx_runner import (CANCELLED, FAILED, OK, QUEUED, RUNNING, Job, LaunchSpec, RunnerError,
                       clean_path)

try:
    _TEXT_TYPES = (basestring,)  # IronPython 2.7
    _INTEGER_TYPES = (int, long)
except NameError:
    _TEXT_TYPES = (str,)
    _INTEGER_TYPES = (int,)

SESSION_KEY = "RevitExtractor.StatusSession"
PROTOCOL = 1
WEBSITE_URL = "https://kopecp.github.io/RevitExtractor/"  # D9, the launcher's URL
NODE_MIN_MAJOR = 24

_METRICS = "[[extractor-metrics]]:"
_PROGRESS = "[[progress]]:"
_PATH_FIELDS = ("model_path", "revit_dir", "output_parent")

# Static window text; rx_status.xaml refers to each key as {DynamicResource key}.
UI_TEXT = {
    "status_title": ("Revit Extractor — exports", "Revit Extractor — eksporty"),
    "status_header": ("Exports in this Revit session", "Eksporty w tej sesji Revita"),
    "status_col_model": ("Model", "Plik modelu"),
    "status_col_state": ("State", "Stan"),
    "status_col_progress": ("Progress / result", "Postęp / wynik"),
    "status_col_started": ("Started", "Start"),
    "status_col_time": ("Time", "Czas"),
    "status_cancel": ("Cancel export", "Anuluj eksport"),
    "status_cancel_tip": ("Stops the highlighted export. Its run folder stays as it is.",
                          "Zatrzymuje podświetlony eksport. Jego folder eksportu zostaje bez "
                          "zmian."),
    "status_open_folder": ("Open output folder", "Otwórz folder wyników"),
    "status_open_folder_tip": ("The output folder of a finished export, otherwise its run folder "
                               "with the logs.",
                               "Folder output zakończonego eksportu, w innym przypadku folder "
                               "eksportu z logami."),
    "status_open_analyzer": ("Open in Analyzer", "Otwórz w Analyzerze"),
    "status_open_analyzer_tip": ("Starts the local Analyzer with this export when Node.js is "
                                 "installed; otherwise opens the folder and the website.",
                                 "Uruchamia lokalny Analyzer z tym eksportem, jeśli jest "
                                 "zainstalowany Node.js; w innym przypadku otwiera folder i "
                                 "stronę internetową."),
    "status_close": ("Close", "Zamknij"),
    "status_close_tip": ("Exports keep running. While any is queued or running the window is "
                         "minimised, not closed.",
                         "Eksporty działają dalej. Dopóki któryś czeka lub trwa, okno jest "
                         "minimalizowane, a nie zamykane."),
}


def resources():
    """UI_TEXT in the current language, ready for Window.Resources."""
    return dict((key, tr(english, polish)) for key, (english, polish) in UI_TEXT.items())


def _error_text(error):
    if error.args:
        try:
            return "%s" % (error.args[0],)
        except Exception:
            pass
    return type(error).__name__


def _is_text(value):
    return isinstance(value, _TEXT_TYPES)


# --- progress -------------------------------------------------------------------------------

def _json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _percent(data):
    if not isinstance(data, dict):
        return None
    for value in data.values():
        if isinstance(value, bool):
            continue
        try:
            if _is_text(value):
                value = float(value.strip())
            number = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        return max(0, min(100, number))
    return None


def progress_info(console_tail):
    """{"task", "status", "percent"} from the end of console.log; each may be None.

    task/status: rvt-TaskName / rvt-Status of the last [[extractor-metrics]] rvt-TaskData line
    (the Extractor writes one when a step completes, in English). percent: the last
    [[progress]] value. A first line cut in half or broken JSON is skipped.
    """
    info = {"task": None, "status": None, "percent": None}
    if not _is_text(console_tail):
        return info
    for line in console_tail.splitlines():
        text = line.strip()
        if text.startswith(_METRICS):
            data = _json(text[len(_METRICS):])
            task = data.get("rvt-TaskData") if isinstance(data, dict) else None
            if not isinstance(task, dict):
                continue
            name = task.get("rvt-TaskName")
            if not _is_text(name) or not name.strip():
                continue
            status = task.get("rvt-Status")
            info["task"] = name.strip()
            info["status"] = status.strip() if _is_text(status) and status.strip() else None
        elif text.startswith(_PROGRESS):
            percent = _percent(_json(text[len(_PROGRESS):]))
            if percent is not None:
                info["percent"] = percent
    return info


# --- rows -----------------------------------------------------------------------------------

def _file_name(path):
    if not _is_text(path):
        return ""
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1]


def _clock_text(value):
    return value.strftime("%H:%M:%S") if hasattr(value, "strftime") else ""


def _duration(start, end):
    if not hasattr(start, "strftime") or not hasattr(end, "strftime"):
        return ""
    total = max(0, int((end - start).total_seconds()))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, seconds)
    return "%d:%02d" % (minutes, seconds)


def _running_text(info):
    info = info or {}
    parts = []
    task = info.get("task")
    if task:
        step = tr("Last step: {0}", "Ostatni krok: {0}").format(task)
        status = info.get("status")
        if status and status.lower() != "completed":
            step += " (" + status + ")"
        parts.append(step)
    if info.get("percent") is not None:
        parts.append("%d%%" % info["percent"])
    if not parts:
        return tr("Started; no step has finished yet.",
                  "Uruchomiony; żaden krok jeszcze się nie zakończył.")
    return " · ".join(parts)


def job_view(job, info, now, position, held=False):
    """Plain dict for one row: its texts, and which footer buttons apply.

    job: an rx_runner.Job. info: progress_info() of a running job, or None. position: 1-based
    place among queued jobs, or None. held: Queue.held (another Extractor is running).
    """
    state = job.state
    paths = job.paths
    message = job.result.message if job.result is not None else ""
    folder = output = None
    if paths is not None:
        folder = paths.output if state == OK else paths.root
        output = paths.output if state == OK else None
    if state == RUNNING:
        elapsed = _duration(job.started_at, now)
    elif state in (OK, FAILED, CANCELLED):
        elapsed = _duration(job.started_at, job.ended_at)
    else:
        elapsed = ""

    if state == QUEUED and held:
        state_text = tr("Waiting", "Oczekuje")
        progress = tr("Waiting: another Extractor is running on this computer.",
                      "Oczekuje: na tym komputerze działa inny Extractor.")
    elif state == QUEUED:
        state_text = tr("Queued", "W kolejce")
        progress = (tr("Position {0} in the queue.", "Pozycja w kolejce: {0}.").format(position)
                    if position else tr("Waiting in the queue.", "Czeka w kolejce."))
    elif state == RUNNING and job.cancel_requested:
        state_text = tr("Cancelling", "Anulowanie")
        progress = tr("Cancelling; the run folder stays.", "Anulowanie; folder eksportu zostaje.")
    elif state == RUNNING:
        state_text = tr("Running", "Trwa")
        progress = _running_text(info)
    elif state == OK:
        state_text = tr("Done", "Gotowe")
        progress = message
    elif state == FAILED:
        state_text = tr("Failed", "Błąd")
        progress = message
        # The runner's exit-code and failed-jobs messages already name console.log.
        if paths is not None and "console.log" not in progress:
            progress = (progress + " " if progress else "") + tr(
                "The logs are in the run folder.", "Logi są w folderze eksportu.")
    elif state == CANCELLED:
        state_text = tr("Cancelled", "Anulowany")
        progress = message
    else:
        state_text = "%s" % (state,)
        progress = message

    return {
        "id": job.id, "state": state, "model": _file_name(job.model_path),
        "model_path": job.model_path, "state_text": state_text, "progress": progress,
        "started": _clock_text(job.started_at), "time": elapsed,
        "can_cancel": state == QUEUED or (state == RUNNING and not job.cancel_requested),
        "can_open_folder": folder is not None,
        "can_open_analyzer": state == OK and output is not None,
        "folder": folder, "output": output,
    }


def summary(views):
    """One line over all rows, e.g. "Exports: 3 · running: 1 · queued: 2"."""
    if not views:
        return tr("No exports yet.", "Brak eksportów.")
    counts = {}
    for view in views:
        counts[view["state"]] = counts.get(view["state"], 0) + 1
    parts = [tr("Exports: {0}", "Eksporty: {0}").format(len(views))]
    for state, english, polish in ((RUNNING, "running: {0}", "w toku: {0}"),
                                   (QUEUED, "queued: {0}", "w kolejce: {0}"),
                                   (OK, "done: {0}", "gotowe: {0}"),
                                   (FAILED, "failed: {0}", "z błędem: {0}"),
                                   (CANCELLED, "cancelled: {0}", "anulowane: {0}")):
        if counts.get(state):
            parts.append(tr(english, polish).format(counts[state]))
    return " · ".join(parts)


def queue_hint(views):
    """D5: shown while any export waits in the queue."""
    if not any(view["state"] == QUEUED for view in views):
        return ""
    return tr("Queued exports start only while Revit is open. If Revit closes, the running "
              "export finishes and the queued ones are dropped.",
              "Eksporty z kolejki startują tylko przy otwartym Revicie. Jeśli Revit zostanie "
              "zamknięty, trwający eksport się dokończy, a oczekujące zostaną pominięte.")


# --- Open in Analyzer -----------------------------------------------------------------------

def _env(environ, name):
    """Case-insensitive lookup: Windows names PATH "Path", IronPython keeps the case."""
    try:
        value = environ.get(name)
        if value is None:
            for key in environ.keys():
                if key.upper() == name.upper():
                    value = environ[key]
                    break
    except Exception:
        return None
    return value if _is_text(value) and value.strip() else None


def _exists(exists, path):
    try:
        return bool(exists(path))
    except Exception:
        return False


def _find_node(environ, exists):
    """First node.exe on PATH, else %ProgramFiles%\\nodejs\\node.exe, else None."""
    for entry in (_env(environ, "PATH") or "").split(os.pathsep):
        entry = entry.strip().strip('"').strip()
        if entry:
            candidate = os.path.join(entry, "node.exe")
            if _exists(exists, candidate):
                return candidate
    program_files = _env(environ, "ProgramFiles")
    if program_files:
        candidate = os.path.join(program_files.strip().strip('"'), "nodejs", "node.exe")
        if _exists(exists, candidate):
            return candidate
    return None


def analyzer_dir(lib_dir):
    """<clone>\\Analyzer: lib -> Extractor.extension -> pyRevit -> clone."""
    clone = os.path.dirname(os.path.dirname(os.path.dirname(os.path.normpath(lib_dir))))
    return os.path.join(clone, "Analyzer")


def analyzer_plan(output, lib_dir, environ, exists, node_major, free_port):
    """("local", LaunchSpec, url) when Node 24+, server.mjs and its packages are found;
    otherwise ("web", reason). Starts nothing and never runs npm.

    node_major(path) -> int read from the file version; free_port() -> int. Both may raise.
    """
    reasons = []
    try:
        output_path = clean_path(output)
    except RunnerError as error:
        output_path = None
        reasons.append(tr("The export folder cannot be passed to the Analyzer: {0}",
                          "Folderu eksportu nie można przekazać do Analyzera: {0}")
                       .format(_error_text(error)))

    node = _find_node(environ, exists)
    if node is None:
        reasons.append(tr("Node.js was not found (node.exe on PATH or in Program Files\\nodejs). "
                          "The local Analyzer needs Node.js {0} or later.",
                          "Nie znaleziono Node.js (node.exe w PATH lub w Program Files\\nodejs). "
                          "Lokalny Analyzer wymaga Node.js {0} lub nowszego.")
                       .format(NODE_MIN_MAJOR))
    else:
        try:
            node = clean_path(node)
            try:
                major = node_major(node)
            except Exception:
                major = None
            if isinstance(major, bool) or not isinstance(major, _INTEGER_TYPES):
                reasons.append(tr("The Node.js version of {0} cannot be read.",
                                  "Nie można odczytać wersji Node.js z {0}.").format(node))
            elif major < NODE_MIN_MAJOR:
                reasons.append(tr("Node.js {0} or later is needed; {1} is version {2}.",
                                  "Wymagany jest Node.js {0} lub nowszy; {1} ma wersję {2}.")
                               .format(NODE_MIN_MAJOR, node, major))
        except RunnerError as error:
            reasons.append(tr("Node.js cannot be started from {0}",
                              "Nie można uruchomić Node.js z: {0}").format(_error_text(error)))

    analyzer = analyzer_dir(lib_dir)
    server = os.path.join(analyzer, "server.mjs")
    packages = os.path.join(analyzer, "node_modules", "pdfjs-dist", "build", "pdf.mjs")
    if not _exists(exists, server):
        reasons.append(tr("The Analyzer was not found: {0}",
                          "Nie znaleziono Analyzera: {0}").format(server))
    elif not _exists(exists, packages):
        reasons.append(tr("The Analyzer's packages are not installed. Run npm ci in {0} once "
                          "(or start Start-Analyzer.cmd there).",
                          "Pakiety Analyzera nie są zainstalowane. Uruchom raz npm ci w {0} "
                          "(albo Start-Analyzer.cmd w tym folderze).").format(analyzer))
    else:
        try:
            analyzer = clean_path(analyzer)
        except RunnerError as error:
            reasons.append(_error_text(error))

    if not reasons:
        try:
            port = free_port()
        except Exception:
            port = None
        if (isinstance(port, bool) or not isinstance(port, _INTEGER_TYPES)
                or not 0 < port < 65536):
            reasons.append(tr("No free local port was found for the Analyzer.",
                              "Nie znaleziono wolnego portu lokalnego dla Analyzera."))
    if reasons:
        return ("web", " ".join(reasons))
    port = int(port)
    spec = LaunchSpec(file=node,
                      arguments='server.mjs --output "%s" --port %d --open' % (output_path, port),
                      working_dir=analyzer, env={})
    return ("local", spec, "http://127.0.0.1:%d/" % port)


# --- session protocol -----------------------------------------------------------------------

def _time_text(value):
    return value.isoformat() if hasattr(value, "isoformat") else None


class _RequestError(ValueError):
    pass


def _job_from(data):
    if not isinstance(data, dict):
        raise _RequestError(tr("The export is not a JSON object.",
                               "Eksport nie jest obiektem JSON."))
    bad = [name for name in _PATH_FIELDS[:1] if not _is_text(data.get(name))]
    if not isinstance(data.get("index"), dict):
        bad.append("index")
    bad.extend(name for name in _PATH_FIELDS[1:] if not _is_text(data.get(name)))
    if bad:
        raise _RequestError(tr("Missing or invalid field: {0}",
                               "Brak pola lub nieprawidłowe pole: {0}").format(", ".join(bad)))
    return Job(data["model_path"], data["index"], data["revit_dir"], data["output_parent"])


class SessionCore(object):
    """The session's request handler; the only thing other engines call (as JSON text).

    ops: {"op": "ping"} -> {"ok", "protocol", "busy", "jobs", "since"};
         {"op": "submit", "jobs": [{"model_path", "index", "revit_dir", "output_parent"}]}
            -> {"ok", "added", "errors"};
         {"op": "show"} -> {"ok"}.
    listener (optional): on_submit(ids) and on_show(), the window side. handle() never raises.
    """

    def __init__(self, queue, clock, listener=None):
        self._queue = queue
        self._listener = listener
        try:
            self._since = _time_text(clock())
        except Exception:
            self._since = None

    def handle(self, request_json):
        try:
            answer = self._dispatch(request_json)
        except Exception as error:
            answer = {"ok": False, "error": _error_text(error)}
        try:
            return json.dumps(answer, ensure_ascii=True, sort_keys=True)
        except Exception:
            return '{"error": "The answer could not be written as JSON.", "ok": false}'

    def _dispatch(self, request_json):
        if not _is_text(request_json):
            raise _RequestError(tr("The request must be JSON text.",
                                   "Żądanie musi być tekstem JSON."))
        request = _json(request_json)
        if not isinstance(request, dict):
            raise _RequestError(tr("The request is not a valid JSON object.",
                                   "Żądanie nie jest poprawnym obiektem JSON."))
        op = request.get("op")
        if op == "ping":
            return {"ok": True, "protocol": PROTOCOL, "busy": bool(self._queue.busy()),
                    "jobs": len(self._queue.jobs()), "since": self._since}
        if op == "submit":
            return self._submit(request.get("jobs"))
        if op == "show":
            if self._listener is not None:
                self._listener.on_show()
            return {"ok": True}
        raise _RequestError(tr("Unknown operation: {0}", "Nieznana operacja: {0}")
                            .format(json.dumps(op)))

    def _submit(self, jobs):
        if not isinstance(jobs, list) or not jobs:
            raise _RequestError(tr("Nothing to export: the request has no jobs.",
                                   "Nie ma czego eksportować: żądanie nie zawiera zadań."))
        added = []
        errors = []
        for number, data in enumerate(jobs, 1):
            try:
                added.append(self._queue.add(_job_from(data)))
            except Exception as error:  # one bad job; the others are still added
                errors.append(tr("Export {0}: {1}", "Eksport {0}: {1}")
                              .format(number, _error_text(error)))
        if added and self._listener is not None:
            try:
                self._listener.on_submit(list(added))
            except Exception as error:
                errors.append(tr("The status window failed: {0}",
                                 "Błąd okna statusu: {0}").format(_error_text(error)))
        return {"ok": True, "added": added, "errors": errors}


def find_session(domain):
    """The published handler, or None when absent, not callable, raising or of another
    PROTOCOL. A None here means: publish a new session (the old one keeps its own jobs)."""
    try:
        handler = domain.GetData(SESSION_KEY)
        if handler is None:
            return None
        answer = json.loads(handler(json.dumps({"op": "ping"})))
    except Exception:
        return None
    if (isinstance(answer, dict) and answer.get("ok") is True
            and not isinstance(answer.get("protocol"), bool)
            and answer.get("protocol") == PROTOCOL):
        return handler
    return None


def publish_session(domain, handler):
    """AppDomain.CurrentDomain.SetData(SESSION_KEY, handler); handler is a Func[String, String]
    in Revit (wrapped by rx_status_ui), any callable in tests."""
    domain.SetData(SESSION_KEY, handler)
