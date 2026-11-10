# -*- coding: utf-8 -*-
"""Excel-style column filter popups on list headers (ported from MGo Family Manager
column_filter_ui; English/Polish text, Rx theme keys).

Needs only WPF, rx_column_filter_model and rx_search_bar. Theme keys RxAccent,
RxCardBackground and RxBorder come from the host window (rx_theme.xaml).
"""
from __future__ import unicode_literals

from collections import OrderedDict

import System
from System.Windows import FontWeights, Thickness, VerticalAlignment
from System.Windows.Controls import (Border, Button, CheckBox, Control, Orientation,
                                     ScrollBarVisibility, ScrollViewer, Separator, StackPanel,
                                     TextBlock)
from System.Windows.Controls.Primitives import PlacementMode, Popup
from System.Windows.Input import Key
from System.Windows.Media import FontFamily

from rx_i18n import tr
from rx_column_filter_model import (all_values, blank_label, cascading_counts,
                                    reconcile_filters, row_matches_filters, value_sort_key)
from rx_search_bar import SearchBar

FILTER_GLYPH = "▾"
FILTER_ACTIVE_GLYPH = ""
# rebuild_values without a value to keep focused.
_NO_VALUE = object()


class ColumnFilterController(object):
    """Exact-value filters for some columns of one list.

    rows(): the current rows; refresh(): called after every filter change;
    base_visible(row): the host's other rules (search), so popup counts follow them.
    """

    def __init__(self, rows, refresh, base_visible=None, label=None, tooltip=None,
                 active_changed=None, before_open=None):
        self._before_open = before_open
        self._rows = rows
        self._refresh = refresh
        self._base_visible = base_visible or (lambda unused: True)
        self._label = label or self._default_label
        self._tooltip = tooltip or (lambda unused_attribute, unused_value: None)
        self._active_changed = [active_changed] if active_changed else []
        self.Filters = OrderedDict()
        self._headers = {}
        self._popup = None

    @staticmethod
    def _default_label(unused_attribute, value):
        return blank_label() if value in (None, "") else "{0}".format(value)

    def register(self, column, title, attribute):
        self.Filters.setdefault(attribute, None)
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        label = TextBlock()
        label.Text = title
        label.VerticalAlignment = VerticalAlignment.Center
        panel.Children.Add(label)
        button = Button()
        glyph = TextBlock()
        glyph.Text = FILTER_GLYPH
        button.Content = glyph
        button.Padding = Thickness(5, 0, 5, 0)
        button.Margin = Thickness(6, 0, 0, 0)
        button.MinWidth = 0
        button.MinHeight = 0
        button.Click += lambda sender, args: self.open(sender, attribute)
        panel.Children.Add(button)
        column.Header = panel
        self._headers[attribute] = (button, label, title, glyph)
        self._update_header(attribute)

    def matches(self, row):
        return row_matches_filters(row, self.Filters)

    def reconcile(self):
        reconciled = reconcile_filters(list(self._rows()), self.Filters)
        for attribute in self.Filters:
            self.Filters[attribute] = reconciled.get(attribute)
        self._update_headers()
        self._notify_active_changed()

    def clear_all(self):
        for attribute in self.Filters:
            self.Filters[attribute] = None
        self._changed()

    @property
    def IsActive(self):
        return any(value is not None for value in self.Filters.values())

    def _all_values(self, attribute):
        return all_values(list(self._rows()), attribute)

    def _update_header(self, attribute):
        header = self._headers.get(attribute)
        if header is None:
            return
        button, label, title, glyph = header
        selected = self.Filters.get(attribute)
        if selected is None:
            label.ClearValue(TextBlock.FontWeightProperty)
            button.ClearValue(Control.ForegroundProperty)
            glyph.ClearValue(TextBlock.FontFamilyProperty)
            glyph.Text = FILTER_GLYPH
            button.ToolTip = tr("Filter {0}", "Filtruj: {0}").format(title)
        else:
            values = self._all_values(attribute)
            label.FontWeight = FontWeights.SemiBold
            button.SetResourceReference(Control.ForegroundProperty, "RxAccent")
            # The symbol font goes on the glyph only. On the placement button the popup
            # would inherit Segoe MDL2 and draw ordinary labels as boxes.
            glyph.FontFamily = FontFamily("Segoe MDL2 Assets")
            glyph.Text = FILTER_ACTIVE_GLYPH
            button.ToolTip = tr("Filter {0} — {1} of {2} values selected",
                                "Filtruj: {0} — wybrano {1} z {2} wartości").format(
                                    title, len(values.intersection(selected)), len(values))

    def _update_headers(self):
        for attribute in self.Filters:
            self._update_header(attribute)

    def on_active_changed(self, callback):
        """Also call callback(IsActive) on every change; called once now."""
        self._active_changed.append(callback)
        callback(self.IsActive)

    def _notify_active_changed(self):
        for callback in self._active_changed:
            callback(self.IsActive)

    def _changed(self):
        self._update_headers()
        self._refresh()
        self._notify_active_changed()

    def _select_all_clicked(self, unused_sender, unused_args, attribute, update):
        # Use the filter state, not WPF's checked -> indeterminate -> unchecked cycle: from a
        # partial selection one click selects every value; from all selected it clears all.
        selected = self.Filters.get(attribute)
        was_all = selected is None or set(selected) >= self._all_values(attribute)
        self.Filters[attribute] = set() if was_all else None
        self._changed()
        update()

    def _value_clicked(self, sender, unused_args, attribute, value, update):
        selected = self.Filters.get(attribute)
        selected = set(self._all_values(attribute)) if selected is None else set(selected)
        if sender.IsChecked:
            selected.add(value)
        else:
            selected.discard(value)
        self.Filters[attribute] = None if selected >= self._all_values(attribute) else selected
        self._changed()
        update()

    def open(self, button, attribute):
        if self._popup is not None:
            self._popup.IsOpen = False
        if self._before_open is not None:
            self._before_open()
        popup = Popup()
        popup.PlacementTarget = button
        popup.Placement = PlacementMode.Bottom
        popup.StaysOpen = False
        popup.AllowsTransparency = True

        border = Border()
        border.Width = 310
        border.Padding = Thickness(10)
        border.CornerRadius = System.Windows.CornerRadius(5)
        border.SetResourceReference(Border.BackgroundProperty, "RxCardBackground")
        border.SetResourceReference(Border.BorderBrushProperty, "RxBorder")
        border.BorderThickness = Thickness(1)
        panel = StackPanel()
        border.Child = panel

        search = SearchBar(None, lambda unused_sender, unused_args: rebuild_values(),
                           tooltip=tr("Search filter values", "Szukaj wartości filtra"))
        search.Root.Margin = Thickness(0, 0, 0, 8)
        panel.Children.Add(search.Root)

        select_all = CheckBox()
        select_all.Content = tr("Select all", "Zaznacz wszystko")
        select_all.IsThreeState = True
        select_all.Margin = Thickness(2, 0, 0, 6)
        panel.Children.Add(select_all)

        separator = Separator()
        separator.Margin = Thickness(0, 0, 0, 4)
        panel.Children.Add(separator)

        values_panel = StackPanel()
        viewer = ScrollViewer()
        viewer.MaxHeight = 300
        viewer.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        viewer.Content = values_panel
        panel.Children.Add(viewer)

        def update_select_all():
            selected = self.Filters.get(attribute)
            values = self._all_values(attribute)
            count = len(values if selected is None else values.intersection(selected))
            if not values or count == 0:
                select_all.IsChecked = False
            elif count == len(values):
                select_all.IsChecked = True
            else:
                select_all.IsChecked = None

        def rebuild_values(unused_sender=None, unused_args=None, focus=_NO_VALUE):
            # Rebuilt after every click as well, keeping the scroll position and the clicked
            # value's focus.
            offset = viewer.VerticalOffset
            focused = None
            values_panel.Children.Clear()
            query = "{0}".format(search.Text or "").strip().lower()
            counts = cascading_counts(list(self._rows()), attribute, self.Filters,
                                      self._base_visible)
            ordered = sorted(counts.items(), key=lambda item: value_sort_key(
                item[0], self._label(attribute, item[0])))
            selected = self.Filters.get(attribute)
            for value, count in ordered:
                display = self._label(attribute, value)
                if query and query not in display.lower():
                    continue
                checkbox = CheckBox()
                # A TextBlock keeps underscores literal (CheckBox content treats them as
                # access keys).
                value_label = TextBlock()
                value_label.Text = "{0} ({1})".format(display, count)
                value_label.TextWrapping = System.Windows.TextWrapping.Wrap
                checkbox.Content = value_label
                checkbox.Margin = Thickness(2, 2, 2, 2)
                checkbox.IsChecked = selected is None or value in selected
                checkbox.ToolTip = self._tooltip(attribute, value)
                checkbox.Click += (
                    lambda sender, args, item=value: self._value_clicked(
                        sender, args, attribute, item,
                        lambda item=item: rebuild_values(focus=item)))
                values_panel.Children.Add(checkbox)
                if focus is not _NO_VALUE and value == focus:
                    focused = checkbox
            update_select_all()
            viewer.ScrollToVerticalOffset(offset)
            if focused is not None:
                focused.Focus()

        select_all.Click += (lambda sender, args: self._select_all_clicked(
            sender, args, attribute, rebuild_values))

        def popup_key_down(unused_sender, args):
            # Esc clears a filled search first, then closes. PreviewKeyDown runs before the
            # box's own Esc handling.
            if args.Key == Key.Escape:
                if search.Text:
                    search.Text = ""
                else:
                    popup.IsOpen = False
                args.Handled = True

        border.PreviewKeyDown += popup_key_down
        rebuild_values()
        popup.Child = border
        self._popup = popup
        popup.IsOpen = True
        search.Focus()
