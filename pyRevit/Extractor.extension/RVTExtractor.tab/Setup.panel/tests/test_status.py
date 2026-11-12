# -*- coding: utf-8 -*-
"""status-window (specs/SPEC-status-window.md): lib/rx_status.py and lib/rx_status_ui.py.

CPython 3 with WPF, System and pyRevit stubbed. Cannot prove anything inside Revit: the call
between two IronPython engines through the delegate, the modeless window, the timer next to
Revit's own work, minimise/restore and Revit closing are in specs/v1-revit-test.md.
Console fixture lines are copied from the Dynamo sample run of 2026-11-10 (never a client log).
"""
import ast
import datetime
import json
import os
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

LIB = Path(__file__).resolve().parents[3] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))  # append, never insert (same-named modules in the bundles)

import rx_runner  # noqa: E402
import rx_status  # noqa: E402
from rx_status import (PROTOCOL, SESSION_KEY, WEBSITE_URL, SessionCore,  # noqa: E402
                       analyzer_plan, find_session, job_view, progress_info, publish_session)
from wpf_fakes import (Collection, Control, Event, Items, SharedEventReactive,  # noqa: E402
                       polish, reactive, stub_module)

ON_WINDOWS = os.name == "nt"
ROOT = "C:" + os.sep if ON_WINDOWS else os.sep
XNAME = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
NOW = datetime.datetime(2026, 11, 11, 10, 0, 0)
MODEL = os.path.join(ROOT, "Projects", "Sample House", "DynamoSample_2023.rvt")
REVIT = os.path.join(ROOT, "Program Files", "Autodesk", "Revit X")
OUT = os.path.join(ROOT, "Exports")
INDEX = {"metadata": {"parameters": {"derivative_type": {"2dviewing": {}, "3dviewing": {}}}}}

# Lines from console.log of the Dynamo sample run (Revit 2023 Extractor, 2026-11-10), CRLF as
# written. The first line starts mid-line, as a 64 KiB tail usually does.
TASK_OPEN = ('[[extractor-metrics]]:{"rvt-TaskData":{"rvt-ClientIndex":"0","rvt-TaskName":'
             '"Open RVT file.","rvt-ElapsedTime":"3329","rvt-PeakPhysicalMemoryUsage":"639",'
             '"rvt-Status":"completed"}}')
TASK_SVF = ('[[extractor-metrics]]:{"rvt-TaskData":{"rvt-ClientIndex":"0","rvt-TaskName":'
            '"Export SVF For 3D Views. Views Count: 1","rvt-ElapsedTime":"1874",'
            '"rvt-PeakPhysicalMemoryUsage":"639","rvt-Status":"completed"}}')
REAL_TAIL = "\r\n".join([
    'd2862ea8ec77850509bc3b077299acf9a09f84dc INFO Revit file opened by RCE version: 2023',
    '[[extractor-metrics]]:{"rvt-VersionNumber":"2023"}',
    '- 2026-11-10 19:39:05,442 build_commit:d2862ea8ec77850509bc3b077299acf9a09f84dc INFO '
    'Job Started []',
    TASK_OPEN,
    '[[extractor-metrics]]:{"rvt-TaskData":{"rvt-ClientIndex":"0","rvt-TaskName":'
    '"Resolve the link files.","rvt-ElapsedTime":"8","rvt-PeakPhysicalMemoryUsage":"639",'
    '"rvt-Status":"completed"}}',
    '[[extractor-metrics]]:{"rvt-Exported3DView":"1","rvt-Exported2DViews":"5",'
    '"rvt-ExportedSheets":"5"}',
    '[[progress]]:{"44745acb-ebea-4fb9-a091-88d28bd746c7-000ea86d": "10"}',
    '[[progress]]:{"44745acb-ebea-4fb9-a091-88d28bd746c7-000ea86d": "35"}',
    '[[progress]]:{"44745acb-ebea-4fb9-a091-88d28bd746c7-000ea86d": "100"}',
    TASK_SVF,
    '[[progress]]:{"6d3acd40-53b7-41b4-9d96-72e9eaf4bc89-0005d699": "30"}',
    '[[extractor-metrics]]:{"rvt-ElapsedTime":"85135"}',
    '- 2026-11-10 19:40:29,598 build_commit:d2862ea8ec77850509bc3b077299acf9a09f84dc INFO '
    'Success Jobs: 13, Failed Jobs: 0',
    '',
])


def under_polish(function, *args, **kwargs):
    with patch.dict(sys.modules, polish()):
        return function(*args, **kwargs)


# --- Criterion 1: progress_info ---------------------------------------------------------------

class ProgressInfo(unittest.TestCase):
    def test_last_task_status_and_percentage_of_the_real_run(self):
        self.assertEqual(progress_info(REAL_TAIL),
                         {"task": "Export SVF For 3D Views. Views Count: 1",
                          "status": "completed", "percent": 30})

    def test_metrics_lines_without_task_data_are_ignored(self):
        tail = TASK_OPEN + "\r\n" + '[[extractor-metrics]]:{"rvt-ElapsedTime":"85135"}\r\n'
        self.assertEqual(progress_info(tail)["task"], "Open RVT file.")
        only_metrics = ('[[extractor-metrics]]:{"rvt-VersionNumber":"2023"}\r\n'
                        '[[extractor-metrics]]:{"rvt-FilePathType":"Others"}\r\n')
        self.assertEqual(progress_info(only_metrics),
                         {"task": None, "status": None, "percent": None})

    def test_a_first_line_cut_in_half_is_not_a_task(self):
        cut = TASK_SVF[len("[[extractor-metrics]]:{\"rvt-Task"):]
        self.assertEqual(progress_info(cut + "\r\n" + TASK_OPEN)["task"], "Open RVT file.")
        self.assertIsNone(progress_info(cut)["task"])

    def test_broken_json_is_skipped(self):
        tail = "\r\n".join([TASK_OPEN, TASK_SVF[:-7],  # the line being written
                            '[[progress]]:{"a": "55"}', '[[progress]]:{"a": "6',
                            '[[progress]]:["7"]', '[[progress]]:{"a": "x"}',
                            '[[extractor-metrics]]:{"rvt-TaskData": "text"}',
                            '[[extractor-metrics]]:{"rvt-TaskData": {"rvt-Status": "completed"}}'])
        self.assertEqual(progress_info(tail),
                         {"task": "Open RVT file.", "status": "completed", "percent": 55})

    def test_percent_is_clamped(self):
        self.assertEqual(progress_info('[[progress]]:{"a": "250"}')["percent"], 100)
        self.assertEqual(progress_info('[[progress]]:{"a": -3}')["percent"], 0)
        self.assertEqual(progress_info('[[progress]]:{"a": "97.6"}')["percent"], 97)

    def test_empty_inputs(self):
        for tail in (None, "", "\r\n", "   "):
            self.assertEqual(progress_info(tail),
                             {"task": None, "status": None, "percent": None}, repr(tail))


# --- Criterion 2: job_view ---------------------------------------------------------------------

def make_job(state, started=None, ended=None, result=None, with_paths=True, cancel=False):
    job = rx_runner.Job(MODEL, INDEX, REVIT, OUT)
    job.id = "job-1"
    job.state = state
    job.queued_at = NOW
    job.started_at = started
    job.ended_at = ended
    job.result = result
    job.cancel_requested = cancel
    if with_paths:
        job.paths = rx_runner.plan_run(OUT, started or NOW, "a1b2c3d4")
    return job


def at(minutes=0, seconds=0, hours=0):
    return NOW + datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)


def result(state, message):
    return rx_runner.Result(state, None, None, message)


INFO = {"task": "Open RVT file.", "status": "completed", "percent": 40}


class JobView(unittest.TestCase):
    def all_views(self):
        """(name, function) pairs for every state the window shows."""
        ok = result("ok", "Export finished: 13 job(s) succeeded.")
        failed = result("failed", "The Extractor ended with exit code 1.")
        return [
            ("queued", lambda: job_view(make_job("queued", with_paths=False), None, NOW, 2)),
            ("held", lambda: job_view(make_job("queued", with_paths=False), None, NOW, 1,
                                      held=True)),
            ("running", lambda: job_view(make_job("running", NOW), INFO, at(1, 5), None)),
            ("cancelling", lambda: job_view(make_job("running", NOW, cancel=True), INFO,
                                            at(1, 5), None)),
            ("ok", lambda: job_view(make_job("ok", NOW, at(2), ok), None, at(9), None)),
            ("failed", lambda: job_view(make_job("failed", NOW, at(2), failed), None, at(9),
                                        None)),
            ("cancelled", lambda: job_view(make_job("cancelled", NOW, at(1), result(
                "cancelled", "Export cancelled.")), None, at(9), None)),
        ]

    def test_queued_shows_its_position(self):
        view = job_view(make_job("queued", with_paths=False), None, NOW, 3)
        self.assertEqual(view["id"], "job-1")
        self.assertEqual(view["state"], "queued")
        self.assertEqual(view["model"], "DynamoSample_2023.rvt")
        self.assertEqual(view["model_path"], MODEL)
        self.assertEqual(view["state_text"], "Queued")
        self.assertIn("3", view["progress"])
        self.assertEqual((view["started"], view["time"]), ("", ""))
        self.assertEqual((view["can_cancel"], view["can_open_folder"], view["can_open_analyzer"]),
                         (True, False, False))
        self.assertIsNone(view["folder"])
        self.assertIsNone(view["output"])

    def test_held_says_another_extractor_runs(self):
        view = job_view(make_job("queued", with_paths=False), None, NOW, 1, held=True)
        self.assertEqual(view["state_text"], "Waiting")
        self.assertIn("another Extractor is running on this computer", view["progress"])
        self.assertTrue(view["can_cancel"])

    def test_running_shows_step_percentage_and_elapsed_time(self):
        job = make_job("running", NOW)
        view = job_view(job, INFO, at(1, 5), None)
        self.assertEqual(view["state_text"], "Running")
        self.assertIn("Open RVT file.", view["progress"])
        self.assertIn("40%", view["progress"])
        self.assertEqual(view["started"], "10:00:00")
        self.assertEqual(view["time"], "1:05")
        self.assertEqual((view["can_cancel"], view["can_open_folder"], view["can_open_analyzer"]),
                         (True, True, False))
        self.assertEqual(view["folder"], job.paths.root)

    def test_running_without_a_finished_step(self):
        for info in (None, {"task": None, "status": None, "percent": None}):
            view = job_view(make_job("running", NOW), info, at(0, 3), None)
            self.assertIn("no step has finished yet", view["progress"])
            self.assertEqual(view["time"], "0:03")
        view = job_view(make_job("running", NOW), {"task": None, "status": None, "percent": 12},
                        at(0, 3), None)
        self.assertIn("12%", view["progress"])

    def test_a_status_other_than_completed_is_shown(self):
        view = job_view(make_job("running", NOW),
                        {"task": "Export PDF", "status": "failed", "percent": None}, at(1), None)
        self.assertIn("Export PDF", view["progress"])
        self.assertIn("failed", view["progress"])
        self.assertNotIn("completed", job_view(make_job("running", NOW), INFO, at(1),
                                               None)["progress"])

    def test_cancel_once(self):
        view = job_view(make_job("running", NOW, cancel=True), INFO, at(1), None)
        self.assertEqual(view["state_text"], "Cancelling")
        self.assertFalse(view["can_cancel"])

    def test_ok(self):
        job = make_job("ok", NOW, at(2, 30), result("ok", "Export finished: 13 job(s) succeeded."))
        view = job_view(job, None, at(9), None)
        self.assertEqual(view["state_text"], "Done")
        self.assertEqual(view["progress"], "Export finished: 13 job(s) succeeded.")
        self.assertEqual(view["time"], "2:30")
        self.assertEqual((view["can_cancel"], view["can_open_folder"], view["can_open_analyzer"]),
                         (False, True, True))
        self.assertEqual(view["folder"], job.paths.output)
        self.assertEqual(view["output"], job.paths.output)

    def test_failed_points_at_the_logs(self):
        job = make_job("failed", NOW, at(1, 2, 1), result("failed", "Exit code 1."))
        view = job_view(job, None, at(9), None)
        self.assertEqual(view["state_text"], "Failed")
        self.assertTrue(view["progress"].startswith("Exit code 1."))
        self.assertIn("logs are in the run folder", view["progress"])
        self.assertEqual(view["time"], "1:01:02")
        self.assertEqual((view["can_cancel"], view["can_open_folder"], view["can_open_analyzer"]),
                         (False, True, False))
        self.assertEqual(view["folder"], job.paths.root)
        self.assertIsNone(view["output"])

    def test_failed_hint_is_not_repeated_when_the_message_names_the_logs(self):
        message = rx_runner.check_result(1, "", True, True).message  # mentions console.log
        job = make_job("failed", NOW, at(1), result("failed", message))
        self.assertEqual(job_view(job, None, at(9), None)["progress"], message)
        incomplete = rx_runner.check_result(0, "", False, True).message
        job = make_job("failed", NOW, at(1), result("failed", incomplete))
        self.assertIn("logs are in the run folder", job_view(job, None, at(9), None)["progress"])

    def test_failed_start_has_no_run_folder(self):
        job = make_job("failed", NOW, NOW, result("failed", "The export could not start: x"),
                       with_paths=False)
        view = job_view(job, None, at(9), None)
        self.assertFalse(view["can_open_folder"])
        self.assertIsNone(view["folder"])
        self.assertNotIn("logs are in the run folder", view["progress"])

    def test_cancelled(self):
        job = make_job("cancelled", NOW, at(1), result("cancelled", "Export cancelled."))
        view = job_view(job, None, at(9), None)
        self.assertEqual(view["state_text"], "Cancelled")
        self.assertEqual((view["can_cancel"], view["can_open_folder"], view["can_open_analyzer"]),
                         (False, True, False))
        self.assertEqual(view["folder"], job.paths.root)
        queued = make_job("cancelled", None, NOW, result("cancelled", "Before start."),
                          with_paths=False)
        self.assertFalse(job_view(queued, None, at(9), None)["can_open_folder"])

    def test_every_state_in_english_and_polish(self):
        for name, build in self.all_views():
            english = build()
            polish_view = under_polish(build)
            with self.subTest(state=name):
                self.assertTrue(english["state_text"] and polish_view["state_text"])
                self.assertNotEqual(english["state_text"], polish_view["state_text"])
                if name not in ("ok", "cancelled"):  # those show the runner's own message
                    self.assertNotEqual(english["progress"], polish_view["progress"])
        self.assertEqual(under_polish(self.all_views()[1][1])["progress"],
                         "Oczekuje: na tym komputerze działa inny Extractor.")

    def test_view_is_plain_data(self):
        for name, build in self.all_views():
            json.dumps(build())

    def test_summary_and_hint(self):
        views = [build() for name, build in self.all_views()]
        summary = rx_status.summary(views)
        self.assertIn("7", summary)
        self.assertNotEqual(summary, under_polish(rx_status.summary, views))
        self.assertIsInstance(rx_status.summary([]), str)
        hint = rx_status.queue_hint(views)
        self.assertIn("only while Revit is open", hint)
        self.assertNotEqual(hint, under_polish(rx_status.queue_hint, views))
        self.assertEqual(rx_status.queue_hint([v for v in views if v["state"] != "queued"]), "")


class TextTable(unittest.TestCase):
    XAML_PATH = LIB / "rx_status.xaml"

    def test_every_entry_has_english_and_polish(self):
        self.assertTrue(rx_status.UI_TEXT)
        for key, (english, polish_text) in rx_status.UI_TEXT.items():
            with self.subTest(key=key):
                self.assertTrue(english.strip() and polish_text.strip())
                self.assertNotEqual(english, polish_text)
                self.assertFalse(key.startswith("Rx"), "Rx* keys are the theme")

    def test_resources_follow_language(self):
        self.assertEqual(rx_status.resources()["status_close"], "Close")
        self.assertEqual(under_polish(rx_status.resources)["status_close"], "Zamknij")

    def test_constants(self):
        self.assertEqual(WEBSITE_URL, "https://kopecp.github.io/RevitExtractor/")
        self.assertTrue(SESSION_KEY.startswith("RevitExtractor."))
        self.assertIsInstance(PROTOCOL, int)

    def test_xaml_keys_and_text_table_match_both_ways(self):
        xaml = self.XAML_PATH.read_text(encoding="utf-8")
        used = set(key for key in re.findall(r"\{DynamicResource (\w+)\}", xaml)
                   if not key.startswith("Rx"))
        self.assertEqual(used, set(rx_status.UI_TEXT))

    def test_no_hard_coded_label_left_in_xaml(self):
        xaml = self.XAML_PATH.read_text(encoding="utf-8")
        attributes = re.findall(r'\b(Title|Text|Content|Header|ToolTip)="([^"]*)"', xaml)
        self.assertEqual({value for name, value in attributes
                          if value and not value.startswith("{")}, set())
        root = ET.fromstring(xaml)
        for element in root.iter():
            if element.text and element.text.strip():
                self.fail("literal element text: " + element.text.strip())

    def test_every_theme_key_used_exists(self):
        theme = ET.parse(str(LIB / "rx_theme.xaml")).getroot()
        keys = {element.get("{http://schemas.microsoft.com/winfx/2006/xaml}Key")
                for element in theme.iter()}
        xaml = self.XAML_PATH.read_text(encoding="utf-8")
        used = set(re.findall(r"\{DynamicResource (Rx\w+)\}", xaml))
        used |= set(re.findall(r'"(Rx[A-Z]\w+)"', (LIB / "rx_status_ui.py").read_text(
            encoding="utf-8")))
        self.assertTrue(used)
        self.assertEqual(used - keys, set())
        self.assertNotIn("StaticResource Rx", xaml, "theme keys are merged after load")


# --- Criterion 3: SessionCore --------------------------------------------------------------

class NeverStarter(object):
    def start(self, spec, show_window=False):
        raise AssertionError("SessionCore must not start anything")

    def run(self, spec):
        raise AssertionError("SessionCore must not kill anything")


def new_queue(**kwargs):
    return rx_runner.Queue(NeverStarter(), lambda: NOW, system_root=REVIT, **kwargs)


def job_data(model=MODEL, **changes):
    data = {"model_path": model, "index": INDEX, "revit_dir": REVIT, "output_parent": OUT}
    data.update(changes)
    return data


class Listener(object):
    def __init__(self, fail=False):
        self.submitted = []
        self.shown = 0
        self.fail = fail

    def on_submit(self, ids):
        self.submitted.append(list(ids))
        if self.fail:
            raise RuntimeError("window gone")

    def on_show(self):
        self.shown += 1
        if self.fail:
            raise RuntimeError("window gone")


def call(core, request):
    text = core.handle(request if isinstance(request, str) or request is None
                       else json.dumps(request))
    self_check = text.encode("ascii")  # only ASCII JSON text crosses engines
    assert self_check
    return json.loads(text)


class SessionCoreTest(unittest.TestCase):
    def setUp(self):
        self.queue = new_queue()
        self.listener = Listener()
        self.core = SessionCore(self.queue, lambda: NOW, self.listener)

    def test_ping_reports_protocol_and_busy(self):
        answer = call(self.core, {"op": "ping"})
        self.assertEqual((answer["ok"], answer["protocol"], answer["busy"]), (True, PROTOCOL, False))
        call(self.core, {"op": "submit", "jobs": [job_data()]})
        self.assertIs(call(self.core, {"op": "ping"})["busy"], True)

    def test_submit_builds_jobs_from_plain_data(self):
        answer = call(self.core, {"op": "submit", "jobs": [
            job_data(), job_data(os.path.join(ROOT, "P", "Zażółć ąę.rvt"))]})
        self.assertEqual((answer["ok"], answer["errors"]), (True, []))
        self.assertEqual(answer["added"], ["job-1", "job-2"])
        jobs = self.queue.jobs()
        self.assertEqual([job.state for job in jobs], ["queued", "queued"])
        self.assertIsInstance(jobs[0], rx_runner.Job)
        self.assertEqual(jobs[1].model_path, os.path.join(ROOT, "P", "Zażółć ąę.rvt"))
        self.assertEqual(jobs[0].index, INDEX)
        self.assertEqual(self.listener.submitted, [["job-1", "job-2"]])

    def test_one_bad_job_is_reported_and_the_others_added(self):
        answer = call(self.core, {"op": "submit", "jobs": [
            job_data(), job_data("relative.rvt"), "not a job",
            {"model_path": MODEL, "index": INDEX}, job_data(index={"x": 1}),
            job_data(revit_dir=7), job_data(os.path.join(ROOT, "P", "B.rvt"))]})
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["added"], ["job-1", "job-2"])
        self.assertEqual(len(answer["errors"]), 5)
        for number, error in zip((2, 3, 4, 5, 6), answer["errors"]):
            self.assertIsInstance(error, str)
            self.assertIn(str(number), error)
        self.assertIn("absolute", answer["errors"][0])
        self.assertIn("revit_dir", answer["errors"][2] + answer["errors"][4])
        self.assertEqual(len(self.queue.jobs()), 2)

    def test_unexpected_errors_never_raise(self):
        class Broken(object):
            def add(self, job):
                raise RuntimeError("boom")

            def busy(self):
                raise RuntimeError("boom")

            def jobs(self):
                return []
        core = SessionCore(Broken(), lambda: NOW)
        answer = call(core, {"op": "submit", "jobs": [job_data()]})
        self.assertEqual(answer["added"], [])
        self.assertIn("boom", answer["errors"][0])
        answer = call(core, {"op": "ping"})
        self.assertIs(answer["ok"], False)
        self.assertIn("boom", answer["error"])

    def test_bad_requests_answer_ok_false(self):
        for request in ("{not json", "[1, 2]", '"text"', "", None, 42, b"{}",
                        '{"op": "explode"}', '{"op": 3}', '{}',
                        '{"op": "submit"}', '{"op": "submit", "jobs": []}',
                        '{"op": "submit", "jobs": {"a": 1}}'):
            with self.subTest(request=request):
                answer = json.loads(self.core.handle(request))
                self.assertIs(answer["ok"], False)
                self.assertTrue(answer["error"])
        self.assertEqual(self.queue.jobs(), [])

    def test_show_asks_the_listener(self):
        self.assertIs(call(self.core, {"op": "show"})["ok"], True)
        self.assertEqual(self.listener.shown, 1)
        self.assertIs(call(SessionCore(new_queue(), lambda: NOW), {"op": "show"})["ok"], True)

    def test_listener_failure_is_reported_not_raised(self):
        core = SessionCore(self.queue, lambda: NOW, Listener(fail=True))
        answer = call(core, {"op": "submit", "jobs": [job_data()]})
        self.assertEqual(answer["added"], ["job-1"])
        self.assertIn("window gone", answer["errors"][-1])
        answer = call(core, {"op": "show"})
        self.assertIs(answer["ok"], False)
        self.assertIn("window gone", answer["error"])

    def test_errors_follow_language(self):
        request = json.dumps({"op": "submit", "jobs": [job_data("relative.rvt")]})
        english = json.loads(self.core.handle(request))["errors"][0]
        polish_text = json.loads(under_polish(self.core.handle, request))["errors"][0]
        self.assertNotEqual(english, polish_text)
        self.assertNotEqual(json.loads(self.core.handle("{"))["error"],
                            json.loads(under_polish(self.core.handle, "{"))["error"])


# --- Criterion 4: find_session / publish_session ---------------------------------------------

class FakeDomain(object):
    def __init__(self, data=None, fail=False):
        self.data = dict(data or {})
        self.fail = fail
        self.sets = []

    def GetData(self, key):
        if self.fail:
            raise RuntimeError("AppDomain unavailable")
        return self.data.get(key)

    def SetData(self, key, value):
        self.sets.append(key)
        self.data[key] = value


def answering(text):
    calls = []

    def handler(request):
        calls.append(request)
        if isinstance(text, Exception):
            raise text
        return text
    handler.calls = calls
    return handler


class FindSession(unittest.TestCase):
    def test_absent_or_stale_is_none(self):
        cases = {
            "no data": FakeDomain(),
            "not callable": FakeDomain({SESSION_KEY: 42}),
            "raises": FakeDomain({SESSION_KEY: answering(RuntimeError("engine shut down"))}),
            "other protocol": FakeDomain({SESSION_KEY: answering(json.dumps(
                {"ok": True, "protocol": PROTOCOL + 1, "busy": False}))}),
            "not ok": FakeDomain({SESSION_KEY: answering('{"ok": false, "protocol": %d}'
                                                         % PROTOCOL)}),
            "broken json": FakeDomain({SESSION_KEY: answering("{")}),
            "no text": FakeDomain({SESSION_KEY: answering(None)}),
            "domain fails": FakeDomain(fail=True),
        }
        for name, domain in cases.items():
            with self.subTest(case=name):
                self.assertIsNone(find_session(domain))

    def test_live_session_is_found_with_a_ping(self):
        core = SessionCore(new_queue(), lambda: NOW)
        domain = FakeDomain()
        publish_session(domain, core.handle)
        self.assertEqual(domain.sets, [SESSION_KEY])
        self.assertEqual(find_session(domain), core.handle)

    def test_publish_replaces_a_stale_handler(self):
        stale = answering(RuntimeError("engine shut down"))
        domain = FakeDomain({SESSION_KEY: stale})
        self.assertIsNone(find_session(domain))
        core = SessionCore(new_queue(), lambda: NOW)
        publish_session(domain, core.handle)
        self.assertEqual(find_session(domain), core.handle)
        self.assertEqual(json.loads(stale.calls[0]), {"op": "ping"})


# --- Criterion 5: analyzer_plan ----------------------------------------------------------------

CLONE = os.path.join(ROOT, "Tools", "RevitExtractor")
LIB_DIR = os.path.join(CLONE, "pyRevit", "Extractor.extension", "lib")
ANALYZER = os.path.join(CLONE, "Analyzer")
SERVER = os.path.join(ANALYZER, "server.mjs")
PACKAGES = os.path.join(ANALYZER, "node_modules", "pdfjs-dist", "build", "pdf.mjs")
NODE_DIR = os.path.join(ROOT, "Tools", "node")
NODE = os.path.join(NODE_DIR, "node.exe")
PROGRAM_FILES = os.path.join(ROOT, "Program Files")
PF_NODE = os.path.join(PROGRAM_FILES, "nodejs", "node.exe")
OUTPUT = os.path.join(OUT, "export-20261111-100000-a1b2c3d4", "output")


class AnalyzerPlan(unittest.TestCase):
    def plan(self, output=OUTPUT, files=(NODE, SERVER, PACKAGES), path=None, major=24, port=4555,
             program_files=PROGRAM_FILES, path_name="Path"):
        environ = {"ProgramFiles": program_files}
        environ[path_name] = os.pathsep.join([os.path.join(ROOT, "Windows"), NODE_DIR]) \
            if path is None else path
        majors = []

        def node_major(found):
            majors.append(found)
            if isinstance(major, Exception):
                raise major
            return major

        def free_port():
            if isinstance(port, Exception):
                raise port
            return port
        files = set(files)
        self.majors = majors
        return analyzer_plan(output, LIB_DIR, environ, lambda p: p in files, node_major,
                             free_port)

    def test_local_with_the_command(self):
        kind, spec, url = self.plan()
        self.assertEqual(kind, "local")
        self.assertEqual(spec.file, NODE)
        self.assertEqual(spec.arguments,
                         'server.mjs --output "%s" --port 4555 --open' % OUTPUT)
        self.assertEqual(spec.working_dir, ANALYZER)
        self.assertEqual(spec.env, {})
        self.assertEqual(url, "http://127.0.0.1:4555/")
        self.assertEqual(self.majors, [NODE])

    def test_path_lookup_is_case_insensitive_and_strips_quotes(self):
        for name in ("PATH", "path", "Path"):
            self.assertEqual(self.plan(path_name=name)[1].file, NODE)
        quoted = '"%s"' % NODE_DIR + os.pathsep + os.pathsep
        self.assertEqual(self.plan(path=quoted)[1].file, NODE)

    def test_program_files_fallback(self):
        kind, spec, url = self.plan(files=(PF_NODE, SERVER, PACKAGES), path="")
        self.assertEqual((kind, spec.file), ("local", PF_NODE))

    def test_first_node_on_path_wins_even_if_too_old(self):
        kind, reason = self.plan(files=(NODE, PF_NODE, SERVER, PACKAGES), major=22)
        self.assertEqual(kind, "web")
        self.assertIn("24", reason)
        self.assertIn("22", reason)
        self.assertEqual(self.majors, [NODE])

    def test_unreadable_node_version(self):
        for major in (None, OSError("locked"), "24"):
            kind, reason = self.plan(major=major)
            self.assertEqual(kind, "web", major)
            self.assertIn("Node.js", reason)

    def test_each_missing_piece_has_a_reason(self):
        cases = {
            "Node.js": (SERVER, PACKAGES),
            "server.mjs": (NODE, PACKAGES),
            "npm ci": (NODE, SERVER),
        }
        for needle, files in cases.items():
            with self.subTest(missing=needle):
                kind, reason = self.plan(files=files, path="", program_files=PROGRAM_FILES)
                self.assertEqual(kind, "web")
                self.assertIn(needle, reason)
        kind, reason = self.plan(files=(), path="", program_files="")
        self.assertEqual(kind, "web")
        for needle in ("Node.js", "server.mjs"):
            self.assertIn(needle, reason)

    def test_reasons_in_english_and_polish(self):
        for kwargs in ({"files": (SERVER, PACKAGES), "path": ""}, {"files": (NODE, SERVER)},
                       {"files": (NODE, PACKAGES)}, {"major": 20},
                       {"output": OUTPUT + '"x'}, {"port": OSError("no port")}):
            english = self.plan(**kwargs)[1]
            polish_text = under_polish(self.plan, **kwargs)[1]
            self.assertNotEqual(english, polish_text, kwargs)

    def test_a_path_with_a_quote_is_refused(self):
        kind, reason = self.plan(output=os.path.join(OUT, 'a"b', "output"))
        self.assertEqual(kind, "web")
        self.assertIn("quote", reason)
        node_with_quote = os.path.join(ROOT, 'no"de')
        kind, reason = self.plan(files=(os.path.join(node_with_quote, "node.exe"), SERVER,
                                        PACKAGES), path=node_with_quote)
        self.assertEqual(kind, "web")

    def test_trailing_backslash_cannot_escape_the_quote(self):
        kind, spec, url = self.plan(output=OUTPUT + os.sep)
        self.assertIn('"%s"' % OUTPUT, spec.arguments)

    def test_relative_output_and_bad_ports(self):
        self.assertEqual(self.plan(output="output")[0], "web")
        for port in (0, -1, 70000, True, "4555", None, OSError("none free")):
            self.assertEqual(self.plan(port=port)[0], "web", port)

    def test_never_runs_npm(self):
        source = (LIB / "rx_status.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"['\"]npm(\.cmd)?['\"]")


# --- .NET helpers in rx_status_ui (System stubbed) ----------------------------------------------

class StartInfo(object):
    def __init__(self):
        self.FileName = ""
        self.Arguments = ""
        self.UseShellExecute = False


class ShellProcess(object):
    started = []

    def __init__(self, info):
        self.info = info
        self.disposed = False

    def Dispose(self):
        self.disposed = True

    @staticmethod
    def Start(info):
        process = ShellProcess(info)
        ShellProcess.started.append(process)
        return process


class Listener4(object):
    instances = []

    def __init__(self, address, port):
        self.address = address
        self.requested = port
        self.started = self.stopped = False
        self.LocalEndpoint = types.SimpleNamespace(Port=50123)
        Listener4.instances.append(self)

    def Start(self):
        self.started = True

    def Stop(self):
        self.stopped = True


def helper_stubs():
    diagnostics = stub_module(
        "System.Diagnostics", Process=ShellProcess, ProcessStartInfo=StartInfo,
        FileVersionInfo=types.SimpleNamespace(
            GetVersionInfo=lambda path: types.SimpleNamespace(FileMajorPart=24, path=path)))
    net = stub_module("System.Net", IPAddress=types.SimpleNamespace(Loopback="127.0.0.1"))
    sockets = stub_module("System.Net.Sockets", TcpListener=Listener4)
    return {"System": stub_module("System"), "System.Diagnostics": diagnostics,
            "System.Net": net, "System.Net.Sockets": sockets}


def load_ui():
    """rx_status_ui with nothing stubbed: the guarded pyrevit import must not fail on CPython."""
    import importlib
    return importlib.import_module("rx_status_ui")


class Helpers(unittest.TestCase):
    def setUp(self):
        ShellProcess.started = []
        Listener4.instances = []
        self.ui = load_ui()
        self.tmp = os.path.dirname(os.path.abspath(__file__))

    def test_shell_open_an_existing_folder_without_arguments(self):
        with patch.dict(sys.modules, helper_stubs()):
            self.ui.shell_open(self.tmp)
        process = ShellProcess.started[0]
        self.assertEqual(process.info.FileName, self.tmp)
        self.assertEqual(process.info.Arguments, "")
        self.assertIs(process.info.UseShellExecute, True)
        self.assertTrue(process.disposed)

    def test_shell_open_urls(self):
        with patch.dict(sys.modules, helper_stubs()):
            self.ui.shell_open("http://127.0.0.1:4555/")
            self.ui.shell_open(WEBSITE_URL)
        self.assertEqual([p.info.FileName for p in ShellProcess.started],
                         ["http://127.0.0.1:4555/", WEBSITE_URL])

    def test_shell_open_refuses_anything_else(self):
        here = os.path.abspath(__file__)
        for target in (here, os.path.join(self.tmp, "missing folder"), "file:///C:/x",
                       "http://example.com/", "calc.exe", "", None,
                       "http://127.0.0.1:4555/\" & calc"):
            with patch.dict(sys.modules, helper_stubs()):
                with self.assertRaises(ValueError, msg=repr(target)):
                    self.ui.shell_open(target)
        self.assertEqual(ShellProcess.started, [])

    def test_explorer_select_starts_explorer_without_the_shell(self):
        here = os.path.abspath(__file__)
        with patch.dict(sys.modules, helper_stubs()):
            self.ui.explorer_select(here)
        process = ShellProcess.started[0]
        self.assertEqual(process.info.FileName, "explorer.exe")
        self.assertEqual(process.info.Arguments, '/select,"%s"' % os.path.normpath(here))
        self.assertIs(process.info.UseShellExecute, False)
        self.assertTrue(process.disposed)

    def test_explorer_select_refuses_unsafe_or_missing_files(self):
        for target in (os.path.join(self.tmp, "missing.rvt"), 'C:\\a"b.rvt', "a.rvt",
                       "C:\\a\nb.rvt", self.tmp + '" /root,"C:\\Windows', None):
            with patch.dict(sys.modules, helper_stubs()):
                with self.assertRaises(ValueError, msg=repr(target)):
                    self.ui.explorer_select(target)
        self.assertEqual(ShellProcess.started, [])

    def test_free_port_binds_loopback_and_releases(self):
        with patch.dict(sys.modules, helper_stubs()):
            self.assertEqual(self.ui.free_port(), 50123)
        listener = Listener4.instances[0]
        self.assertEqual((listener.address, listener.requested), ("127.0.0.1", 0))
        self.assertTrue(listener.started and listener.stopped)

    def test_node_major_reads_the_file_version(self):
        with patch.dict(sys.modules, helper_stubs()):
            self.assertEqual(self.ui.node_major(NODE), 24)

    def test_imports_are_lazy(self):
        self.assertNotIn("System.Diagnostics", sys.modules)
        self.assertIsNone(self.ui.forms, "no pyRevit under CPython: the guard keeps it None")


# --- Criteria 6-9: window and session logic (WPF stubbed) ---------------------------------------

def status_names(path=None):
    root = ET.parse(str(path or LIB / "rx_status.xaml")).getroot()
    return [element.get(XNAME) for element in root.iter() if element.get(XNAME)]


class FakeStatusWindowBase(object):
    """forms.WPFWindow for rx_status.xaml: one Control per x:Name, plus the window members the
    status window uses. Close() must never be called (the window is never destroyed)."""

    def __init__(self, xaml_path, literal_string=False, handle_esc=True, set_owner=True):
        self.xaml_path = xaml_path
        self.handle_esc = handle_esc
        self.set_owner = set_owner
        self.Resources = {}
        self.merged = []
        self.Closing = Event()
        self.Dispatcher = types.SimpleNamespace(ShutdownStarted=Event())
        self.WindowState = "Normal"
        self.IsVisible = False
        self.shows = self.hides = self.activations = self.closes = 0
        self.dialogs = 0
        for name in status_names(xaml_path):
            setattr(self, name, Control(name))
        if hasattr(self, "jobs_lv"):
            self.jobs_lv.SelectedItem = None

    def merge_resource_dict(self, path):
        self.merged.append(path)

    def FindResource(self, key):
        raise KeyError(key)

    def Show(self):
        self.IsVisible = True
        self.shows += 1

    def Hide(self):
        self.IsVisible = False
        self.hides += 1

    def ShowDialog(self):
        self.dialogs += 1
        hook = getattr(type(self), "dialog_hook", None)
        if hook is not None:
            hook(self)
        return True

    def Activate(self):
        self.activations += 1
        return True

    def Close(self):
        self.closes += 1


class FuncType(object):
    """System.Func: Func[String, String](callable) -> a delegate (here: the callable)."""
    made = []

    def __getitem__(self, types_):
        def make(function):
            FuncType.made.append((types_, function))
            return function
        return make


class FakeTimer(object):
    def __init__(self):
        self.Tick = Event()
        self.Interval = None
        self.IsEnabled = False
        self.starts = 0
        self.stops = 0

    def Start(self):
        self.IsEnabled = True
        self.starts += 1

    def Stop(self):
        self.IsEnabled = False
        self.stops += 1


def ui_system_stubs(domain=None, timers=None):
    timers = timers if timers is not None else []

    def new_timer():
        timer = FakeTimer()
        timers.append(timer)
        return timer
    listed = types.SimpleNamespace(GetProcessesByName=lambda name: [])
    system = stub_module("System", AppDomain=types.SimpleNamespace(CurrentDomain=domain),
                         Func=FuncType(), String=str,
                         TimeSpan=types.SimpleNamespace(FromSeconds=lambda s: ("seconds", s)))
    return {
        "System": system,
        "System.Collections": stub_module("System.Collections"),
        "System.Collections.ObjectModel": stub_module("System.Collections.ObjectModel",
                                                      ObservableCollection={object: Collection}),
        "System.Windows": stub_module("System.Windows", WindowState=types.SimpleNamespace(
            Minimized="Minimized", Normal="Normal")),
        "System.Windows.Threading": stub_module("System.Windows.Threading",
                                                DispatcherTimer=new_timer),
        "System.Diagnostics": stub_module("System.Diagnostics", Process=listed),
    }


def load_status_ui():
    """rx_status_ui with pyRevit's forms stubbed (the window base is chosen at import)."""
    import importlib.util
    forms = types.SimpleNamespace(WPFWindow=FakeStatusWindowBase, Reactive=SharedEventReactive,
                                  reactive=reactive)
    saved = dict(sys.modules)
    try:
        sys.modules["pyrevit"] = types.SimpleNamespace(forms=forms)
        spec = importlib.util.spec_from_file_location("rx_status_ui_under_test",
                                                      str(LIB / "rx_status_ui.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for key in list(sys.modules):
            if key not in saved:
                del sys.modules[key]
        sys.modules.update(saved)
    return module


class Handle(object):
    def __init__(self, pid):
        self.pid = pid
        self.exited = False
        self.code = None

    def has_exited(self):
        return self.exited

    def exit_code(self):
        return self.code if self.exited else None

    def close(self):
        pass


class Starter(object):
    """The queue's starter and the Analyzer starter in one; records every start."""

    def __init__(self):
        self.started = []  # (spec, show_window, handle)
        self.killed = []
        self.pid = 2000

    def start(self, spec, show_window=False):
        self.pid += 1
        handle = Handle(self.pid)
        self.started.append((spec, show_window, handle))
        return handle

    def run(self, spec):
        self.killed.append(spec)
        return 0

    def extractor_handles(self):
        return [h for spec, show, h in self.started if "RX_MODEL" in spec.env]


class Clock(object):
    def __init__(self):
        self.now = NOW
        self.step = datetime.timedelta(seconds=1)

    def __call__(self):
        self.now += self.step
        return self.now


class Notice(object):
    """The injectable notice: records the reasons it was shown for."""

    def __init__(self):
        self.shown = []
        self.answer = False
        self.error = None
        self.log = None

    def __call__(self, reason):
        self.shown.append(reason)
        if self.log is not None:
            self.log.append(("notice", reason))
        if self.error is not None:
            raise self.error
        return self.answer


class Shell(object):
    def __init__(self):
        self.opened = []
        self.fail = False
        self.log = None

    def __call__(self, target):
        if self.log is not None:
            self.log.append(("shell", target))
        if self.fail:
            raise ValueError("cannot open " + target)
        self.opened.append(target)


class Explorer(object):
    def __init__(self):
        self.selected = []

    def __call__(self, path):
        self.selected.append(path)


class ExplorerLogic(unittest.TestCase):
    def test_arguments_quote_the_path_and_keep_special_characters(self):
        for path in ("C:\\Models\\a.rvt", "C:\\Moje modele\\Żółć & Co\\100% (v2).rvt",
                     "C:\\a,b;c\\x.rvt", "\\\\server\\share\\Zażółć\\m.rvt"):
            with self.subTest(path=path):
                self.assertEqual(rx_status.explorer_arguments(path), '/select,"%s"' % path)

    def test_arguments_normalise_slashes(self):
        self.assertEqual(rx_status.explorer_arguments("C:/Models/a.rvt"),
                         '/select,"C:\\Models\\a.rvt"')

    def test_arguments_refuse_unsafe_paths(self):
        for path in ('C:\\a"b.rvt', "C:\\a\nb.rvt", "C:\\a\rb.rvt", "a.rvt", "..\\a.rvt", "",
                     None, 'C:\\x" /root,"C:\\Windows\\System32\\calc.exe'):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    rx_status.explorer_arguments(path)

    def test_target_selects_an_existing_file(self):
        path = "C:\\Modele\\Zażółć & 100%\\a.rvt"
        got = rx_status.model_target(path, isfile=lambda p: True, isdir=lambda p: False)
        self.assertEqual(got, ("select", path))

    def test_target_falls_back_to_the_parent_folder(self):
        got = rx_status.model_target("C:\\Models\\gone.rvt", isfile=lambda p: False,
                                     isdir=lambda p: p == "C:\\Models")
        self.assertEqual(got, ("folder", "C:\\Models"))

    def test_target_is_none_when_nothing_exists_or_the_path_is_refused(self):
        never = lambda p: False  # noqa: E731
        self.assertIsNone(rx_status.model_target("C:\\Gone\\a.rvt", never, never))
        self.assertIsNone(rx_status.model_target("C:\\", never, never), "a root has no parent")
        for path in ('C:\\a"b.rvt', "C:\\a\nb.rvt", "a.rvt", "", None):
            with self.subTest(path=path):
                self.assertIsNone(rx_status.model_target(path, lambda p: True, lambda p: True))

    def test_menu_texts_exist_in_both_languages(self):
        self.assertEqual(rx_status.resources()["status_menu_model"],
                         "Show model in File Explorer")
        self.assertEqual(rx_status.resources()["status_menu_folder"],
                         "Show export folder in File Explorer")
        polish_texts = under_polish(rx_status.resources)
        self.assertIn("Eksploratorze", polish_texts["status_menu_model"])
        self.assertIn("Eksploratorze", polish_texts["status_menu_folder"])


class WindowTest(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="rx-status-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.revit = os.path.join(self.tmp, "Revit")
        os.makedirs(os.path.join(self.revit, "RevitExtractor"))
        open(os.path.join(self.revit, "RevitExtractor", "RevitExtractor.exe"), "w").close()
        self.out = os.path.join(self.tmp, "out")
        SharedEventReactive.PropertyChanged = Event()
        SharedEventReactive.raised = []
        FuncType.made = []
        self.timers = []
        patcher = patch.dict(sys.modules, ui_system_stubs(timers=self.timers))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ui = load_status_ui()
        self.starter = Starter()
        self.clock = Clock()
        self.timer = FakeTimer()
        self.shell = Shell()
        self.explorer = Explorer()
        self.plans = []
        self.plan_answer = None
        self.queue = rx_runner.Queue(self.starter, self.clock, system_root=self.tmp)
        self.polls = 0
        poll = self.queue.poll

        def counting_poll():
            self.polls += 1
            return poll()
        self.queue.poll = counting_poll
        self.notice = Notice()
        self.prefs = os.path.join(self.tmp, "appdata", "RevitExtractor", "preferences.json")
        self.session = self.ui.Session(self.queue, self.timer, self.clock, self.ui.StatusWindow,
                                       self.starter, shell=self.shell, plan_analyzer=self.plan,
                                       notice=self.notice, preferences=self.prefs,
                                       explorer=self.explorer)
        self.window = self.session.window

    def test_on_show_reapplies_localized_resources(self):
        self.assertNotEqual(self.window.Resources.get("probe"), "changed")
        with patch.object(self.ui, "resources", lambda: {"probe": "changed"}):
            self.session.on_show()
        self.assertEqual(self.window.Resources.get("probe"), "changed")

    def plan(self, output):
        self.plans.append(output)
        return self.plan_answer

    def submit(self, *names):
        jobs = [job_data(os.path.join(self.tmp, "models", name + ".rvt"), revit_dir=self.revit,
                         output_parent=self.out) for name in names]
        return call(self.session.core, {"op": "submit", "jobs": jobs})

    def tick(self):
        self.timer.Tick.fire(self.timer, None)

    def rows(self):
        return list(self.window.jobs_lv.ItemsSource)

    def select(self, index):
        self.window.jobs_lv.SelectedItem = self.rows()[index] if index is not None else None
        self.window.jobs_lv.SelectionChanged.fire(self.window.jobs_lv, None)

    def click(self, name):
        button = getattr(self.window, name)
        button.Click.fire(button, None)

    def buttons(self):
        return tuple(getattr(self.window, name).IsEnabled
                     for name in ("cancel_btn", "open_folder_btn", "open_analyzer_btn"))

    def finish(self, index, code=0, complete=True):
        job = self.queue.jobs()[index]
        if complete:
            open(os.path.join(job.paths.output, "bubble.json"), "w").close()
            os.makedirs(os.path.join(job.paths.output, "Resource"))
        with open(job.paths.console, "w") as handle:
            handle.write("Success Jobs: 3, Failed Jobs: 0\n")
        handle = self.starter.extractor_handles()[index]
        handle.exited = True
        handle.code = code

    def test_window_setup(self):
        self.assertEqual([Path(p).name for p in self.window.merged], ["rx_theme.xaml"])
        self.assertEqual(Path(self.window.xaml_path).name, "rx_status.xaml")
        self.assertIs(self.window.handle_esc, False, "Esc is the Close button (IsCancel)")
        self.assertEqual(self.window.Resources["status_close"], "Close")
        self.assertEqual(self.window.shows, 0, "created hidden; shown on submit or show")
        self.assertEqual(self.timer.Tick.handlers, [self.session.tick])
        self.assertEqual(self.buttons(), (False, False, False))

    def test_submit_shows_the_window_starts_the_timer_and_the_first_export(self):
        answer = self.submit("a", "b")
        self.assertEqual(answer["added"], ["job-1", "job-2"])
        self.assertTrue(self.timer.IsEnabled)
        self.assertEqual((self.window.shows, self.window.IsVisible), (1, True))
        self.assertEqual([job.state for job in self.queue.jobs()], ["running", "queued"])
        self.assertEqual([row.Model for row in self.rows()], ["a.rvt", "b.rvt"])
        self.assertEqual(self.rows()[1].Progress, "Position 1 in the queue.")
        self.assertIn("only while Revit is open", self.window.hint_text.Text)
        self.assertIn("2", self.window.summary_text.Text)

    def test_a_tick_polls_once_and_refreshes_at_most_once(self):
        self.submit("a", "b", "c")
        polls, refreshes = self.polls, self.window.jobs_lv.Items.refreshes
        self.tick()
        self.assertEqual(self.polls, polls + 1)
        self.assertLessEqual(self.window.jobs_lv.Items.refreshes, refreshes + 1)
        self.finish(0)
        refreshes = self.window.jobs_lv.Items.refreshes
        self.tick()  # job a ends, job b starts, every row changes
        self.assertEqual(self.window.jobs_lv.Items.refreshes, refreshes + 1)
        self.clock.step = datetime.timedelta(0)
        self.tick()
        refreshes = self.window.jobs_lv.Items.refreshes
        self.tick()
        self.assertEqual(self.window.jobs_lv.Items.refreshes, refreshes, "nothing changed")

    def test_progress_comes_from_the_console_tail(self):
        self.submit("a")
        with open(self.queue.jobs()[0].paths.console, "w", newline="") as handle:
            handle.write(REAL_TAIL)
        self.tick()
        self.assertEqual(self.rows()[0].Progress,
                         "Last step: Export SVF For 3D Views. Views Count: 1 · 30%")

    def test_the_window_never_subscribes_to_a_row(self):
        self.submit("a", "b")
        self.select(0)
        self.tick()
        self.finish(0)
        self.tick()
        self.click("cancel_btn")
        self.assertIsInstance(self.rows()[0], SharedEventReactive)
        self.assertEqual(SharedEventReactive.PropertyChanged.handlers, [])
        self.assertEqual(SharedEventReactive.raised, [])
        source = (LIB / "rx_status_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("PropertyChanged", source)

    def test_buttons_follow_the_highlighted_row(self):
        self.submit("a", "b")
        self.assertIs(self.window.jobs_lv.SelectedItem, self.rows()[0],
                      "the first new row is highlighted")
        self.assertEqual(self.buttons(), (True, True, False), "running: cancel, run folder")
        self.select(1)
        self.assertEqual(self.buttons(), (True, False, False), "queued: cancel only")
        self.finish(0)
        self.tick()
        self.select(0)
        self.assertEqual(self.buttons(), (False, True, True), "ok: folder and Analyzer")
        self.select(None)
        self.assertEqual(self.buttons(), (False, False, False))
        self.assertTrue(self.window.close_btn.IsEnabled)

    def test_cancel_calls_queue_cancel_once(self):
        self.submit("a", "b")
        calls = []
        cancel = self.queue.cancel
        self.queue.cancel = lambda job_id: calls.append(job_id) or cancel(job_id)
        self.select(1)
        self.click("cancel_btn")
        self.assertEqual(calls, ["job-2"])
        self.assertEqual(self.queue.jobs()[1].state, "cancelled")
        self.assertEqual(self.buttons(), (False, False, False), "refreshed right away")
        self.select(0)
        self.click("cancel_btn")
        self.assertEqual(calls, ["job-2", "job-1"])
        self.assertEqual(len(self.starter.killed), 1)
        self.assertEqual(self.buttons()[0], False, "a cancel is asked only once")

    def clear_enabled(self):
        return self.window.clear_finished_btn.IsEnabled

    def test_clear_finished_button_follows_the_finished_rows(self):
        self.assertFalse(self.clear_enabled(), "empty list")
        self.submit("a", "b")
        self.assertFalse(self.clear_enabled(), "running and waiting only")
        self.finish(0)
        self.tick()
        self.assertTrue(self.clear_enabled())
        self.select(1)
        self.assertTrue(self.clear_enabled(), "independent of the highlighted row")
        self.click("clear_finished_btn")
        self.assertFalse(self.clear_enabled(), "nothing finished left")

    def test_clear_finished_removes_only_finished_rows_and_files_stay(self):
        self.submit("a", "b", "c")
        self.finish(0)
        self.tick()  # a done, b running, c queued
        job_a = self.queue.jobs()[0]
        output = job_a.paths.output
        analyzer = self.session._analyzers
        self.select(1)
        before = [row.view["id"] for row in self.rows()]
        self.assertEqual(before, ["job-1", "job-2", "job-3"])
        kills = len(self.starter.killed)
        self.click("clear_finished_btn")
        self.assertEqual([row.view["id"] for row in self.rows()], ["job-2", "job-3"])
        self.assertEqual([j.id for j in self.queue.jobs()], ["job-2", "job-3"])
        self.assertEqual(sorted(self.window._by_id), ["job-2", "job-3"])
        self.assertIs(self.window.jobs_lv.SelectedItem, self.rows()[0], "selection kept")
        self.assertTrue(os.path.isdir(output), "run folder is not deleted")
        self.assertEqual(len(self.starter.killed), kills, "nothing cancelled")
        self.assertEqual(self.shell.opened, [], "nothing opened")
        self.assertIs(self.session._analyzers, analyzer)
        self.assertEqual(self.window.error_text.Text, "")
        self.assertIn("1", self.window.summary_text.Text)

    def test_clear_finished_with_the_highlighted_row_removed_and_window_keeps_updating(self):
        self.submit("a", "b")
        self.finish(0)
        self.tick()
        self.select(0)
        self.click("clear_finished_btn")
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.buttons()[2], False)
        job = self.queue.jobs()[0]
        open(os.path.join(job.paths.output, "bubble.json"), "w").close()
        os.makedirs(os.path.join(job.paths.output, "Resource"))
        with open(job.paths.console, "w") as handle:
            handle.write("Success Jobs: 3, Failed Jobs: 0\n")
        running = self.starter.extractor_handles()[1]
        running.exited = True
        running.code = 0
        self.tick()
        self.assertEqual(self.rows()[0].view["state"], "ok", "later updates still arrive")
        self.assertTrue(self.clear_enabled())
        self.submit("c")
        self.assertEqual([r.view["id"] for r in self.rows()], ["job-2", "job-3"],
                         "ids are not reused")

    def test_clear_finished_nothing_to_do_changes_nothing(self):
        self.submit("a")
        self.session.clear_finished()
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.queue.jobs()[0].state, "running")

    def test_clear_finished_failure_goes_to_the_error_line(self):
        self.submit("a", "b")
        self.finish(0)
        self.tick()

        def boom():
            raise RuntimeError("boom")
        self.queue.clear_finished = boom
        self.click("clear_finished_btn")
        self.assertIn("boom", self.window.error_text.Text)

    def test_clear_finished_text_in_both_languages(self):
        english = rx_status.resources()
        self.assertEqual(english["status_clear_finished"], "Clear finished")
        self.assertIn("no files are deleted", english["status_clear_finished_tip"])
        polish_texts = under_polish(rx_status.resources)
        self.assertEqual(polish_texts["status_clear_finished"], "Wyczyść zakończone")
        self.assertNotEqual(polish_texts["status_clear_finished_tip"],
                            english["status_clear_finished_tip"])

    def test_open_output_folder_targets(self):
        self.submit("a", "b")
        job_a, job_b = self.queue.jobs()
        self.select(0)
        self.click("open_folder_btn")
        self.finish(0)
        self.tick()
        self.finish(1, code=1)
        self.tick()
        self.select(0)
        self.click("open_folder_btn")
        self.select(1)
        self.click("open_folder_btn")
        self.assertEqual(self.shell.opened, [job_a.paths.root, job_a.paths.output,
                                             job_b.paths.root])

    # -- right-click menu on a row

    def right_click(self, index):
        """Right-click a row (index) or empty space (None); returns the opening event args."""
        lv = self.window.jobs_lv
        row = self.rows()[index] if index is not None else None
        item = types.SimpleNamespace(DataContext=row) if row is not None else None
        with patch.object(self.ui, "list_item_from", lambda source: item):
            lv.PreviewMouseRightButtonDown.fire(lv, types.SimpleNamespace(OriginalSource=object()))
        args = types.SimpleNamespace(Handled=False)
        lv.ContextMenuOpening.fire(lv, args)
        return args

    def pick(self, name):
        item = getattr(self.window, name)
        item.Click.fire(item, None)

    def make_model(self, name):
        path = os.path.join(self.tmp, "models", name + ".rvt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        return path

    def test_menu_is_wired_once_on_the_list_and_localised(self):
        lv = self.window.jobs_lv
        self.assertEqual(len(lv.PreviewMouseRightButtonDown.handlers), 1)
        self.assertEqual(len(lv.ContextMenuOpening.handlers), 1)
        self.assertEqual(self.window.menu_show_model.Header, "Show model in File Explorer")
        self.assertEqual(self.window.menu_show_folder.Header,
                         "Show export folder in File Explorer")
        under_polish(self.window.apply_resources)
        self.assertIn("Eksploratorze", self.window.menu_show_model.Header)

    def test_right_click_selects_the_clicked_row_first(self):
        self.submit("a", "b")
        self.assertIs(self.window.jobs_lv.SelectedItem, self.rows()[0])
        args = self.right_click(1)
        self.assertIs(self.window.jobs_lv.SelectedItem, self.rows()[1])
        self.assertFalse(args.Handled)
        self.assertEqual(self.buttons(), (True, False, False), "buttons follow the new row")

    def test_right_click_on_empty_space_opens_no_menu_and_keeps_the_selection(self):
        self.submit("a")
        args = self.right_click(None)
        self.assertTrue(args.Handled)
        self.assertIs(self.window.jobs_lv.SelectedItem, self.rows()[0])

    def test_menu_items_follow_the_row(self):
        self.submit("a", "b")
        self.right_click(0)
        self.assertEqual((self.window.menu_show_model.IsEnabled,
                          self.window.menu_show_folder.IsEnabled), (True, True))
        self.right_click(1)  # queued: no run folder yet
        self.assertEqual((self.window.menu_show_model.IsEnabled,
                          self.window.menu_show_folder.IsEnabled), (True, False))

    def test_show_model_selects_the_file(self):
        path = self.make_model("a")
        self.submit("a")
        self.right_click(0)
        self.pick("menu_show_model")
        self.assertEqual(self.explorer.selected, [os.path.normpath(path)])
        self.assertEqual(self.shell.opened, [])
        self.assertEqual(self.window.error_text.Text, "")

    def test_show_model_falls_back_to_the_parent_folder(self):
        self.submit("a")  # the file does not exist, its folder does
        os.makedirs(os.path.join(self.tmp, "models"))
        self.right_click(0)
        self.pick("menu_show_model")
        self.assertEqual(self.explorer.selected, [])
        self.assertEqual(self.shell.opened, [os.path.join(self.tmp, "models")])

    def test_show_model_with_nothing_left_shows_the_error_line(self):
        self.submit("a")
        self.right_click(0)
        self.pick("menu_show_model")
        self.assertEqual((self.explorer.selected, self.shell.opened), ([], []))
        self.assertIn("were not found", self.window.error_text.Text)
        self.assertIn("a.rvt", self.window.error_text.Text)

    def test_show_model_failure_is_shown_on_the_error_line(self):
        self.make_model("a")
        self.submit("a")
        self.right_click(0)

        def broken(path):
            raise ValueError("explorer failed")
        self.session._explorer = broken
        self.pick("menu_show_model")
        self.assertIn("explorer failed", self.window.error_text.Text)

    def test_show_run_folder_uses_the_open_output_folder_target(self):
        self.submit("a", "b")
        job_a = self.queue.jobs()[0]
        self.right_click(0)
        self.pick("menu_show_folder")
        self.finish(0)
        self.tick()
        self.right_click(0)
        self.pick("menu_show_folder")
        self.assertEqual(self.shell.opened, [job_a.paths.root, job_a.paths.output])

    def test_show_run_folder_is_ignored_for_a_queued_row(self):
        self.submit("a", "b")
        self.right_click(1)
        self.pick("menu_show_folder")
        self.assertEqual(self.shell.opened, [])

    def test_show_run_folder_missing_on_disk_is_reported(self):
        self.submit("a")
        self.right_click(0)
        self.shell.fail = True
        self.pick("menu_show_folder")
        self.assertIn("cannot open", self.window.error_text.Text)

    def test_open_in_analyzer_starts_once_then_reuses_the_url(self):
        self.submit("a")
        self.finish(0)
        self.tick()
        output = self.queue.jobs()[0].paths.output
        spec = rx_runner.LaunchSpec("node.exe", "server.mjs", self.tmp, {})
        self.plan_answer = ("local", spec, "http://127.0.0.1:4555/")
        self.select(0)
        self.click("open_analyzer_btn")
        self.assertEqual(self.plans, [output])
        analyzer = [entry for entry in self.starter.started if entry[0] is spec]
        self.assertEqual(len(analyzer), 1)
        self.assertIs(analyzer[0][1], True, "a visible console window")
        self.assertEqual(self.shell.opened, [], "Node opens the browser itself (--open)")
        self.click("open_analyzer_btn")
        self.assertEqual(self.shell.opened, ["http://127.0.0.1:4555/"])
        self.assertEqual(self.plans, [output], "no second plan while the server runs")
        analyzer[0][2].exited = True  # the user closed the console window
        self.click("open_analyzer_btn")
        self.assertEqual(len([e for e in self.starter.started if e[0] is spec]), 2)
        self.assertEqual(self.starter.killed, [], "the Analyzer is never ended by the window")

    def test_open_in_analyzer_falls_back_to_folder_and_website(self):
        self.submit("a")
        self.finish(0)
        self.tick()
        self.plan_answer = ("web", "Node.js was not found.")
        self.select(0)
        self.click("open_analyzer_btn")
        self.assertEqual(self.shell.opened, [self.queue.jobs()[0].paths.output, WEBSITE_URL])
        self.assertIn("Node.js was not found.", self.window.error_text.Text)

    def fall_back(self):
        self.submit("a")
        self.finish(0)
        self.tick()
        self.plan_answer = ("web", "Node.js was not found.")
        self.select(0)
        self.click("open_analyzer_btn")

    def test_fallback_shows_the_notice_with_the_reason_before_opening(self):
        events = []
        self.notice.log = events
        self.shell.log = events
        self.fall_back()
        output = self.queue.jobs()[0].paths.output
        self.assertEqual(events, [("notice", "Node.js was not found."), ("shell", output),
                                  ("shell", WEBSITE_URL)])

    def test_notice_not_shown_for_a_local_plan(self):
        self.submit("a")
        self.finish(0)
        self.tick()
        spec = rx_runner.LaunchSpec("node.exe", "server.mjs", self.tmp, {})
        self.plan_answer = ("local", spec, "http://127.0.0.1:4555/")
        self.select(0)
        self.click("open_analyzer_btn")
        self.assertEqual(self.notice.shown, [])

    def test_ticking_dont_show_again_stores_the_flag_and_suppresses_the_next_notice(self):
        self.notice.answer = True
        self.fall_back()
        self.assertEqual(len(self.notice.shown), 1)
        with open(self.prefs, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"hide_node_notice": True})
        self.click("open_analyzer_btn")
        self.assertEqual(len(self.notice.shown), 1, "suppressed")
        self.assertEqual(len(self.shell.opened), 4, "folder and website still opened")

    def test_unticked_notice_is_shown_every_time_and_writes_nothing(self):
        self.fall_back()
        self.click("open_analyzer_btn")
        self.assertEqual(len(self.notice.shown), 2)
        self.assertFalse(os.path.exists(self.prefs))

    def test_a_failing_notice_never_blocks_the_fallback(self):
        self.notice.error = RuntimeError("no WPF")
        self.fall_back()
        self.assertEqual(self.shell.opened, [self.queue.jobs()[0].paths.output, WEBSITE_URL])
        self.assertIn("Node.js was not found.", self.window.error_text.Text)

    def test_a_failing_preference_write_never_blocks_the_fallback(self):
        self.notice.answer = True
        os.makedirs(os.path.dirname(self.prefs))
        os.makedirs(self.prefs)  # a folder where the file should be: reading and writing fail
        self.fall_back()
        self.assertEqual(self.shell.opened, [self.queue.jobs()[0].paths.output, WEBSITE_URL])
        self.assertIn("Node.js was not found.", self.window.error_text.Text)

    def test_a_hidden_window_still_starts_the_next_export(self):
        self.submit("a", "b")
        self.idle_close()
        self.finish(0)
        self.tick()
        self.assertEqual([job.state for job in self.queue.jobs()], ["ok", "running"])

    def idle_close(self):
        args = types.SimpleNamespace(Cancel=False)
        self.window.Closing.fire(self.window, args)
        self.assertIs(args.Cancel, True)
        return args

    def test_timer_stops_when_idle_and_restarts_on_submit(self):
        self.submit("a")
        self.finish(0)
        self.tick()
        self.assertFalse(self.timer.IsEnabled)
        stops = self.timer.stops
        self.submit("b")
        self.assertTrue(self.timer.IsEnabled)
        self.assertEqual(self.queue.jobs()[1].state, "running")
        self.assertEqual(self.timer.stops, stops)

    def test_closing_minimises_while_busy_hides_when_idle_and_restores(self):
        self.submit("a")
        self.idle_close()
        self.assertEqual(self.window.WindowState, "Minimized")
        self.assertTrue(self.window.IsVisible)
        activations = self.window.activations
        self.finish(0)
        self.tick()
        self.assertEqual(self.window.WindowState, "Normal", "restored when the queue is idle")
        self.assertEqual(self.window.activations, activations, "without taking focus")
        self.idle_close()
        self.assertFalse(self.window.IsVisible)
        self.assertEqual(self.window.hides, 1)
        self.click("close_btn")
        self.assertEqual(self.window.closes, 0, "never destroyed")
        call(self.session.core, {"op": "show"})
        self.assertTrue(self.window.IsVisible)
        self.assertEqual(self.window.WindowState, "Normal")

    def test_close_button_minimises_while_busy(self):
        self.submit("a")
        self.click("close_btn")
        self.assertEqual(self.window.WindowState, "Minimized")
        call(self.session.core, {"op": "show"})
        self.assertEqual(self.window.WindowState, "Normal")

    def test_closing_is_not_blocked_while_the_dispatcher_shuts_down(self):
        self.submit("a")
        self.window.Dispatcher.ShutdownStarted.fire(None, None)
        args = types.SimpleNamespace(Cancel=False)
        self.window.Closing.fire(self.window, args)
        self.assertIs(args.Cancel, False)

    def test_errors_are_shown_and_the_next_tick_still_runs(self):
        self.submit("a")

        def broken():
            self.polls += 1
            raise RuntimeError("poll broke")
        self.queue.poll = broken
        polls = self.polls
        self.tick()
        self.assertIn("poll broke", self.window.error_text.Text)
        self.assertTrue(self.timer.IsEnabled)
        self.tick()
        self.assertEqual(self.polls, polls + 2)

    def test_handler_errors_are_shown_not_raised(self):
        self.submit("a")
        self.shell.fail = True
        self.select(0)
        self.click("open_folder_btn")
        self.assertIn("cannot open", self.window.error_text.Text)
        self.queue.cancel = lambda job_id: 1 / 0
        self.click("cancel_btn")
        self.assertIn("division", self.window.error_text.Text)
        self.window.jobs_lv.SelectedItem = object()  # not a row
        self.window.jobs_lv.SelectionChanged.fire(None, None)
        self.assertEqual(self.buttons(), (False, False, False))

    def test_window_texts_follow_language(self):
        with patch.dict(sys.modules, polish()):
            ui = load_status_ui()
            session = ui.Session(rx_runner.Queue(Starter(), Clock(), system_root=self.tmp),
                                 FakeTimer(), Clock(), ui.StatusWindow, Starter(),
                                 shell=Shell(), plan_analyzer=self.plan)
            self.assertEqual(session.window.Resources["status_close"], "Zamknij")


class OpenSession(unittest.TestCase):
    def setUp(self):
        SharedEventReactive.PropertyChanged = Event()
        FuncType.made = []
        self.domain = FakeDomain()
        self.timers = []
        patcher = patch.dict(sys.modules, ui_system_stubs(self.domain, self.timers))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ui = load_status_ui()

    def test_created_once_and_published_as_a_func(self):
        handler = self.ui.open_session(3)
        self.assertEqual(self.domain.sets, [SESSION_KEY])
        self.assertIs(self.domain.data[SESSION_KEY], handler)
        (types_, function), = FuncType.made
        self.assertEqual(types_, (str, str))
        self.assertEqual(len(self.timers), 1)
        self.assertEqual(self.timers[0].Interval, ("seconds", 1))
        self.assertIs(self.ui.open_session(1), handler, "the live session is reused")
        self.assertEqual(len(self.timers), 1)
        answer = json.loads(handler(json.dumps({"op": "ping"})))
        self.assertEqual((answer["ok"], answer["protocol"]), (True, PROTOCOL))

    def test_parallel_stays_one_until_verified(self):
        handler = self.ui.open_session(4)
        session = handler.__self__._listener
        self.assertEqual(session.queue._max, 1)

    def test_a_stale_handler_is_replaced(self):
        self.domain.data[SESSION_KEY] = answering(RuntimeError("old engine"))
        handler = self.ui.open_session(1)
        self.assertIs(self.domain.data[SESSION_KEY], handler)
        self.assertEqual(self.domain.sets, [SESSION_KEY])

    def test_submit_through_the_handler_holds_for_a_foreign_extractor(self):
        handler = self.ui.open_session(1)
        sys.modules["System.Diagnostics"].Process = types.SimpleNamespace(
            GetProcessesByName=lambda name: [types.SimpleNamespace(Dispose=lambda: None)])
        answer = json.loads(handler(json.dumps({"op": "submit", "jobs": [job_data()]})))
        self.assertEqual(answer["added"], ["job-1"])
        session = handler.__self__._listener
        self.assertIs(session.queue.held, True)
        self.assertEqual(session.queue.jobs()[0].state, "queued")
        row = list(session.window.jobs_lv.ItemsSource)[0]
        self.assertIn("another Extractor", row.Progress)


# --- Criterion 10: AST guards -------------------------------------------------------------------

def imported_names(node):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module or ""]
    return []


def ironpython_problems(source):
    tree = ast.parse(source)
    problems = []
    if not source.startswith("# -*- coding: utf-8 -*-"):
        problems.append("coding header")
    if "from __future__ import unicode_literals" not in source:
        problems.append("unicode_literals")
    for node in ast.walk(tree):
        if isinstance(node, (ast.JoinedStr, ast.AnnAssign, ast.AsyncFunctionDef, ast.Await,
                             ast.YieldFrom, ast.Nonlocal, ast.NamedExpr)):
            problems.append(type(node).__name__)
        if isinstance(node, ast.FunctionDef):
            if node.returns is not None or node.args.kwonlyargs:
                problems.append("annotation/kwonly: " + node.name)
            for arg in node.args.args:
                if arg.annotation is not None:
                    problems.append("annotation: " + node.name)
        if isinstance(node, ast.Starred) and not isinstance(getattr(node, "ctx", None), ast.Load):
            problems.append("starred assignment")
        for name in imported_names(node):
            if name.split(".")[0] in {"pathlib", "typing", "shlex", "subprocess", "threading",
                                      "_thread", "multiprocessing", "asyncio", "concurrent"}:
                problems.append("import " + name)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and \
                node.func.id == "print":
            problems.append("print")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and \
                node.func.id == "namedtuple" and node.args and \
                not (isinstance(node.args[0], ast.Call) and getattr(node.args[0].func, "id", "")
                     == "str"):
            problems.append("namedtuple name without str()")
    for banned in ("os.replace", "exist_ok", "yield from", ".format_map("):
        if banned in source:
            problems.append(banned)
    return problems


class Guards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pure = (LIB / "rx_status.py").read_text(encoding="utf-8")
        cls.ui = (LIB / "rx_status_ui.py").read_text(encoding="utf-8")

    def test_both_pass_the_ironpython_guard(self):
        self.assertEqual(ironpython_problems(self.pure), [])
        self.assertEqual(ironpython_problems(self.ui), [])

    def test_rx_status_is_pure(self):
        for node in ast.walk(ast.parse(self.pure)):
            for name in imported_names(node):
                self.assertNotIn(name.split(".")[0], {"pyrevit", "Autodesk", "System", "clr",
                                                      "rx_status_ui", "rx_reader", "rx_catalog"},
                                 name)

    def test_rx_status_ui_boundaries(self):
        tree = ast.parse(self.ui)
        for node in ast.walk(tree):
            for name in imported_names(node):
                self.assertNotIn(name.split(".")[0], {"Autodesk", "rx_reader", "rx_catalog",
                                                      "RevitServices"}, name)
                self.assertNotEqual(name, "pyrevit.script")
            if isinstance(node, ast.ImportFrom) and node.module == "pyrevit":
                self.assertEqual([alias.name for alias in node.names], ["forms"])
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"Exited", "EnableRaisingEvents",
                                             "OutputDataReceived", "ErrorDataReceived",
                                             "BeginOutputReadLine", "PropertyChanged", "alert",
                                             "get_output", "get_logger", "Kill"}, node.attr)
        self.assertNotIn("print", re.findall(r"\bprint\b", self.ui))

    def test_system_imports_only_inside_functions_or_guarded(self):
        tree = ast.parse(self.ui)

        def top_level(node, guarded=False):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.Lambda, ast.ClassDef)):
                    continue
                inside = guarded or isinstance(child, ast.Try)
                yield child, inside
                for item in top_level(child, inside):
                    yield item
        for node, guarded in top_level(tree):
            for name in imported_names(node):
                root = name.split(".")[0]
                if root in {"System", "clr"}:
                    self.fail("module-level System import: " + name)
                if root == "pyrevit":
                    self.assertTrue(guarded, "pyrevit import must be guarded")


if __name__ == "__main__":
    unittest.main()
