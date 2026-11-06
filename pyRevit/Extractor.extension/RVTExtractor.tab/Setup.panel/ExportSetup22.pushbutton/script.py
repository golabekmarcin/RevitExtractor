# -*- coding: utf-8 -*-
"""Generate a Revit 2022 Extractor index from the active project's views."""
from __future__ import unicode_literals

__title__ = "Eksport\nsetup 2022"
__doc__ = "Wybierz widoki i zapisz index.json dla Autodesk Revit Extractor w Revit 2022 (2D, 3D i SQLite)."

from pyrevit import forms, revit, script
from extractor_model import collect_views
from extractor_ui import ExportSetupWindow


def main():
    doc = revit.doc
    if doc is None or doc.IsFamilyDocument:
        forms.alert("Otwórz projekt RVT, dla którego chcesz przygotować eksport.",
                    title="Eksport setup 2022")
        return
    if doc.Application.VersionNumber != "2022":
        forms.alert("Ten przycisk przygotowuje konfigurację wyłącznie dla Revita 2022.",
                    title="Eksport setup 2022")
        return
    try:
        snapshot = collect_views(doc)
        ExportSetupWindow(snapshot).ShowDialog()
    except Exception as error:
        script.get_logger().exception("Nie udało się otworzyć konfiguratora eksportu.")
        forms.alert("Nie udało się przygotować konfiguracji.\n\n{0}".format(error),
                    title="Eksport setup 2022")


if __name__ == "__main__":
    main()
