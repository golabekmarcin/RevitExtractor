# -*- coding: utf-8 -*-
"""The status window: one modeless window per Revit session that owns the export queue.

IronPython 2.7 inside pyRevit. Pure logic is in rx_status.py; this file is the WPF side:
open_session (AppDomain data), Session (queue + window + DispatcherTimer) and StatusWindow.
Spec: specs/SPEC-status-window.md.

This code may keep running after pyRevit shut its script engine down (`engine: clean: true`, a
reload): pyRevit's builtins are None then and its output is disposed. So it never prints, never
uses pyrevit.script, its logger or forms.alert, makes no Revit API call, and every timer tick and
event handler catches its own errors and shows them on the window's error line. System and WPF
are imported inside functions; the pyrevit import is guarded so CPython tests can load the
helpers. No Python threads, no process events, no per-row subscriptions.
"""
from __future__ import unicode_literals

import datetime
import os
import re

from rx_i18n import tr
from rx_runner import QUEUED, RUNNING, DotNetStarter, Queue, effective_parallel
from rx_status import (WEBSITE_URL, SessionCore, analyzer_plan, find_session, hide_notice,
                       job_view, notice_hidden, notice_resources, preferences_path,
                       progress_info, publish_session, queue_hint, resources, summary)

try:
    from pyrevit import forms
except Exception:  # outside pyRevit (CPython tests): only the helpers are usable
    forms = None

_WINDOW_BASE = forms.WPFWindow if forms is not None else object
_ROW_BASE = forms.Reactive if forms is not None else object

LIB_DIR = os.path.dirname(os.path.abspath(__file__))
XAML_PATH = os.path.join(LIB_DIR, "rx_status.xaml")
NOTICE_XAML_PATH = os.path.join(LIB_DIR, "rx_notice.xaml")
THEME_PATH = os.path.join(LIB_DIR, "rx_theme.xaml")
TICK_SECONDS = 1
_LOOPBACK_URL = re.compile(r"^http://127\.0\.0\.1:\d{1,5}/\Z")


def _error_text(error):
    if error.args:
        try:
            return "%s" % (error.args[0],)
        except Exception:
            pass
    return type(error).__name__


# --- thin .NET helpers ----------------------------------------------------------------------

def _openable(target):
    try:
        text = "%s" % (target,) if target is not None else ""
    except Exception:
        return False
    if not text or '"' in text or "\n" in text or "\r" in text:
        return False
    if text == WEBSITE_URL or _LOOPBACK_URL.match(text):
        return True
    return os.path.isabs(text) and os.path.isdir(text)


def shell_open(target):
    """Shell-open an existing folder, the local Analyzer URL or WEBSITE_URL; nothing else."""
    if not _openable(target):
        raise ValueError(tr("Not opened (only an existing folder or the Analyzer page): {0}",
                            "Nie otwarto (tylko istniejący folder lub strona Analyzera): {0}")
                         .format(target))
    from System.Diagnostics import Process, ProcessStartInfo
    info = ProcessStartInfo()
    info.FileName = target
    info.UseShellExecute = True
    process = Process.Start(info)
    if process is not None:
        process.Dispose()


def free_port():
    """A free TCP port on 127.0.0.1, released again before the Analyzer binds it."""
    from System.Net import IPAddress
    from System.Net.Sockets import TcpListener
    listener = TcpListener(IPAddress.Loopback, 0)
    listener.Start()
    try:
        return int(listener.LocalEndpoint.Port)
    finally:
        listener.Stop()


def node_major(path):
    """Major version from node.exe's file version; no process is started."""
    from System.Diagnostics import FileVersionInfo
    return int(FileVersionInfo.GetVersionInfo(path).FileMajorPart)


def _plan_analyzer(output):
    return analyzer_plan(output, LIB_DIR, os.environ, os.path.isfile, node_major, free_port)


def _preferences_path():
    return preferences_path(os.environ.get("APPDATA"))


# --- window ---------------------------------------------------------------------------------

class StatusRow(_ROW_BASE):
    """One export. Plain attributes for the columns; the list is refreshed once per tick."""

    def __init__(self, view):
        self.JobId = view["id"]
        self.view = None
        self.update(view)

    def update(self, view):
        """Take a new job_view(); True when anything shown changed."""
        changed = view != self.view
        self.view = view
        self.Model = view["model"]
        self.ModelPath = view["model_path"]
        self.State = view["state_text"]
        self.Progress = view["progress"]
        self.Started = view["started"]
        self.Time = view["time"]
        return changed


class StatusWindow(_WINDOW_BASE):
    """Created once per session and never destroyed: Close minimises or hides it.

    `actions` (the Session) has cancel(job_id), open_folder(view), open_analyzer(view) and
    close_window().
    """

    def __init__(self, actions):
        from System.Collections.ObjectModel import ObservableCollection
        from System.Windows import WindowState
        self._actions = actions
        self._window_state = WindowState
        self._shutting_down = False
        # Esc is the Close button (IsCancel); pyRevit's Esc hook would call Close().
        forms.WPFWindow.__init__(self, XAML_PATH, handle_esc=False)
        self.apply_resources()
        self.merge_resource_dict(THEME_PATH)
        try:
            self.Style = self.FindResource("RxWindow")
        except Exception:
            pass
        self._rows = ObservableCollection[object]()
        self._by_id = {}
        self.jobs_lv.ItemsSource = self._rows
        self.jobs_lv.SelectionChanged += self._on_selection
        self.cancel_btn.Click += self._on_cancel
        self.open_folder_btn.Click += self._on_open_folder
        self.open_analyzer_btn.Click += self._on_open_analyzer
        self.close_btn.Click += self._on_close_click
        self.Closing += self._on_closing
        try:
            self.Dispatcher.ShutdownStarted += self._on_shutdown
        except Exception:
            pass
        self.error_text.Text = ""
        self._update_buttons()

    def apply_resources(self):
        """(Re)load the localized texts; also on every show, so a pyRevit language change that
        reloaded the script reaches the retained window."""
        for key, value in resources().items():
            self.Resources[key] = value

    # -- shown state

    def show_views(self, views, summary_line, hint):
        """Add new rows, update the others, and refresh the list once if anything changed."""
        changed = False
        first_new = None
        for view in views:
            row = self._by_id.get(view["id"])
            if row is None:
                row = StatusRow(view)
                self._by_id[view["id"]] = row
                self._rows.Add(row)
                if first_new is None:
                    first_new = row
            elif row.update(view):
                changed = True
        if changed:
            self.jobs_lv.Items.Refresh()
        if first_new is not None and self._selected_row() is None:
            self.jobs_lv.SelectedItem = first_new
        self._set_text(self.summary_text, summary_line)
        self._set_text(self.hint_text, hint)
        self._update_buttons()
        return changed

    def _set_text(self, control, text):
        if control.Text != text:
            control.Text = text

    def show_error(self, text):
        self._set_text(self.error_text, text or "")

    def _selected_row(self):
        row = self.jobs_lv.SelectedItem
        return row if isinstance(row, StatusRow) else None

    def selected_view(self):
        row = self._selected_row()
        return row.view if row is not None else None

    def _update_buttons(self):
        view = self.selected_view() or {}
        self.cancel_btn.IsEnabled = bool(view.get("can_cancel"))
        self.open_folder_btn.IsEnabled = bool(view.get("can_open_folder"))
        self.open_analyzer_btn.IsEnabled = bool(view.get("can_open_analyzer"))

    def bring_up(self):
        if not self.IsVisible:
            self.Show()
        if self.WindowState == self._window_state.Minimized:
            self.WindowState = self._window_state.Normal
        self.Activate()

    def minimise(self):
        self.WindowState = self._window_state.Minimized

    def restore_quietly(self):
        """Back from minimised when the queue becomes idle; Activate() is not called."""
        if self.IsVisible and self.WindowState == self._window_state.Minimized:
            self.WindowState = self._window_state.Normal

    # -- handlers: each catches its own errors

    def _guard(self, action, *args):
        try:
            self.show_error("")
            action(*args)
        except Exception as error:
            self._report(error)

    def _report(self, error):
        try:
            self.show_error(tr("Status window error: {0}", "Błąd okna statusu: {0}")
                            .format(_error_text(error)))
        except Exception:
            pass

    def _on_selection(self, sender, args):
        try:
            self._update_buttons()
        except Exception as error:
            self._report(error)

    def _on_cancel(self, sender, args):
        view = self.selected_view()
        if view and view.get("can_cancel"):
            self._guard(self._actions.cancel, view["id"])

    def _on_open_folder(self, sender, args):
        view = self.selected_view()
        if view and view.get("can_open_folder"):
            self._guard(self._actions.open_folder, view)

    def _on_open_analyzer(self, sender, args):
        view = self.selected_view()
        if view and view.get("can_open_analyzer"):
            self._guard(self._actions.open_analyzer, view)

    def _on_close_click(self, sender, args):
        self._guard(self._actions.close_window)

    def _on_closing(self, sender, args):
        if self._shutting_down:
            return  # never hold up Revit's exit
        try:
            args.Cancel = True
        except Exception:
            return
        self._guard(self._actions.close_window)

    def _on_shutdown(self, sender, args):
        self._shutting_down = True


class NoticeWindow(_WINDOW_BASE):
    """Modal "Node.js is needed" notice. OK is the default and cancel button (rx_notice.xaml), so
    the window needs no click handler; the caller reads the check box after ShowDialog."""

    def __init__(self, reason):
        forms.WPFWindow.__init__(self, NOTICE_XAML_PATH)
        for key, value in notice_resources().items():
            self.Resources[key] = value
        self.merge_resource_dict(THEME_PATH)
        try:
            self.Style = self.FindResource("RxWindow")
        except Exception:
            pass
        self.reason_text.Text = reason or ""


def show_notice(reason):
    """Show the notice modally; True when "Don't show this again" was ticked."""
    window = NoticeWindow(reason)
    window.ShowDialog()
    return bool(window.dont_show_chk.IsChecked)


# --- session --------------------------------------------------------------------------------

def _has_exited(handle):
    try:
        return bool(handle.has_exited())
    except Exception:
        return True


class Session(object):
    """The export queue, its window and the DispatcherTimer that polls it.

    The timer belongs to the session, not the window, so a hidden window still starts the next
    export. It runs while the queue is busy and stops when it is idle. One session per Revit
    process; it lives as long as the handler published in AppDomain data.
    """

    def __init__(self, queue, timer, clock, window_factory, starter, shell=None,
                 plan_analyzer=None, notice=None, preferences=None):
        self.queue = queue
        self._timer = timer
        self._clock = clock
        self._starter = starter
        self._shell = shell or shell_open
        self._plan = plan_analyzer or _plan_analyzer
        self._notice = notice or show_notice  # notice(reason) -> True when "don't show again"
        self._preferences = preferences if preferences is not None else _preferences_path()
        self._analyzers = {}  # job id -> (handle, url); servers this session started
        self._was_busy = False
        self.handler = None
        self.core = SessionCore(queue, clock, self)
        self.window = window_factory(self)
        timer.Tick += self.tick

    # -- SessionCore listener (called through the published handler)

    def on_submit(self, job_ids):
        if not self._timer.IsEnabled:
            self._timer.Start()
        self.tick()
        self.window.bring_up()

    def on_show(self):
        try:
            self.window.apply_resources()
        except Exception as error:
            self.window._report(error)
        self.refresh()
        self.window.bring_up()

    # -- timer

    def tick(self, sender=None, args=None):
        """Poll once, refresh once; never raises into the dispatcher."""
        try:
            self.queue.poll()
            self.refresh()
            busy = self.queue.busy()
            if not busy:
                self._timer.Stop()
                if self._was_busy:
                    self.window.restore_quietly()
            self._was_busy = busy
        except Exception as error:
            self.window._report(error)

    def views(self):
        now = self._clock()
        held = bool(getattr(self.queue, "held", False))
        views = []
        position = 0
        for job in self.queue.jobs():
            info = None
            place = None
            if job.state == RUNNING:
                info = progress_info(self.queue.tail(job.id))
            elif job.state == QUEUED:
                position += 1
                place = position
            views.append(job_view(job, info, now, place, held=held))
        return views

    def refresh(self):
        views = self.views()
        return self.window.show_views(views, summary(views), queue_hint(views))

    # -- window actions

    def cancel(self, job_id):
        acted = self.queue.cancel(job_id)
        self.refresh()
        if not acted:
            self.window.show_error(tr(
                "The export could not be cancelled. If it is still running, try again.",
                "Nie udało się anulować eksportu. Jeśli nadal trwa, spróbuj ponownie."))

    def open_folder(self, view):
        self._shell(view["folder"])

    def open_analyzer(self, view):
        job_id = view["id"]
        known = self._analyzers.get(job_id)
        if known is not None:
            handle, url = known
            if not _has_exited(handle):
                self._shell(url)
                return
            del self._analyzers[job_id]
        plan = self._plan(view["output"])
        if plan[0] == "local":
            spec, url = plan[1], plan[2]
            # A visible console: closing it stops the server (D10). Node opens the browser.
            self._analyzers[job_id] = (self._starter.start(spec, show_window=True), url)
            return
        self._explain_fallback(plan[1])
        problems = []
        for target in (view["output"], WEBSITE_URL):
            try:
                self._shell(target)
            except Exception as error:
                problems.append(_error_text(error))
        message = tr("The local Analyzer is not available: {0} The output folder and the website "
                     "were opened instead.",
                     "Lokalny Analyzer jest niedostępny: {0} Zamiast niego otwarto folder output "
                     "i stronę internetową.").format(plan[1])
        self.window.show_error(" ".join([message] + problems))

    def _explain_fallback(self, reason):
        """The Node.js notice, unless the user hid it. Never raises: the fallback goes on."""
        try:
            if notice_hidden(self._preferences):
                return
            if self._notice(reason):
                hide_notice(self._preferences)
        except Exception:
            pass

    def close_window(self):
        if self.queue.busy():
            self.window.minimise()
        else:
            self.window.Hide()


def open_session(max_parallel=1):
    """This Revit process's session handler (a Func[String, String]); created on first use.

    A published handler that answers ping with this PROTOCOL is reused, from any script engine.
    Otherwise a new session is created and published; an old one keeps running its own jobs,
    and the hold gate keeps the two from starting two Extractors at once.
    """
    from System import AppDomain, Func, String, TimeSpan
    from System.Windows.Threading import DispatcherTimer
    domain = AppDomain.CurrentDomain
    handler = find_session(domain)
    if handler is not None:
        return handler
    starter = DotNetStarter()
    clock = datetime.datetime.now
    queue = Queue(starter, clock, max_parallel=effective_parallel(max_parallel),
                  hold=starter.extractor_running)
    timer = DispatcherTimer()
    timer.Interval = TimeSpan.FromSeconds(TICK_SECONDS)
    session = Session(queue, timer, clock, StatusWindow, starter)
    handler = Func[String, String](session.core.handle)
    session.handler = handler
    publish_session(domain, handler)
    return handler
