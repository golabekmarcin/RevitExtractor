# -*- coding: utf-8 -*-
"""The naming profile dialog (specs/SPEC-named-copies.md): two tabs (Views, Sheets), the properties
you can use on the left, the ones in the name on the right, Add/Remove between them, a separator,
a live example and Save / Save as. The logic is in lib/rx_naming_profiles.py; this file only wires
the controls.

NamingWindow(profile, path, catalog, sample) -> after ShowDialog(), `result` is None (cancelled)
or {"profile": dict, "path": str}. `path` is where the profile was saved. Editing Default has no
path: Save is off and only Save as works, so Default itself never changes.
"""
from __future__ import unicode_literals

import copy
import os

from pyrevit import forms

from rx_export_text import resources
from rx_i18n import tr
from rx_naming import NamingError
from rx_naming_profiles import (SEPARATORS, available, preview, profile_path, save_profile,
                                validate)
from rx_search_bar import SearchBar

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "lib")
NAMING_XAML = os.path.join(HERE, "rx_export_naming.xaml")
THEME_PATH = os.path.join(LIB_DIR, "rx_theme.xaml")
TABS = ("views", "sheets")


class PropRow(forms.Reactive):
    """One property in a list: Label to show, Cls (builtin, custom, system) for the style."""

    def __init__(self, part, label, cls):
        self.Part = part
        self.Label = label
        self.Cls = cls


def _is_polish():
    return tr("en", "pl") == "pl"


def _label(part, items):
    for item in items:
        if item[0] == part:
            return item[1], item[2]
    return part[6:] if part.startswith("param:") else part, "custom"


class NamingWindow(forms.WPFWindow):
    def __init__(self, profile, path, catalog, sample):
        # Inside the function: on .NET 8 the type needs rx_dotnet.ensure_assemblies() first.
        from System.Collections.ObjectModel import ObservableCollection
        self._updating = True
        self._path = path                   # None while editing Default
        self._catalog = catalog
        self._sample = dict(sample)
        for names in (catalog.get("views") or []) + (catalog.get("sheets") or []):
            self._sample.setdefault("param:" + names, "(" + names + ")")
        self._lang = "pl" if _is_polish() else "en"
        self._profile = copy.deepcopy(profile)
        self._tab = "views"
        self.result = None
        forms.WPFWindow.__init__(self, NAMING_XAML, handle_esc=False)
        for key, value in resources().items():
            self.Resources[key] = value
        self.merge_resource_dict(THEME_PATH)
        try:
            self.Style = self.FindResource("RxWindow")
        except Exception:
            pass
        self._search = SearchBar(self.search_host, self._refresh_available,
                                 tooltip=tr("Search the properties", "Szukaj właściwości"))
        self.profile_name_tb.Text = "" if path is None else self._profile.get("name", "")
        for separator in SEPARATORS:
            self.separator_cb.Items.Add(separator if separator.strip() else tr("(space)", "(spacja)"))
        self.separator_cb.SelectedIndex = SEPARATORS.index(self._profile["separator"])
        self.split_cb.IsChecked = self._profile.get("split_by_format") is True
        self.save_btn.IsEnabled = path is not None
        self._available = ObservableCollection[object]()
        self._chosen = ObservableCollection[object]()
        self.available_lb.ItemsSource = self._available
        self.chosen_lb.ItemsSource = self._chosen
        self.kind_tabs.SelectionChanged += self._on_tab
        self.separator_cb.SelectionChanged += self._on_change
        self.split_cb.Click += self._on_change
        self.add_btn.Click += self._on_add
        self.remove_btn.Click += self._on_remove
        self.up_btn.Click += self._on_up
        self.down_btn.Click += self._on_down
        self.available_lb.MouseDoubleClick += self._on_add
        self.chosen_lb.MouseDoubleClick += self._on_remove
        self.save_btn.Click += self._on_save
        self.save_as_btn.Click += self._on_save_as
        self._updating = False
        self._refresh_lists()

    # -- state

    def _parts(self):
        return self._profile[self._tab]

    def _separator(self):
        index = self.separator_cb.SelectedIndex
        return SEPARATORS[index] if index >= 0 else self._profile["separator"]

    def _current(self):
        data = copy.deepcopy(self._profile)
        data["name"] = (self.profile_name_tb.Text or "").strip()
        data["separator"] = self._separator()
        data["split_by_format"] = bool(self.split_cb.IsChecked)
        return data

    # -- lists

    def _refresh_lists(self):
        self._refresh_available()
        self._refresh_chosen()

    def _refresh_available(self, *unused):
        if self._updating:
            return
        taken = set(self._parts())
        self._available.Clear()
        for part, label, cls in available(self._tab, self._catalog, self._search.Text, self._lang):
            if part not in taken:
                self._available.Add(PropRow(part, label, cls))

    def _refresh_chosen(self, select=None):
        items = available(self._tab, self._catalog, "", self._lang)
        self._chosen.Clear()
        for part in self._parts():
            label, cls = _label(part, items)
            self._chosen.Add(PropRow(part, label, cls))
        if select is not None and 0 <= select < self._chosen.Count:
            self.chosen_lb.SelectedIndex = select
        self._show_preview()

    def _show_preview(self):
        self.error_text.Text = ""
        data = self._current()
        data["separator"] = self._separator()
        text = preview(data, self._tab, self._sample) if self._parts() else ""
        self.preview_text.Text = text or tr("Add at least one property.",
                                            "Dodaj co najmniej jedną właściwość.")

    # -- events

    def _on_tab(self, sender, args):
        if self._updating or args.OriginalSource is not self.kind_tabs:
            return
        self._tab = "views" if self.kind_tabs.SelectedIndex == 0 else "sheets"
        self._refresh_lists()

    def _on_change(self, *unused):
        if not self._updating:
            self._show_preview()

    def _on_add(self, *unused):
        for row in list(self.available_lb.SelectedItems):
            self._parts().append(row.Part)
        self._refresh_lists()

    def _on_remove(self, *unused):
        gone = set(row.Part for row in self.chosen_lb.SelectedItems)
        self._profile[self._tab] = [p for p in self._parts() if p not in gone]
        self._refresh_lists()

    def _move(self, step):
        index = self.chosen_lb.SelectedIndex
        target = index + step
        parts = self._parts()
        if index < 0 or not 0 <= target < len(parts):
            return
        parts[index], parts[target] = parts[target], parts[index]
        self._refresh_chosen(select=target)

    def _on_up(self, *unused):
        self._move(-1)

    def _on_down(self, *unused):
        self._move(1)

    # -- saving

    def _checked(self, need_name):
        """The profile to save, or None with the reason on the error line."""
        data = self._current()
        try:
            clean = validate(data)
        except NamingError as error:
            self.error_text.Text = "%s" % (error,)
            return None
        if need_name:
            if not clean["name"]:
                self.error_text.Text = tr("Give the profile a name.", "Nadaj profilowi nazwę.")
                return None
            if clean["name"].lower() in ("default", "domyślny"):
                self.error_text.Text = tr("Choose a name other than Default.",
                                          "Wybierz nazwę inną niż Domyślny.")
                return None
        return clean

    def _write(self, path, clean):
        try:
            save_profile(path, clean)
        except (NamingError, EnvironmentError) as error:
            self.error_text.Text = tr("The profile could not be saved: {0}",
                                      "Nie można zapisać profilu: {0}").format(error)
            return
        self.result = {"profile": clean, "path": path}
        self.Close()

    def _on_save(self, *unused):
        clean = self._checked(need_name=True)
        if clean is not None and self._path:
            self._write(self._path, clean)

    def _on_save_as(self, *unused):
        clean = self._checked(need_name=True)
        if clean is None:
            return
        start = os.path.dirname(self._path) if self._path else os.path.expanduser("~")
        chosen = forms.save_file(
            file_ext="json",
            files_filter=tr("Naming profile (*.rx-naming.json)|*.rx-naming.json",
                            "Profil nazewnictwa (*.rx-naming.json)|*.rx-naming.json"),
            init_dir=start, default_name=clean["name"] + ".rx-naming.json",
            title=tr("Save the naming profile", "Zapisz profil nazewnictwa"))
        if chosen:
            self._write(profile_path(chosen), clean)
