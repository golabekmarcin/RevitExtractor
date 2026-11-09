# -*- coding: utf-8 -*-
"""Generate a Revit 2022-2025 Extractor index from the active project's views.

Button title and tooltip (English and Polish) live in bundle.yaml.
"""
from __future__ import unicode_literals

from pyrevit import forms, revit, script
from extractor_i18n import tr
from extractor_model import collect_views
from extractor_ui import ExportSetupWindow

FIRST_YEAR, LAST_YEAR = 2022, 2025


def supported_version(version_number):
    try:
        year = int(version_number)
    except (TypeError, ValueError):
        return False
    return FIRST_YEAR <= year <= LAST_YEAR


def main():
    title = tr("Export setup", "Eksport setup")
    doc = revit.doc
    if doc is None or doc.IsFamilyDocument:
        forms.alert(tr("Open the RVT project you want to prepare the export for.",
                       "Otwórz projekt RVT, dla którego chcesz przygotować eksport."),
                    title=title)
        return
    if not supported_version(doc.Application.VersionNumber):
        forms.alert(tr("This copy of the button (folder ExportSetupLegacy.pushbutton) is for "
                       "Revit 2022-2025 only. For Revit 2026 and later use the button from "
                       "folder ExportSetup.pushbutton.",
                       "Ta kopia przycisku (folder ExportSetupLegacy.pushbutton) działa tylko "
                       "w Revicie 2022-2025. Dla Revita 2026 i nowszego użyj przycisku z folderu "
                       "ExportSetup.pushbutton."),
                    title=title)
        return
    try:
        snapshot = collect_views(doc)
        ExportSetupWindow(snapshot).ShowDialog()
    except Exception as error:
        script.get_logger().exception("Could not open the export configurator.")
        forms.alert(tr("Could not prepare the configuration.\n\n{0}",
                       "Nie udało się przygotować konfiguracji.\n\n{0}").format(error),
                    title=title)


if __name__ == "__main__":
    main()
