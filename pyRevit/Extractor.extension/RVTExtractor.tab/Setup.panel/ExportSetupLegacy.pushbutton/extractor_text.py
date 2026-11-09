# -*- coding: utf-8 -*-
"""All fixed window text in English and Polish. Pure Python, so it is testable outside Revit.

UI_TEXT keys are referenced from ui.xaml as {DynamicResource key}; the window loads them with
resources(). Text that is built at runtime (counters, summary) uses tr() in extractor_ui.py.
"""
from __future__ import unicode_literals

from extractor_i18n import tr

UI_TEXT = {
    "window_title": ("Revit Extractor — export configuration",
                     "Revit Extractor — konfiguracja eksportu"),
    "header": ("Export configuration", "Konfiguracja eksportu"),
    "reset": ("Restore defaults", "Przywróć domyślne"),
    "views_2d": ("2D views and sheets", "Widoki 2D i arkusze"),
    "views_3d": ("3D views", "Widoki 3D"),
    "sqlite": ("Local SQLite database", "Lokalna baza danych SQLite"),
    "scope_default": ("Extractor default scope", "Domyślny zakres Extractora"),
    "scope_selected": ("Selected only", "Tylko zaznaczone"),
    "hint_2d": ("The default scope leaves the choice to the Extractor. Choose “Selected only” "
                "to pick specific drawings.",
                "Domyślny zakres pozostawia wybór Extractorowi. Wybierz „Tylko zaznaczone”, "
                "aby wskazać konkretne rysunki."),
    "hint_3d": ("Selections are kept while you search. The list contains the active model's views.",
                "Zaznaczenia są zachowywane podczas wyszukiwania. Lista obejmuje widoki "
                "aktywnego modelu."),
    "search_2d": ("Search by name, sheet number or ID", "Szukaj po nazwie, numerze arkusza lub ID"),
    "search_3d": ("Search by name or ID", "Szukaj po nazwie lub ID"),
    "view_type": ("View type", "Typ widoku"),
    "check_visible": ("Tick all shown", "Zaznacz wszystkie widoczne"),
    "uncheck_visible": ("Untick all shown", "Odznacz wszystkie widoczne"),
    "selection_hint": ("Ctrl/Shift+click or Ctrl+A selects rows; Space or a checkbox ticks all "
                       "selected rows.",
                       "Ctrl/Shift+klik lub Ctrl+A wybiera wiersze; Spacja lub pole wyboru "
                       "zaznacza wszystkie wybrane."),
    "check_tooltip": ("Tick for export (applies to all selected rows)",
                      "Zaznacz do eksportu (dotyczy wszystkich wybranych wierszy)"),
    "col_name_2d": ("View name / sheet number and name", "Nazwa widoku / numer i nazwa arkusza"),
    "col_name_3d": ("View name", "Nazwa widoku"),
    "col_type": ("Type", "Typ"),
    "advanced": ("Advanced options", "Opcje zaawansowane"),
    "advanced_hint": ("The defaults match the current preset. Other modes need checking on "
                      "the chosen model.",
                      "Domyślne wartości odpowiadają obecnemu presetowi. Dodatkowe tryby wymagają "
                      "sprawdzenia na wybranym modelu."),
    "section_3d": ("3D data and views", "Dane i widoki 3D"),
    "aec": ("AEC data — levels, phases, grids and model information",
            "Dane AEC — poziomy, fazy, osie i informacje o modelu"),
    "description": ("Document description and dependencies between files",
                    "Opis dokumentu i zależności między plikami"),
    "master": ("Generate additional master views", "Generuj dodatkowe widoki master"),
    "section_2d": ("2D drawings", "Rysunki 2D"),
    "f2d": ("Process 2D in F2D mode", "Przetwarzanie 2D w trybie F2D"),
    "section_formats": ("Additional formats", "Dodatkowe formaty"),
    "formats_note": ("This Extractor profile supports 2D, 3D and SQLite. Export IFC and DWG files "
                     "with the Export command in Revit.",
                     "Ten profil Extractora obsługuje 2D, 3D i SQLite. Pliki IFC i DWG wyeksportuj "
                     "poleceniem Eksportuj w Revicie."),
    "preview_tab": ("index.json preview", "Podgląd index.json"),
    "preview_hint": ("The button below saves this configuration.",
                     "Taką konfigurację zapisze przycisk poniżej."),
    "close": ("Close", "Zamknij"),
    "save": ("Save index.json", "Zapisz index.json"),
}

# Keyed by Revit's ViewType name, so filtering and sorting never depend on the language.
VIEW_KINDS = {
    "FloorPlan": ("Floor plans", "Rzuty kondygnacji"),
    "CeilingPlan": ("Ceiling plans", "Rzuty sufitów"),
    "EngineeringPlan": ("Structural plans", "Rzuty konstrukcyjne"),
    "AreaPlan": ("Area plans", "Rzuty powierzchni"),
    "Section": ("Sections", "Przekroje"),
    "Elevation": ("Elevations", "Elewacje"),
    "Detail": ("Detail views", "Detale"),
    "DraftingView": ("Drafting views", "Widoki kreślarskie"),
    "Legend": ("Legends", "Legendy"),
    "DrawingSheet": ("Sheets", "Arkusze"),
    "ThreeD": ("3D views", "Widoki 3D"),
}


def resources():
    """UI_TEXT in the current language, ready for Window.Resources."""
    return dict((key, tr(english, polish)) for key, (english, polish) in UI_TEXT.items())
