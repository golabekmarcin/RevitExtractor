# -*- coding: utf-8 -*-
"""Shift+click: read-only cloud (ACC) model check. Prints facts about the model, its links,
Revit's local cache and journals to the pyRevit output window as plain text.
Opens, copies and writes nothing."""
from __future__ import print_function, unicode_literals

from pyrevit import DB, forms, revit, script
from extractor_i18n import tr
import extractor_cloud_probe as probe


def element_name(element):
    """IronPython often cannot read Name on element types (first report: "ERROR: Name");
    .NET reflection on Element.Name always works."""
    try:
        return element.Name
    except Exception:
        import clr  # IronPython only; imported here so the module loads in CPython tests
        return clr.GetClrType(DB.Element).GetProperty("Name").GetValue(element, None)


def main():
    title = tr("Export setup — cloud check", "Eksport setup — sprawdzenie chmury")
    doc = revit.doc
    if doc is None or doc.IsFamilyDocument:
        forms.alert(tr("Open the RVT project you want to check.",
                       "Otwórz projekt RVT, który chcesz sprawdzić."), title=title)
        return
    try:
        version = doc.Application.VersionNumber
        link_types = list(DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkType))
        data = probe.collect(doc, link_types, DB.ExternalFileUtils.GetExternalFileReference,
                             DB.ModelPathUtils.ConvertModelPathToUserVisiblePath, element_name)
        found = probe.guids(data)
        roots = probe.cache_roots(version)
        journals = probe.journal_roots(version)
        report = probe.format_report(
            data, roots, probe.scan_cache(roots, found), probe.scan_project_folders(roots, found),
            journals, probe.journal_cloud_names(journals))
        output = script.get_output()
        (getattr(output, "print_code", None) or print)(report)
    except Exception as error:
        script.get_logger().exception("Cloud check failed.")
        forms.alert(tr("The cloud check failed.\n\n{0}",
                       "Sprawdzenie chmury nie powiodło się.\n\n{0}").format(error), title=title)


if __name__ == "__main__":
    main()
