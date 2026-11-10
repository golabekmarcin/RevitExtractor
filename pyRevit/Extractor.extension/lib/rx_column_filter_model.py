# -*- coding: utf-8 -*-
"""Pure Excel-style column filter logic (ported from MGo Family Manager column_filter_model).

Filters map a row attribute to None (show every value) or a set of the values to show.
"""
from __future__ import unicode_literals

import numbers
from collections import OrderedDict

from rx_i18n import tr


def blank_label():
    return tr("(Blanks)", "(Puste)")


def value_sort_key(value, label):
    """Popup order: Yes, No, whole numbers by size (2 before 10), then the rest by label."""
    text = "{0}".format(value)
    if text == "Yes":
        return (0, 0)
    if text == "No":
        return (1, 0)
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        return (2, value)
    return (3, (label or "").lower())


def row_matches_filters(row, filters, exclude=None):
    """True when row satisfies every active exact-value filter."""
    for attribute, selected in (filters or {}).items():
        if attribute == exclude or selected is None:
            continue
        if getattr(row, attribute, None) not in selected:
            return False
    return True


def all_values(rows, attribute):
    return set(getattr(row, attribute, None) for row in (rows or []))


def cascading_counts(rows, attribute, filters, base_visible=None):
    """Value counts after every other column filter and the host's own rules (search).

    The column itself is excluded, as in Excel: its complete set of values stays available
    while its own selection is edited.
    """
    counts = {}
    for row in rows or []:
        if base_visible is not None and not base_visible(row):
            continue
        if not row_matches_filters(row, filters, exclude=attribute):
            continue
        value = getattr(row, attribute, None)
        counts[value] = counts.get(value, 0) + 1
    return counts


def reconcile_filters(rows, filters):
    """Keep surviving selections after the rows change.

    None keeps showing everything, including new values. An active set stays active, so new
    values start unticked even if every surviving old value is selected.
    """
    result = OrderedDict()
    for attribute, selected in (filters or {}).items():
        if selected is None:
            result[attribute] = None
        else:
            result[attribute] = set(selected).intersection(all_values(rows, attribute))
    return result
