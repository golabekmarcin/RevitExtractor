# -*- coding: utf-8 -*-
"""Search bar: [search box + clear button] [Regex] [Clear all filters].

Ported from the MGo Family Manager search bar (lib/search_bar.py + search_bar.xaml);
differences: English/Polish text, no scope combo, and plain search needs every word.
- The clear button shows only while there is text; Esc in a filled box clears it (handled,
  so the window's Close button does not also fire); clearing touches the search text only.
- "Clear all filters" shows only while column filters are active and clears those only.
- An invalid regex gives the box a red border, puts the error in its tooltip and matches
  nothing.

Usage: put <ContentControl x:Name="..._host" Focusable="False"/> where the bar goes, then
    bar = SearchBar(self.search_host, self.search_changed, tooltip="...", regex=True)
changed(sender, args) gets the bar and None.
"""
from __future__ import unicode_literals

import io
import os
import re

from System.Windows import Visibility
from System.Windows.Controls import Control
from System.Windows.Input import Key
from System.Windows.Markup import XamlReader
from System.Windows.Media import Color, SolidColorBrush

from extractor_i18n import tr

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rx_search_bar.xaml")
_TEMPLATE = []
# RxErrorText (rx_theme.xaml).
_ERROR_BRUSH = SolidColorBrush(Color.FromRgb(179, 38, 30))


def _template_text():
    if not _TEMPLATE:
        with io.open(TEMPLATE_PATH, encoding="utf-8") as stream:
            _TEMPLATE.append(stream.read())
    return _TEMPLATE[0]


def regex_error(pattern):
    """The error text of an invalid pattern, else None."""
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as error:
        return "{0}".format(error)
    return None


def text_matches(query, regex, value):
    """Plain: every word of the query appears, any order, any case. Regex: a search, any
    case. An empty query matches everything; an invalid pattern matches nothing."""
    query = "{0}".format(query or "").strip()
    if not query:
        return True
    value = "" if value is None else "{0}".format(value)
    if regex:
        try:
            return re.search(query, value, re.IGNORECASE) is not None
        except re.error:
            return False
    value = value.lower()
    return all(word in value for word in query.lower().split())


class SearchBar(object):
    def __init__(self, host, changed=None, tooltip=None, regex=False, clear_filters=None,
                 text=""):
        self.Root = XamlReader.Parse(_template_text())
        self.TextBox = self.Root.FindName("SearchText")
        self._clear_button = self.Root.FindName("ClearSearch")
        self._regex = self.Root.FindName("SearchRegex")
        self._clear_filters = self.Root.FindName("ClearFilters")
        self._changed = changed
        self._tooltip = tooltip
        self._clear_filters_action = clear_filters
        self._notify = False
        self._clear_button.ToolTip = tr("Clear search (Esc)", "Wyczyść wyszukiwanie (Esc)")
        self._regex.Content = tr("Regex", "Regex")
        self._regex.ToolTip = tr("Search with a regular expression (any case)",
                                 "Szukaj wyrażeniem regularnym (bez rozróżniania wielkości liter)")
        self._clear_filters.Content = tr("Clear all filters", "Wyczyść wszystkie filtry")
        self._clear_filters.ToolTip = tr("Clear every column filter; the search stays",
                                         "Wyczyść filtry wszystkich kolumn; wyszukiwanie zostaje")
        self.TextBox.ToolTip = tooltip
        self.TextBox.Text = text or ""
        if regex:
            self._regex.Visibility = Visibility.Visible
            self._regex.Click += self._raise
        self._clear_filters.Click += self._clear_filters_click
        self.TextBox.TextChanged += self._text_changed
        self.TextBox.KeyDown += self._key_down
        self._clear_button.Click += self._clear_click
        try:
            from rx_search_placeholder import attach_search_placeholder
            attach_search_placeholder(self.TextBox)
        except Exception:
            pass
        self._refresh()
        self._notify = True
        if host is not None:
            host.Content = self.Root

    # -- TextBox-like interface ---------------------------------------------------------

    @property
    def Text(self):
        return self.TextBox.Text or ""

    @Text.setter
    def Text(self, value):
        self.TextBox.Text = value or ""

    @property
    def IsKeyboardFocusWithin(self):
        return bool(self.TextBox.IsKeyboardFocusWithin)

    def Focus(self):
        return self.TextBox.Focus()

    # -- Search state -------------------------------------------------------------------

    @property
    def IsRegex(self):
        return self._regex.Visibility == Visibility.Visible and bool(self._regex.IsChecked)

    @IsRegex.setter
    def IsRegex(self, value):
        self._regex.IsChecked = bool(value)
        self._refresh()

    @property
    def Error(self):
        """The invalid-regex message, else None."""
        query = self.Text.strip()
        if not query or not self.IsRegex:
            return None
        return regex_error(query)

    def matches(self, value):
        return text_matches(self.Text, self.IsRegex, value)

    def show_clear_filters(self, active):
        self._clear_filters.Visibility = (
            Visibility.Visible if active and self._clear_filters_action is not None
            else Visibility.Collapsed)

    def bind_filters(self, controller):
        """"Clear all filters" for a ColumnFilterController."""
        self._clear_filters_action = controller.clear_all
        controller.on_active_changed(self.show_clear_filters)

    # -- Events -------------------------------------------------------------------------

    def _refresh(self):
        self._clear_button.Visibility = Visibility.Visible if self.Text else Visibility.Collapsed
        error = self.Error
        if error:
            self.TextBox.BorderBrush = _ERROR_BRUSH
            self.TextBox.ToolTip = tr("Invalid regular expression: {0}",
                                      "Nieprawidłowe wyrażenie regularne: {0}").format(error)
        else:
            self.TextBox.ClearValue(Control.BorderBrushProperty)
            self.TextBox.ToolTip = self._tooltip

    def _raise(self, *unused):
        self._refresh()
        if self._notify and self._changed is not None:
            self._changed(self, None)

    def _text_changed(self, *unused):
        self._raise()

    def _clear_click(self, *unused):
        self.Text = ""
        self.TextBox.Focus()

    def _key_down(self, unused_sender, args):
        if args.Key == Key.Escape and self.Text:
            self.Text = ""
            args.Handled = True

    def _clear_filters_click(self, *unused):
        if self._clear_filters_action is not None:
            self._clear_filters_action()
