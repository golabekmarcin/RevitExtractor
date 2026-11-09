# -*- coding: utf-8 -*-
"""English by default; Polish when pyRevit's language setting is Polish.

Uses pyrevit.coreutils.applocales.get_locale_string, the same resolver pyRevit applies to the
en_us/pl title and tooltip maps in bundle.yaml, so the ribbon button and this window always agree.
Anything unexpected, including running outside pyRevit, falls back to English.
"""
from __future__ import unicode_literals


def tr(english, polish):
    try:
        from pyrevit.coreutils import applocales
        value = applocales.get_locale_string({"en_us": english, "pl": polish})
    except Exception:
        value = None
    return value or english
