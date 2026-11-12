# -*- coding: utf-8 -*-
"""WPF and pyRevit fakes for the window tests (CPython, no WPF).

Moved unchanged from test_window_legacy.py (status-window, plan Task 5), so they outlive the
old buttons. Search bar parts, the column-filter popup's Fake elements, pyRevit's shared-event
Reactive, ListView pieces and module stubs.
"""
import types


def stub_module(name, **values):
    module = types.ModuleType(name)
    for key, value in values.items():
        setattr(module, key, value)
    return module


def polish():
    """pyRevit set to Polish (same resolver shape as test_config_legacy.fake_pyrevit_locale)."""
    def get_locale_string(string_dict):
        for code in ("pl", "polish", "en_us", "english"):
            if code in string_dict:
                return string_dict[code]
        return None
    applocales = types.SimpleNamespace(get_locale_string=get_locale_string)
    coreutils = types.SimpleNamespace(applocales=applocales)
    return {"pyrevit": types.SimpleNamespace(coreutils=coreutils),
            "pyrevit.coreutils": coreutils, "pyrevit.coreutils.applocales": applocales}


class Event(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, *args):
        for handler in list(self.handlers):
            handler(*args)


class Part(object):
    def __init__(self):
        self.Visibility = "Collapsed"
        self.ToolTip = None
        self.Content = None
        self.Click = Event()


class Box(Part):
    def __init__(self):
        Part.__init__(self)
        self.TextChanged = Event()
        self.KeyDown = Event()
        self.BorderBrush = None
        self.IsKeyboardFocusWithin = False
        self.focused = False
        self._text = ""

    @property
    def Text(self):
        return self._text

    @Text.setter
    def Text(self, value):
        self._text = value
        self.TextChanged.fire(self, None)

    def ClearValue(self, prop):
        self.BorderBrush = None

    def Focus(self):
        self.focused = True
        return True


class Check(Part):
    IsChecked = False


class BarRoot(object):
    def __init__(self):
        self.parts = {"SearchText": Box(), "ClearSearch": Part(), "SearchRegex": Check(),
                      "ClearFilters": Part()}
        self.Margin = None

    def FindName(self, name):
        return self.parts[name]


SEARCH_BAR_STUBS = {
    "System": stub_module("System"),
    "System.Windows": stub_module("System.Windows", Visibility=types.SimpleNamespace(
        Visible="Visible", Collapsed="Collapsed")),
    "System.Windows.Input": stub_module("System.Windows.Input", Key=types.SimpleNamespace(
        Escape="Escape", A="A")),
    "System.Windows.Markup": stub_module("System.Windows.Markup", XamlReader=types.SimpleNamespace(
        Parse=lambda text: BarRoot())),
    "System.Windows.Media": stub_module(
        "System.Windows.Media", Color=types.SimpleNamespace(FromRgb=lambda *rgb: rgb),
        SolidColorBrush=lambda color: ("brush", color)),
    "System.Windows.Controls": stub_module(
        "System.Windows.Controls",
        Control=types.SimpleNamespace(BorderBrushProperty="BorderBrush")),
    # The placeholder needs real WPF; the bar must survive it failing.
    "rx_search_placeholder": stub_module("rx_search_placeholder"),
}


class Args(object):
    def __init__(self, key=None, source=None):
        self.Key = key
        self.OriginalSource = source
        self.Handled = False


class Changes(object):
    def __init__(self):
        self.calls = []

    def __call__(self, sender, args):
        self.calls.append((sender, args))


class Host(object):
    Content = None


class Children(list):
    def Add(self, item):
        self.append(item)

    def Clear(self):
        del self[:]


POPUP_EVENTS = ("Click", "PreviewKeyDown", "TextChanged", "SelectionChanged")


class Fake(object):
    """Any WPF element or value the popup builds."""

    def __init__(self, *unused_args, **unused_kwargs):
        self.Children = Children()
        self.VerticalOffset = 7
        self.focused = False
        self.scrolled_to = None
        self.resources = {}
        for name in POPUP_EVENTS:
            setattr(self, name, Event())

    def __getattr__(self, name):
        if name[:1].isupper():
            return Fake()
        raise AttributeError(name)

    def __call__(self, *unused_args, **unused_kwargs):
        return Fake()

    def SetResourceReference(self, prop, key):
        self.resources[prop] = key

    def ClearValue(self, *unused):
        pass

    def Focus(self):
        self.focused = True

    def ScrollToVerticalOffset(self, offset):
        self.scrolled_to = offset


class FakePopupSearchBar(object):
    def __init__(self, host, changed, **unused_options):
        self.Root = Fake()
        self.Text = ""

    def Focus(self):
        pass


class AnyModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Fake()


def any_module(name, **values):
    module = AnyModule(name)
    for key, value in values.items():
        setattr(module, key, value)
    return module


POPUP_STUBS = {
    "System": any_module("System", Windows=Fake()),
    "System.Windows": any_module("System.Windows"),
    "System.Windows.Controls": any_module("System.Windows.Controls"),
    "System.Windows.Controls.Primitives": any_module("System.Windows.Controls.Primitives"),
    "System.Windows.Input": any_module("System.Windows.Input",
                                       Key=types.SimpleNamespace(Escape="Escape")),
    "System.Windows.Media": any_module("System.Windows.Media"),
    "rx_search_bar": stub_module("rx_search_bar", SearchBar=FakePopupSearchBar),
}


class SharedEventReactive(object):
    """Like pyRevit forms.Reactive: ONE PropertyChanged list shared by every instance."""
    PropertyChanged = Event()
    raised = []

    def OnPropertyChanged(self, name):
        SharedEventReactive.raised.append((self, name))
        SharedEventReactive.PropertyChanged.fire(self, name)


class reactive(property):
    """Like pyRevit forms.reactive: notify only when the value changes."""

    def __init__(self, getter):
        property.__init__(self, getter)

    def setter(self, setter):
        def newsetter(obj, value):
            if self.fget(obj) != value:
                setter(obj, value)
                obj.OnPropertyChanged(setter.__name__)
        return property(self.fget, newsetter)


class Collection(list):
    def Add(self, item):
        self.append(item)

    def Remove(self, item):
        if item in self:
            self.remove(item)
            return True
        return False


class FakeView(object):
    """ListCollectionView: iterates and counts the rows its Filter accepts."""

    def __init__(self, rows):
        self.rows = rows
        self.Filter = None
        self.refreshes = 0

    def __iter__(self):
        return iter([row for row in self.rows if self.Filter is None or self.Filter(row)])

    @property
    def Count(self):
        return len(list(self))

    def Refresh(self):
        self.refreshes += 1


class Items(object):
    def __init__(self):
        self.refreshes = 0

    def Refresh(self):
        self.refreshes += 1


CONTROL_EVENTS = ("Click", "Checked", "Unchecked", "PreviewKeyDown", "SelectionChanged",
                  "PreviewMouseRightButtonDown", "ContextMenuOpening")


class Control(object):
    def __init__(self, name, tag=None):
        self.Name = name
        self.Tag = tag
        self.IsChecked = False
        self.IsEnabled = True
        self.IsSelected = False
        self.Text = ""
        self.ToolTip = None
        self.ItemsSource = None
        self.SelectedItems = []
        self.Items = Items()
        self.View = types.SimpleNamespace(Columns=[types.SimpleNamespace(Header=None)
                                                   for unused in range(4)])
        self.routed = []
        for event in CONTROL_EVENTS:
            setattr(self, event, Event())

    def AddHandler(self, event, handler):
        self.routed.append((event, handler))
