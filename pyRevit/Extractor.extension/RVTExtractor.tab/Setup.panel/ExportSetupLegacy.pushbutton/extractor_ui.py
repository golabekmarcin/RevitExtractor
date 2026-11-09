# -*- coding: utf-8 -*-
"""Read-only Revit 2022-2025 WPF editor; only the selected index file is written.

Speed with 1000+ views: pyRevit's forms.Reactive declares PropertyChanged once at class
level, so all rows share one handler list. The window therefore never subscribes to row
events. Each list is one CollectionView (search and column filters refresh it). A checkbox
Click bubbles to one ListView handler. Bulk changes set the rows quietly and refresh the list
once, and the JSON preview is built only while its tab is open (and on save).
"""
from __future__ import unicode_literals

import os
import uuid

from System import Environment, Predicate
from System.Collections.ObjectModel import ObservableCollection
from System.IO import File
from System.Text import UTF8Encoding
from System.Windows import RoutedEventHandler
from System.Windows.Controls.Primitives import ButtonBase
from System.Windows.Data import CollectionViewSource
from System.Windows.Input import Key
from pyrevit import forms

from extractor_config import (DEFAULTS, SetupError, build_index, database_warning,
                              tick_targets, to_json, toggled_state)
from extractor_i18n import tr
from extractor_text import resources
from rx_column_filter_ui import ColumnFilterController
from rx_search_bar import SearchBar

try:
    text = unicode
except NameError:
    text = str


HERE = os.path.dirname(os.path.abspath(__file__))
THEME_PATH = os.path.join(HERE, "rx_theme.xaml")
DIMENSIONS = ("2d", "3d")
TYPE_COLUMN = 2  # views2d_lv: check, name, type, ElementId
BOOL_CONTROLS = {
    "enable_2d": "enable2d_cb", "enable_3d": "enable3d_cb", "pdb": "pdb_cb",
    "aec_model_data": "aec_cb", "design_description": "description_cb",
    "generate_master_views": "master_cb", "f2d": "f2d_cb",
}


class ViewRow(forms.Reactive):
    """One view or sheet. Plain attributes for the columns; Checked notifies the checkbox."""

    def __init__(self, record):
        self.Name = record["name"]
        self.Kind = record["kind"]
        self.ElementId = record["id"]
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


def default_save_directory():
    # When run from this checkout, offer the index used by extractorScript_v1.ps1.
    candidate = HERE
    for unused in range(7):
        if os.path.isfile(os.path.join(candidate, "extractorScript_v1.ps1")):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    return Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments)


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


class ExportSetupWindow(forms.WPFWindow):
    def __init__(self, snapshot):
        self._updating = True
        self.snapshot = snapshot
        self.last_saved_path = None
        # Esc: the search bar clears a filled box first, then Close (IsCancel) closes.
        # pyRevit's own Esc hook would close the window over a filled search box.
        forms.WPFWindow.__init__(self, os.path.join(HERE, "ui.xaml"), handle_esc=False)
        # ui.xaml labels are {DynamicResource key}; they update as soon as the keys exist.
        for key, value in resources().items():
            self.Resources[key] = value
        self.merge_resource_dict(THEME_PATH)
        try:
            self.Style = self.FindResource("RxWindow")
        except Exception:
            pass
        self.model_title.Text = snapshot["title"]
        self.model_path.Text = snapshot["path"] or tr("The model has no saved path yet.",
                                                      "Model nie ma jeszcze zapisanej ścieżki.")
        self.model_path.ToolTip = snapshot["path"]
        self.model_note.Text = tr(
            "Views come from the active model. The Extractor reads the saved RVT.",
            "Widoki pochodzą z aktywnego modelu. Extractor odczyta zapisaną wersję RVT.") + (
                tr(" The model has unsaved changes.", " Model ma niezapisane zmiany.")
                if snapshot["modified"] else "")

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
            for record in snapshot["views_" + dimension]:
                rows.Add(ViewRow(record))
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
            # SelectionMode="Extended" (ui.xaml) gives Explorer-like Ctrl/Shift-click and
            # Ctrl+A highlighting over the shown rows; Space selects the highlighted rows.
            list_view.PreviewKeyDown += self._on_list_key_down

        for name in BOOL_CONTROLS.values():
            control = getattr(self, name)
            control.Checked += self._on_settings_changed
            control.Unchecked += self._on_settings_changed
        for name in ("default2d_rb", "selected2d_rb", "default3d_rb", "selected3d_rb"):
            getattr(self, name).Checked += self._on_settings_changed
        for name in ("all2d_btn", "none2d_btn", "all3d_btn", "none3d_btn"):
            getattr(self, name).Click += self._on_bulk_check
        self.tabs.SelectionChanged += self._on_tab_changed
        self.reset_btn.Click += self._on_reset
        self.save_btn.Click += self._on_save
        self.close_btn.Click += self._on_close
        self._on_reset(None, None)

    # -- Rows ---------------------------------------------------------------------------

    def _list(self, dimension):
        return getattr(self, "views" + dimension + "_lv")

    def _visible_2d(self, row):
        return self._search["2d"].matches(row.SearchText) and self._filters.matches(row)

    def _visible_3d(self, row):
        return self._search["3d"].matches(row.SearchText)

    def _selected(self, dimension):
        # Includes selected rows hidden by the current search/filter.
        return [row.ElementId for row in self._rows[dimension] if row.Checked]

    def _set_checked(self, list_view, rows, state):
        for row in rows:
            row.set_quietly(state)
        list_view.Items.Refresh()

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

    def _on_list_key_down(self, sender, args):
        if args.Key != Key.Space:
            return
        # Only on a row or the list itself: a filter popup's search box and value checkboxes
        # route their keys through the column header into this list.
        source = args.OriginalSource
        if source is not sender and not isinstance(getattr(source, "DataContext", None), ViewRow):
            return
        highlighted = list(sender.SelectedItems)
        if not highlighted:
            return
        # Handled first, so a focused checkbox does not also toggle itself.
        args.Handled = True
        self._set_checked(sender, highlighted,
                          toggled_state([row.Checked for row in highlighted]))
        self._refresh_state()

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

    # -- Settings and state -------------------------------------------------------------

    def _settings(self):
        settings = dict((key, bool(getattr(self, name).IsChecked))
                        for key, name in BOOL_CONTROLS.items())
        settings["scope_2d"] = "selected" if self.selected2d_rb.IsChecked else "default"
        settings["scope_3d"] = "selected" if self.selected3d_rb.IsChecked else "default"
        return settings

    def _payload(self):
        return build_index(self._settings(), self._selected("2d"), self._selected("3d"))

    def _on_settings_changed(self, sender, args):
        if not self._updating:
            self._refresh_state()

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
        self.summary_text.Text = "   |   ".join(summaries)
        try:
            # Validation only; the JSON text is built lazily (preview tab, save).
            build_index(settings, selected["2d"], selected["3d"])
        except SetupError as error:
            self.error_text.Text = text(error)
            self.status_text.Text = ""
            self.save_btn.IsEnabled = False
        else:
            warning = database_warning(settings)
            self.error_text.Text = ""
            self.status_text.Text = tr("Ready to save the configuration.",
                                       "Gotowe do zapisania konfiguracji.") + (
                                           " " + warning if warning else "")
            self.save_btn.IsEnabled = True
        if self.preview_tab.IsSelected:
            self._refresh_preview()

    def _on_reset(self, sender, args):
        self._updating = True
        try:
            for key, name in BOOL_CONTROLS.items():
                getattr(self, name).IsChecked = DEFAULTS[key]
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

    # -- Footer -------------------------------------------------------------------------

    def _on_save(self, sender, args):
        try:
            content = to_json(self._payload())
        except SetupError as error:
            self.error_text.Text = text(error)
            return
        path = forms.save_file(
            file_ext="json",
            files_filter=tr("Extractor configuration (*.json)|*.json",
                            "Konfiguracja Extractora (*.json)|*.json"),
            init_dir=os.path.dirname(self.last_saved_path) if self.last_saved_path else default_save_directory(),
            default_name="index.json",
            title=tr("Save export configuration", "Zapisz konfigurację eksportu"))
        if not path:
            return
        try:
            write_index_atomic(path, content)
        except Exception as error:
            forms.alert(tr("Could not save the file.\n\n{0}",
                           "Nie udało się zapisać pliku.\n\n{0}").format(error),
                        title=tr("Export setup", "Eksport setup"))
            return
        self.last_saved_path = path
        # Keep the database note visible after saving: that is when it matters.
        warning = database_warning(self._settings())
        self.status_text.Text = tr("Saved: ", "Zapisano: ") + path + (
            "\n" + warning if warning else "")
        self.status_text.ToolTip = path

    def _on_close(self, sender, args):
        self.Close()
