# -*- coding: utf-8 -*-
"""Shift+click: read-only cloud (ACC) model check. Prints facts about the model, its links and
Revit's local cache to the pyRevit output window. Opens, copies and writes nothing."""
from __future__ import unicode_literals

from pyrevit import DB, forms, revit, script
from extractor_i18n import tr
import extractor_cloud_probe as probe


def main():
    title = tr("Export setup — cloud check", "Eksport setup — sprawdzenie chmury")
    doc = revit.doc
    if doc is None or doc.IsFamilyDocument:
        forms.alert(tr("Open the RVT project you want to check.",
                       "Otwórz projekt RVT, który chcesz sprawdzić."), title=title)
        return
    try:
        link_types = list(DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkType))
        data = probe.collect(doc, link_types, DB.ExternalFileUtils.GetExternalFileReference,
                             DB.ModelPathUtils.ConvertModelPathToUserVisiblePath)
        roots = probe.cache_roots(doc.Application.VersionNumber)
        cache = probe.scan_cache(roots, probe.guids(data))
        script.get_output().print_md(probe.format_report(data, roots, cache))
    except Exception as error:
        script.get_logger().exception("Cloud check failed.")
        forms.alert(tr("The cloud check failed.\n\n{0}",
                       "Sprawdzenie chmury nie powiodło się.\n\n{0}").format(error), title=title)


if __name__ == "__main__":
    main()
