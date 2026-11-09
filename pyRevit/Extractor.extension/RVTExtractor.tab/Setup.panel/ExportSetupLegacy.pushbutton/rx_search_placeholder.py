# -*- coding: utf-8 -*-
"""Italic grey "Search..." hint for an empty, unfocused search box.

Ported from the MGo extension (MGo_Custom.wpf_search_placeholder.attach_search_placeholder)
so this bundle has no outside dependency; text in English and Polish.

The hint is painted as the TextBox background (a VisualBrush sized to the box), so no
template or layout change is needed and the TextBox keeps its own style.
"""
from __future__ import unicode_literals

from System.Windows import (DependencyProperty, FontStyles, FrameworkElement,
                            HorizontalAlignment, Thickness, VerticalAlignment)
from System.Windows.Controls import Border, Control, TextBlock
from System.Windows.Data import Binding
from System.Windows.Media import (AlignmentX, AlignmentY, Brushes, Color, SolidColorBrush,
                                  Stretch, VisualBrush)

from extractor_i18n import tr

_MARKER = "RxSearchPlaceholder"
_HINT_BRUSH = SolidColorBrush(Color.FromRgb(142, 142, 147))


def _bind_size(target, source):
    for prop, path in ((FrameworkElement.WidthProperty, "ActualWidth"),
                       (FrameworkElement.HeightProperty, "ActualHeight")):
        binding = Binding(path)
        binding.Source = source
        target.SetBinding(prop, binding)


def attach_search_placeholder(text_box, text=None):
    """Show text in italic grey while text_box is empty and unfocused."""
    if text_box is None:
        return
    try:
        if text_box.Resources.Contains(_MARKER):
            return
        text_box.Resources[_MARKER] = True
    except Exception:
        return
    # Restore exactly what the box had: an explicit (local) Background, or the style's
    # value by clearing ours. The theme may be merged after this call, so the style value
    # is read when the hint is shown.
    local = text_box.ReadLocalValue(Control.BackgroundProperty)
    has_local = local is not DependencyProperty.UnsetValue
    label = TextBlock()
    label.Text = text or tr("Search...", "Szukaj...")
    label.FontStyle = FontStyles.Italic
    label.Foreground = _HINT_BRUSH
    label.FontFamily = text_box.FontFamily
    label.FontSize = text_box.FontSize
    label.VerticalAlignment = VerticalAlignment.Center
    label.HorizontalAlignment = HorizontalAlignment.Left
    try:
        left = text_box.Padding.Left + text_box.BorderThickness.Left + 2
    except Exception:
        left = 4
    label.Margin = Thickness(left, 0, 0, 0)
    surface = Border()
    surface.Child = label
    _bind_size(surface, text_box)
    brush = VisualBrush(surface)
    # Stretch.None is not valid Python syntax ("None" is a keyword).
    brush.Stretch = getattr(Stretch, "None")
    brush.AlignmentX = AlignmentX.Left
    brush.AlignmentY = AlignmentY.Top
    showing = [False]

    def restore():
        if has_local:
            text_box.SetValue(Control.BackgroundProperty, local)
        else:
            text_box.ClearValue(Control.BackgroundProperty)

    def update(*unused):
        show = not (text_box.Text or "") and not text_box.IsKeyboardFocused
        if show == showing[0]:
            return
        restore()
        if show:
            current = text_box.Background
            surface.Background = current if current is not None else Brushes.White
            text_box.Background = brush
        showing[0] = show

    text_box.TextChanged += update
    text_box.GotKeyboardFocus += update
    text_box.LostKeyboardFocus += update
    update()
