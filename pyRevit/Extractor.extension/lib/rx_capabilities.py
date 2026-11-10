# -*- coding: utf-8 -*-
"""What does the Revit I am running in support? One table, no per-version files.

Pure Python, no Revit import (a test enforces this). A new Revit version means a new table row.
Spec: specs/SPEC-capabilities.md.
"""
from __future__ import unicode_literals

from collections import namedtuple

from rx_i18n import tr

try:
    _INTEGER_TYPES = (int, long)  # IronPython 2.7 / CPython 2
except NameError:
    _INTEGER_TYPES = (int,)
try:
    _TEXT_TYPES = (basestring,)
except NameError:
    _TEXT_TYPES = (str,)

FLOOR_YEAR = 2022

# Years the owner has tested in Revit with pyRevit. Add a year only with evidence (the owner's
# test, recorded in HANDOVER.md or a VERIFICATION-*.md). The native parser check alone is not
# a test in Revit.
TESTED_YEARS = (2022,)

# (first_year, values), sorted. A year uses the last row whose first_year <= year.
# 2022 row: owner's Revit 2022 (9/9 parser, slice 1 test), Revit 2023 parser check.
# 2026 row: the original author's 2026 button; not verified here (no Revit 2026 available).
# db_export_key: the Extractor build of that row can still read 3dviewing.db_export (2024.0.x
# ships only with Revit 2025 and earlier), so the index writes it when the database is off.
_TABLE = [
    (2022, {"view_key": "view_ids", "formats": (), "ifc_setups": False,
            "extended_properties": False, "topology_metadata": False, "db_export_key": True}),
    (2026, {"view_key": "view_unique_ids", "formats": ("dwg", "ifc"), "ifc_setups": True,
            "extended_properties": True, "topology_metadata": True, "db_export_key": False}),
]


class UnsupportedRevit(ValueError):
    """Revit year below the floor, or a value that is not a year."""


_Fields = namedtuple(
    str("Capabilities"),
    str("year verified tested view_key formats ifc_setups extended_properties topology_metadata "
    "db_export_key"))


class Capabilities(_Fields):
    """Read-only record. verified = the year has its own table row; tested = see TESTED_YEARS."""

    __slots__ = ()

    @property
    def label(self):
        """Window text, translated when read."""
        if not self.verified:
            return tr("Revit %d (untested, treated as %d)" % (self.year, _TABLE[-1][0]),
                      "Revit %d (nietestowane, traktowane jak %d)" % (self.year, _TABLE[-1][0]))
        if self.tested:
            return "Revit %d" % self.year
        return tr("Revit %d (not tested yet)" % self.year,
                  "Revit %d (jeszcze nie testowane)" % self.year)


def _parse_year(value):
    if not isinstance(value, bool):
        if isinstance(value, _INTEGER_TYPES):
            return int(value)
        if isinstance(value, _TEXT_TYPES):
            text = value.strip()
            if text and all(ch in "0123456789" for ch in text):
                return int(text)
    raise UnsupportedRevit(tr(
        "Unsupported Revit version %r: expected a year of %d or later." % (value, FLOOR_YEAR),
        "Nieobsługiwana wersja Revit %r: oczekiwano roku %d lub nowszego." % (value, FLOOR_YEAR)))


def for_revit(version):
    """Capabilities for a VersionNumber string or int. Raises UnsupportedRevit."""
    year = _parse_year(version)
    if year < FLOOR_YEAR:
        raise UnsupportedRevit(tr(
            "Unsupported Revit version %d: the oldest supported is %d." % (year, FLOOR_YEAR),
            "Nieobsługiwana wersja Revit %d: najstarsza obsługiwana to %d." % (year, FLOOR_YEAR)))
    row = _TABLE[0]
    for candidate in _TABLE:
        if candidate[0] <= year:
            row = candidate
    values = row[1]
    verified = year <= _TABLE[-1][0]
    return Capabilities(
        year=year, verified=verified, tested=verified and year in TESTED_YEARS,
        view_key=values["view_key"], formats=values["formats"],
        ifc_setups=values["ifc_setups"], extended_properties=values["extended_properties"],
        topology_metadata=values["topology_metadata"], db_export_key=values["db_export_key"])


def element_id_value(element_id):
    """Numeric ElementId across Revit 2022 and later, picked by feature, not by version.

    RevitAPI docs (revit-api skill, re-checked 2026-11-10): ElementId.IntegerValue is documented
    in the 2022 revision (no ElementId.Value page there) and has no ElementId page in 2026;
    ElementId.Value (Int64) is documented in 2026. WorksetId.IntegerValue still exists in 2026,
    so only the ElementId one went away. Value is read first and IntegerValue never touched when
    Value exists. The caller turns the value into text, so an Int64 never reaches Int32 checks.
    """
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue
