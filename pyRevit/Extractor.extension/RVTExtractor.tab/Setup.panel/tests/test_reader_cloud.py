# -*- coding: utf-8 -*-
"""rx_reader.read_cloud / cloud_open_options / cloud_open_callback / release with recording
fakes (CPython). The collectors are replaced, so these tests cover the open, release and close
order only. Nothing here runs in Revit or proves IronPython accepts the callback class."""
import datetime
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

LIB = Path(__file__).resolve().parents[3] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))

import rx_reader  # noqa: E402
from rx_reader import ReadError, cloud_open_callback, cloud_open_options, read_cloud, release  # noqa: E402

NS = types.SimpleNamespace
PROJECT = "11111111-1111-1111-1111-111111111111"
MODEL = "22222222-2222-2222-2222-222222222222"
REGION = "EMEA"
POLISH = {"pyrevit": NS(coreutils=NS(applocales=NS(get_locale_string=lambda d: d.get("pl"))))}
POLISH["pyrevit.coreutils"] = POLISH["pyrevit"].coreutils
POLISH["pyrevit.coreutils.applocales"] = POLISH["pyrevit"].coreutils.applocales


class Exc(Exception):
    """Host exception whose .NET type name is `name`; its message names the model and GUID."""

    def __init__(self, name):
        Exception.__init__(self, "Model Tower.rvt " + MODEL + " C:\\x")
        self.Message = str(self)
        self.GetType = lambda: NS(Name=name)


class Options(object):
    def __init__(self, log):
        self._log, self.worksets = log, None
        log.append("OpenOptions()")

    def SetOpenWorksetsConfiguration(self, config):
        self.worksets = config


class Workset(object):
    def __init__(self, editable):
        self.IsEditable = editable


class Host(object):
    def __init__(self, test, is_empty=True, logged_in=True, workshared=True, open_error=None,
                 conflict=None, relinquish_error=None, editable=(False, False),
                 close_result=True, close_error=None, collect_error=None):
        self.log = log = []
        self.close_calls = 0
        self.close_result, self.close_error = close_result, close_error
        self.open_error, self.conflict = open_error, conflict
        self.relinquish_error, self.editable = relinquish_error, editable
        self.callbacks = []
        self.opened_paths = []
        self.doc = NS(IsWorkshared=workshared, Close=self._close)

        class Callback(object):
            pass
        self.DB = NS(
            OpenOptions=lambda: Options(log),
            DetachFromCentralOption=NS(DoNotDetach="DoNotDetach",
                                       DetachAndPreserveWorksets="Detach"),
            WorksetConfiguration=lambda option: ("WorksetConfiguration", option),
            WorksetConfigurationOption=NS(OpenAllWorksets="OpenAll", CloseAllWorksets="Close"),
            ModelPathUtils=NS(ConvertCloudGUIDsToCloudPath=self._convert,
                              ConvertUserVisiblePathToModelPath=self._convert_local),
            IOpenFromCloudCallback=Callback,
            OpenConflictResult=NS(Cancel="Cancel", KeepLocalChanges="Keep",
                                  DiscardLocalChangesAndOpenLatestVersion="Discard",
                                  DetachFromCentral="Detach"),
            WorksharingUtils=NS(RelinquishOwnership=self._relinquish),
            RelinquishOptions=lambda everything: ("RelinquishOptions", everything),
            TransactWithCentralOptions=lambda: "TWC",
            FilteredWorksetCollector=self._worksets,
            WorksetKind=NS(UserWorkset="UserWorkset"),
        )
        self.app = NS(Documents=NS(IsEmpty=is_empty), IsLoggedIn=logged_in,
                      OpenDocumentFile=self._open)
        self.system = {"System": NS(Guid=lambda value: ("Guid", value))}
        patcher = patch.multiple(
            rx_reader,
            _kept_views=lambda doc, DB: self._collect("kept", [("v1", "FloorPlan", False)]),
            collect_views=lambda doc, DB, kept: self._collect(
                "views", {"views_2d": [{"id": "1"}], "views_3d": []}),
            collect_values=lambda doc, DB, views: self._collect("values", {"u": {"id": "1"}}),
            collect_cloud_links=lambda doc, DB: self._collect("links", [{"name": "L"}]),
        )
        patcher.start()
        test.addCleanup(patcher.stop)
        self.collect_error = collect_error

    def _collect(self, what, value):
        self.log.append(what)
        if self.collect_error is not None and what == "values":
            raise self.collect_error
        return value

    def _convert(self, *args):
        self.log.append(("convert",) + args)
        return "cloud-path"

    def _convert_local(self, path):
        self.log.append(("convert_local", path))
        return "local-path"

    def _open(self, *args):
        self.log.append(("open", len(args)))
        path, options, callback = args
        self.options, self.callback = options, callback
        self.opened_paths.append(path)
        if self.conflict is not None:
            self.log.append(("conflict", callback.OnOpenConflict(self.conflict)))
        error = self.open_error
        if isinstance(error, list):     # one error per call, then success
            error = error.pop(0) if error else None
        if error is not None:
            raise error
        return self.doc

    def _relinquish(self, doc, options, twc):
        self.log.append(("relinquish", doc is self.doc, options, twc))
        if self.relinquish_error is not None:
            raise self.relinquish_error

    def _worksets(self, doc):
        def of_kind(kind):
            self.log.append(("worksets", kind))
            return [Workset(value) for value in self.editable]
        return NS(OfKind=of_kind)

    def _close(self, *args):
        assert args == (False,), args
        self.close_calls += 1
        self.log.append("Close(False)")
        if self.close_error is not None:
            raise self.close_error
        return self.close_result

    def read(self, region=REGION, values=True, caps=None, all_worksets=True, **kwargs):
        with patch.dict(sys.modules, self.system):
            return read_cloud(self.app, self.DB, region, PROJECT, MODEL,
                              caps or NS(ifc_setups=False), values=values,
                              all_worksets=all_worksets, **kwargs)

    def events(self):
        return [item if isinstance(item, str) else item[0] for item in self.log]


def assert_no_secret(test, text):
    for secret in (PROJECT, MODEL, "Tower", "C:\\x", "cloud-path", REGION):
        test.assertNotIn(secret, text)


class CloudOptions(unittest.TestCase):
    def test_in_place_all_worksets_no_audit(self):
        host = Host(self)
        options = cloud_open_options(host.DB)
        self.assertEqual(options.DetachFromCentralOption, "DoNotDetach")
        self.assertEqual(options.worksets, ("WorksetConfiguration", "OpenAll"))
        self.assertIs(options.Audit, False)
        self.assertFalse(hasattr(options, "AllowOpeningLocalByWrongUser"))

    def test_closed_worksets_variant_is_still_in_place_and_no_audit(self):
        options = cloud_open_options(Host(self).DB, all_worksets=False)
        self.assertEqual(options.DetachFromCentralOption, "DoNotDetach")
        self.assertEqual(options.worksets, ("WorksetConfiguration", "Close"))
        self.assertIs(options.Audit, False)

    def test_read_cloud_closed_worksets_opens_with_the_closed_option(self):
        host = Host(self)
        host.read(all_worksets=False)
        self.assertEqual(host.options.worksets, ("WorksetConfiguration", "Close"))
        self.assertEqual(host.close_calls, 1)

    def test_callback_cancels_every_scenario(self):
        host = Host(self)
        callback = cloud_open_callback(host.DB)
        self.assertIsInstance(callback, host.DB.IOpenFromCloudCallback)
        for scenario in ("Rollback", "Relinquished", "OutOfDate", "VersionArchived", object()):
            self.assertEqual(callback.OnOpenConflict(scenario), "Cancel")
        self.assertEqual(callback.conflicts, 5)


class ReadCloudHappyPath(unittest.TestCase):
    def test_order_open_collect_relinquish_check_close_once(self):
        host = Host(self)
        snapshot = host.read()
        self.assertEqual(host.events(), ["convert", "OpenOptions()", "open", "kept", "views",
                                         "values", "links", "relinquish", "worksets",
                                         "Close(False)"])
        self.assertEqual(host.close_calls, 1)
        self.assertIn(("convert", REGION, ("Guid", PROJECT), ("Guid", MODEL)), host.log)
        self.assertIn(("open", 3), host.log)
        self.assertEqual(host.options.DetachFromCentralOption, "DoNotDetach")
        self.assertIn(("relinquish", True, ("RelinquishOptions", True), "TWC"), host.log)
        self.assertIn(("worksets", "UserWorkset"), host.log)
        self.assertEqual(snapshot, {"title": "", "path": "", "views_2d": [{"id": "1"}],
                                    "views_3d": [], "ifc_setups": [], "ifc_error": "",
                                    "links": [{"name": "L"}], "values": {"u": {"id": "1"}}})

    def test_values_false_skips_values(self):
        host = Host(self)
        snapshot = host.read(values=False)
        self.assertNotIn("values", snapshot)
        self.assertNotIn("values", host.events())

    def test_region_is_stripped(self):
        host = Host(self)
        host.read(region="  EMEA ")
        self.assertIn(("convert", "EMEA", ("Guid", PROJECT), ("Guid", MODEL)), host.log)

    def test_not_workshared_skips_release(self):
        host = Host(self, workshared=False)
        snapshot = host.read()
        self.assertNotIn("relinquish", host.events())
        self.assertNotIn("release_warning", snapshot)
        self.assertEqual(host.close_calls, 1)


class ReadCloudGuards(unittest.TestCase):
    def assert_nothing_opened(self, host):
        self.assertNotIn("open", host.events())
        self.assertEqual(host.close_calls, 0)

    def test_documents_open_is_busy(self):
        for value in (False, None, 1, "True"):
            host = Host(self, is_empty=value)
            with self.assertRaises(ReadError) as caught:
                host.read()
            self.assertEqual(caught.exception.kind, "busy")
            self.assert_nothing_opened(host)

    def test_not_logged_in(self):
        for value in (False, None, 1):
            host = Host(self, logged_in=value)
            with self.assertRaises(ReadError) as caught:
                host.read()
            self.assertEqual(caught.exception.kind, "not_signed_in")
            self.assert_nothing_opened(host)

    def test_unreadable_login_state_is_not_signed_in(self):
        host = Host(self)

        class App(object):
            Documents = NS(IsEmpty=True)

            @property
            def IsLoggedIn(self):
                raise Exc("InvalidOperationException")
        host.app = App()
        with self.assertRaises(ReadError) as caught:
            host.read()
        self.assertEqual(caught.exception.kind, "not_signed_in")
        self.assertEqual(caught.exception.detail, "InvalidOperationException")

    def test_empty_region(self):
        for region in ("", "  ", None):
            host = Host(self)
            with self.assertRaises(ReadError) as caught:
                host.read(region=region)
            self.assertEqual(caught.exception.kind, "open_failed")
            self.assertEqual(caught.exception.detail, "region unknown")
            self.assert_nothing_opened(host)

    def test_open_errors_carry_type_name_only(self):
        for name, kind in (("RevitServerUnauthenticatedUserException", "not_signed_in"),
                           ("FileNotFoundException", "open_failed"),
                           ("RevitServerUnauthorizedException", "open_failed")):
            host = Host(self, open_error=Exc(name))
            with self.assertRaises(ReadError) as caught:
                host.read()
            self.assertEqual(caught.exception.kind, kind)
            self.assertEqual(caught.exception.detail, name)
            assert_no_secret(self, caught.exception.message)
            self.assertEqual(host.close_calls, 0)

    def test_conflict_cancels_and_says_so(self):
        host = Host(self, conflict="OutOfDate", open_error=Exc("OperationCanceledException"))
        with self.assertRaises(ReadError) as caught:
            host.read()
        self.assertIn(("conflict", "Cancel"), host.log)
        self.assertEqual(caught.exception.kind, "open_failed")
        self.assertIn("conflict", caught.exception.message)
        self.assertEqual(host.close_calls, 0)

    def test_open_returning_none(self):
        host = Host(self)
        host.doc = None
        with self.assertRaises(ReadError) as caught:
            host.read()
        self.assertEqual(caught.exception.kind, "open_failed")


class ReadCloudRelease(unittest.TestCase):
    def test_relinquish_error_sets_warning_and_still_closes(self):
        host = Host(self, relinquish_error=Exc("CentralModelContentionException"))
        snapshot = host.read()
        self.assertEqual(host.close_calls, 1)
        warning = snapshot["release_warning"]
        self.assertIn("CentralModelContentionException", warning)
        assert_no_secret(self, warning)
        self.assertNotIn("worksets", host.events())

    def test_leftover_editable_workset_sets_warning(self):
        for editable in ((False, True), (False, None)):
            host = Host(self, editable=editable)
            snapshot = host.read()
            self.assertIn("editable worksets: 1", snapshot["release_warning"])
            self.assertEqual(host.events()[-3:], ["relinquish", "worksets", "Close(False)"])

    def test_warning_in_polish(self):
        host = Host(self, editable=(True,))
        with patch.dict(sys.modules, POLISH):
            snapshot = host.read()
        self.assertIn("Model może być nadal zajęty", snapshot["release_warning"])

    def test_release_function_contract(self):
        host = Host(self, workshared=None, editable=())
        self.assertEqual(release(host.doc, host.DB), (True, ""))
        self.assertIn("relinquish", host.events())  # unknown workshared state still releases
        host = Host(self, workshared=False)
        self.assertEqual(release(host.doc, host.DB), (True, ""))
        self.assertEqual(host.log, [])

    def test_collect_error_still_releases_and_closes_once(self):
        host = Host(self, collect_error=RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            host.read()
        self.assertEqual(host.events()[-3:], ["relinquish", "worksets", "Close(False)"])
        self.assertEqual(host.close_calls, 1)

    def test_collect_error_with_failed_release_reports_both(self):
        host = Host(self, collect_error=RuntimeError("boom " + MODEL),
                    relinquish_error=Exc("CentralModelException"))
        with self.assertRaises(ReadError) as caught:
            host.read()
        self.assertEqual(caught.exception.kind, "open_failed")
        self.assertIn("RuntimeError", caught.exception.message)
        self.assertIn("CentralModelException", caught.exception.message)
        assert_no_secret(self, caught.exception.message)
        self.assertEqual(host.close_calls, 1)

    def test_close_failure_is_close_failed_and_keeps_release_warning(self):
        for kwargs in ({"close_result": False}, {"close_error": Exc("InvalidOperationException")}):
            host = Host(self, relinquish_error=Exc("CentralModelException"), **kwargs)
            with self.assertRaises(ReadError) as caught:
                host.read()
            self.assertEqual(caught.exception.kind, "close_failed")
            self.assertIn("CentralModelException", caught.exception.message)
            assert_no_secret(self, caught.exception.message)
            self.assertEqual(caught.exception.detail, "")
            self.assertEqual(host.close_calls, 1)

    def test_release_raising_base_exception_still_closes_once(self):
        class Stop(BaseException):
            pass
        host = Host(self, relinquish_error=Stop())
        with self.assertRaises(Stop):
            host.read()
        self.assertEqual(host.close_calls, 1)


ROOT = "C:\\Cache\\acct\\" + PROJECT + "\\" + MODEL + ".rvt"
LINKED = "C:\\Cache\\acct\\" + PROJECT + "\\LinkedModels\\" + MODEL + ".rvt"
CENTRAL = "C:\\Cache\\acct\\" + PROJECT + "\\CentralCache\\" + MODEL + ".rvt"
LOG_FOLDER = "%APPDATA%\\RevitExtractor\\logs"


def net_type(name):
    return lambda: NS(Name=name.split(".")[-1], FullName=name)


def internal():
    """InternalException as IronPython wraps it (clsException), with an inner exception; both
    messages carry a GUID, as Revit's own texts may."""
    inner = NS(GetType=net_type("System.Exception"), HResult=-1, Message="inner of " + MODEL,
               StackTrace="   at Deep()", InnerException=None)
    error = Exception("A managed exception was thrown by Revit " + PROJECT)
    error.clsException = NS(GetType=net_type("Autodesk.Revit.Exceptions.InternalException"),
                            HResult=-2146233088, Message=str(error), Source="RevitAPI",
                            StackTrace="   at Open()\n   at Call()", InnerException=inner)
    return error


class ReadCloudRoutes(unittest.TestCase):
    def test_the_root_cache_file_is_opened_by_its_local_path_first(self):
        host = Host(self)
        host.read(local_path=ROOT)
        self.assertEqual(host.log[0], ("convert_local", ROOT))
        self.assertNotIn("convert", host.events(), "no cloud path when the local open works")
        self.assertEqual(host.opened_paths, ["local-path"])
        self.assertEqual(host.options.DetachFromCentralOption, "DoNotDetach")
        self.assertEqual(host.close_calls, 1)

    def test_a_linked_models_or_central_cache_copy_is_never_handed_to_revit(self):
        for path in (LINKED, CENTRAL, LINKED.replace("\\", "/")):
            host = Host(self)
            host.read(local_path=path)
            self.assertNotIn("convert_local", host.events())
            self.assertEqual(host.opened_paths, ["cloud-path"])

    def test_root_cache_file_rule(self):
        self.assertTrue(rx_reader.root_cache_file(ROOT))
        for value in (LINKED, CENTRAL, "", None, "C:\\a.txt", "a.rvt"):
            self.assertFalse(rx_reader.root_cache_file(value), value)

    def test_a_failed_local_open_tries_the_cloud_path_once(self):
        host = Host(self, open_error=[internal()])
        snapshot = host.read(local_path=ROOT)
        self.assertEqual(host.opened_paths, ["local-path", "cloud-path"])
        self.assertIn("views_2d", snapshot)
        self.assertEqual(host.close_calls, 1)

    def test_both_routes_failing_reports_the_first_and_closes_nothing(self):
        host = Host(self, open_error=[internal(), Exc("FileNotFoundException")])
        with self.assertRaises(ReadError) as caught:
            host.read(local_path=ROOT)
        self.assertEqual(caught.exception.detail, "InternalException")
        self.assertEqual(host.close_calls, 0)

    def test_not_signed_in_on_the_second_route_wins(self):
        host = Host(self, open_error=[internal(), Exc("RevitServerUnauthenticatedUserException")])
        with self.assertRaises(ReadError) as caught:
            host.read(local_path=ROOT)
        self.assertEqual(caught.exception.kind, "not_signed_in")

    def test_a_conflict_or_a_cancel_is_not_retried(self):
        host = Host(self, conflict="OutOfDate", open_error=[Exc("OperationCanceledException")])
        with self.assertRaises(ReadError):
            host.read(local_path=ROOT)
        self.assertEqual(host.opened_paths, ["local-path"])
        host = Host(self, open_error=[Exc("OperationCanceledException")])
        with self.assertRaises(ReadError):
            host.read(local_path=ROOT)
        self.assertEqual(host.opened_paths, ["local-path"])

    def test_no_second_route_while_a_document_is_open(self):
        host = Host(self, open_error=[internal()])
        empties = iter([True, True, False])

        class Docs(object):
            @property
            def IsEmpty(self):
                return next(empties)
        host.app.Documents = Docs()
        with self.assertRaises(ReadError):
            host.read(local_path=ROOT)
        self.assertEqual(host.opened_paths, ["local-path"])

    def test_without_region_the_local_route_still_runs(self):
        host = Host(self)
        host.read(region="", local_path=ROOT)
        self.assertEqual(host.opened_paths, ["local-path"])


class Dialogs(object):
    """UIApplication.DialogBoxShowing as IronPython exposes it: += and -= of a function."""

    def __init__(self, show=()):
        self.handlers, self.show, self.overridden = [], list(show), []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self

    def fire(self):
        for args in self.show:
            args.OverrideResult = self.overridden.append
            for handler in list(self.handlers):
                handler(None, args)


class ReadCloudDiagnostics(unittest.TestCase):
    def setUp(self):
        self.entries = []

    def write(self, lines):
        import rx_cloud_log
        self.entries.append(rx_cloud_log.mask("\n".join(lines)))
        return "C:\\log\\cloud-open-20261119.log"

    def failing_host(self, dialogs=None):
        host = Host(self, open_error=[internal(), Exc("FileNotFoundException")])
        host.app.VersionNumber, host.app.VersionBuild = "2022", "22.1.0.0"
        if dialogs is not None:
            original = host._open

            def open_with_dialog(*args):
                dialogs.fire()
                return original(*args)
            host.app.OpenDocumentFile = open_with_dialog
        return host

    def test_a_failure_writes_one_entry_with_both_attempts(self):
        host = self.failing_host()
        with self.assertRaises(ReadError) as caught:
            host.read(local_path=ROOT, diagnostics=self.write)
        self.assertEqual(len(self.entries), 1)
        entry = self.entries[0]
        for expected in ("guard > sign-in", "version=2022 build=22.1.0.0", "region: 'EMEA'",
                         "len=36 canonical=yes", "worksets=OpenAllWorksets",
                         "local path: root cache file", "attempt 1: route=local stage=open",
                         "callback=CancelOnConflict outcome=failed",
                         "Autodesk.Revit.Exceptions.InternalException", "HResult: -2146233088",
                         "StackTrace:    at Open()", "inner 1: System.Exception",
                         "attempt 2: route=cloud", "python traceback", "logged in: True",
                         "documents empty at start: True"):
            self.assertIn(expected, entry)
        self.assertIn(LOG_FOLDER, caught.exception.message)
        self.assertIn(LOG_FOLDER, str(caught.exception.args[0]))
        assert_no_secret(self, caught.exception.message)

    def test_the_entry_names_no_guid_value(self):
        host = self.failing_host()
        with self.assertRaises(ReadError):
            host.read(local_path=ROOT, diagnostics=self.write)
        self.assertNotIn(PROJECT, self.entries[0])
        self.assertNotIn(MODEL, self.entries[0])

    def test_the_reader_s_own_lines_hold_no_guid_or_path(self):
        lines = []
        host = Host(self, open_error=Exc("FileNotFoundException"))
        with self.assertRaises(ReadError):
            host.read(local_path=ROOT, diagnostics=lambda got: lines.extend(got) or "x")
        own = [line for line in lines if "python:" not in line and "Message" not in line
               and "File " not in line and not line.startswith("      ")]
        for line in own:
            for secret in (PROJECT, MODEL, "C:\\Cache"):
                self.assertNotIn(secret, line)

    def test_success_writes_nothing_and_a_missing_log_adds_no_hint(self):
        Host(self).read(local_path=ROOT, diagnostics=self.write)
        self.assertEqual(self.entries, [])
        host = self.failing_host()
        with self.assertRaises(ReadError) as caught:
            host.read(local_path=ROOT, diagnostics=lambda lines: None)
        self.assertNotIn("log folder", caught.exception.message)

    def test_a_broken_logger_never_hides_the_read_error(self):
        host = self.failing_host()

        def broken(lines):
            raise IOError("disk")
        with self.assertRaises(ReadError) as caught:
            host.read(local_path=ROOT, diagnostics=broken)
        self.assertEqual(caught.exception.detail, "InternalException")

    def test_a_guard_failure_is_logged_too(self):
        host = Host(self, is_empty=False)
        with self.assertRaises(ReadError):
            host.read(diagnostics=self.write)
        self.assertIn("stages reached: guard", self.entries[0])

    def test_the_log_hint_is_polish_in_polish(self):
        host = self.failing_host()
        with patch.dict(sys.modules, POLISH):
            with self.assertRaises(ReadError) as caught:
                host.read(local_path=ROOT, diagnostics=self.write)
        self.assertIn("Szczegóły są w folderze logów " + LOG_FOLDER, caught.exception.message)

    def test_revit_dialogs_are_logged_never_answered_and_unsubscribed(self):
        shown = NS(DialogId="Dialog_Revit_HostFailed", Message="The host model failed to open.",
                   GetType=lambda: NS(Name="TaskDialogShowingEventArgs"))
        dialogs = Dialogs([shown])
        host = self.failing_host(dialogs)
        with self.assertRaises(ReadError) as caught:
            host.read(local_path=ROOT, diagnostics=self.write,
                      uiapp=NS(DialogBoxShowing=dialogs))
        self.assertEqual(dialogs.overridden, [], "never answered")
        self.assertEqual(dialogs.handlers, [], "unsubscribed in finally")
        self.assertIn("revit dialogs during the read: 2", self.entries[0])
        self.assertIn("id=Dialog_Revit_HostFailed", self.entries[0])
        self.assertIn("message=The host model failed to open.", self.entries[0])
        self.assertIn("Revit showed its own dialog", caught.exception.message)
        self.assertNotIn("host model failed", caught.exception.message, "no Revit text in the UI")

    def test_the_hook_is_removed_after_a_success_too(self):
        dialogs = Dialogs()
        Host(self).read(uiapp=NS(DialogBoxShowing=dialogs))
        self.assertEqual(dialogs.handlers, [])

    def test_a_hook_that_cannot_subscribe_does_not_stop_the_read(self):
        class NoEvents(object):
            @property
            def DialogBoxShowing(self):
                raise Exc("InvalidOperationException")
        self.assertIn("views_2d", Host(self).read(uiapp=NoEvents()))


class CloudLog(unittest.TestCase):
    def setUp(self):
        import rx_cloud_log
        self.log = rx_cloud_log
        self.tmp = tempfile.mkdtemp(prefix="rx-cloud-log-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.folder = self.log.log_folder(self.tmp)

    def read_text(self, path):
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_append_creates_the_dated_file_and_masks_guids(self):
        path = self.log.append(self.folder, ["model " + MODEL, "braces {" + PROJECT.upper() + "}",
                                             "plain " + MODEL.replace("-", "")],
                               now=datetime.datetime(2026, 11, 19, 8, 0))
        self.assertEqual(path, os.path.join(self.tmp, "RevitExtractor", "logs",
                                            "cloud-open-20261119.log"))
        content = self.read_text(path)
        self.assertEqual(content.count("<guid>"), 3)
        self.assertNotIn(MODEL, content)

    def test_the_file_stays_under_the_cap_and_keeps_the_newest_entries(self):
        for number in range(12):
            path = self.log.append(self.folder, ["entry %04d " % number + "x" * 1000],
                                   max_bytes=5 * 1024)
        content = self.read_text(path)
        self.assertLessEqual(os.path.getsize(path), 5 * 1024)
        self.assertIn("entry 0011", content)
        self.assertNotIn("entry 0000", content)
        self.assertTrue(content.lstrip("\n").startswith("entry "), "cut at a line start")

    def test_the_default_cap_is_about_200_kb(self):
        self.assertEqual(self.log.MAX_BYTES, 200 * 1024)

    def test_an_entry_larger_than_the_cap_is_cut(self):
        path = self.log.append(self.folder, ["y" * 5000], max_bytes=1000)
        self.assertLessEqual(os.path.getsize(path), 1000)

    def test_old_files_are_pruned_and_the_cache_is_never_written(self):
        for day in range(1, 15):
            self.log.append(self.folder, ["x"], now=datetime.datetime(2026, 11, day))
        self.assertEqual(len(os.listdir(self.folder)), self.log.KEEP_FILES)
        self.assertIn("cloud-open-20261114.log", os.listdir(self.folder))
        cache = os.path.join(self.tmp, "CollaborationCache", "logs")
        self.assertIsNone(self.log.append(cache, ["x"]))
        self.assertFalse(os.path.exists(cache))

    def test_guid_shape_never_shows_the_value(self):
        self.assertEqual(self.log.guid_shape(MODEL), "len=36 canonical=yes")
        self.assertEqual(self.log.guid_shape("abc"), "len=3 canonical=no")

    def test_append_never_raises(self):
        self.assertIsNone(self.log.append(None, ["x"]))


if __name__ == "__main__":
    unittest.main()
