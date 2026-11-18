# -*- coding: utf-8 -*-
"""Source A for named copies: sheet and view values read from an export's property database
(output\\Resource\\objects_*.json.gz), read-only, without Revit, in bounded memory and small time
slices. Pure Python: no Revit, pyRevit, System or clr import. Spec: specs/SPEC-named-copies.md
(Value sources).

Layout, as Analyzer/public/property-index.js reads it: ids[dbId] is the element's external id
(its UniqueId, equal to the viewableID in bubble.json), offs[dbId]..offs[dbId + 1] is its slice of
pairs in avs (avs[2p] = attribute id, avs[2p + 1] = value id; the last element's slice runs to the
end of avs), vals[valueId] is the value and attrs[attrId] = [name, group, type, unit, ?,
display name, flags, ...]. A group starting with "__" is the database's own bookkeeping.

Only attrs is parsed whole. ids, offs, avs and vals can be hundreds of MB decoded, so each is
streamed (1 MiB compressed reads, fed to zlib 64 KiB at a time) and tokenised with one regex over
a carried-over text buffer, keeping only the entries the wanted elements need.
"""
from __future__ import unicode_literals

import bisect
import codecs
import gzip
import io
import json
import os
import re
import zlib
from collections import OrderedDict

from rx_i18n import tr

MAX_BYTES = 400 * 2 ** 20   # total compressed size of the five files
CHUNK = 2 ** 20             # compressed bytes per read
_FEED = 2 ** 16             # compressed bytes per zlib call: bounds the decoded text per step
_FILES = ("ids", "offs", "avs", "attrs", "vals")   # the order of the passes
_BATCH = 200               # elements per step when building the records
_OPEN = 2 ** 62             # the end of the last element's avs slice: the end of the file

# Token -> the attribute names that hold it, first match wins. The names are Revit's parameter
# names in the language of the Revit that exported, so this table only knows English (checked on
# Autodesk's Dynamo sample exported by Revit 2023). For another language, append the localised
# names to each list, e.g. "SheetNumber": ["Sheet Number", "<the name in that language>"]; an
# element of either language is then read. ElementId is not here: it comes from the database's
# own ElementId attribute or the external id. SheetSize is not in the database.
ALIASES = OrderedDict([
    ("SheetNumber", ["Sheet Number"]),
    ("SheetName", ["Sheet Name"]),
    ("CurrentRevision", ["Current Revision"]),
    ("CurrentRevisionDate", ["Current Revision Date"]),
    ("CurrentRevisionDescription", ["Current Revision Description"]),
    ("SheetIssueDate", ["Sheet Issue Date"]),
    ("DrawnBy", ["Drawn By"]),
    ("CheckedBy", ["Checked By"]),
    ("DesignedBy", ["Designed By"]),
    ("ApprovedBy", ["Approved By"]),
    ("ViewName", ["View Name"]),
    # "Family" is a guess (the property of a view's type); check it against a real export
    ("ViewFamily", ["Family"]),
    ("TitleOnSheet", ["Title on Sheet"]),
    ("Scale", ["Scale Value    1:"]),   # the number (100); "View Scale" is the text " 1 : 100"
    ("DetailLevel", ["Detail Level"]),
    ("Discipline", ["Discipline"]),
    ("Phase", ["Phase"]),
    ("ViewTemplate", ["View Template"]),
    ("ViewSheetNumber", ["Sheet Number"]),   # on a view: the sheet it is placed on
])

_SHEET_TOKENS = ("SheetNumber", "SheetName", "CurrentRevision", "CurrentRevisionDate",
                 "CurrentRevisionDescription", "SheetIssueDate", "DrawnBy", "CheckedBy",
                 "DesignedBy", "ApprovedBy")
_VIEW_TOKENS = ("ViewName", "ViewFamily", "TitleOnSheet", "Scale", "DetailLevel", "Discipline",
                "Phase", "ViewTemplate", "ViewSheetNumber")
_KIND_TOKENS = {"sheet": _SHEET_TOKENS, "view": _VIEW_TOKENS,
                None: _SHEET_TOKENS + _VIEW_TOKENS[:-1]}
# BuiltInCategory OST_Sheets / OST_Views: language-neutral, unlike the category name
_CATEGORY_IDS = {"-2003100": "sheet", "-2000279": "view"}
_CATEGORY_NAMES = {"sheet": "sheet", "sheets": "sheet", "view": "view", "views": "view"}
_INTERNAL_KEPT = ("__name__", "__category__", "__categoryId__", "__revit__")

# one JSON value: a whole string, a bare value (number, null, true, false), or a lone quote,
# which only matches where a string is cut off at the end of the buffer
_TOKEN = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"|[^\s,\[\]"]+|"')
_DELIMITERS = ' \t\r\n,[]"'
_ELEMENT_ID = re.compile(r"-([0-9a-fA-F]{8})$")
# gzip of b"[0]", to check that zlib reads the gzip header here (IronPython's may not)
_GZIP_PROBE = (b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff\x8b6\x88\x05\x00\xf9\x034U"
               b"\x03\x00\x00\x00")


class _Refused(Exception):
    """Reading does not start; args[0] is the translated note."""


class PdbError(ValueError):
    """The property database is not in the expected form."""


def _short_error(error):
    code = getattr(error, "winerror", None) or getattr(error, "errno", None)
    return type(error).__name__ + ("(%s)" % code if code else "")


def _open_quote(buf, end):
    """Where the string cut off at the end of buf[:end] starts: its last unescaped quote."""
    p = buf.rfind('"', 0, end)
    while p > 0:
        q = p - 1
        while q >= 0 and buf[q] == "\\":
            q -= 1
        if (p - 1 - q) % 2 == 0:
            return p
        p = buf.rfind('"', 0, p)
    return p


def _text(token):
    """A value token as text: strings unescaped, null as "", numbers as stored."""
    if token[:1] == '"':
        return json.loads(token) if "\\" in token else token[1:-1]
    return "" if token == "null" else token


def _zlib_gzip_works():
    try:
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        return inflater.decompress(_GZIP_PROBE) + inflater.flush() == b"[0]"
    except Exception:
        return False


class ExportValues(object):
    """Reads the values of the sheets and views whose external id is in `viewable_ids`.
    steps() yields (done, total) compressed bytes and never raises; then `.state` is "done" or
    "failed", `.notes` holds translated notes and `.values` maps each found viewable id to
    {"kind", "id", "name", "tokens", "params"} (the form rx_naming.tie and format_name use)."""

    def __init__(self, resource_dir, viewable_ids, aliases=None, max_bytes=MAX_BYTES,
                 chunk=CHUNK, use_zlib=None):
        self.resource_dir = resource_dir
        self.viewable_ids = list(OrderedDict.fromkeys(
            v for v in viewable_ids if isinstance(v, type("")) and v))
        self.aliases = ALIASES if aliases is None else aliases
        self.max_bytes = max_bytes
        self.chunk = chunk
        self.state = None
        self.notes = []
        self.values = {}
        self.done = 0
        self.total = 0
        self._use_zlib = use_zlib   # None: feature check; False forces the gzip.GzipFile path
        self._base = 0
        self._paths = {}
        self._sizes = {}
        self._alias_noted = False
        self._known = set(alias for names in self.aliases.values() for alias in names)

    def steps(self):
        self.state = "running"
        work = self._work()
        try:
            try:
                for step in work:
                    yield step
            except _Refused as refused:
                self._failed(refused.args[0])
                return
            except Exception as error:
                self._failed(tr("The export's property data could not be read ({0}).",
                                "Nie można odczytać danych o właściwościach eksportu ({0}).")
                             .format(_short_error(error)))
                return
        finally:
            work.close()   # IronPython does not close a dropped generator at once
        self.done = self.total
        self.state = "done"
        yield self.done, self.total

    def _failed(self, note):
        self.values = {}
        self.notes.append(note)
        self.state = "failed"

    # ---- passes ----

    def _work(self):
        for name in _FILES:
            self._paths[name] = os.path.join(self.resource_dir, "objects_%s.json.gz" % name)
            self._sizes[name] = os.path.getsize(self._paths[name])   # raises when missing
        self.total = sum(self._sizes.values())
        if self.total > self.max_bytes:
            raise _Refused(tr(
                "The export's property data is too large to read here; files keep their names.",
                "Dane o właściwościach eksportu są za duże, by je tu odczytać; pliki zachowują "
                "nazwy."))
        if self._use_zlib is None:
            self._use_zlib = _zlib_gzip_works()
            if not self._use_zlib:
                self.notes.append(tr("The fast gzip reader is not available here; a slower one "
                                     "was used.",
                                     "Szybki czytnik gzip jest tu niedostępny; użyto wolniejszego."))
        yield self.done, self.total
        if not self.viewable_ids:
            return

        # ids: the dbId of each wanted external id (the first one when an id repeats)
        quoted = dict(('"%s"' % v, v) for v in self.viewable_ids
                      if '"' not in v and "\\" not in v and min(v) >= " ")
        # shortcut: an id that JSON must escape, or that the writer escaped anyway, is not found
        wanted = set(quoted)
        found = OrderedDict()
        lists = self._token_lists("ids")
        try:
            for first, tokens in lists:
                for hit in wanted.intersection(tokens):
                    found[quoted[hit]] = first + tokens.index(hit)
                    wanted.discard(hit)
                yield self.done, self.total
                if not wanted:
                    break
        finally:
            lists.close()
        self._next("ids")
        if not found:
            return

        # offs: where each element's slice starts and ends
        db_ids = sorted(set(found.values()))
        offs = {}
        for _ in self._collect("offs", [(i, i + 1) for i in sorted(set(
                db_ids + [d + 1 for d in db_ids]))], offs):
            yield self.done, self.total
        offs = dict((i, int(t[0])) for i, t in offs.items())
        slices = {}
        for d in db_ids:
            if d not in offs:
                raise PdbError("offs")
            start = 2 * offs[d]
            end = 2 * offs[d + 1] if d + 1 in offs else _OPEN
            if end > start:
                slices[d] = (start, end)

        # avs: the (attribute id, value id) pairs of those slices
        avs = {}
        for _ in self._collect("avs", sorted(set(slices.values())), avs):
            yield self.done, self.total

        # attrs: small, parsed whole
        parts = []
        pieces = self._pieces("attrs")
        try:
            for piece, _ in pieces:
                parts.append(piece)
                yield self.done, self.total
        finally:
            pieces.close()
        self._next("attrs")
        attrs = json.loads("".join(parts))
        del parts[:]
        if not isinstance(attrs, list):
            raise PdbError("attrs")

        # vals: only the values those pairs point to
        pairs = {}
        needed = set()
        for d, span in slices.items():
            numbers = [int(t) for t in avs.get(span[0], [])]
            kept = []
            for a, v in zip(numbers[0::2], numbers[1::2]):
                attr = attrs[a] if 0 <= a < len(attrs) else None
                if isinstance(attr, list) and len(attr) > 1 and (
                        not ("%s" % (attr[1],)).startswith("__") or attr[1] in _INTERNAL_KEPT):
                    kept.append((attr, v))
                    needed.add(v)
            pairs[d] = kept
            if len(pairs) % _BATCH == 0:
                yield self.done, self.total
        avs.clear()
        vals = {}
        for _ in self._collect("vals", [(v, v + 1) for v in sorted(needed)], vals):
            yield self.done, self.total
        for vid, d in found.items():
            self.values[vid] = self._record(vid, [(attr, (vals.get(v) or [None])[0])
                                                  for attr, v in pairs.get(d, [])])
            if len(self.values) % _BATCH == 0:
                yield self.done, self.total

    def _next(self, name):
        self._base += self._sizes[name]
        self.done = self._base

    def _collect(self, name, spans, out):
        """Stores the tokens of each (start, end) element span of the array `name` in
        out[start] (a list). Spans are sorted and disjoint; one step per piece; stops reading
        once past the last span."""
        if spans:
            starts = [s for s, _ in spans]
            ends = [e for _, e in spans]
            last = ends[-1]
            lists = self._token_lists(name)
            try:
                for first, tokens in lists:
                    top = first + len(tokens)
                    lo = bisect.bisect_right(ends, first)
                    hi = bisect.bisect_left(starts, top)
                    for k in range(lo, hi):
                        s, e = spans[k]
                        out.setdefault(s, []).extend(
                            tokens[max(s, first) - first:min(e, top) - first])
                    yield
                    if top >= last:
                        break
            finally:
                lists.close()
        self._next(name)

    # ---- reading ----

    def _token_lists(self, name):
        """(index of the first token, [token texts]) per piece of the array `name`; a token cut
        off at the end of a piece is carried into the next."""
        index = 0
        carry = ""
        pieces = self._pieces(name)
        try:
            for piece, final in pieces:
                buf = carry + piece if carry else piece
                end = len(buf) if final else max(buf.rfind(c) for c in _DELIMITERS) + 1
                tokens = _TOKEN.findall(buf, 0, end)
                cut = end
                if '"' in tokens:
                    if final:
                        raise PdbError(name)
                    tokens = tokens[:tokens.index('"')]
                    cut = _open_quote(buf, end)
                carry = buf[cut:]
                yield index, tokens
                index += len(tokens)
        finally:
            pieces.close()

    def _pieces(self, name):
        """(decoded text, final) pieces of the gz file `name`, opened "rb" only."""
        decoder = codecs.getincrementaldecoder("utf-8-sig")()
        feed = min(self.chunk, _FEED)
        with io.open(self._paths[name], "rb") as handle:
            if self._use_zlib:
                inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
                while True:
                    data = handle.read(self.chunk)
                    if not data:
                        break
                    for at in range(0, len(data), feed):
                        raw = inflater.decompress(data[at:at + feed])
                        self.done = self._base + handle.tell() - len(data) + at
                        yield decoder.decode(raw), False
                tail = inflater.flush()
                # a cut-off file or a second gzip member would silently lose data: fail instead
                # (IronPython 2.7's decompressobj has no .eof; the cut-off check is skipped there)
                if not getattr(inflater, "eof", True) or inflater.unused_data:
                    raise PdbError(name)
                yield decoder.decode(tail, True), True
            else:
                # IronPython's zlib may not read the gzip header; gzip.GzipFile reads it itself
                # and inflates raw deflate (shortcut: .NET GZipStream would be faster, add it
                # behind rx_dotnet.ensure_assemblies if this path proves too slow in Revit)
                reader = gzip.GzipFile(fileobj=handle, mode="rb")
                while True:
                    raw = reader.read(feed * 4)
                    self.done = self._base + handle.tell()
                    if not raw:
                        break
                    yield decoder.decode(raw), False
                yield decoder.decode(b"", True), True

    # ---- the record ----

    def _record(self, vid, attributes):
        name = ""
        category = ""
        category_id = ""
        element_id = None
        by_name = OrderedDict()
        for attr, token in attributes:
            value = _text(token) if token is not None else ""
            group = attr[1]
            if group == "__name__":
                name = value
            elif group == "__category__":
                category = value
            elif group == "__categoryId__":
                category_id = value
            elif group == "__revit__":
                if attr[0] == "ElementId" and value.isdigit():
                    element_id = value
            else:
                label = (attr[5] if len(attr) > 5 and attr[5] else attr[0])
                label = label if isinstance(label, type("")) else "%s" % (label,)
                if not by_name.get(label):
                    by_name[label] = value
        kind = _CATEGORY_IDS.get(category_id)
        if kind is None:
            text = category.lower()
            kind = _CATEGORY_NAMES.get(text[6:] if text.startswith("revit ") else text)
        tokens = {}
        for token in _KIND_TOKENS[kind]:
            for alias in self.aliases.get(token, ()):
                if alias in by_name:
                    tokens[token] = by_name[alias]
                    break
        if not tokens and not self._alias_noted:
            self._alias_noted = True
            self.notes.append(tr("Sheet and view parameter names were not recognised; names "
                                 "kept their original text.",
                                 "Nie rozpoznano nazw parametrów arkuszy i widoków; nazwy "
                                 "zachowały oryginalny tekst."))
        if element_id is None:
            match = _ELEMENT_ID.search(vid)
            element_id = "%d" % int(match.group(1), 16) if match else None
        if element_id is not None:
            tokens["ElementId"] = element_id
        params = dict((k, v) for k, v in by_name.items() if k not in self._known)
        if kind == "sheet" and tokens.get("SheetNumber") and "SheetName" in tokens:
            name = "%s - %s" % (tokens["SheetNumber"], tokens["SheetName"])
        elif kind == "view" and tokens.get("ViewName"):
            name = tokens["ViewName"]
        return {"kind": kind, "id": element_id, "name": name, "tokens": tokens,
                "params": params}
