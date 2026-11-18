# -*- coding: utf-8 -*-
"""Tests for lib/rx_runner.py (pure Python plus a stubbed System.Diagnostics; no Revit).

Spec: specs/SPEC-export-runner.md, acceptance criteria 1-10. Criterion 3 really starts cmd.exe
(Windows only). The real Extractor run is tests/run_extractor_integration.ps1.
"""
import ast
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

LIB = Path(__file__).resolve().parents[3] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))  # append, never insert (same-named modules in the bundles)

import rx_runner  # noqa: E402
from rx_cloud import StageItem  # noqa: E402
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

    def test_local_job_with_output_folder_inside_the_revit_cache_is_refused(self):
        # Nothing is ever written under CollaborationCache, also for a normal (local) job.
        cache_out = os.path.join(self.tmp, "Autodesk Revit X", "CollaborationCache", "exports")
        queue = self.queue()
        job_id = queue.add(rx_runner.Job(self.model("a"), SAMPLE_INDEX, self.revit, cache_out))
        queue.poll()
        job = self.job(queue, job_id)
        self.assertEqual(job.state, "failed")
        self.assertIn("CollaborationCache", job.result.message)
        self.assertFalse(os.path.exists(cache_out), "no folder is created in the cache")
        self.assertEqual(self.starter.started, [], "no process is started")
        # The next job still runs: one failed job never stops the queue.
        other = self.add(queue, "b")
        queue.poll()
        self.assertEqual(self.job(queue, other).state, "running")

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

    def test_clear_finished_removes_only_finished_and_keeps_order_and_ids(self):
        queue = self.queue()
        a, b, c, d, e = [self.add(queue, name) for name in "abcde"]
        queue.poll()
        self.finish(queue, a)
        queue.poll()  # a ok, b running
        queue.cancel(c)  # c cancelled while queued
        self.finish(queue, b, code=3)
        queue.poll()  # b failed, d running
        self.assertEqual([j.state for j in queue.jobs()],
                         ["ok", "failed", "cancelled", "running", "queued"])
        self.assertEqual(queue.clear_finished(), [a, b, c])
        self.assertEqual([j.id for j in queue.jobs()], [d, e])
        self.assertEqual([j.state for j in queue.jobs()], ["running", "queued"])
        self.assertEqual(self.starter.killed, [], "never cancels anything")
        self.assertEqual(len(os.listdir(self.out)), 3, "run folders of a, b, d stay on disk")

    def test_clear_finished_edge_cases(self):
        queue = self.queue()
        self.assertEqual(queue.clear_finished(), [])
        a, b = self.add(queue, "a"), self.add(queue, "b")
        self.assertEqual(queue.clear_finished(), [], "only waiting")
        queue.poll()
        self.assertEqual(queue.clear_finished(), [], "running and waiting")
        self.assertEqual([j.id for j in queue.jobs()], [a, b])
        self.assertTrue(queue.busy())

    def test_ids_keep_counting_after_clear_finished(self):
        queue = self.queue()
        a = self.add(queue, "a")
        queue.poll()
        self.finish(queue, a)
        queue.poll()
        self.assertEqual(queue.clear_finished(), [a])
        self.assertEqual(queue.jobs(), [])
        self.assertEqual(self.add(queue, "b"), "job-2")
        queue.poll()
        self.assertEqual(self.starter.started_models()[-1], self.model("b"))

    def test_clear_finished_does_not_touch_the_hold_gate(self):
        hold = Hold(False)
        queue = self.held_queue_for_clear(hold)
        a = self.add(queue, "a")
        queue.poll()
        self.finish(queue, a)
        queue.poll()
        self.assertEqual(queue.clear_finished(), [a])
        b = self.add(queue, "b")
        hold.value = True
        queue.poll()
        self.assertIs(queue.held, True)
        self.assertEqual(self.job(queue, b).state, "queued")
        hold.value = False
        queue.poll()
        self.assertIs(queue.held, False)
        self.assertEqual(self.job(queue, b).state, "running")

    def held_queue_for_clear(self, hold):
        return Queue(self.starter, FakeClock(), max_parallel=1, system_root=SYSTEM_ROOT,
                     token=lambda: next(self.tokens), hold=hold)

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
        # .NET only in DotNetStarter (System.Diagnostics; System.IO for a file's creation time)
        # and MachineRunLock (the run mutex).
        allowed = {"DotNetStarter": {"System.Diagnostics", "System.IO"},
                   "MachineRunLock": {"System", "System.Threading"}}
        owners = {}
        for node in self.tree.body:
            if isinstance(node, ast.ClassDef) and node.name in allowed:
                for child in ast.walk(node):
                    owners[id(child)] = node.name
        self.assertEqual(sorted(set(owners.values())), sorted(allowed))
        found = 0
        for node in ast.walk(self.tree):
            for name in imported_names(node):
                if name.split(".")[0] in BANNED_TOP:
                    self.assertIn(id(node), owners, name)
                    self.assertIn(name, allowed[owners[id(node)]])
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

class OrphanRunTest(QueueTest):
    """A run an earlier Revit session left going: found in the output folder, then only watched."""

    def run_folder(self, name, console=True, done=False, age=0):
        root = os.path.join(self.out, name)
        os.makedirs(os.path.join(root, "output"))
        if done:
            open(os.path.join(root, "output", "bubble.json"), "w").close()
        if console:
            path = os.path.join(root, "console.log")
            open(path, "w").close()
            when = time.time() - age
            os.utime(path, (when, when))
        return root

    @staticmethod
    def began(path):
        return os.stat(path).st_mtime       # the tests set mtime; it stands for the creation time

    def find(self, starts, parent=None):
        return rx_runner.find_orphan_run(parent or self.out, time.time(), starts, created=self.began)

    def test_the_newest_unfinished_run_is_found(self):
        self.run_folder("export-20261118-100000-aaaaaaaa", age=3000)
        newest = self.run_folder("export-20261118-110000-bbbbbbbb", age=10)
        self.run_folder("export-20261118-120000-cccccccc", done=True, age=1)       # finished
        self.run_folder("export-20261117-090000-dddddddd", age=3 * 86400)           # a day old
        self.run_folder("not-a-run", age=1)
        self.run_folder("export-20261118-130000-eeeeeeee", console=False)           # never started
        found = self.find([time.time() - 10, time.time() - 3000])
        self.assertEqual(found.root, newest)
        self.assertEqual(found.console, os.path.join(newest, "console.log"))

    def test_nothing_found_is_none_and_never_raises(self):
        starts = [time.time()]
        self.assertIsNone(self.find(starts, os.path.join(self.tmp, "missing")))
        self.assertIsNone(self.find(starts, ""))
        self.assertIsNone(self.find(starts, None))
        os.makedirs(self.out)
        self.assertIsNone(self.find(starts))

    def test_a_run_is_matched_to_the_running_extractor_not_just_to_a_recent_log(self):
        self.run_folder("export-20261118-110000-bbbbbbbb", age=600)   # a failed run of today
        self.assertIsNone(self.find([time.time() - 5]), "the process started long after that log")
        self.assertIsNone(self.find([]), "no process start known: nothing is adopted")
        self.assertIsNone(self.find(None))
        self.assertIsNotNone(self.find([time.time() - 600 + 30]), "started within two minutes of it")

    def test_an_adopted_run_is_shown_watched_never_controlled(self):
        root = self.run_folder("export-20261118-110000-bbbbbbbb", age=5)
        paths = rx_runner.run_paths_for(root)
        running = Hold(True)
        queue = self.queue()
        job_id = queue.adopt_run(paths, running=running)
        job = self.job(queue, job_id)
        self.assertEqual((job.state, job.foreign), ("running", True))
        self.assertEqual(queue.adopt_run(paths, running=running), job_id, "the same folder once")
        self.assertTrue(queue.busy())
        self.assertFalse(queue.cancel(job_id), "never ended from here")
        self.assertEqual(self.starter.killed, [])
        queue.poll()
        self.assertEqual(self.job(queue, job_id).state, "running")

    def test_the_queue_waits_for_an_adopted_run_and_it_ends_when_no_extractor_runs(self):
        root = self.run_folder("export-20261118-110000-bbbbbbbb", age=5)
        running = Hold(True)
        queue = Queue(self.starter, FakeClock(), system_root=SYSTEM_ROOT,
                      token=lambda: next(self.tokens), hold=running)
        adopted = queue.adopt_run(rx_runner.run_paths_for(root), running=running)
        queued = self.add(queue, "a")
        queue.poll()
        self.assertEqual(self.job(queue, queued).state, "queued", "one Extractor at a time")
        self.assertEqual(self.starter.started, [])    # its slot is taken, not only held
        running.value = False
        open(os.path.join(root, "output", "bubble.json"), "w").close()
        os.makedirs(os.path.join(root, "output", "Resource"))
        with open(os.path.join(root, "console.log"), "w") as handle:
            handle.write(SUMMARY_OK)
        queue.poll()
        self.assertEqual(self.job(queue, adopted).state, "ok")
        queue.poll()
        self.assertEqual(self.job(queue, queued).state, "running", "the queue goes on after it")

    def test_an_adopted_run_without_a_success_line_is_not_reported_as_done(self):
        root = self.run_folder("export-20261118-110000-bbbbbbbb", age=5)
        open(os.path.join(root, "output", "bubble.json"), "w").close()
        os.makedirs(os.path.join(root, "output", "Resource"))
        running = Hold(True)
        queue = self.queue()
        job_id = queue.adopt_run(rx_runner.run_paths_for(root), running=running)
        running.value = False
        queue.poll()
        job = self.job(queue, job_id)
        self.assertEqual(job.state, "failed", "its real exit code is unknown")
        self.assertIn("could not be confirmed", job.result.message)

    def test_an_adopted_run_that_ends_without_output_is_a_failure(self):
        root = self.run_folder("export-20261118-110000-bbbbbbbb", age=5)
        running = Hold(True)
        queue = self.queue()
        job_id = queue.adopt_run(rx_runner.run_paths_for(root), running=running)
        running.value = False
        queue.poll()
        job = self.job(queue, job_id)
        self.assertEqual(job.state, "failed")
        self.assertIn("incomplete", job.result.message)


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


# --- machine-wide run lock (one Extractor per computer: fixed IPC pipe) ----------------------

class LockState(object):
    """The named mutex every FakeLock of one test shares (one per computer)."""

    def __init__(self):
        self.owner = None


class FakeLock(object):
    """lock stand-in: acquire() -> bool without waiting, release(); can raise on acquire."""

    def __init__(self, state, error=None):
        self.state = state
        self.error = error
        self.acquires = 0
        self.releases = 0

    def acquire(self):
        self.acquires += 1
        if self.error is not None:
            raise self.error
        if self.state.owner is None or self.state.owner is self:
            self.state.owner = self
            return True
        return False

    def release(self):
        self.releases += 1
        if self.state.owner is self:
            self.state.owner = None

    @property
    def owned(self):
        return self.state.owner is self


class QueueLockTest(TempDirTest):
    def setUp(self):
        super(QueueLockTest, self).setUp()
        self.revit = os.path.join(self.tmp, "Revit")
        os.makedirs(os.path.join(self.revit, "RevitExtractor"))
        open(os.path.join(self.revit, "RevitExtractor", "RevitExtractor.exe"), "w").close()
        self.out = os.path.join(self.tmp, "out")
        self.starter = FakeStarter()
        self.tokens = iter("%08x" % n for n in range(1, 1000))

    model = QueueTest.model
    add = QueueTest.add
    job = QueueTest.job
    finish = QueueTest.finish

    def locked_queue(self, lock, starter=None, hold=None, tree_running=None):
        return Queue(starter or self.starter, FakeClock(), system_root=SYSTEM_ROOT,
                     token=lambda: next(self.tokens), hold=hold, lock=lock,
                     tree_running=tree_running)

    def test_second_queue_is_held_while_the_first_holds_the_lock(self):
        # Two Revit sessions start at the same moment: the second sees "held", even before
        # any RevitExtractor.exe exists (only cmd.exe so far), and starts nothing.
        state = LockState()
        first, second = FakeLock(state), FakeLock(state)
        other_starter = FakeStarter()
        q1 = self.locked_queue(first, hold=Hold(False))
        q2 = self.locked_queue(second, starter=other_starter, hold=Hold(False))
        a = self.add(q1, "a")
        b = self.add(q2, "b")
        q1.poll()
        self.assertTrue(first.owned)
        self.assertEqual(self.job(q1, a).state, "running")
        q2.poll()
        self.assertIs(q2.held, True)
        self.assertEqual(other_starter.started, [])
        self.assertEqual(self.job(q2, b).state, "queued")
        self.assertIsNone(self.job(q2, b).paths, "no run folder while held")
        self.finish(q1, a)
        q1.poll()
        self.assertEqual(self.job(q1, a).state, "ok")
        self.assertIsNone(state.owner, "released once the job's tree exited")
        q2.poll()
        self.assertIs(q2.held, False)
        self.assertEqual(other_starter.started_models(), [self.model("b")])
        self.assertTrue(second.owned)

    def test_lock_is_kept_across_back_to_back_jobs_of_one_queue(self):
        state = LockState()
        lock = FakeLock(state)
        queue = self.locked_queue(lock)
        a, b = self.add(queue, "a"), self.add(queue, "b")
        queue.poll()
        self.finish(queue, a)
        queue.poll()
        self.assertEqual(self.job(queue, b).state, "running")
        self.assertTrue(lock.owned)
        self.assertEqual(lock.releases, 0, "no gap another session could slip into")
        self.finish(queue, b)
        queue.poll()
        self.assertIsNone(state.owner)
        self.assertFalse(queue.busy())

    def test_lock_released_after_cancel(self):
        state = LockState()
        queue = self.locked_queue(FakeLock(state))
        a = self.add(queue, "a")
        queue.poll()
        self.assertTrue(queue.cancel(a))
        queue.poll()
        self.assertIsNotNone(state.owner, "kept until the killed tree has exited")
        self.starter.handle_for(self.model("a")).exited = True
        self.starter.handle_for(self.model("a")).code = 1
        queue.poll()
        self.assertEqual(self.job(queue, a).state, "cancelled")
        self.assertIsNone(state.owner)
        self.assertFalse(queue.busy())

    def test_lock_released_after_a_failed_start(self):
        state = LockState()
        lock = FakeLock(state)
        self.starter.fail_models.add(self.model("a"))
        queue = self.locked_queue(lock)
        a = self.add(queue, "a")
        queue.poll()
        self.assertEqual(self.job(queue, a).state, "failed")
        self.assertEqual(lock.acquires, 1)
        self.assertIsNone(state.owner)
        self.assertFalse(queue.busy())
        other_starter = FakeStarter()
        other = self.locked_queue(FakeLock(state), starter=other_starter)
        self.add(other, "b")
        other.poll()
        self.assertEqual(other_starter.started_models(), [self.model("b")])

    def test_lock_released_when_the_run_folder_cannot_be_prepared(self):
        state = LockState()
        queue = self.locked_queue(FakeLock(state))
        a = queue.add(rx_runner.Job(self.model("a"), SAMPLE_INDEX,
                                    os.path.join(self.tmp, "no-revit"), self.out))
        queue.poll()
        self.assertEqual(self.job(queue, a).state, "failed")
        self.assertIsNone(state.owner)

    def test_raising_hold_does_not_deadlock(self):
        state = LockState()
        queue = self.locked_queue(FakeLock(state), hold=Hold(OSError("no process list")))
        a = self.add(queue, "a")
        queue.poll()
        self.assertIs(queue.held, False)
        self.assertEqual(self.job(queue, a).state, "running")
        self.finish(queue, a)
        queue.poll()
        self.assertIsNone(state.owner)
        self.assertFalse(queue.busy())

    def test_hold_true_after_taking_the_lock_gives_it_back(self):
        # A foreign Extractor (the .ps1 launcher) runs: held, and the lock is not kept, so
        # another session is not blocked by a queue that starts nothing.
        state = LockState()
        hold = Hold(True)
        queue = self.locked_queue(FakeLock(state), hold=hold)
        self.add(queue, "a")
        queue.poll()
        self.assertIs(queue.held, True)
        self.assertEqual(self.starter.started, [])
        self.assertIsNone(state.owner)
        hold.value = False
        queue.poll()
        self.assertEqual(len(self.starter.started), 1)

    def test_a_raising_lock_counts_as_held(self):
        # Fail closed: without the lock no Extractor is started; hold() is not even asked.
        hold = Hold(False)
        lock = FakeLock(LockState(), error=RuntimeError("mutex unavailable"))
        queue = self.locked_queue(lock, hold=hold)
        a = self.add(queue, "a")
        queue.poll()
        self.assertIs(queue.held, True)
        self.assertEqual(self.starter.started, [])
        self.assertEqual(hold.calls, 0)
        self.assertTrue(queue.cancel(a))
        self.assertFalse(queue.busy())

    def test_lock_is_kept_until_the_tree_has_exited(self):
        state = LockState()
        alive = {"value": True}
        queue = self.locked_queue(FakeLock(state), tree_running=lambda: alive["value"])
        a = self.add(queue, "a")
        queue.poll()
        self.finish(queue, a)
        queue.poll()
        self.assertEqual(self.job(queue, a).state, "ok")
        self.assertIsNotNone(state.owner, "a client process may still use the pipe")
        self.assertTrue(queue.busy(), "keeps polling until the lock is released")
        alive["value"] = False
        queue.poll()
        self.assertIsNone(state.owner)
        self.assertFalse(queue.busy())

    def test_lock_is_not_asked_without_a_start(self):
        lock = FakeLock(LockState())
        queue = self.locked_queue(lock)
        queue.poll()
        a = self.add(queue, "a")
        queue.cancel(a)
        queue.poll()
        self.assertEqual(lock.acquires, 0)
        self.assertEqual(lock.releases, 0)

    def test_close_releases_the_lock(self):
        state = LockState()
        queue = self.locked_queue(FakeLock(state), tree_running=lambda: True)
        a = self.add(queue, "a")
        queue.poll()
        self.finish(queue, a)
        queue.poll()
        self.assertIsNotNone(state.owner)
        queue.release_lock()
        self.assertIsNone(state.owner)
        queue.release_lock()   # idempotent


class FakeAbandoned(Exception):
    pass


class FakeUnauthorized(Exception):
    pass


class FakeMutex(object):
    """System.Threading.Mutex stand-in. `behaviour` picks what WaitOne(0) does."""
    made = []
    behaviour = "take"
    construct_error = None

    def __init__(self, initially_owned, name):
        if FakeMutex.construct_error is not None:
            raise FakeMutex.construct_error
        self.initially_owned = initially_owned
        self.name = name
        self.waits = []
        self.released = 0
        self.disposed = False
        FakeMutex.made.append(self)

    def WaitOne(self, milliseconds):
        self.waits.append(milliseconds)
        if FakeMutex.behaviour == "abandoned":
            raise FakeAbandoned("abandoned")
        return FakeMutex.behaviour == "take"

    def ReleaseMutex(self):
        self.released += 1

    def Dispose(self):
        self.disposed = True


class FakeLockDomain(object):
    def __init__(self):
        self.data = {}

    def GetData(self, key):
        return self.data.get(key)

    def SetData(self, key, value):
        self.data[key] = value


def stub_threading(domain):
    threading = types.ModuleType("System.Threading")
    threading.Mutex = FakeMutex
    threading.AbandonedMutexException = FakeAbandoned
    system = types.ModuleType("System")
    system.Threading = threading
    system.UnauthorizedAccessException = FakeUnauthorized
    system.AppDomain = types.SimpleNamespace(CurrentDomain=domain)
    return {"System": system, "System.Threading": threading}


class MachineRunLockTest(unittest.TestCase):
    def setUp(self):
        FakeMutex.made = []
        FakeMutex.behaviour = "take"
        FakeMutex.construct_error = None
        self.domain = FakeLockDomain()
        patcher = patch.dict(sys.modules, stub_threading(self.domain))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_takes_without_waiting_and_releases(self):
        lock = rx_runner.MachineRunLock()
        self.assertTrue(lock.acquire())
        mutex = FakeMutex.made[0]
        self.assertEqual(mutex.name, rx_runner.RUN_LOCK_NAME)
        self.assertTrue(mutex.name.startswith("Global\\"))
        self.assertIs(mutex.initially_owned, False)
        self.assertEqual(mutex.waits, [0], "never blocks the UI thread")
        self.assertTrue(lock.acquire(), "already ours")
        self.assertEqual(len(FakeMutex.made), 1)
        lock.release()
        self.assertEqual(mutex.released, 1)
        self.assertTrue(mutex.disposed)
        lock.release()
        self.assertEqual(mutex.released, 1, "release is idempotent")

    def test_owned_elsewhere_is_false_and_closes_the_handle(self):
        FakeMutex.behaviour = "busy"
        lock = rx_runner.MachineRunLock()
        self.assertFalse(lock.acquire())
        self.assertTrue(FakeMutex.made[0].disposed)
        self.assertEqual(FakeMutex.made[0].released, 0)
        lock.release()
        self.assertEqual(FakeMutex.made[0].released, 0, "never releases what it does not own")

    def test_abandoned_counts_as_acquired(self):
        FakeMutex.behaviour = "abandoned"
        lock = rx_runner.MachineRunLock()
        self.assertTrue(lock.acquire())
        self.assertFalse(FakeMutex.made[0].disposed)
        lock.release()
        self.assertEqual(FakeMutex.made[0].released, 1)

    def test_another_windows_user_holding_it_is_false(self):
        FakeMutex.construct_error = FakeUnauthorized("access denied")
        self.assertFalse(rx_runner.MachineRunLock().acquire())

    def test_other_errors_propagate(self):
        FakeMutex.construct_error = RuntimeError("bad name")
        with self.assertRaises(RuntimeError):
            rx_runner.MachineRunLock().acquire()

    def test_a_second_engine_in_this_process_is_refused(self):
        # A Mutex is re-entrant on its owning thread, and every pyRevit engine runs on Revit's
        # UI thread: a process-wide marker keeps a second session's lock from re-entering it.
        first, second = rx_runner.MachineRunLock(), rx_runner.MachineRunLock()
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        self.assertEqual(len(FakeMutex.made), 1, "the second never touches the mutex")
        second.release()
        self.assertEqual(FakeMutex.made[0].released, 0)
        first.release()
        self.assertTrue(second.acquire())


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

    def test_extractor_tree_running_lists_both_process_names(self):
        with patch.dict(sys.modules, self.stubs()):
            self.assertIs(rx_runner.DotNetStarter().extractor_tree_running(), False)
            FakeProcessWithList.listed = [FakeListedProcess()]
            self.assertIs(rx_runner.DotNetStarter().extractor_tree_running(), True)
        self.assertIn("RevitExtractor", FakeProcessWithList.names)
        self.assertIn("RevitExtractor_Client", FakeProcessWithList.names)
        self.assertTrue(all(p.disposed for p in FakeProcessWithList.listed))
        self.assertEqual(FakeProcess.started, [], "the check starts nothing")


# --- cloud-catalog amendments (specs/SPEC-cloud-catalog.md, criterion 9) --------------------
# Synthetic GUIDs only (repeated digits), as the privacy guard in test_cloud.py requires.

P1 = "11111111-1111-1111-1111-111111111111"
M3 = "33333333-3333-3333-3333-333333333333"
M4 = "44444444-4444-4444-4444-444444444444"
CHUNK = 64 * 1024


class StageTicker(object):
    """The injectable stage clock: each call advances by `step` seconds; counts calls."""

    def __init__(self, step=0.015):
        self.now = 100.0
        self.step = step
        self.calls = 0

    def __call__(self):
        self.calls += 1
        self.now += self.step
        return self.now


class Remover(object):
    """os.remove stand-in that fails for the names in `locked` (a file still in use)."""

    def __init__(self):
        self.locked = set()
        self.removed = []

    def __call__(self, path):
        if os.path.basename(path) in self.locked:
            raise OSError("in use")
        os.remove(path)
        self.removed.append(path)


def sha256(path):
    import hashlib
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class QueueStagingTest(TempDirTest):
    """queued -> staging -> running; copies from a fake CollaborationCache tree."""

    def setUp(self):
        super(QueueStagingTest, self).setUp()
        self.revit = os.path.join(self.tmp, "Revit")
        os.makedirs(os.path.join(self.revit, "RevitExtractor"))
        open(os.path.join(self.revit, "RevitExtractor", "RevitExtractor.exe"), "w").close()
        self.out = os.path.join(self.tmp, "out")
        self.starter = FakeStarter()
        self.tokens = iter("%08x" % n for n in range(1, 1000))
        project = os.path.join(self.tmp, "Autodesk Revit X", "CollaborationCache", "99999999", P1)
        os.makedirs(os.path.join(project, "LinkedModels"))
        self.host = os.path.join(project, M3 + ".rvt")
        self.link = os.path.join(project, "LinkedModels", M4 + ".rvt")
        with open(self.host, "wb") as handle:
            handle.write(os.urandom(5 * CHUNK + 123))
        with open(self.link, "wb") as handle:
            handle.write(os.urandom(2 * CHUNK + 7))
        self.cache_root = os.path.dirname(os.path.dirname(project))
        self.cache_before = snapshot(self.cache_root)
        self.hashes = {path: sha256(path) for path in (self.host, self.link)}
        self.ticker = StageTicker()
        self.tree = Hold(False)
        self.remover = Remover()
        self.free = None

    def tearDown(self):
        self.assertEqual(snapshot(self.cache_root), self.cache_before, "the cache is never written")
        for path, digest in self.hashes.items():
            self.assertEqual(sha256(path), digest)

    def queue(self, max_parallel=1, hold=None, **kwargs):
        return Queue(self.starter, FakeClock(), max_parallel=max_parallel,
                     system_root=SYSTEM_ROOT, token=lambda: next(self.tokens), hold=hold,
                     stage_clock=self.ticker, stage_chunk=CHUNK,
                     free_space=lambda path: self.free, tree_running=self.tree,
                     remove=self.remover, **kwargs)

    def item(self, src, name):
        info = os.stat(src)
        return {"src": src, "name": name, "size": info.st_size, "mtime": info.st_mtime}

    def stage(self, host_name="Zażółć-Konstrukcja.rvt", link_name="Alpha-Architecture.rvt",
              notes=None):
        stage = {"items": [self.item(self.host, host_name)]}
        if link_name:
            stage["items"].append(self.item(self.link, link_name))
        if notes is not None:
            stage["notes"] = notes
        return stage

    def staged_job(self, stage=None, model_name="Zażółć-Konstrukcja.rvt",
                   model_key="cloud:%s/%s" % (P1, M3), model_path=None):
        stage = self.stage() if stage is None else stage
        return rx_runner.Job(model_path or self.host, SAMPLE_INDEX, self.revit, self.out,
                             stage=stage, model_name=model_name, model_key=model_key)

    def plain_job(self, name):
        return rx_runner.Job(os.path.join(self.tmp, "models", name + ".rvt"), SAMPLE_INDEX,
                             self.revit, self.out)

    def job(self, queue, job_id):
        return [job for job in queue.jobs() if job.id == job_id][0]

    def model_dir(self, job):
        return os.path.join(job.paths.root, "model")

    def poll_until(self, queue, job_id, states, limit=200):
        for _ in range(limit):
            queue.poll()
            if self.job(queue, job_id).state in states:
                return self.job(queue, job_id)
        self.fail("job never reached %s" % (states,))

    def exit(self, job, code=0, complete=True):
        if complete:
            open(os.path.join(job.paths.output, "bubble.json"), "w").close()
            os.makedirs(os.path.join(job.paths.output, "Resource"))
        with open(job.paths.console, "w") as handle:
            handle.write(SUMMARY_OK)
        handle = self.starter.handle_for(job.staged_model)
        handle.exited = True
        handle.code = code

    # -- states, model path and copies

    def test_queued_staging_running(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        self.assertEqual(self.job(queue, a).state, "queued")
        self.assertFalse(os.path.exists(self.out), "nothing is created while queued")
        queue.poll()
        job = self.job(queue, a)
        self.assertEqual(job.state, "staging")
        self.assertEqual(self.starter.started, [], "no process while copying")
        self.assertTrue(os.path.isfile(os.path.join(self.model_dir(job), "stage.json")))
        job = self.poll_until(queue, a, ("running",))
        target = os.path.join(job.paths.root, "model", "Zażółć-Konstrukcja.rvt")
        self.assertEqual(job.staged_model, target)
        (spec, handle), = self.starter.started
        self.assertEqual(spec.env["RX_MODEL"], target)
        self.assertEqual(spec.env["RX_INDEX"], job.paths.index)
        self.assertEqual(sha256(target), self.hashes[self.host])
        self.assertEqual(sha256(os.path.join(self.model_dir(job), "Alpha-Architecture.rvt")),
                         self.hashes[self.link])
        self.assertEqual(job.stage_done, job.stage_total)
        self.assertEqual(job.stage_total, os.path.getsize(self.host) + os.path.getsize(self.link))
        self.exit(job)
        queue.poll()
        self.assertEqual(self.job(queue, a).state, "ok")

    def test_changed_cache_file_adds_a_warning_but_not_a_failure(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        job = self.poll_until(queue, a, ("running",))
        info = os.stat(self.link)
        os.utime(self.link, ns=(info.st_atime_ns, info.st_mtime_ns + 60 * 10 ** 9))   # as if Revit wrote
        self.exit(job)
        queue.poll()
        job = self.job(queue, a)
        self.assertEqual(job.state, "ok")
        self.assertIn("cache file(s) changed during the export: Alpha-Architecture.rvt",
                      job.result.message)
        self.assertNotIn("hard links", job.result.message)
        os.utime(self.link, ns=(info.st_atime_ns, info.st_mtime_ns))    # tearDown checks the cache

    def test_unchanged_cache_files_add_no_warning(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        job = self.poll_until(queue, a, ("running",))
        self.exit(job)
        queue.poll()
        self.assertNotIn("changed during the export", self.job(queue, a).result.message)

    def test_stage_record_tells_how_each_file_was_staged(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        job = self.poll_until(queue, a, ("running",))
        with open(os.path.join(self.model_dir(job), "stage.json"), "rb") as handle:
            record = json.loads(handle.read().decode("ascii"))
        self.assertEqual([item["mode"] for item in record["items"]], ["copied", "copied"])
        self.assertEqual(job.stage_modes, {"Zażółć-Konstrukcja.rvt": "copied",
                                           "Alpha-Architecture.rvt": "copied"})

    def test_disk_check_counts_only_what_hard_links_cannot_save(self):
        total = os.path.getsize(self.host) + os.path.getsize(self.link)
        self.free = total + 1
        for writable, state in ((False, "failed"), (True, "staging")):
            for path in (self.host, self.link):
                os.chmod(path, 0o666 if writable else 0o444)
            def copier(plan, folder, chunk, report=None):
                return rx_runner.copy_steps(plan, folder, chunk=chunk, report=report)
            copier.accepts_report = True
            copier.linking = lambda: True
            queue = self.queue(copier=copier)
            a = queue.add(self.staged_job())
            queue.poll()
            self.assertEqual(self.job(queue, a).state, state, writable)
        for path in (self.host, self.link):
            os.chmod(path, 0o444)

    def test_progress_grows_and_each_poll_stays_within_its_budget(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        queue.poll()  # staging begins; the copy starts on this poll too
        seen = []
        while self.job(queue, a).state == "staging":
            before = self.ticker.calls
            start = self.ticker.now
            queue.poll()
            steps_time = self.ticker.now - start
            # one reading at the start, then one per chunk: stops once 40 ms are used
            # (the first reading itself advanced the ticker by one step)
            self.assertLessEqual(steps_time - self.ticker.step,
                                 rx_runner.STAGE_BUDGET + self.ticker.step + 1e-9)
            self.assertLessEqual(self.ticker.calls - before, 4)
            seen.append(self.job(queue, a).stage_done)
        self.assertEqual(seen, sorted(seen))
        self.assertGreater(len(seen), 2, "the copy is spread over several polls")

    def test_a_slow_step_still_ends_the_poll_after_one_chunk(self):
        self.ticker.step = 1.0
        queue = self.queue()
        a = queue.add(self.staged_job())
        queue.poll()
        done = []
        for _ in range(3):
            queue.poll()
            done.append(self.job(queue, a).stage_done)
        self.assertEqual(done, [CHUNK * 2, CHUNK * 3, CHUNK * 4][:len(done)])

    def test_stage_record_has_names_sizes_and_cache_dates_only(self):
        queue = self.queue()
        a = queue.add(self.staged_job(stage=self.stage(notes=["Link X is not in the cache."])))
        job = self.poll_until(queue, a, ("running",))
        with open(os.path.join(self.model_dir(job), "stage.json"), "rb") as handle:
            raw = handle.read()
        raw.decode("ascii")  # ASCII JSON, names escaped but kept as given
        record = json.loads(raw.decode("ascii"))
        self.assertEqual([item["name"] for item in record["items"]],
                         ["Zażółć-Konstrukcja.rvt", "Alpha-Architecture.rvt"])
        self.assertEqual([item["size"] for item in record["items"]],
                         [os.path.getsize(self.host), os.path.getsize(self.link)])
        expected = datetime.datetime.fromtimestamp(os.stat(self.host).st_mtime)
        self.assertEqual(record["items"][0]["cache_date"],
                         expected.strftime("%Y-%m-%d %H:%M:%S"))
        self.assertEqual(record["notes"], ["Link X is not in the cache."])
        self.assertNotIn(M3, raw.decode("ascii"), "no cache path or GUID in the record")
        self.assertNotIn("src", record["items"][0])

    # -- cancel

    def test_cancel_during_staging_starts_no_process(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        b = queue.add(self.plain_job("b"))
        queue.poll()
        queue.poll()
        job = self.job(queue, a)
        self.assertEqual(job.state, "staging")
        self.assertGreater(job.stage_done, 0)
        self.assertTrue(queue.cancel(a))
        self.assertEqual(job.state, "cancelled")
        self.assertIn("copying", job.result.message)
        self.assertFalse(queue.cancel(a), "only once")
        self.assertEqual(os.listdir(self.model_dir(job)), ["stage.json"],
                         "partial and finished copies are removed, the record stays")
        self.assertTrue(os.path.isdir(job.paths.root), "the run folder stays")
        queue.poll()
        self.assertEqual(self.starter.started_models(), [self.plain_job("b").model_path])
        self.assertEqual(self.job(queue, b).state, "running")
        self.assertEqual(self.starter.killed, [])

    def test_cancel_after_the_copy_while_held_starts_nothing(self):
        hold = Hold(False)
        queue = self.queue(hold=hold)
        a = queue.add(self.staged_job())
        queue.poll()
        hold.value = True  # a foreign Extractor started while we were copying
        for _ in range(50):
            queue.poll()
        job = self.job(queue, a)
        self.assertEqual(job.state, "staging")
        self.assertTrue(job.stage_ready)
        self.assertIs(queue.held, True)
        self.assertEqual(self.starter.started, [], "the launch waits for the hold gate")
        self.assertTrue(queue.cancel(a))
        self.assertEqual(sorted(os.listdir(self.model_dir(job))), ["stage.json"])
        hold.value = False
        queue.poll()
        self.assertEqual(self.starter.started, [])

    def test_launch_starts_once_the_hold_lifts(self):
        hold = Hold(False)
        queue = self.queue(hold=hold)
        a = queue.add(self.staged_job())
        queue.poll()
        hold.value = True
        for _ in range(50):
            queue.poll()
        hold.value = False
        queue.poll()
        self.assertEqual(self.job(queue, a).state, "running")

    def test_cancel_while_running_kills_and_removes_after_exit(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        job = self.poll_until(queue, a, ("running",))
        self.assertTrue(queue.cancel(a))
        self.assertEqual(len(self.starter.killed), 1)
        self.exit(job, code=1, complete=False)
        queue.poll()
        self.assertEqual(job.state, "cancelled")
        self.assertEqual(os.listdir(self.model_dir(job)), ["stage.json"])

    # -- failures

    def test_a_changed_cache_file_fails_only_that_job(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        b = queue.add(self.plain_job("b"))
        stage = self.job(queue, a).stage
        stage["items"][1]["size"] += 1  # the link changed after planning (as seen by the plan)
        job = self.poll_until(queue, a, ("failed",))
        self.assertIn("The cache file changed while it was copied", job.result.message)
        self.assertEqual(self.starter.started, [], "no process for the failed job")
        self.assertEqual(os.listdir(self.model_dir(job)), ["stage.json"],
                         "the copies this job made are removed at once (no process ran)")
        queue.poll()
        self.assertEqual(self.job(queue, b).state, "running")
        self.assertEqual(self.starter.started_models(), [self.plain_job("b").model_path])

    def test_copy_failure_message_in_polish(self):
        def run():
            queue = self.queue()
            job = self.staged_job()
            a = queue.add(job)
            job.stage["items"][0]["mtime"] += 5
            return self.poll_until(queue, a, ("failed",)).result.message
        with patch.dict(sys.modules, polish()):
            message = run()
        self.assertIn("Plik w pamięci podręcznej zmienił się podczas kopiowania", message)

    def test_any_copy_error_fails_the_job_and_the_queue_goes_on(self):
        def broken(plan, dest, chunk):
            yield 1, 2, StageItem(self.host, "x.rvt", 2, 0)
            raise IOError("disk full")
        queue = self.queue(copier=broken)
        a = queue.add(self.staged_job())
        b = queue.add(self.plain_job("b"))
        job = self.poll_until(queue, a, ("failed",))
        self.assertIn("disk full", job.result.message)
        queue.poll()
        self.assertEqual(self.job(queue, b).state, "running")

    def test_a_missing_source_fails_the_job(self):
        queue = self.queue()
        stage = self.stage()
        stage["items"][1]["src"] = os.path.join(os.path.dirname(self.link), "missing.rvt")
        a = queue.add(self.staged_job(stage=stage))
        job = self.poll_until(queue, a, ("failed",))
        self.assertEqual(self.starter.started, [])
        self.assertEqual(os.listdir(self.model_dir(job)), ["stage.json"])

    def test_not_enough_space_fails_before_any_folder(self):
        self.free = 10
        queue = self.queue()
        a = queue.add(self.staged_job())
        queue.poll()
        job = self.job(queue, a)
        self.assertEqual(job.state, "failed")
        self.assertIn("Not enough free disk space", job.result.message)
        self.assertFalse(os.path.exists(self.out))

    def test_unknown_or_broken_free_space_lets_the_copy_go_on(self):
        def broken(path):
            raise OSError("no drive")
        for free_space in (lambda path: None, broken):
            queue = Queue(self.starter, FakeClock(), system_root=SYSTEM_ROOT,
                          token=lambda: next(self.tokens), stage_clock=self.ticker,
                          stage_chunk=CHUNK, free_space=free_space)
            a = queue.add(self.staged_job())
            queue.poll()
            self.assertEqual(self.job(queue, a).state, "staging")
            queue.cancel(a)

    def test_launch_failure_after_the_copy_removes_the_copies(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        queue.poll()
        target = os.path.join(self.model_dir(self.job(queue, a)), "Zażółć-Konstrukcja.rvt")
        self.starter.fail_models.add(target)
        job = self.poll_until(queue, a, ("failed",))
        self.assertIn("cannot start", job.result.message)
        self.assertEqual(os.listdir(self.model_dir(job)), ["stage.json"])

    def test_missing_extractor_fails_before_the_copy(self):
        queue = self.queue()
        job = self.staged_job()
        job.revit_dir = os.path.join(self.tmp, "no revit")
        a = queue.add(job)
        queue.poll()
        self.assertEqual(self.job(queue, a).state, "failed")
        self.assertIsNone(self.job(queue, a).paths)

    def test_an_output_folder_in_the_cache_fails_before_anything_is_written(self):
        destinations = {
            "under CollaborationCache": os.path.join(self.cache_root, "exports"),
            "under the host's own folder": os.path.join(os.path.dirname(self.host), "exports"),
        }
        for label, out in destinations.items():
            with self.subTest(label):
                queue = self.queue()
                job = self.staged_job()
                job.output_parent = out
                a = queue.add(job)
                queue.poll()
                job = self.job(queue, a)
                self.assertEqual(job.state, "failed")
                self.assertIn("cache", job.result.message)
                self.assertIn("CollaborationCache", job.result.message)
                self.assertIsNone(job.paths)
                self.assertEqual(self.starter.started, [])
                self.assertFalse(queue.busy())
                self.assertEqual(snapshot(self.cache_root), self.cache_before,
                                 "no run folder, index or stage.json in the cache")
                self.assertFalse(os.path.exists(out))

    def test_an_output_folder_in_the_cache_message_in_polish(self):
        queue = self.queue()
        job = self.staged_job()
        job.output_parent = os.path.join(self.cache_root, "exports")
        a = queue.add(job)
        with patch.dict(sys.modules, polish()):
            queue.poll()
        message = self.job(queue, a).result.message
        self.assertIn("pamięci podręcznej", message)
        self.assertIn("CollaborationCache", message)

    def test_a_locked_copy_after_a_copy_failure_is_retried_and_then_reported(self):
        self.remover.locked.add("Zażółć-Konstrukcja.rvt")
        queue = self.queue()
        a = queue.add(self.staged_job())
        self.job(queue, a).stage["items"][1]["size"] += 1    # the link fails after the host
        job = self.poll_until(queue, a, ("failed",))
        self.assertIn("The cache file changed", job.result.message)
        self.assertEqual(sorted(os.listdir(self.model_dir(job))),
                         ["Zażółć-Konstrukcja.rvt", "stage.json"])
        self.assertEqual(job.cleanup, "pending")
        self.assertTrue(queue.busy(), "the timer keeps running for the clean-up")
        with patch.object(rx_runner, "CLEANUP_SECONDS", 5):
            for _ in range(10):
                queue.poll()
        self.assertEqual(job.cleanup, "incomplete")
        self.assertEqual(job.state, "failed")
        self.assertIn("The cache file changed", job.result.message)
        self.assertIn("could not be deleted", job.result.message)
        self.assertIn(self.model_dir(job), job.result.message)
        self.assertFalse(queue.busy())

    def test_revits_backup_folder_goes_even_with_read_only_files_inside(self):
        import stat
        folder = os.path.join(self.tmp, "run", "model", "Zażółć-Konstrukcja_backup")
        os.makedirs(os.path.join(folder, "inner"))
        for name in ("a.rvt", os.path.join("inner", "b.slog")):
            path = os.path.join(folder, name)
            with open(path, "wb") as handle:
                handle.write(b"x")
            os.chmod(path, stat.S_IREAD)
        rx_runner._rmtree_writable(folder)
        self.assertFalse(os.path.exists(folder))

    def test_stage_record_keeps_how_the_cleanup_ended(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        job = self.poll_until(queue, a, ("running",))
        self.exit(job)
        for _ in range(3):
            queue.poll()
        self.assertEqual(job.cleanup, "done")
        with open(os.path.join(self.model_dir(job), "stage.json"), "rb") as handle:
            record = json.loads(handle.read().decode("ascii"))
        self.assertEqual((record["cleanup"], record["cleanup_error"]), ("done", None))

    def test_a_failed_delete_leaves_its_error_type_in_the_record(self):
        self.remover.locked.add("Zażółć-Konstrukcja.rvt")
        queue = self.queue()
        a = queue.add(self.staged_job())
        self.job(queue, a).stage["items"][1]["size"] += 1
        job = self.poll_until(queue, a, ("failed",))
        with patch.object(rx_runner, "CLEANUP_SECONDS", 5):
            for _ in range(10):
                queue.poll()
        self.assertEqual(job.cleanup_error, "OSError")
        with open(os.path.join(self.model_dir(job), "stage.json"), "rb") as handle:
            record = json.loads(handle.read().decode("ascii"))
        self.assertEqual((record["cleanup"], record["cleanup_error"]), ("incomplete", "OSError"))
        self.assertNotIn(self.tmp, json.dumps(record), "no path in the record")

    def test_a_locked_copy_after_a_copy_failure_removed_on_a_later_poll(self):
        self.remover.locked.add("Zażółć-Konstrukcja.rvt")
        queue = self.queue()
        a = queue.add(self.staged_job())
        self.job(queue, a).stage["items"][1]["size"] += 1
        job = self.poll_until(queue, a, ("failed",))
        self.assertEqual(job.cleanup, "pending")
        self.remover.locked.clear()
        queue.poll()
        self.assertEqual(job.cleanup, "done")
        self.assertEqual(os.listdir(self.model_dir(job)), ["stage.json"])
        self.assertFalse(queue.busy())

    def test_a_locked_copy_after_a_launch_failure_is_retried_and_then_reported(self):
        self.remover.locked.add("Alpha-Architecture.rvt")
        queue = self.queue()
        a = queue.add(self.staged_job())
        queue.poll()
        target = os.path.join(self.model_dir(self.job(queue, a)), "Zażółć-Konstrukcja.rvt")
        self.starter.fail_models.add(target)
        job = self.poll_until(queue, a, ("failed",))
        self.assertIn("cannot start", job.result.message)
        self.assertEqual(sorted(os.listdir(self.model_dir(job))),
                         ["Alpha-Architecture.rvt", "stage.json"])
        self.assertEqual(job.cleanup, "pending")
        self.assertTrue(queue.busy())
        with patch.object(rx_runner, "CLEANUP_SECONDS", 5):
            for _ in range(10):
                queue.poll()
        self.assertEqual(job.cleanup, "incomplete")
        self.assertIn("cannot start", job.result.message)
        self.assertIn(self.model_dir(job), job.result.message)
        self.assertFalse(queue.busy())

    # -- same model, one at a time

    def test_the_same_model_key_never_runs_twice(self):
        queue = self.queue(max_parallel=2)
        first = queue.add(self.staged_job())
        second = queue.add(self.staged_job())
        queue.poll()
        self.assertEqual(self.job(queue, first).state, "staging")
        self.assertEqual(self.job(queue, second).state, "queued", "same key while staging")
        job = self.poll_until(queue, first, ("running",))
        queue.poll()
        self.assertEqual(self.job(queue, second).state, "queued", "same key while running")
        self.exit(job)
        self.poll_until(queue, second, ("staging", "running"))

    def test_model_key_is_used_for_plain_jobs_too(self):
        queue = self.queue(max_parallel=2)
        a = self.plain_job("a")
        a.model_key = "same"
        b = self.plain_job("b")
        b.model_key = "SAME"
        queue.add(a)
        queue.add(b)
        queue.poll()
        self.assertEqual([j.state for j in queue.jobs()], ["running", "queued"])

    def test_staging_takes_the_only_slot(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        b = queue.add(self.plain_job("b"))
        queue.poll()
        self.assertEqual([j.state for j in queue.jobs()], ["staging", "queued"])
        self.poll_until(queue, a, ("running",))
        self.assertEqual(self.job(queue, b).state, "queued", "runs stay one at a time")

    # -- clean-up after the run

    def test_copies_are_removed_only_after_the_process_tree_exited(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        job = self.poll_until(queue, a, ("running",))
        folder = self.model_dir(job)
        other = os.path.join(folder, "written-by-the-extractor.txt")
        open(other, "w").close()
        queue.poll()
        self.assertEqual(len(os.listdir(folder)), 4, "nothing is removed while running")
        self.tree.value = True  # cmd.exe has exited, but an Extractor process is still listed
        self.exit(job)
        queue.poll()
        self.assertEqual(job.state, "ok")
        self.assertEqual(job.cleanup, "pending")
        self.assertTrue(queue.busy(), "the timer keeps running for the clean-up")
        self.assertEqual(len(os.listdir(folder)), 4)
        self.tree.value = False
        queue.poll()
        self.assertEqual(job.cleanup, "done")
        self.assertEqual(sorted(os.listdir(folder)),
                         ["stage.json", "written-by-the-extractor.txt"],
                         "only the copies this job staged are removed")
        self.assertTrue(os.path.isfile(os.path.join(job.paths.output, "bubble.json")))
        self.assertFalse(queue.busy())

    def test_a_locked_copy_is_retried_and_then_reported(self):
        self.remover.locked.add("Alpha-Architecture.rvt")
        queue = self.queue()
        a = queue.add(self.staged_job())
        job = self.poll_until(queue, a, ("running",))
        self.exit(job)
        queue.poll()
        self.assertEqual(job.cleanup, "pending")
        self.assertEqual(sorted(os.listdir(self.model_dir(job))),
                         ["Alpha-Architecture.rvt", "stage.json"])
        with patch.object(rx_runner, "CLEANUP_SECONDS", 5):
            for _ in range(10):
                queue.poll()
        self.assertEqual(job.cleanup, "incomplete")
        self.assertEqual(job.state, "ok", "the export result itself stands")
        self.assertIn("could not be deleted", job.result.message)
        self.assertIn(self.model_dir(job), job.result.message)
        self.assertFalse(queue.busy())

    def test_a_locked_copy_removed_on_a_later_poll(self):
        self.remover.locked.add("Alpha-Architecture.rvt")
        queue = self.queue()
        a = queue.add(self.staged_job())
        job = self.poll_until(queue, a, ("running",))
        self.exit(job)
        queue.poll()
        self.remover.locked.clear()
        queue.poll()
        self.assertEqual(job.cleanup, "done")
        self.assertEqual(os.listdir(self.model_dir(job)), ["stage.json"])

    def test_the_backup_folder_revit_left_beside_a_copy_is_removed(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        job = self.poll_until(queue, a, ("running",))
        backup = os.path.join(self.model_dir(job), "Alpha-Architecture_backup")
        os.makedirs(backup)
        with open(os.path.join(backup, "Alpha-Architecture.0001.rvt"), "wb") as handle:
            handle.write(b"x")
        self.exit(job)
        queue.poll()
        self.assertEqual(job.cleanup, "done")
        self.assertEqual(os.listdir(self.model_dir(job)), ["stage.json"])

    def test_clear_finished_does_not_stop_a_pending_clean_up(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        job = self.poll_until(queue, a, ("running",))
        self.tree.value = True
        self.exit(job)
        queue.poll()
        self.assertEqual(queue.clear_finished(), [a])
        self.tree.value = False
        queue.poll()
        self.assertEqual(job.cleanup, "done")
        self.assertEqual(os.listdir(self.model_dir(job)), ["stage.json"])

    def test_notes_are_added_to_the_result(self):
        queue = self.queue()
        a = queue.add(self.staged_job(stage=self.stage(
            notes=["Link Beta-MEP.rvt is not in the cache; exported without it."])))
        job = self.poll_until(queue, a, ("running",))
        self.exit(job)
        queue.poll()
        self.assertIn("Export finished", job.result.message)
        self.assertIn("Link Beta-MEP.rvt is not in the cache", job.result.message)

    def test_job_record_has_the_stage_fields(self):
        queue = self.queue()
        a = queue.add(self.staged_job())
        record = self.job(queue, a).as_dict()
        self.assertEqual(record["model_name"], "Zażółć-Konstrukcja.rvt")
        self.assertEqual(record["model_key"], "cloud:%s/%s" % (P1, M3))
        self.assertEqual(len(record["stage"]["items"]), 2)
        self.assertEqual(record["stage_done"], 0)
        self.assertIsNone(record["cleanup"])

    # -- validation in add()

    def test_add_validates_the_stage(self):
        def with_items(*changes):
            stage = self.stage()
            for index, key, value in changes:
                if key is None:
                    stage["items"][index] = value
                else:
                    stage["items"][index][key] = value
            return stage
        bad = {
            "stage not a dict": dict(stage=[self.item(self.host, "a.rvt")]),
            "no items": dict(stage={"items": []}),
            "items not a list": dict(stage={"items": "x"}),
            "entry not a dict": dict(stage=with_items((1, None, [self.link, "b.rvt", 1, 1]))),
            "relative src": dict(stage=with_items((1, "src", "LinkedModels\\b.rvt"))),
            "quote in src": dict(stage=with_items((1, "src", self.link + '"'))),
            "line break in src": dict(stage=with_items((1, "src", self.link + "\n"))),
            "folder in name": dict(stage=with_items((1, "name", "..\\b.rvt"))),
            "not rvt": dict(stage=with_items((1, "name", "stage.json"))),
            "same name": dict(stage=with_items((1, "name", "ZAŻÓŁĆ-konstrukcja.RVT"))),
            "negative size": dict(stage=with_items((1, "size", -1))),
            "bool size": dict(stage=with_items((1, "size", True))),
            "text mtime": dict(stage=with_items((1, "mtime", "yesterday"))),
            "missing key": dict(stage={"items": [{"src": self.host, "name": "a.rvt"}]}),
            "notes not text": dict(stage=dict(self.stage(), notes=[1])),
            "no model name": dict(model_name=None),
            "model name is not the host": dict(model_name="Alpha-Architecture.rvt"),
            "model path is not the host": dict(model_path=self.link),
            "bad key": dict(model_key="a\nb"),
            "empty key": dict(model_key=" "),
        }
        queue = self.queue()
        for label, changes in bad.items():
            with self.subTest(label):
                with self.assertRaises(RunnerError):
                    queue.add(self.staged_job(**changes))
        plain = self.plain_job("a")
        plain.model_name = "a.rvt"
        with self.assertRaises(RunnerError, msg="model_name needs a stage"):
            queue.add(plain)
        self.assertEqual(queue.jobs(), [])

    def test_add_copies_the_stage_as_plain_dicts(self):
        queue = self.queue()
        stage = self.stage()
        job = self.staged_job(stage=stage)
        queue.add(job)
        self.assertIsNot(job.stage, stage)
        stage["items"][0]["name"] = "changed.rvt"
        self.assertEqual(job.stage["items"][0]["name"], "Zażółć-Konstrukcja.rvt")
        self.assertTrue(all(type(item) is dict for item in job.stage["items"]))
        self.assertEqual(job.stage["notes"], [])

    def test_plain_jobs_never_touch_the_stage_clock(self):
        def no_clock():
            raise AssertionError("the stage clock is only read while copying")
        queue = Queue(self.starter, FakeClock(), system_root=SYSTEM_ROOT,
                      token=lambda: next(self.tokens), stage_clock=no_clock)
        a = queue.add(self.plain_job("a"))
        queue.poll()
        job = self.job(queue, a)
        self.assertEqual(job.state, "running")
        self.assertFalse(os.path.exists(os.path.join(job.paths.root, "model")))
        self.assertIsNone(job.staged_model)
        self.assertIsNone(job.cleanup)

    def test_naming_gets_one_step_when_staging_uses_the_whole_budget(self):
        # named copies (Task 5): the copy budget is shared; naming does not wait for the clean-up
        namer = FakeNamer(steps=4)
        self.tree.value = True            # the staged copies cannot be deleted yet
        queue = self.queue(namer=namer)
        first = self.staged_job()
        first.naming = dict(NAMING)
        a = queue.add(first)
        job_a = self.poll_until(queue, a, ("running",))
        b = queue.add(self.staged_job())  # same model: starts once a has ended
        self.exit(job_a)
        queue.poll()      # a ends; b starts staging and copies for the whole budget
        self.assertEqual(job_a.state, "ok")
        self.assertEqual(job_a.cleanup, "pending")
        self.assertEqual(self.job(queue, b).state, "staging")
        counts = [len(namer.log)]
        while self.job(queue, b).state == "staging" and job_a.naming_state == "running":
            before = len(namer.log)
            queue.poll()
            counts.append(len(namer.log) - before)
        self.assertEqual(counts[:2], [1, 1], "staging used the budget: one naming step each")
        while job_a.naming_state == "running":
            queue.poll()
        self.assertEqual((job_a.state, job_a.naming_state), ("ok", "done"))
        self.assertEqual(job_a.cleanup, "pending", "naming did not wait for the clean-up")
        self.tree.value = False
        queue.cancel(b)
        for _ in range(3):
            queue.poll()


# --- Named copies, Task 5 (SPEC-named-copies.md criterion 7) ---------------------------------

import rx_naming  # noqa: E402

NAMING = {"template": "{OriginalName}", "system": {}, "values": None}


class FakeRun(object):
    """Stands for rx_naming.NamedRun: `steps` steps, then `final`; logs every step."""

    def __init__(self, namer, paths, naming):
        self.namer, self.paths, self.naming = namer, paths, naming
        self.state = None
        self.done = 0
        self.total = namer.steps
        self.messages = 0
        self.closed = False

    def steps(self):
        self.state = "running"
        try:
            for number in range(self.total):
                if self.namer.raise_at == number:
                    raise OSError("step failed")
                self.done = number + 1
                self.namer.log.append((self.paths.root, number))
                yield self.done, self.total
        except GeneratorExit:
            self.closed = True
            raise
        self.state = self.namer.final

    def result_message(self):
        self.messages += 1
        return "Named: %s." % self.state


class FakeNamer(object):
    def __init__(self, steps=3, final="done", raise_at=None, fail_create=False):
        self.steps, self.final, self.raise_at, self.fail_create = steps, final, raise_at, fail_create
        self.calls = []
        self.runs = []
        self.log = []

    def __call__(self, paths, naming):
        self.calls.append((paths, naming))
        if self.fail_create:
            raise ValueError("namer broke")
        run = FakeRun(self, paths, naming)
        self.runs.append(run)
        return run


class NamingQueueTest(TempDirTest):
    """Named copies after an ok export: queue state, shared budget, failure isolation."""
    # QueueTest's fixtures and helpers without re-running its tests.
    model = QueueTest.model
    job = QueueTest.job
    finish = QueueTest.finish

    def setUp(self):
        super(NamingQueueTest, self).setUp()
        self.revit = os.path.join(self.tmp, "Revit")
        os.makedirs(os.path.join(self.revit, "RevitExtractor"))
        open(os.path.join(self.revit, "RevitExtractor", "RevitExtractor.exe"), "w").close()
        self.out = os.path.join(self.tmp, "out")
        self.starter = FakeStarter()
        self.tokens = iter("%08x" % n for n in range(1, 1000))
        self.namer = FakeNamer()
        self.ticker = StageTicker()     # 0.015 s per reading; STAGE_BUDGET 0.04

    def queue(self, max_parallel=1, **kwargs):
        kwargs.setdefault("namer", self.namer)
        return Queue(self.starter, FakeClock(), max_parallel=max_parallel,
                     system_root=SYSTEM_ROOT, token=lambda: next(self.tokens),
                     stage_clock=self.ticker, **kwargs)

    def add(self, queue, name, naming=NAMING):
        return queue.add(rx_runner.Job(self.model(name), SAMPLE_INDEX, self.revit, self.out,
                                       naming=dict(naming) if naming else None))

    def finished_ok(self, queue, name="a"):
        job_id = self.add(queue, name)
        queue.poll()
        self.finish(queue, job_id)
        return job_id

    def poll_naming(self, queue, job_id, limit=50):
        for _ in range(limit):
            queue.poll()
            if self.job(queue, job_id).naming_state in ("done", "partial", "failed"):
                return self.job(queue, job_id)
        self.fail("naming never ended")

    def test_an_ok_job_with_naming_is_named_and_its_state_never_changes(self):
        queue = self.queue()
        a = self.finished_ok(queue)
        changed = queue.poll()
        job = self.job(queue, a)
        self.assertIn(a, changed)
        self.assertEqual(job.state, "ok")
        self.assertEqual(len(self.namer.calls), 1)
        self.assertEqual(self.namer.calls[0], (job.paths, NAMING))
        self.assertIn(job.naming_state, ("running", "done"))
        job = self.poll_naming(queue, a)
        self.assertEqual((job.state, job.naming_state), ("ok", "done"))
        self.assertEqual((job.naming_done, job.naming_total), (3, 3))
        self.assertEqual(self.namer.runs[0].messages, 1)
        self.assertTrue(job.result.message.endswith(" Named: done."), job.result.message)
        self.assertEqual(job.result.message.count("Named:"), 1)
        for _ in range(3):
            queue.poll()
        self.assertEqual(job.result.message.count("Named:"), 1, "appended once")
        self.assertEqual(len(self.namer.calls), 1)
        self.assertFalse(queue.busy())

    def test_a_partial_or_failed_naming_keeps_the_job_ok(self):
        for final in ("partial", "failed"):
            with self.subTest(final):
                self.namer = FakeNamer(final=final)
                queue = self.queue()
                job = self.poll_naming(queue, self.finished_ok(queue))
                self.assertEqual((job.state, job.result.state, job.naming_state),
                                 ("ok", "ok", final))
                self.assertIn("Named: %s." % final, job.result.message)

    def test_failed_cancelled_and_plain_jobs_are_never_named(self):
        queue = self.queue()
        failed = self.add(queue, "a")
        queue.poll()
        self.finish(queue, failed, code=1)
        queue.poll()
        cancelled = self.add(queue, "b")
        queue.cancel(cancelled)      # before it starts
        incomplete = self.add(queue, "c")
        plain = self.add(queue, "d", naming=None)
        for job_id, kwargs in ((incomplete, {"complete": False}), (plain, {})):
            self.poll_until_running(queue, job_id)
            self.finish(queue, job_id, **kwargs)
        for _ in range(3):
            queue.poll()
        states = dict((j.id, (j.state, j.naming_state)) for j in queue.jobs())
        self.assertEqual(states[failed], ("failed", None))
        self.assertEqual(states[cancelled], ("cancelled", None))
        self.assertEqual(states[incomplete], ("failed", None))
        self.assertEqual(states[plain], ("ok", None))
        self.assertEqual(self.namer.calls, [], "a job without naming never calls the namer")
        self.assertFalse(queue.busy())

    def poll_until_running(self, queue, job_id, limit=10):
        for _ in range(limit):
            queue.poll()
            if self.job(queue, job_id).state == "running":
                return
        self.fail("never started")

    def test_a_running_job_cancelled_is_never_named(self):
        queue = self.queue()
        a = self.add(queue, "a")
        queue.poll()
        self.assertTrue(queue.cancel(a))
        self.finish(queue, a)
        queue.poll()
        queue.poll()
        job = self.job(queue, a)
        self.assertEqual((job.state, job.naming_state), ("cancelled", None))
        self.assertEqual(self.namer.calls, [])

    def test_each_poll_names_within_the_budget_and_at_least_one_step(self):
        self.namer = FakeNamer(steps=10)
        queue = self.queue()
        a = self.finished_ok(queue)
        queue.poll()     # finishes the export; naming starts in the same poll
        per_poll = [len(self.namer.log)]
        while self.job(queue, a).naming_state == "running":
            before = len(self.namer.log)
            queue.poll()
            per_poll.append(len(self.namer.log) - before)
        # one reading at the start, then one per step: 0.015, 0.030, 0.045 >= 0.04 -> 3 steps
        self.assertEqual(per_poll[:3], [3, 3, 3])
        self.assertEqual(sum(per_poll), 10)
        self.assertEqual(self.job(queue, a).naming_state, "done")

    def test_a_tiny_budget_still_makes_one_step_per_poll(self):
        queue = self.queue(stage_budget=0.0)
        a = self.finished_ok(queue)
        counts = []
        for _ in range(4):
            before = len(self.namer.log)
            queue.poll()
            counts.append(len(self.namer.log) - before)
        self.assertEqual(counts[:3], [1, 1, 1])
        self.assertEqual(self.job(queue, a).naming_state, "done")

    def test_several_jobs_are_named_one_after_another_in_order(self):
        queue = self.queue()
        a, b = self.add(queue, "a"), self.add(queue, "b")
        queue.poll()
        self.finish(queue, a)
        queue.poll()         # a ends; b starts
        self.finish(queue, b)
        queue.poll()         # b ends too
        roots = [root for root, _ in self.namer.log]
        root_a, root_b = self.job(queue, a).paths.root, self.job(queue, b).paths.root
        while queue.busy():
            queue.poll()
            roots = [root for root, _ in self.namer.log]
        self.assertEqual(roots, [root_a] * 3 + [root_b] * 3, "FIFO, one at a time")
        self.assertEqual([self.job(queue, j).naming_state for j in (a, b)], ["done", "done"])

    def test_the_next_export_starts_and_runs_while_the_last_is_named(self):
        self.namer = FakeNamer(steps=50)
        lock = FakeLock(LockState())
        queue = self.queue(lock=lock)
        a, b = self.add(queue, "a"), self.add(queue, "b")
        queue.poll()
        self.finish(queue, a)
        queue.poll()
        self.assertEqual(self.job(queue, a).naming_state, "running")
        self.assertEqual(self.job(queue, b).state, "running", "naming never holds back an export")
        self.finish(queue, b)
        queue.poll()
        self.assertEqual(self.job(queue, b).state, "ok")
        self.assertEqual(self.job(queue, a).naming_state, "running")
        self.assertFalse(lock.state.owner, "the run lock is given back while naming goes on")
        self.assertTrue(queue.busy())

    def test_busy_and_clear_finished_wait_for_naming(self):
        queue = self.queue()
        a = self.finished_ok(queue)
        done = self.add(queue, "plain", naming=None)
        self.poll_until_running(queue, done)
        self.assertEqual(self.poll_naming(queue, a).naming_state, "done")
        self.finish(queue, done)
        self.namer.steps = 9
        c = self.add(queue, "c")
        self.poll_until_running(queue, c)
        self.finish(queue, c)
        queue.poll()
        self.assertEqual(self.job(queue, c).naming_state, "running")
        self.assertTrue(queue.busy())
        self.assertEqual(sorted(queue.clear_finished()), sorted([a, done]))
        self.assertEqual([j.id for j in queue.jobs()], [c], "its row stays while it is named")
        self.poll_naming(queue, c)
        self.assertFalse(queue.busy())
        self.assertEqual(queue.clear_finished(), [c])

    def test_a_namer_that_raises_at_creation_fails_the_naming_only(self):
        self.namer = FakeNamer(fail_create=True)
        queue = self.queue()
        a, b = self.add(queue, "a"), self.add(queue, "b")
        queue.poll()
        self.finish(queue, a)
        queue.poll()
        job = self.job(queue, a)
        self.assertEqual((job.state, job.naming_state), ("ok", "failed"))
        self.assertTrue(job.result.message.endswith("Named copies were not made: namer broke"))
        self.assertEqual(self.job(queue, b).state, "running", "the queue goes on")
        self.finish(queue, b)
        queue.poll()
        self.assertEqual(self.job(queue, b).naming_state, "failed")
        self.assertEqual(len(self.namer.calls), 2)

    def test_a_step_that_raises_fails_the_naming_only_and_is_closed(self):
        self.namer = FakeNamer(steps=5, raise_at=2)
        queue = self.queue()
        job = self.poll_naming(queue, self.finished_ok(queue))
        self.assertEqual((job.state, job.naming_state), ("ok", "failed"))
        self.assertIn("Named copies were not made: step failed", job.result.message)
        self.assertEqual(job.result.message.count("Named copies were not made"), 1)
        self.assertEqual(job.naming_done, 2)
        self.assertFalse(queue.busy())

    def test_a_run_without_an_end_state_is_failed(self):
        self.namer = FakeNamer(final="running")
        queue = self.queue()
        job = self.poll_naming(queue, self.finished_ok(queue))
        self.assertEqual(job.naming_state, "failed")
        self.assertIn("without a result", job.result.message)

    def test_the_failure_note_is_polish_too(self):
        self.namer = FakeNamer(fail_create=True)
        with patch.dict(sys.modules, polish()):
            queue = self.queue()
            job = self.poll_naming(queue, self.finished_ok(queue))
        self.assertIn("Nie utworzono kopii z nazwami: namer broke", job.result.message)

    def test_close_closes_the_naming_generator(self):
        self.namer = FakeNamer(steps=50)
        queue = self.queue()
        a = self.finished_ok(queue)
        queue.poll()
        self.assertEqual(self.job(queue, a).naming_state, "running")
        queue.close()
        self.assertTrue(self.namer.runs[0].closed)
        self.assertFalse(queue.busy())
        before = len(self.namer.log)
        queue.poll()
        self.assertEqual(len(self.namer.log), before, "nothing resumes it")

    def test_a_bad_naming_refuses_the_job_in_english_and_polish(self):
        bad = {"template": "{Nope}", "system": {}, "values": None}
        for modules in ({}, polish()):
            with patch.dict(sys.modules, modules):
                with self.assertRaises(rx_naming.NamingError) as expected:
                    rx_naming.check_naming(bad)
                queue = self.queue()
                for naming in (bad, {"template": "{OriginalName}", "system": {"A": 1}},
                               "not a dict"):
                    with self.subTest(naming=naming):
                        job = rx_runner.Job(self.model("a"), SAMPLE_INDEX, self.revit, self.out,
                                            naming=naming)
                        with self.assertRaises(RunnerError):
                            queue.add(job)
                        self.assertIsNone(job.id)
                message = message_of(queue.add, rx_runner.Job(
                    self.model("a"), SAMPLE_INDEX, self.revit, self.out, naming=bad))
                self.assertEqual(message, str(expected.exception))
                self.assertEqual(queue.jobs(), [])
        self.assertNotEqual(message_of(self.queue().add, rx_runner.Job(
            self.model("a"), SAMPLE_INDEX, self.revit, self.out, naming=bad)), message)

    def test_a_foreign_job_is_never_named(self):
        queue = self.queue()
        job = rx_runner.Job(self.model("a"), SAMPLE_INDEX, self.revit, self.out, naming=NAMING)
        job.foreign = True
        with self.assertRaises(RunnerError):
            queue.add(job)
        # an adopted run never gets naming, even if one is set on it afterwards
        root = os.path.join(self.out, "export-20261118-110000-bbbbbbbb")
        os.makedirs(os.path.join(root, "output", "Resource"))
        open(os.path.join(root, "output", "bubble.json"), "w").close()
        with open(os.path.join(root, "console.log"), "w") as handle:
            handle.write(SUMMARY_OK)
        running = Hold(True)
        adopted = queue.adopt_run(rx_runner.run_paths_for(root), running=running)
        self.job(queue, adopted).naming = dict(NAMING)
        running.value = False
        queue.poll()
        queue.poll()
        job = self.job(queue, adopted)
        self.assertEqual((job.state, job.naming_state), ("ok", None))
        self.assertEqual(self.namer.calls, [])

    def test_as_dict_has_the_naming_fields_but_not_the_naming(self):
        queue = self.queue()
        a = self.finished_ok(queue)
        data = self.job(queue, a).as_dict()
        self.assertEqual((data["naming_state"], data["naming_done"], data["naming_total"]),
                         (None, 0, 0))
        self.assertNotIn("naming", data)
        job = self.poll_naming(queue, a)
        data = job.as_dict()
        self.assertEqual((data["naming_state"], data["naming_done"], data["naming_total"]),
                         ("done", 3, 3))
        self.assertNotIn("{OriginalName}", json.dumps(data))

    def test_the_default_namer_is_the_real_named_run(self):
        queue = Queue(self.starter, FakeClock(), system_root=SYSTEM_ROOT,
                      token=lambda: next(self.tokens))
        a = queue.add(rx_runner.Job(self.model("a"), SAMPLE_INDEX, self.revit, self.out,
                                    naming=dict(NAMING)))
        queue.poll()
        job = self.job(queue, a)
        self.finish(queue, a)         # an empty bubble.json: NamedRun refuses, changes nothing
        before = snapshot(job.paths.output)
        for _ in range(20):
            queue.poll()
            if job.naming_state not in ("pending", "running"):
                break
        self.assertEqual((job.state, job.naming_state), ("ok", "failed"))
        self.assertIn("Named copies were not made: bubble.json could not be read",
                      job.result.message)
        self.assertEqual(snapshot(job.paths.output), before)
        self.assertFalse(os.path.exists(os.path.join(job.paths.root, "named")))

    def test_the_real_named_run_makes_named_copies_after_an_ok_export(self):
        queue = Queue(self.starter, FakeClock(), system_root=SYSTEM_ROOT,
                      token=lambda: next(self.tokens))
        a = queue.add(rx_runner.Job(self.model("a"), SAMPLE_INDEX, self.revit, self.out,
                                    naming=dict(NAMING)))
        queue.poll()
        job = self.job(queue, a)
        self.finish(queue, a)
        with open(os.path.join(job.paths.output, "bubble.json"), "w") as handle:
            handle.write("{}")
        with open(os.path.join(job.paths.output, "Model.ifc"), "wb") as handle:
            handle.write(b"ifc" * 10)
        before = snapshot(job.paths.output)
        for _ in range(20):
            queue.poll()
            if job.naming_state not in ("pending", "running"):
                break
        self.assertEqual((job.state, job.naming_state), ("ok", "done"))
        self.assertEqual((job.naming_done, job.naming_total), (1, 1))
        self.assertIn("Named copies: 1 in named\\", job.result.message)
        self.assertTrue(os.path.isfile(os.path.join(job.paths.root, "named", "Model.ifc")))
        self.assertEqual(snapshot(job.paths.output), before, "output\\ is never changed")


if __name__ == "__main__":
    unittest.main()
