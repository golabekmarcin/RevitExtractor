# -*- coding: utf-8 -*-
"""The Export button's two modal windows: ModelWindow (model list) and ViewWindow (views).

IronPython 2.7 inside pyRevit. No Revit import: script.py passes in `read` (background read of
one model), `read_info` (version facts without opening), the catalog `scan` and the settings
callback, so the window tests can prove that nothing else opens a model.
Spec: specs/SPEC-export-button.md.

Speed with many rows: pyRevit's forms.Reactive declares PropertyChanged once at class level,
so all rows share one handler list. The windows never subscribe to row events. Each list is one
CollectionView (search and column filters refresh it). A checkbox Click bubbles to one ListView
handler. Bulk changes set the rows quietly and refresh the list once. The model scan is pulled
from a DispatcherTimer in slices of at most 40 ms, so rows appear while files are read.
"""
from __future__ import unicode_literals

import os
import time
import uuid

from System import Action, Environment, Predicate, TimeSpan
from System.Collections.ObjectModel import ObservableCollection
from System.IO import File
from System.Text import UTF8Encoding
from System.Windows import RoutedEventHandler, Visibility
from System.Windows.Controls import ComboBoxItem
from System.Windows.Controls.Primitives import ButtonBase
from System.Windows.Data import CollectionViewSource
from System.Windows.Input import Cursors, Key, Mouse
from System.Windows.Threading import DispatcherPriority, DispatcherTimer
from pyrevit import forms

import rx_cloud
from rx_cloud import StageError
from rx_column_filter_ui import ColumnFilterController
from rx_export_logic import (inside_onedrive, link_key, load_shared_index, plan_cloud_job, plan_cloud_jobs,
                             plan_jobs, settings_to_save, has_nested_roots, tick_targets, toggled_state)
from rx_export_text import resources
from rx_i18n import tr
from rx_index import SetupError, build_index, database_warning, defaults, to_json
from rx_runner import RunnerError, clean_path
from rx_search_bar import SearchBar

try:
    text = unicode  # IronPython 2.7
except NameError:
    text = str

HERE = os.path.dirname(os.path.abspath(__file__))
# Extractor.extension/lib, three levels up from RVTExtractor.tab/Setup.panel/Export.pushbutton.
LIB_DIR = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir, "lib"))
THEME_PATH = os.path.join(LIB_DIR, "rx_theme.xaml")
MODELS_XAML = os.path.join(HERE, "rx_export_models.xaml")
VIEWS_XAML = os.path.join(HERE, "rx_export_views.xaml")

SCAN_SLICE_SECONDS = 0.04   # at most this long per timer tick (spec: 40 ms)
SCAN_INTERVAL_MS = 10
FOLDER_COLUMN, VERSION_COLUMN = 2, 3   # models_lv: check, name, folder, version, note
TYPE_COLUMN = 2                        # views2d_lv: check, name, type, ElementId
DIMENSIONS = ("2d", "3d")
SEPARATOR = "    •    "
MAX_NOTES_SHOWN = 3
CLOUD_PREFIX = "cloud:"     # rx_cloud.CloudRow keys; a local job key is a normalized path
# Settings key -> check box. Only the keys in defaults(caps) are read or shown.
BOOL_CONTROLS = {
    "enable_2d": "enable2d_cb", "enable_3d": "enable3d_cb", "pdb": "pdb_cb",
    "aec_model_data": "aec_cb", "design_description": "description_cb",
    "generate_master_views": "master_cb", "f2d": "f2d_cb",
    "extended_properties": "extended_cb", "topology_metadata": "topology_cb",
    "dwg": "dwg_cb", "ifc": "ifc_cb",
}


def _error_text(error):
    if getattr(error, "args", None):
        try:
            return "%s" % (error.args[0],)
        except Exception:
            pass
    try:
        return text(error)
    except Exception:
        return type(error).__name__


def _key(path):
    return os.path.normcase(os.path.normpath(path))


def _shown(flag):
    return Visibility.Visible if flag else Visibility.Collapsed


def _render_pass():
    """Empty dispatcher job: invoking it at Background priority lets one render run first."""


def _apply_theme(window):
    # The XAML labels are {DynamicResource key}; they update as soon as the keys exist.
    for key, value in resources().items():
        window.Resources[key] = value
    window.merge_resource_dict(THEME_PATH)
    try:
        window.Style = window.FindResource("RxWindow")
    except Exception:
        pass


def _guarded(handler):
    """An event handler that shows its error on the window's error line instead of raising
    into the WPF dispatcher."""
    def run(self, *args):
        try:
            return handler(self, *args)
        except Exception as error:
            try:
                self._show_error(tr("Unexpected error: {0}", "Nieoczekiwany błąd: {0}")
                                 .format(_error_text(error)))
            except Exception:
                pass
    run.__name__ = handler.__name__
    run.__doc__ = handler.__doc__
    return run


def write_index_atomic(path, content):
    """Keep the previous index intact if writing or replacement fails."""
    temporary = path + "." + uuid.uuid4().hex + ".tmp"
    try:
        File.WriteAllText(temporary, content, UTF8Encoding(False))
        if File.Exists(path):
            File.Replace(temporary, path, None)
        else:
            File.Move(temporary, path)
    finally:
        if File.Exists(temporary):
            File.Delete(temporary)


# =============================================================================== model window

def _masked(value):
    """A window handle as one comparable number: window handles use 32 significant bits on 32-
    and 64-bit Windows, and ctypes may return them signed. None stays None."""
    if value is None:
        return None
    try:
        return int(value) & 0xFFFFFFFF
    except Exception:
        return None


def _foreground_handle():
    """The window that has the keyboard focus system-wide, as a number; None when unknown."""
    try:
        import ctypes
        function = ctypes.windll.user32.GetForegroundWindow
        function.restype = ctypes.c_void_p      # pointer-sized, not a signed 32-bit int
        return _masked(function())
    except Exception:
        return None


def _handle_number(handle):
    try:
        return _masked(handle.ToInt64())    # an IntPtr
    except Exception:
        return _masked(handle)


def reclaim_front(window, revit_handle, foreground=_foreground_handle):
    """Bring `window` back to the front when it is not active and Revit's main window has the
    front. The windows here are modal over Revit, so Revit's window is never meant to be in
    front of them; any other program in front is left alone (the user went there). True when
    the window was reclaimed."""
    try:
        if window.IsActive or not revit_handle:
            return False
        if _masked(foreground()) != _masked(revit_handle):
            return False
        window.Activate()
        return True
    except Exception:
        return False


def keep_in_front(window, revit_handle):
    """After this window is deactivated, reclaim the front once things have settled (Revit
    takes the front while a cloud list loads or a model opens in the background)."""
    number = _handle_number(revit_handle)
    if not number:
        return False
    def after_deactivation(sender, args):
        try:
            window.Dispatcher.BeginInvoke(DispatcherPriority.Background,
                                          Action(lambda: reclaim_front(window, number)))
        except Exception:
            pass
    try:
        window.Deactivated += after_deactivation
    except Exception:
        return False
    return True


class ModelRow(forms.Reactive):
    """One model file from the catalog. Plain attributes for the columns and the item style;
    Checked notifies the checkbox. Greyed rows (newer or unreadable version) have Enabled False."""

    def __init__(self, row):
        self.path = row.path
        self.workshared = row.workshared
        self.state = row.state
        self.enabled = row.enabled is True
        self.Enabled = self.enabled
        self.Name = row.name
        self.Folder = row.folder
        self.Version = row.version or ""
        self.Note = row.note or ""
        self.Tip = row.path if self.enabled else (row.note or row.path)
        self.SearchText = self.Name.lower()
        self.SearchWide = " ".join((self.Name, self.Folder)).lower()
        self.job_key = _key(row.path)
        self._checked = False

    @forms.reactive
    def Checked(self):
        return self._checked

    @Checked.setter
    def Checked(self, value):
        self._checked = bool(value)

    def set_quietly(self, value):
        """No PropertyChanged: the caller refreshes the list once afterwards."""
        self._checked = bool(value)


class CloudModelRow(forms.Reactive):
    """One cloud model from the cache catalog (an rx_cloud.CloudRow). Shows the real project and
    file name and the cache date, never the GUID-named cache file. `cloud` is the plain CloudRow."""

    def __init__(self, row):
        self.cloud = row
        self.key = row.key
        self.job_key = row.key
        self.cache_path = row.cache_path
        self.state = row.state
        self.enabled = row.enabled is True
        self.Enabled = self.enabled
        self.Name = row.name
        self.Project = row.project
        self.CacheDate = row.cache_date
        self.Note = row.note or ""
        self.Tip = row.note if row.note else "%s / %s" % (row.project, row.name)
        self.SearchText = row.name.lower()
        self.SearchWide = " ".join((row.name, row.project)).lower()
        self._checked = False

    @forms.reactive
    def Checked(self):
        return self._checked

    @Checked.setter
    def Checked(self, value):
        self._checked = bool(value)

    def set_quietly(self, value):
        """No PropertyChanged: the caller refreshes the list once afterwards."""
        self._checked = bool(value)


class ProjectRow(forms.Reactive):
    """One cloud project in the projects card (an rx_cloud.Project): a check box."""

    def __init__(self, project):
        self.key = project.key
        if project.unnamed:
            self.Label = tr("{0} (models: {1}, without a name: {2})",
                            "{0} (modele: {1}, bez nazwy: {2})").format(
                project.name, project.count, project.unnamed)
        else:
            self.Label = tr("{0} (models: {1})", "{0} (modele: {1})").format(
                project.name, project.count)
        self.Tip = project.note or self.Label
        self._checked = bool(project.selected)

    @forms.reactive
    def Checked(self):
        return self._checked

    @Checked.setter
    def Checked(self, value):
        self._checked = bool(value)


ROW_TYPES = (ModelRow, CloudModelRow)


class ModelWindow(forms.WPFWindow):
    """Pick models, then Export (one job per ticked model) or Choose views… (one model).

    Export hands the jobs over at once through `submit(jobs, output_parent)` (script.py) and the
    window STAYS OPEN, so more exports can be queued. `submit` returns {"queued": n, "failed":
    [positions in jobs], "warning": text} or raises with the error text. Closing the window hands
    over nothing. After show_dialog(): `output_parent` is the chosen output folder; `fatal_error`
    is set when Revit did not close a model read in the background (the window then closed).

    `cloud` (optional) adds the Cloud source: {"folders": rx_cloud.revit_folders(...), "memory":
    rx_cloud.Memory}, plus optional "scan", "scan_cache" and "now" for tests. It is scanned
    time-sliced from the same timer, on the first switch to Cloud. `read(path, workshared,
    links=False)` also reads the link list of a cloud model. Export and Choose views… act on the
    source that is shown.
    """

    def __init__(self, caps, settings, read_info, cache, read, save_settings, extractor_build="",
                 scan=None, clock=None, submit=None, cloud=None):
        self._updating = True
        self._caps = caps
        self._read_info = read_info
        self._cache = cache
        self._read = read
        self._save_settings = save_settings
        self._submit = submit
        self._submitting = False
        self._kept_jobs = {}            # _key(path) -> job from Choose views… that failed to queue
        self._scan = scan
        self._clock = clock or time.time
        self._roots = list(settings.get("roots") or [])
        self._max_parallel = settings.get("max_parallel", 1)
        self._shared_path = settings.get("shared_index_path") or ""
        self._subfolders = settings.get("subfolders") is not False
        self.output_parent = settings.get("output_parent") or ""
        self.fatal_error = None
        self._generator = None
        self._scan_errors = []
        self._local_copies = 0
        self._keep = set()
        self._loaded = False
        self._cloud = cloud
        self._source = "local"
        self._cloud_gen = None
        self._cloud_started = False
        self._cloud_catalog = None
        self._cloud_files = None        # the cache files, walked at most once per scan
        self._cloud_keep = set()        # keys ticked before a rescan, restored when it ends
        self._host_only = set()         # cloud keys exported without their links (open failed)
        self._statuses = {"local": "", "cloud": ""}
        # Esc: the search bar clears a filled box first, then Close (IsCancel) closes.
        forms.WPFWindow.__init__(self, MODELS_XAML, handle_esc=False)
        _apply_theme(self)

        header = caps.label
        if extractor_build:
            header = header + "   ·   Extractor " + extractor_build
        self.caps_text.Text = header
        self._show_roots()
        self.folders_exp.IsExpanded = not self._roots   # folders are set up once; then out of the way
        self._show_output()
        self._show_shared_path()
        self.default_scope_rb.IsChecked = True
        self.shared_scope_rb.IsChecked = False

        self._rows = ObservableCollection[object]()
        self._search = SearchBar(self.search_host, self._on_filter_changed, regex=True,
                                 tooltip=tr("Search by file name (tick \"Also search folder\" to include the folder)",
                                            "Szukaj po nazwie pliku (zaznacz \"Szukaj też w folderze\", aby objąć folder)"))
        # Before any Filter is assigned: the view may run the predicate at once.
        self._filters = ColumnFilterController(
            lambda: self._rows, self._on_filter_changed,
            base_visible=lambda row: self._search.matches(self._search_text(row)))
        columns = self.models_lv.View.Columns
        self._filters.register(columns[FOLDER_COLUMN], self.Resources["models_col_folder"],
                               "Folder")
        self._filters.register(columns[VERSION_COLUMN], self.Resources["models_col_version"],
                               "Version")
        self._search.bind_filters(self._filters)
        self._view = CollectionViewSource.GetDefaultView(self._rows)
        self._view.Filter = Predicate[object](self._visible)
        self.models_lv.ItemsSource = self._view
        # One handler per list: a row checkbox Click bubbles up here.
        self.models_lv.AddHandler(ButtonBase.ClickEvent, RoutedEventHandler(self._on_check_click))
        self.models_lv.PreviewKeyDown += self._on_list_key_down

        self._cloud_rows = ObservableCollection[object]()
        self._cloud_view = CollectionViewSource.GetDefaultView(self._cloud_rows)
        self._cloud_view.Filter = Predicate[object](self._cloud_visible)
        self.cloud_lv.ItemsSource = self._cloud_view
        self.cloud_lv.AddHandler(ButtonBase.ClickEvent, RoutedEventHandler(self._on_check_click))
        self.cloud_lv.PreviewKeyDown += self._on_list_key_down
        self.cloud_projects_lb.AddHandler(ButtonBase.ClickEvent,
                                          RoutedEventHandler(self._on_project_click))
        self.cloud_message_text.Text = ""
        self.source_local_rb.IsChecked = True
        self.source_cloud_rb.IsChecked = False
        self.source_bar.Visibility = _shown(cloud is not None)
        self.cloud_panel.Visibility = _shown(False)
        self.cloud_header.Visibility = _shown(False)

        self._timer = DispatcherTimer()
        self._timer.Interval = TimeSpan.FromMilliseconds(SCAN_INTERVAL_MS)
        self._timer.Tick += self._on_tick

        self.add_root_btn.Click += self._on_add_root
        self.remove_root_btn.Click += self._on_remove_root
        self.output_btn.Click += self._on_output
        self.shared_choose_btn.Click += self._on_shared_choose
        self.default_scope_rb.Checked += self._on_scope_changed
        self.shared_scope_rb.Checked += self._on_scope_changed
        self.source_local_rb.Checked += self._on_source_changed
        self.source_cloud_rb.Checked += self._on_source_changed
        self.all_btn.Click += self._on_select_all
        self.none_btn.Click += self._on_unselect_all
        self.rescan_btn.Click += self._on_rescan
        self.subfolders_cb.IsChecked = self._subfolders
        self.subfolders_cb.Click += self._on_subfolders
        self.search_folder_cb.Click += self._on_filter_changed
        self.close_btn.Click += self._on_close
        self.views_btn.Click += self._on_views
        self.export_btn.Click += self._on_export
        self._revit_handle = None
        self.Loaded += self._on_loaded
        self.Closed += self._on_closed
        self.error_text.Text = ""
        self._updating = False
        self._refresh_state()

    # -- texts

    def _show_error(self, message):
        self.error_text.Text = message or ""

    def _set_status(self, message):
        self.status_text.Text = message or ""

    def _show_output(self):
        self.output_text.Text = self.output_parent
        self.output_text.ToolTip = self.output_parent or None
        self.output_warn_text.Visibility = _shown(inside_onedrive(self.output_parent))

    def _show_roots(self):
        """The folder list, and its one-line summary beside the collapsed "Model folders"."""
        self.roots_lb.ItemsSource = list(self._roots)
        summary = ", ".join(self._roots) if self._roots else tr(
            "none yet: open this section and add a folder",
            "brak: rozwiń tę sekcję i dodaj folder")
        self.folders_summary_text.Text = summary
        self.folders_summary_text.ToolTip = summary

    def _own(self, window):
        """Make this window the owner of a child window, so the child stays above it."""
        try:
            window.Owner = self
        except Exception:   # a window that cannot be owned still works, only less tidily
            pass
        if self._revit_handle:
            keep_in_front(window, self._revit_handle)

    def keep_in_front(self, revit_handle):
        """script.py gives the Revit main window handle: this window and its children then
        win the front back from Revit (see reclaim_front)."""
        self._revit_handle = revit_handle
        return keep_in_front(self, revit_handle)

    def _show_shared_path(self):
        if self._shared_path:
            self.shared_path_text.Text = self._shared_path
            self.shared_path_text.ToolTip = self._shared_path
        else:
            self.shared_path_text.Text = tr("No file chosen.", "Nie wybrano pliku.")
            self.shared_path_text.ToolTip = None

    # -- scan

    def _on_loaded(self, sender, args):
        if self._loaded:
            return
        self._loaded = True
        self._start_scan()

    def _say(self, source, message):
        """Status line text of one source; shown at once only while that source is shown."""
        self._statuses[source] = message or ""
        if source == self._source:
            self._set_status(message)

    def _start_scan(self):
        self._stop_local_scan()
        self._scan_errors = []
        self._local_copies = 0
        if not self._roots:
            self._stop_timer_if_idle()
            self._say("local", tr("Add a folder with models (Add folder…).",
                                  "Dodaj folder z modelami (Dodaj folder…)."))
            self._refresh_state()
            return
        if self._scan is None:
            self._stop_timer_if_idle()
            self._show_error(tr("The model list is not available.",
                                "Lista modeli jest niedostępna."))
            return
        self._generator = self._scan(list(self._roots), self._caps.year, self._read_info,
                                     self._cache, errors=self._scan_errors,
                                     subfolders=self._subfolders)
        self._say("local", tr("Reading the model folders…", "Odczytywanie folderów z modelami…"))
        self._timer.Start()
        self._refresh_state()

    def _stop_local_scan(self):
        generator, self._generator = self._generator, None
        if generator is not None:
            try:
                generator.close()
            except Exception:
                pass

    def _stop_cloud_scan(self):
        generator, self._cloud_gen = self._cloud_gen, None
        if generator is not None:
            try:
                generator.close()
            except Exception:
                pass

    def _stop_timer_if_idle(self):
        if self._generator is None and self._cloud_gen is None:
            self._timer.Stop()

    def _scanning(self):
        return self._generator is not None or self._cloud_gen is not None

    def stop_scan(self):
        """Stop the timer and close both scan generators (the local one saves the catalog
        cache). Safe to call more than once; script.py calls it after the dialog."""
        self._stop_local_scan()
        self._stop_cloud_scan()
        self._timer.Stop()

    def _on_tick(self, sender, args):
        if self._generator is None and self._cloud_gen is None:
            self._timer.Stop()
            return
        local_active = self._generator is not None
        deadline = self._clock() + SCAN_SLICE_SECONDS
        try:
            self._pump_local(deadline)
        except Exception as error:
            self._stop_local_scan()
            self._stop_timer_if_idle()
            self._show_error(tr("The model list could not be read: {0}",
                                "Nie udało się odczytać listy modeli: {0}")
                             .format(_error_text(error)))
        if self._cloud_gen is not None and not (local_active and self._clock() >= deadline):
            self._pump_cloud(deadline)
        self._refresh_state()

    def _pump_local(self, deadline):
        while self._generator is not None:
            try:
                row = next(self._generator)
            except StopIteration:
                self._generator = None
                self._stop_timer_if_idle()
                self._scan_finished()
                break
            self._add_row(row)
            if self._clock() >= deadline:
                break

    def _add_row(self, row):
        if row.state == "local_copy":
            self._local_copies += 1
            return
        model = ModelRow(row)
        if model.enabled and _key(model.path) in self._keep:
            model.set_quietly(True)
        self._rows.Add(model)

    def _scan_finished(self):
        self._keep = set()
        status = tr("Models found: {0}.", "Znalezione modele: {0}.").format(len(self._rows))
        if getattr(self._cache, "last_error", None):
            status += " " + tr("The model list cache could not be saved; the next start reads "
                               "every file again.",
                               "Nie udało się zapisać pamięci podręcznej listy; przy następnym "
                               "uruchomieniu wszystkie pliki zostaną odczytane ponownie.")
        self._say("local", status)

    def _rescan(self):
        keep = set(_key(row.path) for row in self._ticked_in(self._rows))
        if self._generator is not None:
            keep |= self._keep          # ticks of rows the interrupted scan had not reached
        self._keep = keep
        # The list is rebuilt: a retained views job of a local row is dropped.
        self._kept_jobs = dict((key, job) for key, job in self._kept_jobs.items()
                               if key.startswith(CLOUD_PREFIX))
        self._stop_local_scan()
        self._rows.Clear()
        self._start_scan()

    @_guarded
    def _on_subfolders(self, sender, args):
        self._subfolders = bool(self.subfolders_cb.IsChecked)
        self._show_error("")
        self._persist()
        if self._loaded and self._roots:
            self._rescan()

    @_guarded
    def _on_rescan(self, sender, args):
        self._show_error("")
        if self._source == "cloud":
            self._rescan_cloud()
        else:
            self._rescan()

    def _on_closed(self, sender, args):
        self.stop_scan()

    # -- rows

    def _visible(self, row):
        return self._search.matches(self._search_text(row)) and self._filters.matches(row)

    def _project_chosen(self):
        catalog = self._cloud_catalog
        return catalog is not None and any(project.selected for project in catalog.projects)

    def _cloud_visible(self, row):
        # once a project is ticked, models of the other projects are hidden, not greyed
        if row.state == "not_selected" and self._project_chosen():
            return False
        return self._search.matches(self._search_text(row))

    def _search_text(self, row):
        """File name only, or name and folder (project for cloud) when the box is ticked."""
        return row.SearchWide if self.search_folder_cb.IsChecked else row.SearchText

    @staticmethod
    def _ticked_in(rows):
        return [row for row in rows if row.enabled and row.Checked]

    def _ticked(self):
        """Ticked rows of the shown source that may be exported, in list order. A greyed row
        never counts."""
        return self._ticked_in(self._cloud_rows if self._source == "cloud" else self._rows)

    def _set_checked(self, list_view, rows, state):
        for row in rows:
            row.set_quietly(state)
        list_view.Items.Refresh()

    @_guarded
    def _on_check_click(self, sender, args):
        row = getattr(args.OriginalSource, "DataContext", None)
        if not isinstance(row, ROW_TYPES):
            return  # e.g. a column header or its filter button
        if not row.enabled:
            row.set_quietly(False)
            sender.Items.Refresh()
            self._refresh_state()
            return
        # The binding has already updated row.Checked. A checkbox on a row that is part of a
        # multi-row highlight applies to the whole highlight, greyed rows left out.
        targets = [target for target in tick_targets(sender.SelectedItems, row)
                   if isinstance(target, ROW_TYPES) and target.enabled]
        if len(targets) > 1:
            self._set_checked(sender, targets, row.Checked)
        self._refresh_state()

    @_guarded
    def _on_list_key_down(self, sender, args):
        if args.Key != Key.Space:
            return
        # Only on a row or the list itself: a filter popup's search box and value checkboxes
        # route their keys through the column header into this list.
        source = args.OriginalSource
        if source is not sender and not isinstance(getattr(source, "DataContext", None),
                                                   ROW_TYPES):
            return
        highlighted = list(sender.SelectedItems)
        if not highlighted:
            return
        # Handled first, so a focused checkbox does not also toggle itself.
        args.Handled = True
        rows = [row for row in highlighted if isinstance(row, ROW_TYPES) and row.enabled]
        if rows:
            self._set_checked(sender, rows, toggled_state([row.Checked for row in rows]))
        self._refresh_state()

    def _shown_list(self):
        """(ListView, its collection view) of the shown source."""
        if self._source == "cloud":
            return self.cloud_lv, self._cloud_view
        return self.models_lv, self._view

    @_guarded
    def _on_select_all(self, sender, args):
        list_view, view = self._shown_list()
        self._set_checked(list_view, [row for row in view if row.enabled], True)
        self._refresh_state()

    @_guarded
    def _on_unselect_all(self, sender, args):
        list_view, view = self._shown_list()
        self._set_checked(list_view, [row for row in view if row.enabled], False)
        self._refresh_state()

    def _on_filter_changed(self, *unused):
        if not self._updating:
            self._view.Refresh()
            self._cloud_view.Refresh()
            self._refresh_state()

    def _shared_scope(self):
        return bool(self.shared_scope_rb.IsChecked)

    def _forget_unticked(self):
        """A retained views job and a host-alone choice are dropped once the row is unticked."""
        ticked_keys = set(row.job_key for row in self._ticked_in(self._rows))
        ticked_keys |= set(row.job_key for row in self._ticked_in(self._cloud_rows))
        for key in list(self._kept_jobs):
            if key not in ticked_keys:
                del self._kept_jobs[key]
        self._host_only &= ticked_keys

    def _refresh_state(self):
        self._forget_unticked()
        if self._source == "cloud":
            self._refresh_cloud_state()
            return
        rows = list(self._rows)
        ticked = [row for row in rows if row.enabled and row.Checked]
        count = tr("Selected: {0} / {1}{2}Shown: {3}{2}Local copies skipped: {4}",
                   "Zaznaczone: {0} / {1}{2}Widoczne: {3}{2}Pominięte kopie lokalne: {4}") \
            .format(len(ticked), len(rows), SEPARATOR, self._view.Count, self._local_copies)
        if self._scan_errors:
            count += SEPARATOR + tr("Folders that could not be read: {0}",
                                    "Foldery, których nie udało się odczytać: {0}") \
                .format(len(self._scan_errors))
        self.count_text.Text = count
        self.count_text.ToolTip = "\n".join(self._scan_errors) if self._scan_errors else None
        self.views_btn.IsEnabled = len(ticked) == 1
        self.export_btn.IsEnabled = bool(ticked)
        if not ticked:
            self.summary_text.Text = tr("No model selected.", "Nie zaznaczono modelu.")
            return
        summary = tr("Models selected: {0}", "Zaznaczone modele: {0}").format(len(ticked))
        older = len([row for row in ticked if row.state == "older"])
        if older:
            summary += SEPARATOR + tr(
                "older Revit version: {0} (the export upgrades a temporary copy)",
                "starsza wersja Revita: {0} (eksport uaktualni tymczasową kopię)").format(older)
        if self._shared_scope():
            summary += SEPARATOR + tr("shared index.json", "wspólny index.json")
        else:
            summary += SEPARATOR + tr("Extractor default scope", "domyślny zakres Extractora")
        self.summary_text.Text = summary

    # -- settings

    def _persist(self, values=None):
        if values is None:
            values = settings_to_save(self._roots, self.output_parent, self._max_parallel,
                                      self._shared_path, self._subfolders)
        try:
            self._save_settings(values)
        except Exception as error:
            self._show_error(tr("The settings could not be saved: {0}",
                                "Nie udało się zapisać ustawień: {0}").format(_error_text(error)))
            return False
        return True

    def _change_roots(self, roots):
        values = settings_to_save(roots, self.output_parent, self._max_parallel,
                                  self._shared_path, self._subfolders)
        redundant = self._subfolders and has_nested_roots(values["roots"])
        if redundant or [_key(root) for root in values["roots"]] == [_key(root) for root in self._roots]:
            self._set_status(tr("That folder is already in the list (or inside one that is).",
                                "Ten folder jest już na liście (lub w folderze z listy)."))
            return
        self._roots = values["roots"]
        self._show_roots()
        self._show_error("")
        self._persist(values)
        if self._loaded:
            self._rescan()

    @_guarded
    def _on_add_root(self, sender, args):
        path = forms.pick_folder(title=tr("Choose a folder with models",
                                          "Wybierz folder z modelami"))
        if not path:
            return
        self._change_roots(list(self._roots) + [text(path)])

    @_guarded
    def _on_remove_root(self, sender, args):
        selected = self.roots_lb.SelectedItem
        if not selected:
            return
        key = _key(text(selected))
        self._change_roots([root for root in self._roots if _key(root) != key])

    @_guarded
    def _on_output(self, sender, args):
        path = forms.pick_folder(title=tr("Choose the output folder",
                                          "Wybierz folder wyników"))
        if not path:
            return
        try:
            chosen = clean_path(text(path))
        except RunnerError as error:
            self._show_error(_error_text(error))
            return
        self.output_parent = chosen
        self._show_output()
        self._show_error("")
        self._persist()

    @_guarded
    def _on_shared_choose(self, sender, args):
        start = os.path.dirname(self._shared_path) if self._shared_path else ""
        path = forms.pick_file(file_ext="json",
                               files_filter=tr("Extractor configuration (*.json)|*.json",
                                               "Konfiguracja Extractora (*.json)|*.json"),
                               init_dir=start,
                               title=tr("Choose the shared index.json",
                                        "Wybierz wspólny plik index.json"))
        if not path:
            return
        path = text(path)
        try:
            load_shared_index(path)
        except SetupError as error:
            self._show_error(_error_text(error))
            return
        self._shared_path = path
        self._show_shared_path()
        self._updating = True
        try:
            self.default_scope_rb.IsChecked = False
            self.shared_scope_rb.IsChecked = True
        finally:
            self._updating = False
        self._show_error("")
        self._persist()
        self._refresh_state()

    @_guarded
    def _on_scope_changed(self, sender, args):
        if not self._updating:
            self._show_error("")
            self._refresh_state()

    # -- footer

    @_guarded
    def _on_close(self, sender, args):
        self.Close()

    @_guarded
    def _on_export(self, sender, args):
        if self._submitting:
            return                      # a second click while the hand-over runs
        models = self._ticked()
        if not models:
            return
        if self._source == "cloud":
            self._export_cloud(models)
            return
        # A row whose Choose views… hand-over failed sends exactly that job again, so the shared
        # index.json (checked only for the other rows) cannot block that retry.
        fresh = [row for row in models if row.job_key not in self._kept_jobs]
        planned = {}
        if fresh:
            try:
                shared = self._shared_index_or_none()
                planned = dict(zip([row.job_key for row in fresh],
                                   plan_jobs(fresh, self._caps, shared)))
            except SetupError as error:
                self._show_error(_error_text(error))
                return
        jobs = [self._kept_jobs.get(row.job_key) or planned[row.job_key] for row in models]
        self._queue(jobs, models)

    def _shared_index_or_none(self):
        """The shared index.json when that scope is chosen, else None. Raises SetupError."""
        if not self._shared_scope():
            return None
        if not self._shared_path:
            raise SetupError(tr("Choose the shared index.json first (Choose…).",
                                "Najpierw wybierz wspólny plik index.json (Wybierz…)."))
        return load_shared_index(self._shared_path)

    def _kept_note(self, models, positions):
        """Error-line sentence when a retained views job stays for one of `positions`."""
        if any(models[position].job_key in self._kept_jobs for position in positions):
            return " " + tr("The selected views are kept; click Export to try again.",
                            "Wybrane widoki zostały zachowane; kliknij Eksportuj, aby spróbować "
                            "ponownie.")
        return ""

    def _queue(self, jobs, models, retain=False, notes=()):
        """Hand `jobs` (one per row in `models`, same order) to the queue and stay open.

        The button is off while the hand-over runs, and `_submitting` drops a click that still
        gets through. Success clears the ticks of the queued models and shows a confirmation on
        the status line. A failure shows the error and keeps every tick so the user can retry;
        with partial errors only the models that failed keep their tick. No modal alert.
        `retain` (the job came from Choose views…) keeps a failed job for the next Export click;
        a queued job is forgotten. `notes` (cloud staging notes) are shown on the error line
        after a hand-over.
        """
        if self._submitting:
            return False
        self._submitting = True
        self.export_btn.IsEnabled = False
        self.views_btn.IsEnabled = False
        try:
            try:
                if self._submit is None:
                    raise RuntimeError(tr("The export queue is not available.",
                                          "Kolejka eksportów jest niedostępna."))
                result = self._submit(jobs, self.output_parent)
            except Exception as error:
                if retain:
                    for row, job in zip(models, jobs):
                        self._kept_jobs[row.job_key] = job
                self._show_error((_error_text(error) or type(error).__name__) +
                                 self._kept_note(models, range(len(models))))
                return False
            if not isinstance(result, dict):
                result = {}
            failed = set(number for number in (result.get("failed") or [])
                         if isinstance(number, int))
            for position, row in enumerate(models):
                if position not in failed:
                    row.set_quietly(False)
                    self._kept_jobs.pop(row.job_key, None)
                    self._host_only.discard(row.job_key)
                elif retain:
                    self._kept_jobs[row.job_key] = jobs[position]
            self.models_lv.Items.Refresh()
            self.cloud_lv.Items.Refresh()
            if not failed:
                self._reset_scope()
            queued = result.get("queued")
            if not isinstance(queued, int):
                queued = len(jobs) - len(failed)
            warning = result.get("warning") or ""
            if warning:
                warning += self._kept_note(models, sorted(failed))
            note_text = self._notes_text(notes)
            if note_text:
                warning = (warning + " " + note_text).strip()
            self._show_error(warning)
            self._set_status(tr("Exports queued: {0}. Close this window or queue more.",
                                "Dodano eksportów do kolejki: {0}. Zamknij okno albo dodaj "
                                "kolejne.").format(queued))
            self._persist()
            return True
        finally:
            self._submitting = False
            self._refresh_state()

    def _reset_scope(self):
        """Back to the Extractor default scope; the remembered shared index.json file stays."""
        self._updating = True
        try:
            self.default_scope_rb.IsChecked = True
            self.shared_scope_rb.IsChecked = False
        finally:
            self._updating = False

    def _save_dir(self):
        if self._shared_path:
            return os.path.dirname(self._shared_path)
        return self.output_parent

    def _force_render(self):
        try:
            self.Dispatcher.Invoke(DispatcherPriority.Background, Action(_render_pass))
        except Exception:
            pass

    @_guarded
    def _on_views(self, sender, args):
        models = self._ticked()
        if len(models) != 1:
            self._show_error(tr("Select exactly one model to choose its views.",
                                "Zaznacz dokładnie jeden model, aby wybrać jego widoki."))
            return
        row = models[0]
        if self._source == "cloud":
            self._views_cloud(row)
            return
        resume = self._scanning()
        snapshot, failure = self._read_in_background(
            row.Name, lambda: self._read(row.path, row.workshared))
        if failure is not None:
            if not self._read_failed(failure):
                self._resume(resume)
            return
        try:
            view = ViewWindow(snapshot, self._caps, note=row.Note, save_dir=self._save_dir())
            self._own(view)
            view.show_dialog()
        except Exception as error:
            self._show_error(tr("The view window failed: {0}", "Błąd okna widoków: {0}")
                             .format(_error_text(error)))
            self._resume(resume)
            return
        job = getattr(view, "job", None)
        if job:
            self._queue([job], [row], retain=True)
        self._resume(resume)
        self._refresh_state()

    def _read_in_background(self, name, call):
        """Run `call` (a background read of one model) with the scan paused, the window off and
        a wait cursor. Returns (snapshot, failure); failure is the exception, never raised."""
        self._timer.Stop()                  # no file is read while the model is open
        self._show_error("")
        self._set_status(tr("Reading {0} in the background (worksets closed, nothing is "
                            "saved). This can take a few minutes…",
                            "Odczytywanie {0} w tle (zamknięte zestawy robocze, nic nie jest "
                            "zapisywane). To może potrwać kilka minut…").format(name))
        self.IsEnabled = False
        Mouse.OverrideCursor = Cursors.Wait
        snapshot, failure = None, None
        try:
            self._force_render()
            snapshot = call()
        except Exception as error:
            failure = error
        finally:
            Mouse.OverrideCursor = None
            self.IsEnabled = True
            try:
                self.Activate()    # a disabled window loses focus; take it back
            except Exception:
                pass
        self._set_status("")
        return snapshot, failure

    def _read_failed(self, failure):
        """Show a failed Choose views… read. True when the window was closed instead: Revit could
        not close the model, so it may still be open and nothing may be queued."""
        kind = getattr(failure, "kind", None)
        if kind == "close_failed":
            self.fatal_error = _error_text(failure)
            self.Close()
            return True
        if kind in ("busy", "open_failed"):
            self._show_error(_error_text(failure))
        else:
            self._show_error(tr("The model could not be read: {0}",
                                "Nie udało się odczytać modelu: {0}")
                             .format(_error_text(failure)))
        return False

    def _resume(self, resume):
        if resume and self._scanning():
            self._timer.Start()

    # -- cloud source

    def _cloud_value(self, name, default):
        value = self._cloud.get(name) if self._cloud else None
        return value if value is not None else default

    def _cloud_now(self):
        return self._cloud_value("now", time.time)()

    @_guarded
    def _on_source_changed(self, sender, args):
        if self._updating:
            return
        wanted = "cloud" if self.source_cloud_rb.IsChecked else "local"
        if wanted == "cloud" and self._cloud is None:
            wanted = "local"
        if wanted == self._source:
            return
        self._source = wanted
        self._show_error("")
        cloud = wanted == "cloud"
        self.models_lv.Visibility = _shown(not cloud)
        self.cloud_panel.Visibility = _shown(cloud)
        self.cloud_header.Visibility = _shown(cloud)   # projects card, like the folders section
        self.folders_exp.Visibility = _shown(not cloud)   # folders belong to local files only
        self._set_status(self._statuses[wanted])
        if cloud and not self._cloud_started:
            self._start_cloud_scan()
        self._refresh_state()

    def _start_cloud_scan(self):
        self._stop_cloud_scan()
        self._cloud_started = True
        self._cloud_files = None
        self._cloud_catalog = None
        scan = self._cloud_value("scan", rx_cloud.scan)
        self._cloud_gen = scan(self._cloud["folders"], self._cloud["memory"], self._cloud_now())
        self._say("cloud", tr("Reading the Revit journals and cache…",
                              "Odczytywanie dzienników i pamięci podręcznej Revita…"))
        self._timer.Start()
        self._refresh_state()

    def _pump_cloud(self, deadline):
        while self._cloud_gen is not None:
            try:
                item = next(self._cloud_gen)
                if isinstance(item, rx_cloud.Catalog):
                    self._cloud_scan_finished(item)
                    continue
            except StopIteration:
                self._cloud_gen = None
                self._stop_timer_if_idle()
                break
            except Exception as error:
                self._stop_cloud_scan()
                self._stop_timer_if_idle()
                self._show_error(tr("The cloud model list could not be read: {0}",
                                    "Nie udało się odczytać listy modeli z chmury: {0}")
                                 .format(_error_text(error)))
                break
            if self._clock() >= deadline:
                break

    def _show_cloud_rows(self, catalog):
        """Rebuild the rows; ticks of rows that are still enabled survive, keyed by CloudRow.key."""
        keep = set(self._cloud_keep) | set(row.key for row in self._ticked_in(self._cloud_rows))
        self._cloud_rows.Clear()
        for cloud_row in catalog.rows:
            row = CloudModelRow(cloud_row)
            if row.enabled and row.key in keep:
                row.set_quietly(True)
            self._cloud_rows.Add(row)

    def _cloud_scan_finished(self, catalog):
        self._cloud_catalog = catalog
        self._show_cloud_rows(catalog)
        self._cloud_keep = set()
        projects = [ProjectRow(project) for project in catalog.projects]
        self.cloud_projects_lb.ItemsSource = projects
        self.cloud_message_text.Text = catalog.message or ""
        counts = catalog.counts or {}
        status = tr("Cloud models found: {0}.", "Znalezione modele w chmurze: {0}.") \
            .format(len(catalog.rows))
        if not counts.get("cache_files"):
            status = tr("No cloud models were found in the Revit cache of this computer.",
                        "Nie znaleziono modeli z chmury w pamięci podręcznej Revita tego "
                        "komputera.")
        elif catalog.rows and not any(project.selected for project in catalog.projects):
            status += " " + tr("Tick a project above to enable its models.",
                               "Zaznacz powyżej projekt, aby włączyć jego modele.")
        if counts.get("cache_errors"):
            status += " " + tr("Part of the cache folder could not be read.",
                               "Nie udało się odczytać części folderu pamięci podręcznej.")
        if getattr(self._cloud["memory"], "last_error", None):
            status += " " + tr("The list of cloud model names could not be saved.",
                               "Nie udało się zapisać listy nazw modeli z chmury.")
        self._say("cloud", status)

    def _rescan_cloud(self):
        keep = set(row.key for row in self._ticked_in(self._cloud_rows))
        if self._cloud_gen is not None:
            keep |= self._cloud_keep    # ticks of rows the interrupted scan had not reached
        self._cloud_keep = keep
        for key in [key for key in self._kept_jobs if key.startswith(CLOUD_PREFIX)]:
            del self._kept_jobs[key]
        self._host_only = set()
        self._stop_cloud_scan()
        self._cloud_rows.Clear()
        self.cloud_projects_lb.ItemsSource = []
        self.cloud_message_text.Text = ""
        self._start_cloud_scan()

    def _cache_files(self):
        """The cache files, walked once per scan (project ticks and link lookups need them)."""
        if self._cloud_files is None:
            scan_cache = self._cloud_value("scan_cache", rx_cloud.scan_cache)
            self._cloud_files = list(scan_cache(self._cloud["folders"]["cache"]))
        return self._cloud_files

    @_guarded
    def _on_project_click(self, sender, args):
        row = getattr(args.OriginalSource, "DataContext", None)
        if not isinstance(row, ProjectRow) or self._cloud_catalog is None:
            return
        memory = self._cloud["memory"]
        projects = list(self.cloud_projects_lb.ItemsSource or [])
        shown = set(project.key for project in projects)
        chosen = set(project.key for project in projects if project.Checked)
        memory.set_included((set(memory.included) - shown) | chosen)
        if memory.save():
            self._show_error("")
        else:
            self._show_error(tr("The project selection could not be saved: {0}",
                                "Nie udało się zapisać wyboru projektów: {0}")
                             .format(getattr(memory, "last_error", None) or ""))
        old = self._cloud_catalog
        catalog = rx_cloud.build_catalog(self._cache_files(), memory, self._cloud_now(),
                                         counts=old.counts, message=old.message)
        self._cloud_catalog = catalog
        self._show_cloud_rows(catalog)
        self._refresh_state()

    def _refresh_cloud_state(self):
        rows = list(self._cloud_rows)
        ticked = self._ticked_in(rows)
        counts = self._cloud_catalog.counts if self._cloud_catalog is not None else {}
        self.count_text.Text = tr(
            "Selected: {0} / {1}{2}Shown: {3}{2}Models without a name: {4}",
            "Zaznaczone: {0} / {1}{2}Widoczne: {3}{2}Modele bez nazwy: {4}") \
            .format(len(ticked), len(rows), SEPARATOR, self._cloud_view.Count,
                    (counts or {}).get("unnamed", 0))
        self.count_text.ToolTip = None
        self.views_btn.IsEnabled = len(ticked) == 1
        self.export_btn.IsEnabled = bool(ticked)
        if not ticked:
            self.summary_text.Text = tr("No model selected.", "Nie zaznaczono modelu.")
            return
        summary = tr("Models selected: {0}", "Zaznaczone modele: {0}").format(len(ticked))
        stale = len([row for row in ticked if row.state == "stale"])
        if stale:
            summary += SEPARATOR + tr("older cache copies: {0}",
                                      "starsze kopie z pamięci podręcznej: {0}").format(stale)
        if self._shared_scope():
            summary += SEPARATOR + tr("shared index.json", "wspólny index.json")
        else:
            summary += SEPARATOR + tr("Extractor default scope", "domyślny zakres Extractora")
        self.summary_text.Text = summary

    @staticmethod
    def _notes_text(notes):
        """The staging notes of a hand-over for the error line: the first few, then a count."""
        unique = []
        for note in notes or ():
            if note not in unique:
                unique.append(note)
        if not unique:
            return ""
        text_ = " ".join(unique[:MAX_NOTES_SHOWN])
        if len(unique) > MAX_NOTES_SHOWN:
            text_ += " " + tr("(and {0} more notes)", "(i jeszcze uwag: {0})").format(
                len(unique) - MAX_NOTES_SHOWN)
        return text_

    def _store_links(self, row, links):
        """A link read succeeded (Export or Choose views): store it, and an earlier failed read
        no longer sends this row out without its links."""
        self._host_only.discard(row.job_key)
        memory = self._cloud["memory"]
        memory.store_links(link_key(row.cloud), row.cloud.cache_mtime, links)
        memory.save()           # a failed save only costs the next read; it never raises

    @staticmethod
    def _links_of(snapshot):
        links = snapshot.get("links") if isinstance(snapshot, dict) else None
        return links if isinstance(links, list) else []

    def _read_links(self, rows, link_lists):
        """Background-read the link list of each cloud row (one open each) into `link_lists`
        and the memory. False when it stopped: the window was closed, or an open failed (the
        error line offers the host alone and the row is marked for it)."""
        resume = self._scanning()
        for row in rows:
            snapshot, failure = self._read_in_background(
                row.Name, lambda row=row: self._read(row.cache_path, None, links=True))
            if failure is not None:
                if self._read_failed_links(row, failure):
                    return False
                self._resume(resume)
                return False
            links = self._links_of(snapshot)
            self._store_links(row, links)
            link_lists[row.key] = links
        self._resume(resume)
        return True

    def _read_failed_links(self, row, failure):
        """True when the window was closed (Revit could not close the model). Otherwise the host
        is marked for export without its links and the error line says how to do that."""
        if getattr(failure, "kind", None) == "close_failed":
            self.fatal_error = _error_text(failure)
            self.Close()
            return True
        self._host_only.add(row.job_key)
        self._show_error(tr("The links of {0} could not be read ({1}). Click Export again to "
                            "export it without its links.",
                            "Nie udało się odczytać linków modelu {0} ({1}). Kliknij Eksportuj "
                            "ponownie, aby wyeksportować go bez linków.")
                         .format(row.Name, _error_text(failure)))
        return False

    def _export_cloud(self, models):
        fresh = [row for row in models if row.job_key not in self._kept_jobs]
        planned = {}
        if fresh:
            memory = self._cloud["memory"]
            try:
                shared = self._shared_index_or_none()
            except SetupError as error:
                self._show_error(_error_text(error))
                return
            link_lists, need = {}, []
            for row in fresh:
                if row.job_key in self._host_only:
                    continue
                stored = memory.links_for(link_key(row.cloud), row.cloud.cache_mtime)
                if stored is None:
                    need.append(row)
                else:
                    link_lists[row.key] = stored
            self._show_error("")
            if need and not self._read_links(need, link_lists):
                return
            try:
                jobs = plan_cloud_jobs([row.cloud for row in fresh], self._caps,
                                       self._cache_files(), memory, link_lists,
                                       set(row.key for row in fresh if row.job_key in
                                           self._host_only), shared)
            except (SetupError, StageError) as error:
                self._show_error(_error_text(error))
                return
            planned = dict(zip([row.job_key for row in fresh], jobs))
        jobs = [self._kept_jobs.get(row.job_key) or planned[row.job_key] for row in models]
        notes = []
        for job in jobs:
            notes.extend((job.get("stage") or {}).get("notes") or [])
        self._queue(jobs, models, notes=notes)

    def _views_cloud(self, row):
        """Choose views… for one cloud row: one background read (links included, stored), the
        slice 1 picker on a copy of the snapshot that shows the real name, then a cloud job."""
        resume = self._scanning()
        snapshot, failure = self._read_in_background(
            row.Name, lambda: self._read(row.cache_path, None, links=True))
        if failure is not None:
            if not self._read_failed(failure):
                self._resume(resume)
            return
        links = self._links_of(snapshot)
        self._store_links(row, links)
        shown = dict(snapshot)
        shown["title"] = row.Name
        shown["path"] = "%s / %s" % (row.Project, row.Name)   # never the GUID-named cache file
        try:
            view = ViewWindow(shown, self._caps, note=row.Note, save_dir=self._save_dir())
            self._own(view)
            view.show_dialog()
        except Exception as error:
            self._show_error(tr("The view window failed: {0}", "Błąd okna widoków: {0}")
                             .format(_error_text(error)))
            self._resume(resume)
            return
        picked = getattr(view, "job", None)
        if picked:
            try:
                job = plan_cloud_job(row.cloud, picked["index"], self._cache_files(),
                                     self._cloud["memory"], links)
            except (SetupError, StageError) as error:
                self._show_error(_error_text(error))
                self._resume(resume)
                return
            self._queue([job], [row], retain=True, notes=job["stage"]["notes"])
        self._resume(resume)
        self._refresh_state()


# =============================================================================== view window

class ViewRow(forms.Reactive):
    """One view or sheet. ElementId is shown; Key is what the index gets (caps.view_key)."""

    def __init__(self, record, view_key):
        self.Name = record["name"]
        self.Kind = record["kind"]
        self.ElementId = record["id"]
        if view_key == "view_unique_ids":
            self.Key = record.get("uid") or ""    # empty: rx_index refuses, never widens
        else:
            self.Key = record["id"]
        self.SearchText = record["search"]
        self._checked = False

    @forms.reactive
    def Checked(self):
        return self._checked

    @Checked.setter
    def Checked(self, value):
        self._checked = bool(value)

    def set_quietly(self, value):
        """No PropertyChanged: the caller refreshes the list once afterwards."""
        self._checked = bool(value)


class ViewWindow(forms.WPFWindow):
    """Slice 1's view picker for one model read in the background. Export sets `job` to one
    {"model_path", "index"} and closes; Back closes with `job` None."""

    def __init__(self, snapshot, caps, note="", save_dir=""):
        self._updating = True
        self._caps = caps
        self._defaults = defaults(caps)
        self._save_dir = save_dir
        self._ifc_items = []
        self.snapshot = snapshot
        self.last_saved_path = None
        self.job = None
        # Esc: the search bar clears a filled box first, then Back (IsCancel) closes.
        forms.WPFWindow.__init__(self, VIEWS_XAML, handle_esc=False)
        _apply_theme(self)
        path = snapshot.get("path") or ""
        self.model_title.Text = snapshot.get("title") or ""
        self.model_path.Text = path
        self.model_path.ToolTip = path or None
        self.model_note.Text = tr(
            "The views were read from the file in the background (worksets closed); the file "
            "was not changed.",
            "Widoki odczytano z pliku w tle (zamknięte zestawy robocze); plik nie został "
            "zmieniony.") + (" " + note if note else "")

        self._search = {
            "2d": SearchBar(self.search2d_host, self._on_filter_changed, regex=True,
                            tooltip=tr("Search by name, sheet number, type or ID",
                                       "Szukaj po nazwie, numerze arkusza, typie lub ID")),
            "3d": SearchBar(self.search3d_host, self._on_filter_changed, regex=True,
                            tooltip=tr("Search by name or ID", "Szukaj po nazwie lub ID")),
        }
        self._rows, self._views, self._shown = {}, {}, {}
        for dimension in DIMENSIONS:
            rows = ObservableCollection[object]()
            for record in snapshot.get("views_" + dimension) or []:
                rows.Add(ViewRow(record, caps.view_key))
            self._rows[dimension] = rows
        # Before any Filter is assigned: the view may run the predicate at once.
        self._filters = ColumnFilterController(
            lambda: self._rows["2d"], self._on_filter_changed,
            base_visible=lambda row: self._search["2d"].matches(row.SearchText))
        self._filters.register(self.views2d_lv.View.Columns[TYPE_COLUMN],
                               self.Resources["col_type"], "Kind")
        self._search["2d"].bind_filters(self._filters)
        predicates = {"2d": self._visible_2d, "3d": self._visible_3d}
        for dimension in DIMENSIONS:
            view = CollectionViewSource.GetDefaultView(self._rows[dimension])
            view.Filter = Predicate[object](predicates[dimension])
            self._views[dimension] = view
            list_view = self._list(dimension)
            list_view.ItemsSource = view
            # One handler per list: a row checkbox Click bubbles up here.
            list_view.AddHandler(ButtonBase.ClickEvent, RoutedEventHandler(self._on_check_click))
            # SelectionMode="Extended" gives Ctrl/Shift-click and Ctrl+A highlighting over the
            # shown rows; Space selects the highlighted rows.
            list_view.PreviewKeyDown += self._on_list_key_down

        self._setup_formats(snapshot)
        for name in BOOL_CONTROLS.values():
            control = getattr(self, name)
            control.Checked += self._on_settings_changed
            control.Unchecked += self._on_settings_changed
        for name in ("default2d_rb", "selected2d_rb", "default3d_rb", "selected3d_rb"):
            getattr(self, name).Checked += self._on_settings_changed
        self.ifc_setup_cb.SelectionChanged += self._on_settings_changed
        for name in ("all2d_btn", "none2d_btn", "all3d_btn", "none3d_btn"):
            getattr(self, name).Click += self._on_bulk_check
        self.tabs.SelectionChanged += self._on_tab_changed
        self.reset_btn.Click += self._on_reset
        self.save_btn.Click += self._on_save
        self.back_btn.Click += self._on_back
        self.export_btn.Click += self._on_export
        self._on_reset(None, None)

    def _show_error(self, message):
        self.error_text.Text = message or ""

    # -- formats and metadata (only what the capabilities row has)

    def _setup_formats(self, snapshot):
        formats = tuple(self._caps.formats)
        self.formats_panel.Visibility = _shown(formats)
        self.formats_note_text.Visibility = _shown(not formats)
        self.dwg_cb.Visibility = _shown("dwg" in formats)
        self.ifc_cb.Visibility = _shown("ifc" in formats)
        self.database_panel.Visibility = _shown(self._caps.extended_properties)
        self.topology_cb.Visibility = _shown(self._caps.topology_metadata)
        if "ifc" in formats:
            first = ComboBoxItem()
            first.Content = tr("None (the Extractor's default)", "Brak (domyślne Extractora)")
            first.Tag = ""
            first.IsEnabled = True
            self._ifc_items.append(first)
            for setup in snapshot.get("ifc_setups") or []:
                name = text(setup.get("name") or "")
                if not name:
                    continue
                ready = setup.get("ready") is True
                item = ComboBoxItem()
                item.Tag = name
                item.IsEnabled = ready
                if ready:
                    item.Content = name
                else:
                    item.Content = tr("{0} (cannot be used: older setup format)",
                                      "{0} (nie do użycia: starszy format setupu)").format(name)
                self._ifc_items.append(item)
            self.ifc_setup_cb.ItemsSource = list(self._ifc_items)
            self.ifc_setup_cb.SelectedItem = first
        error = snapshot.get("ifc_error") or ""
        self.ifc_error_text.Text = error
        self.ifc_error_text.Visibility = _shown(error)

    def _ifc_setup_name(self):
        item = self.ifc_setup_cb.SelectedItem
        if item is None or not item.IsEnabled or not item.Tag:
            return ""                       # a setup the Extractor cannot read is never used
        return text(item.Tag)

    # -- rows

    def _list(self, dimension):
        return getattr(self, "views" + dimension + "_lv")

    def _visible_2d(self, row):
        return self._search["2d"].matches(row.SearchText) and self._filters.matches(row)

    def _visible_3d(self, row):
        return self._search["3d"].matches(row.SearchText)

    def _selected(self, dimension):
        # Includes selected rows hidden by the current search/filter.
        return [row.Key for row in self._rows[dimension] if row.Checked]

    def _set_checked(self, list_view, rows, state):
        for row in rows:
            row.set_quietly(state)
        list_view.Items.Refresh()

    @_guarded
    def _on_check_click(self, sender, args):
        row = getattr(args.OriginalSource, "DataContext", None)
        if not isinstance(row, ViewRow):
            return  # e.g. a column header or its filter button
        # The binding has already updated row.Checked. A checkbox on a row that is part of a
        # multi-row highlight applies to the whole highlight.
        targets = tick_targets(sender.SelectedItems, row)
        if len(targets) > 1:
            self._set_checked(sender, targets, row.Checked)
        self._refresh_state()

    @_guarded
    def _on_list_key_down(self, sender, args):
        if args.Key != Key.Space:
            return
        source = args.OriginalSource
        if source is not sender and not isinstance(getattr(source, "DataContext", None), ViewRow):
            return
        highlighted = list(sender.SelectedItems)
        if not highlighted:
            return
        args.Handled = True
        self._set_checked(sender, highlighted,
                          toggled_state([row.Checked for row in highlighted]))
        self._refresh_state()

    @_guarded
    def _on_bulk_check(self, sender, args):
        dimension, action = text(sender.Tag).split(":")
        self._set_checked(self._list(dimension), list(self._views[dimension]), action == "all")
        self._refresh_state()

    def _on_filter_changed(self, *unused):
        if not self._updating:
            self._refresh_lists()
            self._refresh_state()

    def _refresh_lists(self):
        for dimension in DIMENSIONS:
            view = self._views[dimension]
            view.Refresh()
            self._shown[dimension] = view.Count

    # -- settings and state

    def _settings(self):
        settings = dict((key, bool(getattr(self, name).IsChecked))
                        for key, name in BOOL_CONTROLS.items() if key in self._defaults)
        settings["scope_2d"] = "selected" if self.selected2d_rb.IsChecked else "default"
        settings["scope_3d"] = "selected" if self.selected3d_rb.IsChecked else "default"
        if "ifc" in self._caps.formats:
            settings["ifc_setup_name"] = self._ifc_setup_name()
        return settings

    def _payload(self):
        return build_index(self._caps, self._settings(), self._selected("2d"),
                           self._selected("3d"))

    @_guarded
    def _on_settings_changed(self, sender, args):
        if not self._updating:
            self._refresh_state()

    @_guarded
    def _on_tab_changed(self, sender, args):
        if self.preview_tab.IsSelected:
            self._refresh_preview()

    def _refresh_preview(self):
        try:
            self.json_tb.Text = to_json(self._payload())
        except SetupError:
            self.json_tb.Text = ""  # the error line says why

    def _refresh_state(self):
        settings = self._settings()
        self.tab2d.IsEnabled = settings["enable_2d"]
        self.tab3d.IsEnabled = settings["enable_3d"]
        self.choose2d_panel.IsEnabled = settings["enable_2d"] and settings["scope_2d"] == "selected"
        self.choose3d_panel.IsEnabled = settings["enable_3d"] and settings["scope_3d"] == "selected"
        self.advanced3d_panel.IsEnabled = settings["enable_3d"]
        self.f2d_cb.IsEnabled = settings["enable_2d"]
        self.extended_cb.IsEnabled = settings["pdb"]
        self.ifc_setup_cb.IsEnabled = bool(settings.get("ifc"))
        selected = dict((dimension, self._selected(dimension)) for dimension in DIMENSIONS)
        summaries = []
        for dimension in DIMENSIONS:
            count = len(selected[dimension])
            getattr(self, "count" + dimension + "_text").Text = (
                tr("Selected: {0} / {1}    •    Shown in the list: {2}",
                   "Zaznaczone: {0} / {1}    •    Widoczne na liście: {2}")
                .format(count, len(self._rows[dimension]), self._shown[dimension]))
            if not settings["enable_" + dimension]:
                scope = tr("off", "wyłączone")
            elif settings["scope_" + dimension] == "default":
                scope = tr("default scope", "domyślny zakres")
            else:
                scope = tr("selected: {0}", "wybrane: {0}").format(count)
            summaries.append(dimension.upper() + ": " + scope)
        summaries.append(tr("SQLite database: ", "Baza SQLite: ")
                         + (tr("yes", "tak") if settings["pdb"] else tr("no", "nie")))
        formats = [name.upper() for name in self._caps.formats if settings.get(name)]
        if formats:
            summaries.append(tr("Formats: ", "Formaty: ") + ", ".join(formats))
        self.summary_text.Text = "   |   ".join(summaries)
        try:
            # Validation only; the JSON text is built lazily (preview tab, save).
            build_index(self._caps, settings, selected["2d"], selected["3d"])
        except SetupError as error:
            self.error_text.Text = _error_text(error)
            self.status_text.Text = ""
            self.save_btn.IsEnabled = False
            self.export_btn.IsEnabled = False
        else:
            warning = database_warning(self._caps, settings)
            self.error_text.Text = ""
            self.status_text.Text = tr("Ready to export.", "Gotowe do eksportu.") + (
                " " + warning if warning else "")
            self.save_btn.IsEnabled = True
            self.export_btn.IsEnabled = True
        if self.preview_tab.IsSelected:
            self._refresh_preview()

    @_guarded
    def _on_reset(self, sender, args):
        self._updating = True
        try:
            for key, name in BOOL_CONTROLS.items():
                getattr(self, name).IsChecked = bool(self._defaults.get(key, False))
            if self._ifc_items:
                self.ifc_setup_cb.SelectedItem = self._ifc_items[0]
            for dimension in DIMENSIONS:
                getattr(self, "default" + dimension + "_rb").IsChecked = True
                getattr(self, "selected" + dimension + "_rb").IsChecked = False
                self._search[dimension].Text = ""
            self._filters.clear_all()
            for dimension in DIMENSIONS:
                self._set_checked(self._list(dimension), self._rows[dimension], False)
        finally:
            self._updating = False
        self._refresh_lists()
        self._refresh_state()

    # -- footer

    @_guarded
    def _on_back(self, sender, args):
        self.job = None
        self.Close()

    @_guarded
    def _on_export(self, sender, args):
        try:
            index = self._payload()
        except SetupError as error:
            self._show_error(_error_text(error))
            return
        self.job = {"model_path": self.snapshot.get("path") or "", "index": index}
        self.Close()

    @_guarded
    def _on_save(self, sender, args):
        try:
            content = to_json(self._payload())
        except SetupError as error:
            self._show_error(_error_text(error))
            return
        if self.last_saved_path:
            start = os.path.dirname(self.last_saved_path)
        else:
            start = self._save_dir or Environment.GetFolderPath(
                Environment.SpecialFolder.MyDocuments)
        path = forms.save_file(
            file_ext="json",
            files_filter=tr("Extractor configuration (*.json)|*.json",
                            "Konfiguracja Extractora (*.json)|*.json"),
            init_dir=start, default_name="index.json",
            title=tr("Save index.json", "Zapisz index.json"))
        if not path:
            return
        try:
            write_index_atomic(path, content)
        except Exception as error:
            forms.alert(tr("Could not save the file.\n\n{0}",
                           "Nie udało się zapisać pliku.\n\n{0}").format(_error_text(error)),
                        title=tr("Export", "Eksport"))
            return
        self.last_saved_path = path
        warning = database_warning(self._caps, self._settings())
        self.status_text.Text = tr("Saved: ", "Zapisano: ") + path + (
            "\n" + warning if warning else "")
        self.status_text.ToolTip = path
