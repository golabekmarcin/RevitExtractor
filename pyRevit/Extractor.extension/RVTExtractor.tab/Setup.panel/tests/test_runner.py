# -*- coding: utf-8 -*-
"""Tests for lib/rx_runner.py (pure Python plus a stubbed System.Diagnostics; no Revit).

Spec: specs/SPEC-export-runner.md, acceptance criteria 1-10. Criterion 3 really starts cmd.exe
(Windows only). The real Extractor run is tests/run_extractor_integration.ps1.
"""
import ast
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

LIB = Path(__file__).resolve().parents[3] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))  # append, never insert (same-named modules in the bundles)

import rx_runner  # noqa: E402
from rx_index import to_json  # noqa: E402
from rx_runner import (RunnerError, Queue, check_result, default_output_parent,  # noqa: E402
                       effective_parallel, extractor_exe, kill_spec, launch_spec, plan_run,
                       prepare_run, progress_line)

ON_WINDOWS = os.name == "nt"
NOW = datetime.datetime(2026, 11, 10, 9, 5, 7)
TOKEN = "a1b2c3d4"
SYSTEM_ROOT = os.path.join("C:" + os.sep, "Windows") if ON_WINDOWS else "/windows"
SAMPLE_INDEX = {"metadata": {"parameters": {"derivative_type": {
    "2dviewing": {}, "3dviewing": {}, "properties_data": {"pdb": True}}}},
    "note": "zażółć gęślą jaźń"}
ENV_NAMES = ("RX_EXE", "RX_INDEX", "RX_MODEL", "RX_REVIT", "RX_LOGS", "RX_JOURNALS",
             "RX_CONSOLE", "RX_STDERR")


def polish():
    """pyRevit set to Polish (same resolver shape as test_capabilities.polish)."""
    def get_locale_string(string_dict):
        for code in ("pl", "polish", "en_us", "english"):
            if code in string_dict:
                return string_dict[code]
        return None
    applocales = types.SimpleNamespace(get_locale_string=get_locale_string)
    coreutils = types.SimpleNamespace(applocales=applocales)
    return {"pyrevit": types.SimpleNamespace(coreutils=coreutils),
            "pyrevit.coreutils": coreutils, "pyrevit.coreutils.applocales": applocales}


def message_of(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except RunnerError as error:
        return str(error)
    raise AssertionError("RunnerError expected")


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rx-runner-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)


def snapshot(root):
    """Names, sizes and modification times of everything under root."""
    entries = {}
    for folder, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(folder, name)
            info = os.stat(path)
            entries[os.path.relpath(path, root)] = (os.path.isdir(path), info.st_size,
                                                    info.st_mtime_ns)
    return entries


# --- Criterion 1: run folder ------------------------------------------------------------------

class RunFolder(TempDirTest):
    def test_default_output_parent(self):
        docs = os.path.join(self.tmp, "Documents")
        self.assertEqual(default_output_parent(docs), os.path.join(docs, "RevitExtractor"))

    def test_plan_run_layout(self):
        paths = plan_run(self.tmp, NOW, TOKEN)
        root = os.path.join(self.tmp, "export-20261110-090507-a1b2c3d4")
        self.assertEqual(paths.root, root)
        self.assertEqual(paths.index, os.path.join(root, "index.json"))
        self.assertEqual(paths.output, os.path.join(root, "output"))
        self.assertEqual(paths.logs, os.path.join(root, "logs"))
        self.assertEqual(paths.journals, os.path.join(root, "journals"))
        self.assertEqual(paths.console, os.path.join(root, "console.log"))
        self.assertEqual(paths.stderr, os.path.join(root, "stderr.log"))
        self.assertFalse(os.path.exists(root), "plan_run must not touch the disk")

    def test_plan_run_rejects_bad_token_and_parent(self):
        for token in ("", "a1b2c3d", "a1b2c3d4e", "A1B2C3D4", "../../x1", "a1b2c3d\n"):
            with self.assertRaises(RunnerError, msg=repr(token)):
                plan_run(self.tmp, NOW, token)
        for parent in ("relative\\folder", "", os.path.join(self.tmp, 'a"b'),
                       os.path.join(self.tmp, "a\nb"), os.path.join(self.tmp, "a\rb")):
            with self.assertRaises(RunnerError, msg=repr(parent)):
                plan_run(parent, NOW, TOKEN)

    def test_prepare_run_creates_exactly_the_layout(self):
        parent = os.path.join(self.tmp, "not yet there")
        paths = plan_run(parent, NOW, TOKEN)
        prepare_run(paths, SAMPLE_INDEX)
        self.assertEqual(sorted(os.listdir(paths.root)),
                         ["index.json", "journals", "logs", "output"])
        for folder in (paths.output, paths.logs, paths.journals):
            self.assertEqual(os.listdir(folder), [])
        with open(paths.index, "rb") as handle:
            data = handle.read()
        self.assertEqual(data, to_json(SAMPLE_INDEX).encode("utf-8"))
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))

    def test_prepare_run_refuses_an_existing_root(self):
        paths = plan_run(self.tmp, NOW, TOKEN)
        os.makedirs(os.path.join(paths.root, "output"))
        marker = os.path.join(paths.root, "output", "bubble.json")
        with open(marker, "w") as handle:
            handle.write("old export")
        before = snapshot(paths.root)
        with self.assertRaises(RunnerError):
            prepare_run(paths, SAMPLE_INDEX)
        self.assertEqual(snapshot(paths.root), before, "an existing export must stay untouched")

    def test_prepare_run_refuses_a_file_in_place_of_the_root(self):
        paths = plan_run(self.tmp, NOW, TOKEN)
        with open(paths.root, "w") as handle:
            handle.write("x")
        with self.assertRaises(RunnerError):
            prepare_run(paths, SAMPLE_INDEX)

    def test_extractor_exe(self):
        revit = os.path.join(self.tmp, "Revit X")
        expected = os.path.join(revit, "RevitExtractor", "RevitExtractor.exe")
        self.assertEqual(extractor_exe(revit, exists=lambda path: path == expected), expected)
        self.assertEqual(extractor_exe(revit + os.sep, exists=lambda path: path == expected),
                         expected)
        with self.assertRaises(RunnerError):
            extractor_exe(revit, exists=lambda path: False)

    def test_extractor_exe_default_uses_the_disk(self):
        revit = os.path.join(self.tmp, "Revit")
        with self.assertRaises(RunnerError):
            extractor_exe(revit)
        os.makedirs(os.path.join(revit, "RevitExtractor"))
        exe = os.path.join(revit, "RevitExtractor", "RevitExtractor.exe")
        open(exe, "w").close()
        self.assertEqual(extractor_exe(revit), exe)

    def test_errors_are_bilingual(self):
        english = message_of(extractor_exe, self.tmp, exists=lambda path: False)
        with patch.dict(sys.modules, polish()):
            polish_text = message_of(extractor_exe, self.tmp, exists=lambda path: False)
        self.assertNotEqual(english, polish_text)
        self.assertIn("RevitExtractor.exe", english)
        self.assertIn("RevitExtractor.exe", polish_text)


# --- Criteria 2, 3, 9: launch and kill specs ------------------------------------------------

def spec_inputs(base):
    revit = os.path.join(base, "Revit")
    exe = os.path.join(revit, "RevitExtractor", "RevitExtractor.exe")
    model = os.path.join(base, "Models", "Model.rvt")
    return exe, revit, model, plan_run(os.path.join(base, "out"), NOW, TOKEN)


class LaunchSpec(TempDirTest):
    def test_file_arguments_env(self):
        exe, revit, model, paths = spec_inputs(self.tmp)
        spec = launch_spec(exe, revit, model, paths, SYSTEM_ROOT)
        self.assertEqual(spec.file, os.path.join(SYSTEM_ROOT, "System32", "cmd.exe"))
        self.assertEqual(spec.working_dir, revit)
        self.assertEqual(set(spec.env), set(ENV_NAMES))
        self.assertEqual(spec.env["RX_EXE"], exe)
        self.assertEqual(spec.env["RX_INDEX"], paths.index)
        self.assertEqual(spec.env["RX_MODEL"], model)
        self.assertEqual(spec.env["RX_REVIT"], revit)
        self.assertEqual(spec.env["RX_LOGS"], paths.logs)
        self.assertEqual(spec.env["RX_JOURNALS"], paths.journals)
        self.assertEqual(spec.env["RX_CONSOLE"], paths.console)
        self.assertEqual(spec.env["RX_STDERR"], paths.stderr)
        for value in spec.env.values():
            self.assertNotIn(value, spec.arguments)
        self.assertTrue(spec.arguments.startswith("/d /v:off /s /c "), spec.arguments)
        for name in ENV_NAMES:
            self.assertIn('"%' + name + '%"', spec.arguments)

    def test_arguments_are_constant(self):
        exe, revit, model, paths = spec_inputs(self.tmp)
        other = spec_inputs(os.path.join(self.tmp, "other & 100%"))
        self.assertEqual(launch_spec(exe, revit, model, paths, SYSTEM_ROOT).arguments,
                         launch_spec(other[0], other[1], other[2], other[3],
                                     SYSTEM_ROOT).arguments)

    def test_trailing_backslashes_are_trimmed(self):
        exe, revit, model, paths = spec_inputs(self.tmp)
        spec = launch_spec(exe, revit + "\\\\", model, paths, SYSTEM_ROOT)
        self.assertEqual(spec.env["RX_REVIT"], revit)
        self.assertEqual(spec.working_dir, revit)

    def test_drive_root_is_refused(self):
        exe, revit, model, paths = spec_inputs(self.tmp)
        with self.assertRaises(RunnerError):
            launch_spec(exe, "C:\\", model, paths, SYSTEM_ROOT)

    def test_quotes_and_line_breaks_are_refused(self):
        exe, revit, model, paths = spec_inputs(self.tmp)
        for bad in ('"', "\r", "\n"):
            bad_paths = plan_run(self.tmp, NOW, TOKEN)._replace(
                logs=os.path.join(self.tmp, "lo" + bad + "gs"))
            cases = [
                (exe + bad, revit, model, paths, SYSTEM_ROOT),
                (exe, revit + bad + "x", model, paths, SYSTEM_ROOT),
                (exe, revit, model + bad, paths, SYSTEM_ROOT),
                (exe, revit, model, bad_paths, SYSTEM_ROOT),
                (exe, revit, model, paths, SYSTEM_ROOT + bad),
            ]
            for args in cases:
                with self.assertRaises(RunnerError, msg=repr(args)):
                    launch_spec(*args)

    def test_relative_and_empty_paths_are_refused(self):
        exe, revit, model, paths = spec_inputs(self.tmp)
        for args in ((exe, revit, "Model.rvt", paths, SYSTEM_ROOT),
                     ("", revit, model, paths, SYSTEM_ROOT),
                     (exe, revit, model, paths, ""),
                     (exe, None, model, paths, SYSTEM_ROOT)):
            with self.assertRaises(RunnerError, msg=repr(args)):
                launch_spec(*args)


class KillSpec(unittest.TestCase):
    def test_full_path_and_tree_kill(self):
        spec = kill_spec(1234, SYSTEM_ROOT)
        self.assertEqual(spec.file, os.path.join(SYSTEM_ROOT, "System32", "taskkill.exe"))
        self.assertEqual(spec.arguments, "/PID 1234 /T /F")
        self.assertEqual(spec.env, {})

    def test_only_a_positive_integer_pid(self):
        for pid in ("1234", 12.0, True, False, None, 0, -5, "1234 /IM revit.exe"):
            with self.assertRaises(RunnerError, msg=repr(pid)):
                kill_spec(pid, SYSTEM_ROOT)

    def test_bad_system_root(self):
        for root in ("", "Windows", SYSTEM_ROOT + '"'):
            with self.assertRaises(RunnerError, msg=repr(root)):
                kill_spec(1, root)


STAND_IN = (
    "@echo off\r\n"
    "chcp 65001 >nul\r\n"
    "for %%a in (%*) do echo ARG[%%~a]\r\n"
    "exit /b 3\r\n"
)


@unittest.skipUnless(ON_WINDOWS, "starts cmd.exe; Windows only")
class RealCmdStart(TempDirTest):
    """Criterion 3: the spec started for real, with a stand-in .cmd as RX_EXE."""

    def test_arguments_arrive_intact_and_exit_code_is_read(self):
        weird = os.path.join(self.tmp, "Łódź ż & 100%TEMP% x^y")
        revit = os.path.join(weird, "Revit dir")
        os.makedirs(revit)
        stand_in = os.path.join(weird, "stand in.cmd")
        with open(stand_in, "w", encoding="ascii", newline="") as handle:
            handle.write(STAND_IN)
        model = os.path.join(weird, "Model & ąę %TEMP% ^ !PATH!.rvt")  # ! guards /v:off
        paths = plan_run(os.path.join(weird, "out ^ & %USERNAME%"), NOW, TOKEN)
        prepare_run(paths, SAMPLE_INDEX)
        spec = launch_spec(stand_in, revit, model, paths, os.environ["SystemRoot"])
        env = dict(os.environ)
        env.update(spec.env)
        # .NET Framework builds the command line as "<FileName>" + " " + Arguments.
        command_line = '"' + spec.file + '" ' + spec.arguments
        process = subprocess.Popen(command_line, executable=spec.file, cwd=spec.working_dir,
                                   env=env, creationflags=0x08000000)  # CREATE_NO_WINDOW
        self.assertEqual(process.wait(60), 3)
        with open(paths.console, "rb") as handle:
            lines = handle.read().decode("utf-8").splitlines()
        args = [line[4:-1] for line in lines if line.startswith("ARG[")]
        self.assertEqual(args, [paths.index, model, "-RCEPath", revit, "-LogPath", paths.logs,
                                "-journalPath", paths.journals])
        self.assertTrue(os.path.isfile(paths.stderr))


# --- Criteria 4, 5: result and progress -----------------------------------------------------

SUMMARY_OK = "12:00:01 INFO Success Jobs: 7, Failed Jobs: 0\n"


class CheckResult(unittest.TestCase):
    def test_ok(self):
        result = check_result(0, "start\n" + SUMMARY_OK, True, True)
        self.assertEqual(result.state, "ok")
        self.assertEqual((result.success_jobs, result.failed_jobs), (7, 0))
        self.assertTrue(result.message)

    def test_exit_code(self):
        result = check_result(5, SUMMARY_OK, True, True)
        self.assertEqual(result.state, "failed")
        self.assertIn("5", result.message)
        self.assertEqual(check_result(None, SUMMARY_OK, True, True).state, "failed")

    def test_failed_jobs(self):
        result = check_result(0, "Success Jobs: 5, Failed Jobs: 2\n", True, True)
        self.assertEqual(result.state, "failed")
        self.assertEqual((result.success_jobs, result.failed_jobs), (5, 2))
        self.assertIn("2", result.message)

    def test_output_incomplete(self):
        for bubble, resource in ((False, True), (True, False), (False, False)):
            result = check_result(0, SUMMARY_OK, bubble, resource)
            self.assertEqual(result.state, "failed")
            self.assertIn("bubble.json", result.message)

    def test_last_summary_line_wins(self):
        first_bad = "Success Jobs: 1, Failed Jobs: 3\n" + SUMMARY_OK
        self.assertEqual(check_result(0, first_bad, True, True).state, "ok")
        last_bad = SUMMARY_OK + "success jobs: 2, failed jobs: 1\n"
        result = check_result(0, last_bad, True, True)
        self.assertEqual(result.state, "failed")
        self.assertEqual((result.success_jobs, result.failed_jobs), (2, 1))

    def test_missing_summary_is_ok_but_flagged(self):
        result = check_result(0, "no summary here\n", True, True)
        self.assertEqual(result.state, "ok")
        self.assertIsNone(result.success_jobs)
        self.assertIsNone(result.failed_jobs)
        self.assertIn("Success Jobs", result.message)
        self.assertNotEqual(result.message, check_result(0, SUMMARY_OK, True, True).message)

    def test_messages_are_bilingual(self):
        cases = [(0, SUMMARY_OK, True, True), (1, "", True, True),
                 (0, "Success Jobs: 1, Failed Jobs: 1", True, True), (0, SUMMARY_OK, False, True),
                 (0, "", True, True)]
        for case in cases:
            english = check_result(*case).message
            with patch.dict(sys.modules, polish()):
                polish_text = check_result(*case).message
            self.assertNotEqual(english, polish_text, case)

    def test_none_console_text(self):
        self.assertEqual(check_result(0, None, True, True).state, "ok")


class ProgressLine(unittest.TestCase):
    def test_last_meaningful_line(self):
        tail = ("first\r\nTask SVF started\r\n\r\n"
                "WARN mesh number larger than 64k in svf file\r\n"
                "   \r\nERROR DSM_InternalErrorMessage something\r\n\r\n")
        self.assertEqual(progress_line(tail), "Task SVF started")

    def test_noise_is_case_insensitive(self):
        self.assertEqual(progress_line("ok line\nMesh Number Larger Than 64K\n"), "ok line")

    def test_empty(self):
        for tail in ("", None, "\n\n", "mesh number larger than 64k\n"):
            self.assertEqual(progress_line(tail), "")


# --- Criterion 7: parallel setting ----------------------------------------------------------

class EffectiveParallel(unittest.TestCase):
    def test_one_while_unverified(self):
        with patch.object(rx_runner, "PARALLEL_VERIFIED", False):
            for setting in (1, 2, 4, 99, "3", None, 0, -1):
                self.assertEqual(effective_parallel(setting), 1, setting)

    def test_clamped_once_verified(self):
        with patch.object(rx_runner, "PARALLEL_VERIFIED", True):
            cases = {1: 1, 2: 2, 3: 3, 4: 4, 5: 4, 99: 4, 0: 1, -3: 1, "2": 2, "x": 1,
                     None: 1, True: 1, 2.5: 1}
            for setting, expected in cases.items():
                self.assertEqual(effective_parallel(setting), expected, setting)

    def test_shipped_unverified(self):
        self.assertIs(rx_runner.PARALLEL_VERIFIED, False)


# --- Criteria 6, 8: queue -------------------------------------------------------------------

class FakeHandle(object):
    def __init__(self, pid):
        self.pid = pid
        self.exited = False
        self.code = None
        self.closed = False

    def has_exited(self):
        return self.exited

    def exit_code(self):
        return self.code if self.exited else None

    def close(self):
        self.closed = True


class FakeStarter(object):
    def __init__(self):
        self.started = []  # (spec, handle)
        self.killed = []
        self.fail_models = set()
        self.kill_exit = 0
        self.next_pid = 1000

    def start(self, spec):
        if spec.env["RX_MODEL"] in self.fail_models:
            raise OSError("cannot start")
        self.next_pid += 1
        handle = FakeHandle(self.next_pid)
        self.started.append((spec, handle))
        return handle

    def run(self, spec):
        self.killed.append(spec)
        return self.kill_exit

    def handle_for(self, model):
        return [h for s, h in self.started if s.env["RX_MODEL"] == model][-1]

    def started_models(self):
        return [s.env["RX_MODEL"] for s, h in self.started]


class FakeClock(object):
    def __init__(self):
        self.now = NOW

    def __call__(self):
        self.now += datetime.timedelta(seconds=1)
        return self.now


class QueueTest(TempDirTest):
    def setUp(self):
        super(QueueTest, self).setUp()
        self.revit = os.path.join(self.tmp, "Revit")
        os.makedirs(os.path.join(self.revit, "RevitExtractor"))
        open(os.path.join(self.revit, "RevitExtractor", "RevitExtractor.exe"), "w").close()
        self.out = os.path.join(self.tmp, "out")
        self.starter = FakeStarter()
        self.tokens = iter("%08x" % n for n in range(1, 1000))

    def queue(self, max_parallel=1):
        return Queue(self.starter, FakeClock(), max_parallel=max_parallel,
                     system_root=SYSTEM_ROOT, token=lambda: next(self.tokens))

    def model(self, name):
        return os.path.join(self.tmp, "models", name + ".rvt")

    def add(self, queue, name):
        return queue.add(rx_runner.Job(self.model(name), SAMPLE_INDEX, self.revit, self.out))

    def job(self, queue, job_id):
        return [job for job in queue.jobs() if job.id == job_id][0]

    def finish(self, queue, job_id, code=0, complete=True, summary=SUMMARY_OK):
        job = self.job(queue, job_id)
        if complete:
            open(os.path.join(job.paths.output, "bubble.json"), "w").close()
            os.makedirs(os.path.join(job.paths.output, "Resource"))
        with open(job.paths.console, "w") as handle:
            handle.write(summary)
        handle = self.starter.handle_for(job.model_path)
        handle.exited = True
        handle.code = code
        return handle

    def test_one_at_a_time_in_order(self):
        queue = self.queue()
        a, b, c = self.add(queue, "a"), self.add(queue, "b"), self.add(queue, "c")
        self.assertEqual([j.state for j in queue.jobs()], ["queued"] * 3)
        self.assertFalse(os.path.exists(self.out), "nothing is created while queued")
        queue.poll()
        self.assertEqual(self.starter.started_models(), [self.model("a")])
        self.assertEqual([j.state for j in queue.jobs()], ["running", "queued", "queued"])
        queue.poll()
        self.assertEqual(len(self.starter.started), 1, "no second start while the first runs")
        handle = self.finish(queue, a)
        queue.poll()
        self.assertEqual(self.job(queue, a).state, "ok")
        self.assertTrue(handle.closed)
        self.assertEqual(self.starter.started_models(), [self.model("a"), self.model("b")])
        self.finish(queue, b, code=1)
        queue.poll()
        self.assertEqual(self.job(queue, b).state, "failed")
        self.assertEqual(self.job(queue, c).state, "running")
        self.finish(queue, c, complete=False)
        queue.poll()
        self.assertEqual(self.job(queue, c).state, "failed")
        self.assertFalse(queue.busy())

    def test_job_record(self):
        queue = self.queue()
        job_id = self.add(queue, "a")
        queue.poll()
        job = self.job(queue, job_id)
        self.assertEqual(job.pid, 1001)
        self.assertEqual(job.model_path, self.model("a"))
        self.assertTrue(os.path.isdir(job.paths.output))
        self.assertTrue(job.paths.root.startswith(os.path.join(self.out, "export-")))
        spec = self.starter.started[0][0]
        self.assertEqual(spec.env["RX_INDEX"], job.paths.index)
        self.assertEqual(spec.env["RX_EXE"],
                         os.path.join(self.revit, "RevitExtractor", "RevitExtractor.exe"))
        self.finish(queue, job_id)
        queue.poll()
        record = job.as_dict()
        self.assertEqual(record["state"], "ok")
        self.assertEqual(record["result"]["success_jobs"], 7)
        self.assertEqual(record["exit_code"], 0)
        self.assertIsNotNone(record["started_at"])
        self.assertIsNotNone(record["ended_at"])

    def test_cancel_queued_never_starts(self):
        queue = self.queue()
        a, b = self.add(queue, "a"), self.add(queue, "b")
        self.assertTrue(queue.cancel(b))
        queue.poll()
        self.finish(queue, a)
        queue.poll()
        queue.poll()
        self.assertEqual(self.starter.started_models(), [self.model("a")])
        self.assertEqual(self.job(queue, b).state, "cancelled")
        self.assertIsNone(self.job(queue, b).paths)
        self.assertEqual(len(os.listdir(self.out)), 1, "only job a has a run folder")
        self.assertEqual(self.starter.killed, [])

    def test_cancel_running_kills_once(self):
        queue = self.queue()
        a, b = self.add(queue, "a"), self.add(queue, "b")
        queue.poll()
        self.assertTrue(queue.cancel(a))
        self.assertFalse(queue.cancel(a))
        self.assertEqual([s.arguments for s in self.starter.killed], ["/PID 1001 /T /F"])
        self.assertEqual(self.starter.killed[0].file,
                         os.path.join(SYSTEM_ROOT, "System32", "taskkill.exe"))
        root = self.job(queue, a).paths.root
        self.finish(queue, a, code=1, complete=False, summary="")
        queue.poll()
        self.assertEqual(self.job(queue, a).state, "cancelled")
        self.assertTrue(os.path.isdir(root), "a cancelled run folder stays")
        self.assertEqual(self.job(queue, b).state, "running")
        self.assertEqual(len(self.starter.killed), 1)

    def test_failed_kill_can_be_retried(self):
        queue = self.queue()
        a = self.add(queue, "a")
        queue.poll()
        self.starter.kill_exit = 128
        self.assertFalse(queue.cancel(a))
        self.starter.kill_exit = 0
        self.assertTrue(queue.cancel(a))
        self.assertEqual(len(self.starter.killed), 2)

    def test_cancel_after_exit_never_kills(self):
        queue = self.queue()
        a = self.add(queue, "a")
        queue.poll()
        self.finish(queue, a)
        self.assertFalse(queue.cancel(a), "an exited process is never killed")
        self.assertEqual(self.starter.killed, [])
        queue.poll()
        self.assertEqual(self.job(queue, a).state, "ok")

    def test_cancel_unknown_or_finished(self):
        queue = self.queue()
        self.assertFalse(queue.cancel("nope"))
        a = self.add(queue, "a")
        queue.poll()
        self.finish(queue, a)
        queue.poll()
        self.assertFalse(queue.cancel(a))
        self.assertEqual(self.job(queue, a).state, "ok")
        self.assertEqual(self.starter.killed, [])

    def test_start_failure_does_not_stop_the_queue(self):
        queue = self.queue()
        self.starter.fail_models.add(self.model("a"))
        a, b = self.add(queue, "a"), self.add(queue, "b")
        queue.poll()
        self.assertEqual(self.job(queue, a).state, "failed")
        self.assertIn("cannot start", self.job(queue, a).result.message)
        self.assertEqual(self.job(queue, b).state, "running")

    def test_missing_extractor_fails_the_job_only(self):
        queue = self.queue()
        a = queue.add(rx_runner.Job(self.model("a"), SAMPLE_INDEX,
                                    os.path.join(self.tmp, "no revit"), self.out))
        b = self.add(queue, "b")
        queue.poll()
        self.assertEqual(self.job(queue, a).state, "failed")
        self.assertIsNone(self.job(queue, a).paths, "no folder for a job that cannot start")
        self.assertEqual(self.job(queue, b).state, "running")

    def test_add_validates_paths(self):
        queue = self.queue()
        for job in (rx_runner.Job(self.model('a"'), SAMPLE_INDEX, self.revit, self.out),
                    rx_runner.Job("relative.rvt", SAMPLE_INDEX, self.revit, self.out),
                    rx_runner.Job(self.model("a"), SAMPLE_INDEX, self.revit + "\n", self.out),
                    rx_runner.Job(self.model("a"), SAMPLE_INDEX, self.revit, "rel\\out")):
            with self.assertRaises(RunnerError):
                queue.add(job)
        self.assertEqual(queue.jobs(), [])

    def test_same_model_never_runs_twice(self):
        queue = self.queue(max_parallel=2)
        a1, a2, b = self.add(queue, "a"), self.add(queue, "a"), self.add(queue, "b")
        queue.poll()
        self.assertEqual(self.starter.started_models(), [self.model("a"), self.model("b")])
        self.assertEqual(self.job(queue, a2).state, "queued")
        self.finish(queue, a1)
        queue.poll()
        self.assertEqual(self.job(queue, a2).state, "running")

    def test_same_model_by_case_and_form(self):
        queue = self.queue(max_parallel=2)
        self.add(queue, "a")
        other = queue.add(rx_runner.Job(self.model("a").upper() if ON_WINDOWS
                                        else self.model("a"),
                                        SAMPLE_INDEX, self.revit, self.out))
        queue.poll()
        self.assertEqual(len(self.starter.started), 1)
        self.assertEqual(self.job(queue, other).state, "queued")

    def test_two_in_parallel(self):
        queue = self.queue(max_parallel=2)
        a, b, c = self.add(queue, "a"), self.add(queue, "b"), self.add(queue, "c")
        queue.poll()
        self.assertEqual([j.state for j in queue.jobs()], ["running", "running", "queued"])
        roots = [self.job(queue, x).paths.root for x in (a, b)]
        self.assertNotEqual(roots[0], roots[1])
        self.finish(queue, b)
        queue.poll()
        self.assertEqual([j.state for j in queue.jobs()], ["running", "ok", "running"])

    def test_max_parallel_must_be_positive_int(self):
        for bad in (0, -1, "2", None, True, 1.5):
            with self.assertRaises(RunnerError, msg=repr(bad)):
                Queue(self.starter, FakeClock(), max_parallel=bad, system_root=SYSTEM_ROOT)

    def test_folder_unchanged_by_poll_and_check(self):
        """Criterion 8: after the process exits nothing is written into the run folder."""
        queue = self.queue()
        a = self.add(queue, "a")
        queue.poll()
        self.finish(queue, a)
        root = self.job(queue, a).paths.root
        with open(os.path.join(root, "stderr.log"), "w") as handle:
            handle.write("")
        before = snapshot(root)
        queue.poll()
        job = self.job(queue, a)
        self.assertEqual(job.state, "ok")
        with open(job.paths.console) as handle:
            check_result(0, handle.read(), True, True)
        queue.progress(a)
        self.assertEqual(snapshot(root), before)

    def test_progress(self):
        queue = self.queue()
        a = self.add(queue, "a")
        self.assertEqual(queue.progress(a), "")
        queue.poll()
        self.assertEqual(queue.progress(a), "", "no console.log yet")
        with open(self.job(queue, a).paths.console, "w") as handle:
            handle.write("Task PDF started\nmesh number larger than 64k\n")
        self.assertEqual(queue.progress(a), "Task PDF started")
        self.assertEqual(queue.progress("unknown"), "")


# --- Criterion 10: imports and DotNetStarter ------------------------------------------------

BANNED_TOP = {"pyrevit", "Autodesk", "System", "clr"}


def imported_names(node):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module or ""]
    return []


class Guards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (LIB / "rx_runner.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_no_module_level_host_imports(self):
        def walk_outside_functions(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    continue
                yield child
                for grandchild in walk_outside_functions(child):
                    yield grandchild
        for node in walk_outside_functions(self.tree):
            for name in imported_names(node):
                self.assertNotIn(name.split(".")[0], BANNED_TOP, name)

    def test_system_diagnostics_only_inside_dotnetstarter(self):
        starter = [node for node in self.tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "DotNetStarter"]
        self.assertEqual(len(starter), 1)
        inside = set(id(node) for node in ast.walk(starter[0]))
        found = 0
        for node in ast.walk(self.tree):
            for name in imported_names(node):
                if name.split(".")[0] in BANNED_TOP:
                    self.assertIn(id(node), inside, name)
                    self.assertEqual(name, "System.Diagnostics")
                    found += 1
        self.assertGreater(found, 0)

    def test_no_threads_or_process_events(self):
        for node in ast.walk(self.tree):
            for name in imported_names(node):
                self.assertNotIn(name.split(".")[0], {"threading", "thread", "_thread",
                                                      "multiprocessing", "subprocess"})
            # IronPython subscribes .NET events (PascalCase) with `obj.Event += handler`.
            if (isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute)
                    and node.target.attr[:1].isupper()):
                self.fail("event subscription: " + node.target.attr)
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"Exited", "EnableRaisingEvents",
                                             "OutputDataReceived", "ErrorDataReceived",
                                             "BeginOutputReadLine", "BeginErrorReadLine"})

    def test_ironpython_syntax(self):
        self.assertTrue(self.source.startswith("# -*- coding: utf-8 -*-"))
        self.assertIn("from __future__ import unicode_literals", self.source)
        for node in ast.walk(self.tree):
            self.assertNotIsInstance(node, ast.JoinedStr)
            self.assertNotIsInstance(node, ast.AnnAssign)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.assertNotIsInstance(node, ast.AsyncFunctionDef)
                self.assertIsNone(node.returns)
                for arg in node.args.args + node.args.kwonlyargs:
                    self.assertIsNone(arg.annotation)
                self.assertEqual(node.args.kwonlyargs, [])
            for name in imported_names(node):
                self.assertNotIn(name.split(".")[0], {"pathlib", "typing", "shlex"})
        for banned in ("os.replace", "exist_ok", "nonlocal ", "yield from"):
            self.assertNotIn(banned, self.source)


class FakeEnvironment(dict):
    pass


class FakeStartInfo(object):
    def __init__(self):
        self.FileName = ""
        self.Arguments = ""
        self.WorkingDirectory = ""
        self.UseShellExecute = True  # the .NET default; the starter must turn it off
        self.CreateNoWindow = False
        self.RedirectStandardOutput = False
        self.RedirectStandardError = False
        self.RedirectStandardInput = False
        self.EnvironmentVariables = FakeEnvironment(PATH="C:\\Windows")


class FakeProcess(object):
    started = []
    return_none = False

    def __init__(self, info):
        self.info = info
        self.Id = 4321
        self.HasExited = False
        self._code = None
        self.disposed = False
        self.waits = []

    @property
    def ExitCode(self):
        if not self.HasExited:
            raise RuntimeError("InvalidOperationException: process has not exited")
        return self._code

    def WaitForExit(self, milliseconds):
        self.waits.append(milliseconds)
        self.HasExited = True
        self._code = 7
        return True

    def Dispose(self):
        self.disposed = True

    @staticmethod
    def Start(info):
        if FakeProcess.return_none:
            return None
        process = FakeProcess(info)
        FakeProcess.started.append(process)
        return process


def stub_system():
    diagnostics = types.ModuleType("System.Diagnostics")
    diagnostics.Process = FakeProcess
    diagnostics.ProcessStartInfo = FakeStartInfo
    system = types.ModuleType("System")
    system.Diagnostics = diagnostics
    return {"System": system, "System.Diagnostics": diagnostics}


class DotNetStarterTest(TempDirTest):
    def setUp(self):
        super(DotNetStarterTest, self).setUp()
        FakeProcess.started = []
        FakeProcess.return_none = False

    def test_start_sets_every_field(self):
        exe, revit, model, paths = spec_inputs(self.tmp)
        spec = launch_spec(exe, revit, model, paths, SYSTEM_ROOT)
        with patch.dict(sys.modules, stub_system()):
            handle = rx_runner.DotNetStarter().start(spec)
        info = FakeProcess.started[0].info
        self.assertEqual(info.FileName, spec.file)
        self.assertEqual(info.Arguments, spec.arguments)
        self.assertEqual(info.WorkingDirectory, spec.working_dir)
        self.assertIs(info.UseShellExecute, False)
        self.assertIs(info.CreateNoWindow, True)
        self.assertIs(info.RedirectStandardOutput, False)
        self.assertIs(info.RedirectStandardError, False)
        self.assertIs(info.RedirectStandardInput, False)
        for name in ENV_NAMES:
            self.assertEqual(info.EnvironmentVariables[name], spec.env[name])
        self.assertEqual(info.EnvironmentVariables["PATH"], "C:\\Windows", "parent env kept")
        self.assertEqual(handle.pid, 4321)
        self.assertFalse(handle.has_exited())
        self.assertIsNone(handle.exit_code())
        FakeProcess.started[0].HasExited = True
        FakeProcess.started[0]._code = 3
        self.assertTrue(handle.has_exited())
        self.assertEqual(handle.exit_code(), 3)
        handle.close()
        self.assertTrue(FakeProcess.started[0].disposed)

    def test_run_waits_and_returns_the_exit_code(self):
        with patch.dict(sys.modules, stub_system()):
            code = rx_runner.DotNetStarter().run(kill_spec(99, SYSTEM_ROOT))
        process = FakeProcess.started[0]
        self.assertEqual(code, 7)
        self.assertEqual(process.info.Arguments, "/PID 99 /T /F")
        self.assertEqual(len(process.waits), 1)
        self.assertGreater(process.waits[0], 0)
        self.assertTrue(process.disposed)

    def test_start_returning_nothing_is_an_error(self):
        FakeProcess.return_none = True
        exe, revit, model, paths = spec_inputs(self.tmp)
        with patch.dict(sys.modules, stub_system()):
            with self.assertRaises(RunnerError):
                rx_runner.DotNetStarter().start(launch_spec(exe, revit, model, paths,
                                                            SYSTEM_ROOT))

    def test_import_is_lazy(self):
        self.assertNotIn("System.Diagnostics", sys.modules)


# --- status-window amendments (specs/SPEC-status-window.md, criterion 12) ------------------

class Hold(object):
    """hold() stand-in: answers from `value`, counts calls, can raise."""

    def __init__(self, value=False):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class QueueHoldTest(TempDirTest):
    # QueueTest's fixtures and helpers without re-running its tests.
    def setUp(self):
        super(QueueHoldTest, self).setUp()
        self.revit = os.path.join(self.tmp, "Revit")
        os.makedirs(os.path.join(self.revit, "RevitExtractor"))
        open(os.path.join(self.revit, "RevitExtractor", "RevitExtractor.exe"), "w").close()
        self.out = os.path.join(self.tmp, "out")
        self.starter = FakeStarter()
        self.tokens = iter("%08x" % n for n in range(1, 1000))

    queue = QueueTest.queue
    model = QueueTest.model
    add = QueueTest.add
    job = QueueTest.job

    def held_queue(self, hold, max_parallel=1):
        return Queue(self.starter, FakeClock(), max_parallel=max_parallel,
                     system_root=SYSTEM_ROOT, token=lambda: next(self.tokens), hold=hold)

    def test_held_queue_starts_nothing_and_can_still_cancel(self):
        hold = Hold(True)
        queue = self.held_queue(hold)
        a, b = self.add(queue, "a"), self.add(queue, "b")
        self.assertIs(queue.held, False, "not held before the first poll")
        queue.poll()
        self.assertEqual(self.starter.started, [])
        self.assertIs(queue.held, True)
        self.assertEqual([j.state for j in queue.jobs()], ["queued", "queued"])
        self.assertFalse(os.path.exists(self.out), "no run folder while held")
        self.assertTrue(queue.cancel(b))
        self.assertEqual(self.job(queue, b).state, "cancelled")
        hold.value = False
        queue.poll()
        self.assertIs(queue.held, False)
        self.assertEqual(self.starter.started_models(), [self.model("a")])

    def test_hold_is_not_asked_while_a_job_of_this_queue_runs(self):
        hold = Hold(False)
        queue = self.held_queue(hold, max_parallel=2)
        self.add(queue, "a")
        queue.poll()
        calls = hold.calls
        hold.value = True  # our own RevitExtractor.exe is running now
        self.add(queue, "b")
        queue.poll()
        self.assertEqual(hold.calls, calls)
        self.assertIs(queue.held, False)
        self.assertEqual(self.starter.started_models(), [self.model("a"), self.model("b")])

    def test_failing_hold_counts_as_false(self):
        queue = self.held_queue(Hold(OSError("no process list")))
        self.add(queue, "a")
        queue.poll()
        self.assertIs(queue.held, False)
        self.assertEqual(len(self.starter.started), 1)

    def test_hold_is_not_asked_without_queued_jobs(self):
        hold = Hold(True)
        queue = self.held_queue(hold)
        queue.poll()
        a = self.add(queue, "a")
        queue.cancel(a)
        queue.poll()
        self.assertEqual(hold.calls, 0)
        self.assertIs(queue.held, False)

    def test_no_hold_behaves_as_before(self):
        queue = self.queue()
        self.add(queue, "a")
        queue.poll()
        self.assertIs(queue.held, False)
        self.assertEqual(len(self.starter.started), 1)

    def test_tail_is_the_console_text_read_only(self):
        queue = self.queue()
        a = self.add(queue, "a")
        self.assertEqual(queue.tail(a), "", "queued: no run folder yet")
        queue.poll()
        self.assertEqual(queue.tail(a), "", "no console.log yet")
        console = self.job(queue, a).paths.console
        with open(console, "wb") as handle:
            handle.write(b"first\r\n[[progress]]:{\"x\": \"40\"}\r\nmesh number larger than 64k\r\n")
        root = self.job(queue, a).paths.root
        before = snapshot(root)
        text = queue.tail(a)
        self.assertIn('[[progress]]:{"x": "40"}', text)
        self.assertIn("mesh number", text, "raw text, no filtering")
        self.assertEqual(snapshot(root), before)
        self.assertEqual(queue.tail("unknown"), "")

    def test_tail_is_limited_to_the_end_of_a_long_log(self):
        queue = self.queue()
        a = self.add(queue, "a")
        queue.poll()
        with open(self.job(queue, a).paths.console, "wb") as handle:
            handle.write(b"x" * (rx_runner._PROGRESS_TAIL_BYTES * 2) + b"\nlast line\n")
        text = queue.tail(a)
        self.assertTrue(text.endswith("last line\n"))
        self.assertLessEqual(len(text), rx_runner._PROGRESS_TAIL_BYTES)


class CleanPathIsPublic(unittest.TestCase):
    def test_clean_path(self):
        self.assertTrue(callable(rx_runner.clean_path))
        self.assertEqual(rx_runner.clean_path(SYSTEM_ROOT + os.sep), SYSTEM_ROOT)
        for bad in ("", None, "relative", SYSTEM_ROOT + '"'):
            with self.assertRaises(RunnerError, msg=repr(bad)):
                rx_runner.clean_path(bad)


class FakeListedProcess(object):
    def __init__(self):
        self.disposed = False

    def Dispose(self):
        self.disposed = True


class FakeProcessWithList(FakeProcess):
    listed = []
    names = []

    @staticmethod
    def GetProcessesByName(name):
        FakeProcessWithList.names.append(name)
        return list(FakeProcessWithList.listed)


class DotNetStarterAmendments(TempDirTest):
    def setUp(self):
        super(DotNetStarterAmendments, self).setUp()
        FakeProcess.started = []
        FakeProcess.return_none = False
        FakeProcessWithList.listed = []
        FakeProcessWithList.names = []

    def spec(self):
        exe, revit, model, paths = spec_inputs(self.tmp)
        return launch_spec(exe, revit, model, paths, SYSTEM_ROOT)

    def test_show_window_turns_create_no_window_off(self):
        with patch.dict(sys.modules, stub_system()):
            rx_runner.DotNetStarter().start(self.spec(), show_window=True)
            rx_runner.DotNetStarter().start(self.spec())
        self.assertIs(FakeProcess.started[0].info.CreateNoWindow, False)
        self.assertIs(FakeProcess.started[0].info.UseShellExecute, False)
        self.assertIs(FakeProcess.started[1].info.CreateNoWindow, True)

    def stubs(self):
        stubs = stub_system()
        stubs["System.Diagnostics"].Process = FakeProcessWithList
        return stubs

    def test_extractor_running(self):
        with patch.dict(sys.modules, self.stubs()):
            self.assertIs(rx_runner.DotNetStarter().extractor_running(), False)
            FakeProcessWithList.listed = [FakeListedProcess(), FakeListedProcess()]
            self.assertIs(rx_runner.DotNetStarter().extractor_running(), True)
        self.assertEqual(FakeProcessWithList.names, ["RevitExtractor", "RevitExtractor"])
        self.assertTrue(all(p.disposed for p in FakeProcessWithList.listed),
                        "every listed process object is disposed")
        self.assertEqual(FakeProcess.started, [], "the check starts nothing")


if __name__ == "__main__":
    unittest.main()
