# -*- coding: utf-8 -*-
"""All fixed text of the Export button's two windows, in English and Polish. Pure Python.

UI_TEXT keys are referenced from rx_export_models.xaml and rx_export_views.xaml as
{DynamicResource key}; a test keeps the keys of both files and this table equal. Text built at
runtime (counters, summary, messages) uses tr() in rx_export_ui.py. Compatible with pyRevit
IronPython 2.7. Spec: specs/SPEC-export-button.md.
"""
from __future__ import unicode_literals

from rx_i18n import tr

UI_TEXT = {
    # --- shared by both windows
    "close": ("Close", "Zamknij"),
    "check_visible": ("Select all shown", "Zaznacz wszystkie widoczne"),
    "uncheck_visible": ("Unselect all shown", "Odznacz wszystkie widoczne"),
    # "Select" = mark for export (checkbox); "highlight" = row highlighting (Ctrl/Shift/Ctrl+A).
    "selection_hint": ("Ctrl/Shift+click or Ctrl+A highlights rows; Space or a checkbox selects "
                       "or unselects every highlighted row.",
                       "Ctrl/Shift+klik lub Ctrl+A podświetla wiersze; Spacja lub pole wyboru "
                       "zaznacza albo odznacza wszystkie podświetlone."),
    "check_tooltip": ("Select for export (applies to every highlighted row)",
                      "Zaznacz do eksportu (dotyczy wszystkich podświetlonych wierszy)"),

    # --- model window
    "models_title": ("Revit Extractor — export", "Revit Extractor — eksport"),
    "models_header": ("Models to export", "Modele do eksportu"),
    "models_roots": ("Model folders (searched with subfolders)",
                     "Foldery z modelami (przeszukiwane z podfolderami)"),
    "models_add_root": ("Add folder…", "Dodaj folder…"),
    "models_remove_root": ("Remove", "Usuń"),
    "models_remove_root_tip": ("Remove the highlighted folder from the list. No file is deleted.",
                               "Usuń podświetlony folder z listy. Żaden plik nie zostanie usunięty."),
    "models_output": ("Output folder", "Folder wyników"),
    "models_change_output": ("Change…", "Zmień…"),
    "models_output_hint": ("Every export gets its own new folder here.",
                           "Każdy eksport dostaje tu własny, nowy folder."),
    "models_col_name": ("File name", "Nazwa pliku"),
    "models_col_folder": ("Folder", "Katalog"),
    "models_col_version": ("Revit version", "Wersja Revita"),
    "models_col_note": ("Note", "Uwagi"),
    "models_scope": ("What to export", "Co eksportować"),
    "models_scope_default": ("Extractor default scope", "Domyślny zakres Extractora"),
    "models_scope_default_tip": ("Each model is exported with the default index.json of this "
                                 "Revit. No model is opened.",
                                 "Każdy model zostanie wyeksportowany z domyślnym index.json tego "
                                 "Revita. Żaden model nie jest otwierany."),
    "models_scope_shared": ("Shared index.json", "Wspólny index.json"),
    "models_scope_shared_tip": ("Every selected model is exported with the same index.json. An "
                                "index.json that selects views works for one model only.",
                                "Każdy zaznaczony model zostanie wyeksportowany z tym samym "
                                "index.json. Plik index.json ze wskazanymi widokami działa tylko "
                                "dla jednego modelu."),
    "models_shared_choose": ("Choose…", "Wybierz…"),
    "models_rescan": ("Rescan", "Odśwież listę"),
    "models_rescan_tip": ("Read the model folders again", "Ponownie przeszukaj foldery z modelami"),
    "models_views": ("Choose views…", "Wybierz widoki…"),
    "models_views_tip": ("Read the one selected model in the background (worksets closed, "
                         "nothing is saved) and pick its views.",
                         "Odczytaj jeden zaznaczony model w tle (zamknięte zestawy robocze, nic "
                         "nie jest zapisywane) i wybierz jego widoki."),
    "models_export": ("Export", "Eksportuj"),
    "models_export_tip": ("Queue one export per selected model. Revit stays free while they run.",
                          "Dodaj do kolejki jeden eksport na każdy zaznaczony model. Revit "
                          "pozostaje dostępny w trakcie."),

    # --- view window (slice 1 layout)
    "window_title": ("Revit Extractor — views to export", "Revit Extractor — widoki do eksportu"),
    "header": ("Views to export", "Widoki do eksportu"),
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
    "hint_3d": ("Selected views stay selected while you search and filter. The list contains "
                "the chosen model's views.",
                "Zaznaczenia są zachowywane podczas wyszukiwania i filtrowania. Lista obejmuje "
                "widoki wybranego modelu."),
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
    "topology": ("Topology metadata (untested)", "Metadane topologii (nietestowane)"),
    "section_database": ("Database", "Baza danych"),
    "extended_properties": ("Extended properties in the database (untested)",
                            "Rozszerzone właściwości w bazie danych (nietestowane)"),
    "section_2d": ("2D drawings", "Rysunki 2D"),
    "f2d": ("Process 2D in F2D mode", "Przetwarzanie 2D w trybie F2D"),
    "section_formats": ("Additional formats", "Dodatkowe formaty"),
    "formats_note": ("This Extractor profile supports 2D, 3D and SQLite. Export IFC and DWG files "
                     "with the Export command in Revit.",
                     "Ten profil Extractora obsługuje 2D, 3D i SQLite. Pliki IFC i DWG wyeksportuj "
                     "poleceniem Eksportuj w Revicie."),
    "formats_untested": ("DWG, IFC and the IFC setups have not been tested with this button yet.",
                         "DWG, IFC i setupy IFC nie były jeszcze testowane z tym przyciskiem."),
    "format_dwg": ("DWG files", "Pliki DWG"),
    "format_ifc": ("IFC file", "Plik IFC"),
    "ifc_setup": ("IFC setup saved in the model:", "Setup IFC zapisany w modelu:"),
    "ifc_setup_tip": ("Only setups that the Extractor can read can be chosen.",
                      "Można wybrać tylko setupy, które Extractor potrafi odczytać."),
    "preview_tab": ("index.json preview", "Podgląd index.json"),
    "preview_hint": ("Export uses this configuration; Save index.json… writes it to a file.",
                     "Eksport użyje tej konfiguracji; Zapisz index.json… zapisze ją do pliku."),
    "back": ("Back", "Wstecz"),
    "back_tip": ("Back to the model list. Nothing is exported.",
                 "Powrót do listy modeli. Nic nie zostanie wyeksportowane."),
    "save": ("Save index.json…", "Zapisz index.json…"),
    "save_tip": ("Save this configuration as a file, e.g. to use it as a shared index.json.",
                 "Zapisz tę konfigurację do pliku, np. jako wspólny index.json."),
    "views_export": ("Export", "Eksportuj"),
}


def resources():
    """UI_TEXT in the current language, ready for Window.Resources."""
    return dict((key, tr(english, polish)) for key, (english, polish) in UI_TEXT.items())
