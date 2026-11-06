# -*- coding: utf-8 -*-
"""Read-only Revit 2022 WPF editor; only the selected index file is written."""
from __future__ import unicode_literals

import os
import uuid

from System import Environment
from System.IO import File
from System.Text import UTF8Encoding
from pyrevit import forms

from extractor_config import DEFAULTS, SetupError, build_index, filter_records, to_json

try:
    text = unicode
except NameError:
    text = str


BOOL_CONTROLS = {
    "enable_2d": "enable2d_cb", "enable_3d": "enable3d_cb", "pdb": "pdb_cb",
    "aec_model_data": "aec_cb", "design_description": "description_cb",
    "generate_master_views": "master_cb", "f2d": "f2d_cb",
}


class ViewRow(forms.TemplateListItem):
    @property
    def name(self):
        return self.item["name"]

    @property
    def kind(self):
        return self.item["kind"]

    @property
    def element_id(self):
        return self.item["id"]


def default_save_directory():
    # When run from this checkout, offer the index used by extractorScript_v1.ps1.
    candidate = os.path.dirname(os.path.abspath(__file__))
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
        self._rows = {
            "2d": [ViewRow(row) for row in snapshot["views_2d"]],
            "3d": [ViewRow(row) for row in snapshot["views_3d"]],
        }
        self._visible = {"2d": [], "3d": []}
        forms.WPFWindow.__init__(self, os.path.join(os.path.dirname(__file__), "ui.xaml"))
        self.model_title.Text = snapshot["title"]
        self.model_path.Text = snapshot["path"] or "Model nie ma jeszcze zapisanej ścieżki."
        self.model_path.ToolTip = snapshot["path"]
        self.model_note.Text = (
            "Widoki pochodzą z aktywnego modelu. Extractor odczyta zapisaną wersję RVT."
            + (" Model ma niezapisane zmiany." if snapshot["modified"] else ""))

        kinds = sorted(set(row.item["kind"] for row in self._rows["2d"]))
        self.kind2d_cb.ItemsSource = ["Wszystkie typy"] + kinds
        self.kind2d_cb.SelectedIndex = 0
        for row in self._rows["2d"] + self._rows["3d"]:
            row.PropertyChanged += self._on_row_changed
        for name in BOOL_CONTROLS.values():
            control = getattr(self, name)
            control.Checked += self._on_settings_changed
            control.Unchecked += self._on_settings_changed
        for name in ("default2d_rb", "selected2d_rb", "default3d_rb", "selected3d_rb"):
            getattr(self, name).Checked += self._on_settings_changed
        self.search2d_tb.TextChanged += self._on_filter_changed
        self.search3d_tb.TextChanged += self._on_filter_changed
        self.kind2d_cb.SelectionChanged += self._on_filter_changed
        for name in ("all2d_btn", "none2d_btn", "all3d_btn", "none3d_btn"):
            getattr(self, name).Click += self._on_bulk_check
        self.reset_btn.Click += self._on_reset
        self.save_btn.Click += self._on_save
        self.close_btn.Click += self._on_close
        self._on_reset(None, None)

    def _settings(self):
        settings = dict((key, bool(getattr(self, name).IsChecked))
                        for key, name in BOOL_CONTROLS.items())
        settings["scope_2d"] = "selected" if self.selected2d_rb.IsChecked else "default"
        settings["scope_3d"] = "selected" if self.selected3d_rb.IsChecked else "default"
        return settings

    def _selected(self, dimension):
        # Includes checked items hidden by the current search/filter.
        return [row.item["id"] for row in self._rows[dimension] if row.checked]

    def _payload(self):
        return build_index(self._settings(), self._selected("2d"), self._selected("3d"))

    def _on_settings_changed(self, sender, args):
        if not self._updating:
            self._refresh_state()

    def _on_row_changed(self, sender, args):
        if not self._updating:
            self._refresh_state()

    def _on_filter_changed(self, sender, args):
        if not self._updating:
            self._refresh_lists()
            self._refresh_state()

    def _refresh_lists(self):
        kind = self.kind2d_cb.SelectedItem if self.kind2d_cb.SelectedIndex > 0 else None
        for dimension, query in (("2d", self.search2d_tb.Text), ("3d", self.search3d_tb.Text)):
            matches = filter_records([row.item for row in self._rows[dimension]],
                                     query, kind if dimension == "2d" else None)
            uids = set(row["uid"] for row in matches)
            visible = [row for row in self._rows[dimension] if row.item["uid"] in uids]
            self._visible[dimension] = visible
            getattr(self, "views" + dimension + "_lv").ItemsSource = visible

    def _refresh_state(self):
        settings = self._settings()
        self.tab2d.IsEnabled = settings["enable_2d"]
        self.tab3d.IsEnabled = settings["enable_3d"]
        self.choose2d_panel.IsEnabled = settings["enable_2d"] and settings["scope_2d"] == "selected"
        self.choose3d_panel.IsEnabled = settings["enable_3d"] and settings["scope_3d"] == "selected"
        self.advanced3d_panel.IsEnabled = settings["enable_3d"]
        self.f2d_cb.IsEnabled = settings["enable_2d"]
        summaries = []
        for dimension in ("2d", "3d"):
            selected = len(self._selected(dimension))
            total = len(self._rows[dimension])
            visible = len(self._visible[dimension])
            getattr(self, "count" + dimension + "_text").Text = (
                "Zaznaczone: {0} / {1}    •    Widoczne na liście: {2}"
                .format(selected, total, visible))
            scope = ("wyłączone" if not settings["enable_" + dimension]
                     else "domyślny zakres" if settings["scope_" + dimension] == "default"
                     else "wybrane: {0}".format(selected))
            summaries.append(dimension.upper() + ": " + scope)
        summaries.append("Baza SQLite: " + ("tak" if settings["pdb"] else "nie"))
        self.summary_text.Text = "   |   ".join(summaries)
        try:
            self.json_tb.Text = to_json(self._payload())
            self.status_text.Text = "Gotowe do zapisania konfiguracji."
            self.save_btn.IsEnabled = True
        except SetupError as error:
            self.json_tb.Text = ""
            self.status_text.Text = text(error)
            self.save_btn.IsEnabled = False

    def _on_bulk_check(self, sender, args):
        dimension, action = str(sender.Tag).split(":")
        self._updating = True
        try:
            for row in self._visible[dimension]:
                row.checked = action == "all"
        finally:
            self._updating = False
        self._refresh_state()

    def _on_reset(self, sender, args):
        self._updating = True
        try:
            for key, name in BOOL_CONTROLS.items():
                getattr(self, name).IsChecked = DEFAULTS[key]
            self.default2d_rb.IsChecked = True
            self.default3d_rb.IsChecked = True
            self.search2d_tb.Text = ""
            self.search3d_tb.Text = ""
            self.kind2d_cb.SelectedIndex = 0
            for row in self._rows["2d"] + self._rows["3d"]:
                row.checked = False
        finally:
            self._updating = False
        self._refresh_lists()
        self._refresh_state()

    def _on_save(self, sender, args):
        try:
            content = to_json(self._payload())
        except SetupError as error:
            self.status_text.Text = text(error)
            return
        path = forms.save_file(
            file_ext="json", files_filter="Konfiguracja Extractora (*.json)|*.json",
            init_dir=os.path.dirname(self.last_saved_path) if self.last_saved_path else default_save_directory(),
            default_name="index.json", title="Zapisz konfigurację eksportu")
        if not path:
            return
        try:
            write_index_atomic(path, content)
        except Exception as error:
            forms.alert("Nie udało się zapisać pliku.\n\n{0}".format(error),
                        title="Eksport setup 2022")
            return
        self.last_saved_path = path
        self.status_text.Text = "Zapisano: " + path
        self.status_text.ToolTip = path

    def _on_close(self, sender, args):
        self.Close()
