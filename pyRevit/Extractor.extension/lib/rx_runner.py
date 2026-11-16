# -*- coding: utf-8 -*-
"""Run RevitExtractor.exe as its own process, in a queue, the way Start-RevitExport.ps1 does.

Pure Python except DotNetStarter, the only code that touches .NET (System.Diagnostics, imported
inside its methods). Runs on IronPython 2.7; the tests run on CPython 3. No threads and no
process events: the caller polls Queue.poll() from a WPF DispatcherTimer.
Spec: specs/SPEC-export-runner.md.

Safety rules kept here:
- every run gets a new folder; an existing one is never reused or cleaned;
- no path text is ever parsed by cmd.exe: paths travel in environment variables;
- only a process this queue started, and that has not exited, is ever killed;
- after the process exits, the run folder is only read, with one exception (cloud jobs,
  specs/SPEC-cloud-catalog.md): the copies this job staged into <run>\\model are deleted once
  the process tree has exited; model\\stage.json and everything else stay. Nothing under
  Revit's CollaborationCache is ever written or deleted (rx_cloud_stage opens sources "rb").
"""
from __future__ import unicode_literals

import datetime
import os
import re
import time
import uuid
from collections import namedtuple

import rx_dotnet
from rx_cloud import safe_file_name
from rx_cloud_stage import check_space, copy_steps
from rx_cloud_stage import _in_cache, _items as _stage_items
from rx_i18n import tr
from rx_index import SetupError, require_index_shape, to_json
from rx_json import dumps_ascii

rx_dotnet.ensure_assemblies()   # .NET 8 (Revit 2025+): Process lives in its own assembly

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
STAGING = "staging"     # cloud jobs only: copying from the cache, no process yet
RUNNING = "running"
OK = "ok"
FAILED = "failed"
CANCELLED = "cancelled"

KILL_TIMEOUT_MS = 60000

# Staging (cloud jobs). poll() copies for at most STAGE_BUDGET seconds (checked after each
# chunk, so one chunk may run over). 1 MiB keeps a chunk well under the budget on a local disk.
STAGE_BUDGET = 0.04
STAGE_CHUNK = 2 ** 20
STAGE_FOLDER = "model"
STAGE_RECORD = "stage.json"
CLEANUP_SECONDS = 600   # give up deleting staged copies that stay locked this long
_MAX_KEY = 512
_DEFAULT_STAGE_CLOCK = (getattr(time, "perf_counter", None) or getattr(time, "clock", None)
                        or time.time)   # CPython 3 / IronPython 2.7 (high resolution) / last resort

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


def _job_key(job):
    """Same-model key: Job.model_key when given (a cloud row's key), else the model path."""
    if job.model_key is not None:
        return job.model_key.strip().lower()
    return _model_key(job.model_path)


def _time_text(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _bad_stage(detail):
    return RunnerError(tr("The copy plan is not valid: {0}",
                          "Plan kopiowania jest nieprawidłowy: {0}").format(detail))


def _is_number(value):
    return (not isinstance(value, bool)
            and (isinstance(value, _INTEGER_TYPES) or isinstance(value, float)))


def _checked_stage(job):
    """Job.stage as a fresh plain dict {"items": [{src, name, size, mtime}], "notes": [text]},
    or RunnerError (fail closed). Every src goes through clean_path; every name is one plain
    file name ending in .rvt, unique without regard to case; the host comes first and is the
    job's model_path and model_name."""
    stage = job.stage
    if not isinstance(stage, dict):
        raise _bad_stage("stage")
    raw = stage.get("items")
    if not isinstance(raw, list) or not raw:
        raise _bad_stage("items")
    items = []
    seen = set()
    for number, entry in enumerate(raw, 1):
        if not isinstance(entry, dict):
            raise _bad_stage("items[%d]" % number)
        src, name = entry.get("src"), entry.get("name")
        size, mtime = entry.get("size"), entry.get("mtime")
        src = clean_path(src)
        if (not isinstance(name, _TEXT_TYPES) or not safe_file_name(name)
                or not name.lower().endswith(".rvt")):
            raise _bad_stage("items[%d].name" % number)
        if name.lower() in seen:
            raise _bad_stage("items[%d].name" % number)
        seen.add(name.lower())
        if not _is_number(size) or size < 0 or not _is_number(mtime):
            raise _bad_stage("items[%d]" % number)
        items.append({"src": src, "name": name, "size": size, "mtime": mtime})
    notes = stage.get("notes", [])
    if notes is None:
        notes = []
    if not isinstance(notes, list) or not all(isinstance(n, _TEXT_TYPES) for n in notes):
        raise _bad_stage("notes")
    if not isinstance(job.model_name, _TEXT_TYPES) or job.model_name != items[0]["name"]:
        raise _bad_stage("model_name")
    if _model_key(job.model_path) != _model_key(items[0]["src"]):
        raise _bad_stage("model_path")
    return {"items": items, "notes": list(notes)}


def _cache_date(mtime):
    try:
        return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _write_stage_record(folder, job):
    """model\\stage.json: names (as given), sizes and cache dates; no source path."""
    record = {"version": 1, "model_name": job.model_name, "notes": job.stage["notes"],
              "items": [{"name": item["name"], "size": item["size"],
                         "cache_date": _cache_date(item["mtime"])}
                        for item in job.stage["items"]]}
    data = dumps_ascii(record, indent=2, sort_keys=True).encode("ascii")
    with open(os.path.join(folder, STAGE_RECORD), "wb") as handle:
        handle.write(data)


class Job(object):
    """Plain record of one export. States: queued -> running -> ok | failed | cancelled.

    A cloud job also has `stage` (plain dicts {"items": [{src, name, size, mtime}], "notes"},
    host first, as rx_cloud.plan_stage gives it), `model_name` (the host's staged file name) and
    `model_key` (rx_cloud's row key). It goes queued -> staging -> running: the items are copied
    into <run>\\model and the Extractor opens <run>\\model\\<model_name>.
    """

    def __init__(self, model_path, index, revit_dir, output_parent, stage=None,
                 model_name=None, model_key=None):
        self.id = None
        self.model_path = model_path
        self.index = index
        self.revit_dir = revit_dir
        self.output_parent = output_parent
        self.stage = stage
        self.model_name = model_name
        self.model_key = model_key
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
        self.staged_model = None    # <run>\model\<model_name> once staging began
        self.stage_done = 0         # bytes copied so far
        self.stage_total = 0
        self.stage_ready = False    # every item copied and checked; waiting for the launch
        self.cleanup = None         # None | "pending" | "done" | "incomplete"

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
            "stage": self.stage, "model_name": self.model_name, "model_key": self.model_key,
            "staged_model": self.staged_model, "stage_done": self.stage_done,
            "stage_total": self.stage_total, "stage_ready": self.stage_ready,
            "cleanup": self.cleanup,
        }


class Queue(object):
    """FIFO export queue owned by its caller. `starter` has start(spec) -> handle with pid,
    has_exited(), exit_code(), close(); and run(spec) -> exit code. `clock()` returns a datetime.
    Pass effective_parallel(setting) as max_parallel.

    `hold()` (optional): while no job of this queue runs and it returns true, queued jobs wait
    and `held` is True. A hold that raises counts as false. The status window passes
    DotNetStarter.extractor_running, so a RevitExtractor.exe this queue did not start (another
    session, the .ps1 launcher, a second Revit) keeps the fixed pipe free. A cloud job asks it
    again after its copy, right before the Extractor starts.

    Cloud jobs (Job.stage), all optional and injectable for tests:
    - `stage_clock()`: seconds (float) for the copy budget; read only while a job is staging;
    - `stage_budget`, `stage_chunk`: seconds per poll() and bytes per copy step;
    - `free_space(path)`: free bytes for the run folder's drive, or None when unknown;
    - `tree_running()`: True while an Extractor process may still hold a staged copy; the copies
      are deleted only after the job's process has exited and this is false;
    - `remove(path)`: os.remove; `copier`: rx_cloud_stage.copy_steps.
    """

    def __init__(self, starter, clock, max_parallel=1, system_root=None, token=None, hold=None,
                 stage_clock=None, stage_budget=STAGE_BUDGET, stage_chunk=STAGE_CHUNK,
                 free_space=None, tree_running=None, remove=None, copier=None):
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
        self._stage_clock = stage_clock or _DEFAULT_STAGE_CLOCK
        self._stage_budget = stage_budget
        self._stage_chunk = stage_chunk
        self._free_space = free_space
        self._tree_running = tree_running
        self._remove = remove or os.remove
        self._copier = copier or copy_steps
        self._copies = {}       # job id -> copy generator, while staging
        self._specs = {}        # job id -> LaunchSpec, while staging
        self._staged = {}       # job id -> names this job copied into <run>\model
        self._cleanups = []     # finished jobs whose staged copies still wait for deletion
        self._cleanup_since = {}

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
        if job.model_key is not None and (
                not isinstance(job.model_key, _TEXT_TYPES) or not job.model_key.strip()
                or len(job.model_key) > _MAX_KEY or "\r" in job.model_key
                or "\n" in job.model_key):
            raise RunnerError(tr("Invalid model key.", "Nieprawidłowy klucz modelu."))
        if job.stage is None:
            if job.model_name is not None:
                raise _bad_stage("model_name")
        else:
            job.stage = _checked_stage(job)
            job.stage_total = sum(item["size"] for item in job.stage["items"])
        self._counter += 1
        job.id = "job-%d" % self._counter
        job.state = QUEUED
        job.queued_at = self._clock()
        self._jobs.append(job)
        return job.id

    def jobs(self):
        return list(self._jobs)

    def clear_finished(self):
        """Forget every finished job (OK, FAILED, CANCELLED); queued and running jobs keep their
        order and ids, and ids are never reused. Touches nothing on disk (a pending deletion of
        staged copies goes on). Returns the removed ids in queue order."""
        done = (OK, FAILED, CANCELLED)
        removed = [job.id for job in self._jobs if job.state in done]
        if removed:
            self._jobs = [job for job in self._jobs if job.state not in done]
        return removed

    def busy(self):
        """True while a job waits, copies or runs, or staged copies still wait for deletion."""
        return (any(job.state in (QUEUED, STAGING, RUNNING) for job in self._jobs)
                or bool(self._cleanups))

    def _find(self, job_id):
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None

    def poll(self):
        """Finish exited jobs, delete staged copies whose process tree has exited, start the
        Extractor for copied jobs and queued ones up to the limit, then copy for at most the
        stage budget. Returns changed ids."""
        changed = []
        for job in self._jobs:
            if job.state == RUNNING and self._finish_if_exited(job):
                changed.append(job.id)
        self._advance_cleanups()
        self.held = self._is_held()
        if not self.held:
            for job in self._jobs:
                if job.state == STAGING and job.stage_ready:
                    self._launch_staged(job)
                    changed.append(job.id)
            for job in self._jobs:
                if self._slots_used() >= self._max:
                    break
                if job.state != QUEUED or self._key_busy(job):
                    continue
                if job.stage is None:
                    self._start(job)
                else:
                    self._begin_stage(job)
                changed.append(job.id)
        for job_id in self._advance_staging():
            if job_id not in changed:
                changed.append(job_id)
        return changed

    def _is_held(self):
        """Asked only when a start waits (a queued job with a free slot, or a copied cloud job)
        and none of ours runs (our own Extractor would count)."""
        if self._hold is None or self._running_count():
            return False
        waiting = any(job.state == STAGING and job.stage_ready for job in self._jobs)
        if not waiting and self._slots_used() < self._max:
            waiting = any(job.state == QUEUED for job in self._jobs)
        if not waiting:
            return False
        try:
            return bool(self._hold())
        except Exception:  # fail open: a broken check must not stall the queue for ever
            return False

    def _running_count(self):
        return len([job for job in self._jobs if job.state == RUNNING])

    def _slots_used(self):
        """Running and staging jobs: a staging job will run next, so it takes a slot."""
        return len([job for job in self._jobs if job.state in (RUNNING, STAGING)])

    def _key_busy(self, job):
        key = _job_key(job)
        return any(other.state in (RUNNING, STAGING) and _job_key(other) == key
                   for other in self._jobs)

    def _fail(self, job, message):
        job.state = FAILED
        job.ended_at = self._clock()
        job.result = Result(FAILED, None, None, message)

    def _start(self, job):
        job.started_at = self._clock()
        try:
            exe = extractor_exe(job.revit_dir)
            # Before any write: nothing is ever created under Revit's CollaborationCache.
            if _in_cache(job.output_parent, []):
                raise RunnerError(tr(
                    "The output folder is inside Revit's cache (CollaborationCache); nothing is "
                    "ever written there. Choose another output folder.",
                    "Folder wyjściowy jest w pamięci podręcznej Revita (CollaborationCache); nic "
                    "nie jest tam nigdy zapisywane. Wybierz inny folder wyjściowy."))
            paths = plan_run(job.output_parent, job.started_at, self._token())
            spec = launch_spec(exe, job.revit_dir, job.model_path, paths, self._root())
            prepare_run(paths, job.index)
            job.paths = paths
            handle = self._starter.start(spec)
        except Exception as error:  # one job fails, the queue goes on
            self._fail(job, tr("The export could not start: {0}",
                               "Nie udało się uruchomić eksportu: {0}").format(_error_text(error)))
            return
        job.pid = handle.pid
        self._handles[job.id] = handle
        job.state = RUNNING

    # -- cloud jobs: staging

    def _free_bytes(self, path):
        if self._free_space is None:
            return None
        try:
            return self._free_space(path)
        except Exception:   # unknown: the copy goes ahead and fails on its own if the disk fills
            return None

    def _begin_stage(self, job):
        """Validate everything, create the run folder and <run>\\model with stage.json, and set
        up the copy. No process is started here."""
        job.started_at = self._clock()
        try:
            exe = extractor_exe(job.revit_dir)
            paths = plan_run(job.output_parent, job.started_at, self._token())
            folder = os.path.join(paths.root, STAGE_FOLDER)
            target = os.path.join(folder, job.model_name)
            spec = launch_spec(exe, job.revit_dir, target, paths, self._root())
            # Before any write: the run folder (and so <run>\model) must lie outside Revit's
            # cache. copy_steps checks this too, but only once the run folder exists.
            items = _stage_items(job.stage)
            if _in_cache(paths.root, items) or _in_cache(folder, items):
                raise RunnerError(tr(
                    "The output folder is inside Revit's cache (CollaborationCache) or inside "
                    "the folder of a cache file; nothing is ever written there. Choose another "
                    "output folder.",
                    "Folder wyjściowy jest w pamięci podręcznej Revita (CollaborationCache) lub "
                    "w folderze pliku z tej pamięci; nic nie jest tam nigdy zapisywane. Wybierz "
                    "inny folder wyjściowy."))
            check_space(job.stage, self._free_bytes(job.output_parent))
            prepare_run(paths, job.index)
            job.paths = paths
            os.mkdir(folder)
            _write_stage_record(folder, job)
            copies = self._copier(job.stage, folder, chunk=self._stage_chunk)
        except Exception as error:  # one job fails, the queue goes on
            self._fail(job, tr("The export could not start: {0}",
                               "Nie udało się uruchomić eksportu: {0}").format(_error_text(error)))
            return
        job.staged_model = target
        job.stage_done = 0
        job.stage_ready = False
        self._staged[job.id] = set()
        self._copies[job.id] = copies
        self._specs[job.id] = spec
        job.state = STAGING

    def _advance_staging(self):
        """Copy chunks of the staging jobs until the budget is used (at least one step)."""
        staging = [job for job in self._jobs if job.state == STAGING and not job.stage_ready]
        if not staging:
            return []
        changed = []
        start = self._stage_clock()
        out_of_time = False
        for job in staging:
            copies = self._copies[job.id]
            changed.append(job.id)
            while True:
                try:
                    done, _total, item = next(copies)
                except StopIteration:
                    job.stage_ready = True
                    break
                except Exception as error:  # StageError or any IO error: this job only
                    self._stage_failed(job, error)
                    break
                self._staged[job.id].add(item.name)
                job.stage_done = done
                if self._stage_clock() - start >= self._stage_budget:
                    out_of_time = True
                    break
            if out_of_time:
                break
        return changed

    def _close_copies(self, job):
        copies = self._copies.pop(job.id, None)
        self._specs.pop(job.id, None)
        if copies is not None:
            try:
                copies.close()  # removes the partly written destination, nothing else
            except Exception:
                pass

    def _stage_failed(self, job, error):
        self._close_copies(job)
        self._fail(job, tr("The copy from the cache failed: {0}",
                           "Kopiowanie z pamięci podręcznej nie powiodło się: {0}")
                   .format(_error_text(error)))
        self._remove_or_retry(job)   # no process ran, but another program may hold a copy

    def _launch_staged(self, job):
        spec = self._specs.get(job.id)
        self._close_copies(job)
        try:
            if spec is None:
                raise RunnerError(tr("The copy plan is not valid.",
                                     "Plan kopiowania jest nieprawidłowy."))
            handle = self._starter.start(spec)
        except Exception as error:
            self._fail(job, tr("The export could not start: {0}",
                               "Nie udało się uruchomić eksportu: {0}").format(_error_text(error)))
            self._remove_or_retry(job)
            return
        job.pid = handle.pid
        self._handles[job.id] = handle
        job.state = RUNNING

    # -- cloud jobs: deleting the staged copies

    def _remove_copies(self, job):
        """Delete the copies this job staged; True when none is left. Only names this job's copy
        created, only directly inside <run>\\model, never a link or a path under a
        CollaborationCache folder or equal to a source."""
        names = self._staged.get(job.id) or set()
        if job.paths is None or not names:
            self._staged.pop(job.id, None)
            return True
        folder = os.path.join(job.paths.root, STAGE_FOLDER)
        sources = set(_model_key(item["src"]) for item in job.stage["items"])
        left = set()
        for name in sorted(names):
            path = os.path.join(folder, name)
            parts = [part.lower() for part in _model_key(path).replace("/", "\\").split("\\")]
            if (not safe_file_name(name) or os.path.dirname(path) != folder
                    or "collaborationcache" in parts or _model_key(path) in sources):
                continue    # never ours to delete
            if os.path.islink(path) or not os.path.lexists(path):
                continue
            try:
                self._remove(path)
            except Exception:
                left.add(name)
        if left:
            self._staged[job.id] = left
            return False
        self._staged.pop(job.id, None)
        return True

    def _remove_or_retry(self, job):
        """Delete a finished job's copies now; whatever stays locked is retried on each poll
        (busy() stays True) until CLEANUP_SECONDS, then reported with the folder."""
        if self._remove_copies(job):
            job.cleanup = "done"
        else:
            job.cleanup = "pending"
            self._cleanups.append(job)
            self._cleanup_since[job.id] = job.ended_at

    def _tree_alive(self):
        if self._tree_running is None:
            return False
        try:
            return bool(self._tree_running())
        except Exception:   # unknown: try; a file still in use cannot be deleted anyway
            return False

    def _advance_cleanups(self):
        if not self._cleanups:
            return
        alive = self._tree_alive()
        now = self._clock()
        for job in list(self._cleanups):
            if not alive and self._remove_copies(job):
                job.cleanup = "done"
            elif _seconds(now - self._cleanup_since[job.id]) >= CLEANUP_SECONDS:
                job.cleanup = "incomplete"
                folder = os.path.join(job.paths.root, STAGE_FOLDER)
                job.result = _with_message(job.result, tr(
                    "Some copies from the cache could not be deleted; delete them by hand "
                    "from {0}.",
                    "Nie udało się usunąć części kopii z pamięci podręcznej; usuń je ręcznie "
                    "z {0}.").format(folder))
            else:
                continue
            self._cleanups.remove(job)
            self._cleanup_since.pop(job.id, None)
            self._staged.pop(job.id, None)

    # -- running jobs

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
        if job.stage is not None:
            if job.stage["notes"] and job.state != CANCELLED:
                job.result = _with_message(job.result, " ".join(job.stage["notes"]))
            job.cleanup = "pending"
            self._cleanups.append(job)
            self._cleanup_since[job.id] = job.ended_at
        del self._handles[job.id]
        try:
            handle.close()
        except Exception:
            pass
        return True

    def cancel(self, job_id):
        """Queued: never starts. Staging: the copy stops and its copies are deleted; no process
        is started. Running: kill the tree once. Returns True if it acted."""
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
        if job.state == STAGING:
            self._close_copies(job)
            job.state = CANCELLED
            job.ended_at = self._clock()
            job.result = Result(CANCELLED, None, None, tr(
                "Export cancelled while copying from the cache; the Extractor was not started.",
                "Eksport anulowany podczas kopiowania z pamięci podręcznej; Extractor nie został "
                "uruchomiony."))
            self._remove_or_retry(job)
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


def _seconds(delta):
    try:
        return delta.total_seconds()
    except Exception:
        return 0


def _with_message(result, extra):
    if result is None:
        return Result(FAILED, None, None, extra)
    message = (result.message + " " + extra) if result.message else extra
    return Result(result.state, result.success_jobs, result.failed_jobs, message)


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
        return self._any_running(("RevitExtractor",))

    def extractor_tree_running(self):
        """True while any RevitExtractor.exe or RevitExtractor_Client.exe runs on this computer.
        The queue deletes staged copies only when this is false (a conservative stand-in for
        "this job's whole process tree has exited"). Only lists; never ends one."""
        return self._any_running(("RevitExtractor", "RevitExtractor_Client"))

    def _any_running(self, names):
        from System.Diagnostics import Process
        running = False
        for name in names:
            for process in Process.GetProcessesByName(name):
                running = True
                try:
                    process.Dispose()
                except Exception:
                    pass
        return running
