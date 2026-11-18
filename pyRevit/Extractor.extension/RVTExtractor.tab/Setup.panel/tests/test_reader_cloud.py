# -*- coding: utf-8 -*-
"""rx_reader.read_cloud / cloud_open_options / cloud_open_callback / release with recording
fakes (CPython). The collectors are replaced, so these tests cover the open, release and close
order only. Nothing here runs in Revit or proves IronPython accepts the callback class."""
import sys
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
        self.doc = NS(IsWorkshared=workshared, Close=self._close)

        class Callback(object):
            pass
        self.DB = NS(
            OpenOptions=lambda: Options(log),
            DetachFromCentralOption=NS(DoNotDetach="DoNotDetach",
                                       DetachAndPreserveWorksets="Detach"),
            WorksetConfiguration=lambda option: ("WorksetConfiguration", option),
            WorksetConfigurationOption=NS(OpenAllWorksets="OpenAll", CloseAllWorksets="Close"),
            ModelPathUtils=NS(ConvertCloudGUIDsToCloudPath=self._convert),
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

    def _open(self, *args):
        self.log.append(("open", len(args)))
        path, options, callback = args
        self.options, self.callback = options, callback
        if self.conflict is not None:
            self.log.append(("conflict", callback.OnOpenConflict(self.conflict)))
        if self.open_error is not None:
            raise self.open_error
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

    def read(self, region=REGION, values=True, caps=None):
        with patch.dict(sys.modules, self.system):
            return read_cloud(self.app, self.DB, region, PROJECT, MODEL,
                              caps or NS(ifc_setups=False), values=values)

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


if __name__ == "__main__":
    unittest.main()
