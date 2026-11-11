# -*- coding: utf-8 -*-
"""Run RevitExtractor.exe as its own process, in a queue, the way Start-RevitExport.ps1 does.

Pure Python except DotNetStarter, the only code that touches .NET (System.Diagnostics, imported
inside its methods). Runs on IronPython 2.7; the tests run on CPython 3. No threads and no
process events: the caller polls Queue.poll() from a WPF DispatcherTimer.
Spec: specs/SPEC-export-runner.md.

Safety rules kept here:
- every run gets a new folder; an existing one is never reused, cleaned or deleted;
- no path text is ever parsed by cmd.exe: paths travel in environment variables;
- only a process this queue started, and that has not exited, is ever killed;
- after the process exits, the run folder is only read.
"""
from __future__ import unicode_literals

import os
import re
import uuid
from collections import namedtuple

from rx_i18n import tr
from rx_index import SetupError, require_index_shape, to_json

try:
    _INTEGER_TYPES = (int, long)  # IronPython 2.7 / CPython 2
    _TEXT_TYPES = (basestring,)
except NameError:
    _INTEGER_TYPES = (int,)
    _TEXT_TYPES = (str,)

# True only with the owner's evidence from a parallel run on the Revit 2022 machine (Q28).
# A pass of run_extractor_integration.ps1 -Parallel 2 on another build is not enough.
PARALLEL_VERIFIED = False
MAX_PARALLEL = 4

QUEUED = "queued"
RUNNING = "running"
OK = "ok"
FAILED = "failed"
CANCELLED = "cancelled"

KILL_TIMEOUT_MS = 60000

# Constant command text: cmd.exe only ever sees variable references, never path text. Inside
# double quotes, & ^ | < > are literal; /v:off keeps ! literal; %-expansion is a single pass, so a
# value containing %TEMP% is not expanded again. Quotes in values are refused (launch_spec).
_CMD_ARGUMENTS = (
    '/d /v:off /s /c ""%RX_EXE%" "%RX_INDEX%" "%RX_MODEL%" -RCEPath "%RX_REVIT%" '
    '-LogPath "%RX_LOGS%" -journalPath "%RX_JOURNALS%" 1>"%RX_CONSOLE%" 2>"%RX_STDERR%""')

_SUMMARY_RE = re.compile(r"Success Jobs:\s*(\d+), Failed Jobs:\s*(\d+)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"^[0-9a-f]{8}\Z")
_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{2}[^\\/])")
_NOISE = ("mesh number larger than 64k", "dsm_internalerrormessage")
_PROGRESS_TAIL_BYTES = 65536

RunPaths = namedtuple(str("RunPaths"), str("root index output logs journals console stderr"))
LaunchSpec = namedtuple(str("LaunchSpec"), str("file arguments working_dir env"))
Result = namedtuple(str("Result"), str("state success_jobs failed_jobs message"))


class RunnerError(ValueError):
    """A run cannot be planned, prepared, started or cancelled. The message is translated."""


def _error_text(error):
    if error.args:
        try:
            return "%s" % (error.args[0],)
        except Exception:
            pass
    return type(error).__name__


def _shown(value):
    return value.replace("\r", "\\r").replace("\n", "\\n")


def _is_absolute(value):
    if os.sep == "\\":
        return bool(_ABSOLUTE_RE.match(value))
    return os.path.isabs(value)


def clean_path(value):
    """The path as it may reach the Extractor command line, or RunnerError (fail closed)."""
    if not isinstance(value, _TEXT_TYPES) or not value.strip():
        raise RunnerError(tr("A required path is missing.", "Brakuje wymaganej ścieżki."))
    for char in ('"', "\r", "\n"):
        if char in value:
            raise RunnerError(tr(
                "The path contains a quote or a line break, which the Extractor command line "
                "cannot carry: {0}",
                "Ścieżka zawiera cudzysłów lub znak nowej linii, których wiersz poleceń "
                "Extractora nie przeniesie: {0}").format(_shown(value)))
    if not _is_absolute(value):
        raise RunnerError(tr("The path must be absolute: {0}",
                             "Ścieżka musi być bezwzględna: {0}").format(value))
    # As the launcher: a trailing backslash would escape the closing quote of the argument.
    trimmed = value.rstrip("\\") if os.sep == "\\" else value.rstrip("/") or value
    if not trimmed or trimmed.endswith(":"):
        raise RunnerError(tr("A drive root cannot be used here: {0}",
                             "Nie można tu użyć katalogu głównego dysku: {0}").format(value))
    return trimmed


# --- run folder -----------------------------------------------------------------------------

def default_output_parent(documents_dir):
    """<Documents>\\RevitExtractor, as the launcher."""
    if not isinstance(documents_dir, _TEXT_TYPES) or not documents_dir.strip():
        raise RunnerError(tr("The Documents folder is unknown.",
                             "Nie znaleziono folderu Dokumenty."))
    return os.path.join(documents_dir, "RevitExtractor")


def new_token():
    """8 random hex characters, as the launcher's GUID slice."""
    return uuid.uuid4().hex[:8]


def plan_run(output_parent, now, token):
    """Paths of a new run folder; touches nothing on disk."""
    parent = clean_path(output_parent)
    if not isinstance(token, _TEXT_TYPES) or not _TOKEN_RE.match(token):
        raise RunnerError(tr("Invalid run folder id: {0}",
                             "Nieprawidłowy identyfikator folderu eksportu: {0}")
                          .format(_shown("%s" % (token,))))
    if not hasattr(now, "strftime"):
        raise RunnerError(tr("Invalid run time.", "Nieprawidłowy czas uruchomienia."))
    root = os.path.join(parent, "export-" + now.strftime("%Y%m%d-%H%M%S") + "-" + token)
    return RunPaths(root=root, index=os.path.join(root, "index.json"),
                    output=os.path.join(root, "output"), logs=os.path.join(root, "logs"),
                    journals=os.path.join(root, "journals"),
                    console=os.path.join(root, "console.log"),
                    stderr=os.path.join(root, "stderr.log"))


def prepare_run(paths, index):
    """Create the run folder, output/logs/journals and index.json (UTF-8, no BOM).

    Refuses an existing root: the Extractor empties <index folder>\\output first, so reusing a
    folder would destroy an earlier export.
    """
    try:
        require_index_shape(index)
        data = to_json(index).encode("utf-8")
    except (SetupError, TypeError, ValueError) as error:
        raise RunnerError(_error_text(error))
    if os.path.lexists(paths.root):
        raise RunnerError(tr("The run folder already exists and is never reused: {0}",
                             "Folder eksportu już istnieje i nigdy nie jest używany ponownie: {0}")
                          .format(paths.root))
    parent = os.path.dirname(paths.root)
    try:
        if not os.path.isdir(parent):
            os.makedirs(parent)
        os.mkdir(paths.root)  # fails if the folder appeared in the meantime
    except OSError as error:
        raise RunnerError(tr("Cannot create the run folder {0}: {1}",
                             "Nie można utworzyć folderu eksportu {0}: {1}")
                          .format(paths.root, _error_text(error)))
    try:
        for folder in (paths.output, paths.logs, paths.journals):
            os.mkdir(folder)
        with open(paths.index, "wb") as handle:
            handle.write(data)
    except (IOError, OSError) as error:
        raise RunnerError(tr("Cannot prepare the run folder {0}: {1}",
                             "Nie można przygotować folderu eksportu {0}: {1}")
                          .format(paths.root, _error_text(error)))
    return paths


def extractor_exe(revit_dir, exists=os.path.isfile):
    """<revit_dir>\\RevitExtractor\\RevitExtractor.exe, or RunnerError when it is missing."""
    exe = os.path.join(clean_path(revit_dir), "RevitExtractor", "RevitExtractor.exe")
    if not exists(exe):
        raise RunnerError(tr("RevitExtractor.exe was not found: {0}",
                             "Nie znaleziono RevitExtractor.exe: {0}").format(exe))
    return exe


def default_system_root(environ=None):
    environ = os.environ if environ is None else environ
    for name in ("SystemRoot", "SYSTEMROOT", "windir", "WINDIR"):
        value = environ.get(name)
        if value:
            return value
    raise RunnerError(tr("The Windows folder (SystemRoot) is unknown.",
                         "Nie znaleziono folderu Windows (SystemRoot)."))


# --- process specs --------------------------------------------------------------------------

def launch_spec(exe, revit_dir, model_path, paths, system_root):
    """cmd.exe with a constant command text; every path travels in an RX_* variable.

    cmd.exe does the redirection, so console.log stays complete if Revit closes (Q24). The
    Extractor's arguments match the launcher: index, model, -RCEPath, -LogPath, -journalPath.
    """
    env = {}
    for name, value in (("RX_EXE", exe), ("RX_INDEX", paths.index), ("RX_MODEL", model_path),
                        ("RX_REVIT", revit_dir), ("RX_LOGS", paths.logs),
                        ("RX_JOURNALS", paths.journals), ("RX_CONSOLE", paths.console),
                        ("RX_STDERR", paths.stderr)):
        env[name] = clean_path(value)
    root = clean_path(system_root)
    return LaunchSpec(file=os.path.join(root, "System32", "cmd.exe"), arguments=_CMD_ARGUMENTS,
                      working_dir=env["RX_REVIT"], env=env)


def kill_spec(pid, system_root):
    """taskkill.exe /PID <pid> /T /F: ends cmd.exe, RevitExtractor.exe and its client."""
    if isinstance(pid, bool) or not isinstance(pid, _INTEGER_TYPES) or pid <= 0:
        raise RunnerError(tr("Invalid process id: {0}",
                             "Nieprawidłowy identyfikator procesu: {0}")
                          .format(_shown("%s" % (pid,))))
    root = clean_path(system_root)
    system32 = os.path.join(root, "System32")
    return LaunchSpec(file=os.path.join(system32, "taskkill.exe"),
                      arguments="/PID %d /T /F" % int(pid), working_dir=system32, env={})


# --- result ---------------------------------------------------------------------------------

def check_result(exit_code, console_text, has_bubble, has_resource):
    """The launcher's success check, in its order: exit code, failed jobs, output structure."""
    matches = _SUMMARY_RE.findall(console_text or "")
    success_jobs = failed_jobs = None
    if matches:
        success_jobs, failed_jobs = int(matches[-1][0]), int(matches[-1][1])
    if isinstance(exit_code, bool) or not isinstance(exit_code, _INTEGER_TYPES) or exit_code != 0:
        return Result(FAILED, success_jobs, failed_jobs, tr(
            "The Extractor ended with exit code {0}. Check console.log, stderr.log, logs and "
            "journals in the run folder.",
            "Extractor zakończył się kodem {0}. Sprawdź console.log, stderr.log, logs i journals "
            "w folderze eksportu.").format(exit_code))
    if failed_jobs:
        return Result(FAILED, success_jobs, failed_jobs, tr(
            "{0} export job(s) failed. Check console.log and logs in the run folder.",
            "Nie powiodło się zadań eksportu: {0}. Sprawdź console.log i logs w folderze "
            "eksportu.").format(failed_jobs))
    if not has_bubble or not has_resource:
        return Result(FAILED, success_jobs, failed_jobs, tr(
            "The export is incomplete: output\\bubble.json or output\\Resource is missing.",
            "Eksport jest niekompletny: brakuje output\\bubble.json lub output\\Resource."))
    if success_jobs is None:
        return Result(OK, None, None, tr(
            "Export finished. console.log has no 'Success Jobs' line, so the job count is "
            "unknown.",
            "Eksport zakończony. W console.log brakuje wiersza 'Success Jobs', więc liczba "
            "zadań jest nieznana."))
    return Result(OK, success_jobs, failed_jobs, tr(
        "Export finished: {0} job(s) succeeded.",
        "Eksport zakończony: zadania udane: {0}.").format(success_jobs))


def progress_line(console_tail):
    """The last non-blank line that is not known noise, or ""."""
    for line in reversed((console_tail or "").splitlines()):
        text = line.strip()
        if text and not any(noise in text.lower() for noise in _NOISE):
            return text
    return ""


def effective_parallel(setting):
    """1 until PARALLEL_VERIFIED (Q28); then the setting clamped to 1..MAX_PARALLEL."""
    if not PARALLEL_VERIFIED:
        return 1
    if isinstance(setting, bool):
        return 1
    if isinstance(setting, _INTEGER_TYPES):
        value = int(setting)
    elif isinstance(setting, _TEXT_TYPES) and setting.strip().isdigit():
        value = int(setting.strip())
    else:
        return 1
    return max(1, min(MAX_PARALLEL, value))


def _read_text(path, tail_bytes=None):
    """Read-only; "" when the file is missing or locked."""
    try:
        with open(path, "rb") as handle:
            if tail_bytes:
                handle.seek(0, 2)
                handle.seek(max(0, handle.tell() - tail_bytes))
            data = handle.read()
    except (IOError, OSError):
        return ""
    return data.decode("utf-8", "replace")


# --- queue ----------------------------------------------------------------------------------

def _model_key(path):
    return os.path.normcase(os.path.normpath(path))


def _time_text(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


class Job(object):
    """Plain record of one export. States: queued -> running -> ok | failed | cancelled."""

    def __init__(self, model_path, index, revit_dir, output_parent):
        self.id = None
        self.model_path = model_path
        self.index = index
        self.revit_dir = revit_dir
        self.output_parent = output_parent
        self.state = QUEUED
        self.paths = None
        self.pid = None
        self.queued_at = None
        self.started_at = None
        self.ended_at = None
        self.exit_code = None
        self.result = None
        self.cancel_requested = False
        self.kill_exit_code = None

    def as_dict(self):
        return {
            "id": self.id, "model_path": self.model_path, "index": self.index,
            "revit_dir": self.revit_dir, "output_parent": self.output_parent,
            "state": self.state,
            "paths": dict(self.paths._asdict()) if self.paths else None,
            "pid": self.pid, "queued_at": _time_text(self.queued_at),
            "started_at": _time_text(self.started_at), "ended_at": _time_text(self.ended_at),
            "exit_code": self.exit_code,
            "result": dict(self.result._asdict()) if self.result else None,
            "cancel_requested": self.cancel_requested, "kill_exit_code": self.kill_exit_code,
        }


class Queue(object):
    """FIFO export queue owned by its caller. `starter` has start(spec) -> handle with pid,
    has_exited(), exit_code(), close(); and run(spec) -> exit code. `clock()` returns a datetime.
    Pass effective_parallel(setting) as max_parallel.

    `hold()` (optional): while no job of this queue runs and it returns true, queued jobs wait
    and `held` is True. A hold that raises counts as false. The status window passes
    DotNetStarter.extractor_running, so a RevitExtractor.exe this queue did not start (another
    session, the .ps1 launcher, a second Revit) keeps the fixed pipe free.
    """

    def __init__(self, starter, clock, max_parallel=1, system_root=None, token=None, hold=None):
        if (isinstance(max_parallel, bool) or not isinstance(max_parallel, _INTEGER_TYPES)
                or max_parallel < 1):
            raise RunnerError(tr("Invalid number of parallel exports: {0}",
                                 "Nieprawidłowa liczba równoległych eksportów: {0}")
                              .format(max_parallel))
        self._starter = starter
        self._clock = clock
        self._max = int(max_parallel)
        self._system_root = system_root
        self._token = token or new_token
        self._hold = hold
        self.held = False
        self._jobs = []
        self._handles = {}
        self._counter = 0

    def _root(self):
        if self._system_root is None:
            self._system_root = default_system_root()
        return self._system_root

    def add(self, job):
        """Validate and queue; nothing is created on disk yet. Returns the job id."""
        if job.id is not None:
            raise RunnerError(tr("This export is already in the queue.",
                                 "Ten eksport jest już w kolejce."))
        for value in (job.model_path, job.revit_dir, job.output_parent):
            clean_path(value)
        try:
            require_index_shape(job.index)
        except SetupError as error:
            raise RunnerError(_error_text(error))
        self._counter += 1
        job.id = "job-%d" % self._counter
        job.state = QUEUED
        job.queued_at = self._clock()
        self._jobs.append(job)
        return job.id

    def jobs(self):
        return list(self._jobs)

    def busy(self):
        return any(job.state in (QUEUED, RUNNING) for job in self._jobs)

    def _find(self, job_id):
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None

    def poll(self):
        """Finish exited jobs, then start queued ones up to the limit. Returns changed ids."""
        changed = []
        for job in self._jobs:
            if job.state == RUNNING and self._finish_if_exited(job):
                changed.append(job.id)
        self.held = self._is_held()
        if self.held:
            return changed
        for job in self._jobs:
            if self._running_count() >= self._max:
                break
            if job.state != QUEUED or self._model_running(job.model_path):
                continue
            self._start(job)
            changed.append(job.id)
        return changed

    def _is_held(self):
        """Asked only when a job waits and none of ours runs (our own Extractor would count)."""
        if self._hold is None or self._running_count():
            return False
        if not any(job.state == QUEUED for job in self._jobs):
            return False
        try:
            return bool(self._hold())
        except Exception:  # fail open: a broken check must not stall the queue for ever
            return False

    def _running_count(self):
        return len([job for job in self._jobs if job.state == RUNNING])

    def _model_running(self, model_path):
        key = _model_key(model_path)
        return any(job.state == RUNNING and _model_key(job.model_path) == key
                   for job in self._jobs)

    def _start(self, job):
        job.started_at = self._clock()
        try:
            exe = extractor_exe(job.revit_dir)
            paths = plan_run(job.output_parent, job.started_at, self._token())
            spec = launch_spec(exe, job.revit_dir, job.model_path, paths, self._root())
            prepare_run(paths, job.index)
            job.paths = paths
            handle = self._starter.start(spec)
        except Exception as error:  # one job fails, the queue goes on
            job.state = FAILED
            job.ended_at = self._clock()
            job.result = Result(FAILED, None, None, tr(
                "The export could not start: {0}",
                "Nie udało się uruchomić eksportu: {0}").format(_error_text(error)))
            return
        job.pid = handle.pid
        self._handles[job.id] = handle
        job.state = RUNNING

    def _finish_if_exited(self, job):
        handle = self._handles[job.id]
        if not handle.has_exited():
            return False
        job.exit_code = handle.exit_code()
        job.ended_at = self._clock()
        output = job.paths.output
        result = check_result(job.exit_code, _read_text(job.paths.console),
                              os.path.isfile(os.path.join(output, "bubble.json")),
                              os.path.isdir(os.path.join(output, "Resource")))
        if job.cancel_requested:
            job.state = CANCELLED
            job.result = Result(CANCELLED, result.success_jobs, result.failed_jobs,
                                tr("Export cancelled.", "Eksport anulowany."))
        else:
            job.state = result.state
            job.result = result
        del self._handles[job.id]
        try:
            handle.close()
        except Exception:
            pass
        return True

    def cancel(self, job_id):
        """Queued: never starts. Running: kill the tree once. Returns True if it acted."""
        job = self._find(job_id)
        if job is None:
            return False
        if job.state == QUEUED:
            job.state = CANCELLED
            job.ended_at = self._clock()
            job.result = Result(CANCELLED, None, None,
                                tr("Export cancelled before it started.",
                                   "Eksport anulowany przed uruchomieniem."))
            return True
        if job.state != RUNNING or job.cancel_requested:
            return False
        handle = self._handles[job.id]
        # The open handle keeps the pid from being reused; an exited process is never killed.
        if handle.has_exited():
            return False
        try:
            code = self._starter.run(kill_spec(job.pid, self._root()))
        except Exception:
            return False
        job.kill_exit_code = code
        if code != 0:
            return False
        job.cancel_requested = True
        return True

    def tail(self, job_id):
        """The end of a started job's console.log as text (read-only), or ""."""
        job = self._find(job_id)
        if job is None or job.paths is None:
            return ""
        return _read_text(job.paths.console, _PROGRESS_TAIL_BYTES)

    def progress(self, job_id):
        """Last meaningful console line of a started job (read-only), or ""."""
        return progress_line(self.tail(job_id))


# --- .NET -----------------------------------------------------------------------------------

class _DotNetHandle(object):
    def __init__(self, process):
        self._process = process
        self.pid = process.Id

    def has_exited(self):
        return bool(self._process.HasExited)

    def exit_code(self):
        if not self._process.HasExited:
            return None
        return int(self._process.ExitCode)

    def wait(self, milliseconds):
        return bool(self._process.WaitForExit(milliseconds))

    def close(self):
        self._process.Dispose()


class DotNetStarter(object):
    """Starts a LaunchSpec with System.Diagnostics.Process. No redirection, no events."""

    def start(self, spec, show_window=False):
        """show_window=True gives a console program its own visible window (the Analyzer)."""
        from System.Diagnostics import Process, ProcessStartInfo
        info = ProcessStartInfo()
        info.FileName = spec.file
        info.Arguments = spec.arguments
        info.WorkingDirectory = spec.working_dir
        info.UseShellExecute = False
        info.CreateNoWindow = not show_window
        info.RedirectStandardInput = False
        info.RedirectStandardOutput = False
        info.RedirectStandardError = False
        variables = info.EnvironmentVariables  # starts as a copy of this process's variables
        for name in sorted(spec.env):
            variables[name] = spec.env[name]
        process = Process.Start(info)
        if process is None:
            raise RunnerError(tr("The process did not start: {0}",
                                 "Proces nie został uruchomiony: {0}").format(spec.file))
        return _DotNetHandle(process)

    def run(self, spec, timeout_ms=KILL_TIMEOUT_MS):
        """Start, wait up to timeout_ms, return the exit code (used for taskkill)."""
        handle = self.start(spec)
        try:
            if not handle.wait(timeout_ms):
                raise RunnerError(tr("{0} did not finish in time.",
                                     "{0} nie zakończył się w wyznaczonym czasie.")
                                  .format(spec.file))
            return handle.exit_code()
        finally:
            handle.close()

    def extractor_running(self):
        """True while any RevitExtractor.exe runs on this computer. Only lists; never ends one."""
        from System.Diagnostics import Process
        processes = Process.GetProcessesByName("RevitExtractor")
        running = False
        for process in processes:
            running = True
            try:
                process.Dispose()
            except Exception:
                pass
        return running
