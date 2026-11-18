# -*- coding: utf-8 -*-
"""Tests for lib/rx_naming_pdb.py (source A: values from the export's property database) and its
wiring into rx_naming.NamedRun. Spec: specs/SPEC-named-copies.md (Value sources), plan Task 11a.

Synthetic databases use the real array layout, repeated-digit GUID-like ids and invented names.
RX_SLOW=1 adds the 200,000-element timing run; RX_SAMPLE_EXPORT=<export output folder> runs the
reader on a real export (Autodesk's Dynamo sample: 5 sheets)."""
import ast
import builtins
import datetime
import gzip
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

TESTS = Path(__file__).resolve().parent
LIB = TESTS.parents[2] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))
if str(TESTS) not in sys.path:
    sys.path.append(str(TESTS))

import rx_naming  # noqa: E402
import rx_naming_pdb  # noqa: E402
import rx_runner  # noqa: E402
from rx_naming_pdb import ALIASES, ExportValues  # noqa: E402
from test_naming import copy_link, manifest_of, node, polish, snapshot, touch  # noqa: E402

S1 = "11111111-1111-1111-1111-111111111111-0000007b"   # ElementId 123
S2 = "22222222-2222-2222-2222-222222222222-000001c8"   # 456
V1 = "33333333-3333-3333-3333-333333333333-00000315"   # 789
OTHER = "44444444-4444-4444-4444-444444444444-00000001"
SHEET_CAT = ("Revit Sheet", -2003100)
VIEW_CAT = ("Revit View", -2000279)
WALL_CAT = ("Revit Walls", -2000011)

SHEET_ATTRS = [("Sheet Number", "A101"), ("Sheet Name", "Ground floor"),
               ("Current Revision", "C"), ("Current Revision Date", "2026-01-02"),
               ("Current Revision Description", "For tender"), ("Sheet Issue Date", "01/02/26"),
               ("Drawn By", "AB"), ("Checked By", "CD"), ("Designed By", "EF"),
               ("Approved By", "GH"), ("Scale", " 1 : 100"), ("Zone Code", "Z1")]
VIEW_ATTRS = [("View Name", "Level 1"), ("Title on Sheet", "Plan of level 1"),
              ("View Scale", " 1 : 50"), ("Scale Value    1:", 50), ("Detail Level", "Fine"),
              ("Discipline", "Architectural"), ("Phase", "New Construction"),
              ("View Template", "<None>"), ("Sheet Number", "A101"), ("Crop View", 1)]


def element(ext, category, attrs, name="", revit_id=None):
    return {"id": ext, "category": category, "attrs": attrs, "name": name, "revit_id": revit_id}


def build_db(folder, elements, level=6, extra_vals=0):
    """Writes objects_{attrs,ids,offs,avs,vals}.json.gz with the exported layout. An attrs entry
    in `elements` is (label, value) or (label, value, flags): the same label with other flags is
    another attribute id, like Revit's instance and type parameters."""
    attrs = [0, ["name", "__name__", 20, None, None, None, 0, 0, None],
             ["parent", "__parent__", 11, None, None, None, 1, 0, None],
             ["Category", "__category__", 20, None, None, None, 1, 0, None],
             ["CategoryId", "__categoryId__", 2, None, None, None, 1, 0, None],
             ["ElementId", "__revit__", 20, None, None, None, 1, 0, None],
             ["View", "__internalref__", 11, None, None, None, 1, 0, None]]
    attr_ids = {}
    vals = [0]
    val_ids = {}

    def val(v):
        key = (type(v).__name__, v)
        if key not in val_ids:
            val_ids[key] = len(vals)
            vals.append(v)
        return val_ids[key]

    def attr(label, flags):
        if (label, flags) not in attr_ids:
            attr_ids[(label, flags)] = len(attrs)
            attrs.append([label, "Identity Data", 20, "", None, label, flags, 0, None])
        return attr_ids[(label, flags)]

    ids = [0, "doc_99999999-9999-9999-9999-999999999999"]
    offs = [0, 0]
    avs = [1, val("Model"), 3, val("Revit Document")]
    for _ in range(extra_vals):
        val("filler %d, [x] \"q\"" % len(vals))
    for e in elements:
        ids.append(e["id"])
        offs.append(len(avs) // 2)
        pairs = [(1, val(e["name"])), (2, val(1))]
        for item in e["attrs"]:
            pairs.append((attr(item[0], item[2] if len(item) > 2 else 0), val(item[1])))
        if e["category"]:
            pairs += [(3, val(e["category"][0])), (4, val(e["category"][1]))]
        if e["revit_id"]:
            pairs.append((5, val(e["revit_id"])))
        pairs.append((6, val(7)))
        for a, v in pairs:
            avs += [a, v]
    os.makedirs(folder, exist_ok=True)
    for name, data in (("attrs", attrs), ("ids", ids), ("offs", offs), ("avs", avs),
                       ("vals", vals)):
        text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        with gzip.GzipFile(os.path.join(folder, "objects_%s.json.gz" % name), "wb",
                           compresslevel=level, mtime=0) as fh:
            fh.write(text.encode("utf-8"))


def read(folder, ids, **kw):
    reader = ExportValues(folder, ids, **kw)
    steps = list(reader.steps())
    return reader, steps


class Case(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="rxpdb-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.res = os.path.join(self.root, "Resource")

    def standard(self, **kw):
        build_db(self.res, [
            element(OTHER, WALL_CAT, [("Mark", "W1")], name="Wall"),
            element(S1, SHEET_CAT, SHEET_ATTRS, name="Ground floor", revit_id="123"),
            element(V1, VIEW_CAT, VIEW_ATTRS, name="Level 1"),
            element(S2, SHEET_CAT, [("Sheet Number", "A102"), ("Sheet Name", "Roof")],
                    name="Roof"),
        ], **kw)


class Reading(Case):
    def test_sheets_and_views(self):
        self.standard()
        reader, steps = read(self.res, [S1, V1, S2])
        self.assertEqual((reader.state, reader.notes), ("done", []))
        self.assertEqual(sorted(reader.values), sorted([S1, V1, S2]))
        sheet = reader.values[S1]
        self.assertEqual(sheet["kind"], "sheet")
        self.assertEqual(sheet["id"], "123")
        self.assertEqual(sheet["name"], "A101 - Ground floor")
        self.assertEqual(sheet["tokens"], {
            "SheetNumber": "A101", "SheetName": "Ground floor", "CurrentRevision": "C",
            "CurrentRevisionDate": "2026-01-02", "CurrentRevisionDescription": "For tender",
            "SheetIssueDate": "01/02/26", "DrawnBy": "AB", "CheckedBy": "CD",
            "DesignedBy": "EF", "ApprovedBy": "GH", "ElementId": "123"})
        self.assertEqual(sheet["params"], {"Scale": " 1 : 100", "Zone Code": "Z1"})
        view = reader.values[V1]
        self.assertEqual((view["kind"], view["id"], view["name"]), ("view", "789", "Level 1"))
        self.assertEqual(view["tokens"], {
            "ViewName": "Level 1", "TitleOnSheet": "Plan of level 1", "Scale": "50",
            "DetailLevel": "Fine", "Discipline": "Architectural", "Phase": "New Construction",
            "ViewTemplate": "<None>", "ViewSheetNumber": "A101", "ElementId": "789"})
        self.assertEqual(view["params"], {"View Scale": " 1 : 50", "Crop View": "1"})
        self.assertEqual(reader.values[S2]["id"], "456")   # from the external id's hex tail
        self.assertEqual(steps[-1], (reader.total, reader.total))
        self.assertTrue(all(d <= t for d, t in steps))
        self.assertTrue(all(isinstance(v, str) for r in reader.values.values()
                            for v in list(r["tokens"].values()) + list(r["params"].values())))

    def test_values_feed_format_name_and_tie(self):
        self.standard()
        reader, _ = read(self.res, [S1, V1])
        parsed = rx_naming.parse_template("{SheetNumber} - {SheetName} {param:Zone Code}")
        record = reader.values[S1]
        values = dict(record["tokens"])
        values.update(("param:" + k, v) for k, v in record["params"].items())
        self.assertEqual(rx_naming.format_name(parsed, values, "x"), "A101 - Ground floor Z1")
        item = rx_naming.Deliverable("/abs/a.pdf", "Resource/Sheet/x/a.pdf", "pdf", S1)
        manifest = manifest_of(node("folder", "Sheets", [node("geometry", "A101 - x", vid=S1)]))
        pairs, untied = rx_naming.tie([item], manifest, reader.values)
        self.assertEqual((pairs[0][1], untied), (record, 0))

    def test_same_name_under_two_attribute_ids(self):
        build_db(self.res, [element(S1, SHEET_CAT, [
            ("Sheet Number", "", 0), ("Sheet Number", "A101", 8),
            ("Owner", "first", 0), ("Owner", "second", 8)])])
        values = read(self.res, [S1])[0].values[S1]
        self.assertEqual(values["tokens"]["SheetNumber"], "A101")   # the non-empty one
        self.assertEqual(values["params"], {"Owner": "first"})

    def test_internal_attributes_are_not_params(self):
        self.standard()
        params = read(self.res, [S1])[0].values[S1]["params"]
        for name in ("name", "parent", "Category", "CategoryId", "ElementId", "View"):
            self.assertNotIn(name, params)

    def test_kind_from_category_id_then_name(self):
        build_db(self.res, [
            element(S1, ("Arkusz", -2003100), [("Sheet Number", "A1")]),
            element(S2, ("Revit Sheets", ""), [("Sheet Number", "A2")]),
            element(V1, ("Views", None), [("View Name", "V")]),
            element(OTHER, WALL_CAT, [("Sheet Number", "A3")])])
        values = read(self.res, [S1, S2, V1, OTHER])[0].values
        self.assertEqual([values[i]["kind"] for i in (S1, S2, V1, OTHER)],
                         ["sheet", "sheet", "view", None])
        self.assertEqual(values[OTHER]["tokens"]["SheetNumber"], "A3")
        self.assertNotIn("ViewSheetNumber", values[OTHER]["tokens"])

    def test_unrecognised_names_note_once_and_keep_params(self):
        build_db(self.res, [
            element(S1, SHEET_CAT, [("Numer arkusza", "A101"), ("Nazwa arkusza", "Parter")]),
            element(S2, SHEET_CAT, [("Numer arkusza", "A102")])])
        reader, _ = read(self.res, [S1, S2])
        self.assertEqual(reader.state, "done")
        self.assertEqual(reader.notes, ["Sheet and view parameter names were not recognised; "
                                        "names kept their original text."])
        self.assertEqual(reader.values[S1]["params"],
                         {"Numer arkusza": "A101", "Nazwa arkusza": "Parter"})
        self.assertEqual(reader.values[S1]["tokens"], {"ElementId": "123"})
        with unittest.mock.patch.dict(sys.modules, polish()):
            reader, _ = read(self.res, [S1])
        self.assertIn("Nie rozpoznano", reader.notes[0])

    def test_a_second_language_through_aliases(self):
        build_db(self.res, [element(S1, SHEET_CAT, [("Numer arkusza", "A101")])])
        aliases = dict((k, list(v)) for k, v in ALIASES.items())
        aliases["SheetNumber"].append("Numer arkusza")
        reader, _ = read(self.res, [S1], aliases=aliases)
        self.assertEqual((reader.notes, reader.values[S1]["tokens"]["SheetNumber"]),
                         ([], "A101"))
        self.assertNotIn("Numer arkusza", reader.values[S1]["params"])

    def test_alias_table(self):
        self.assertTrue(set(ALIASES) <= set(rx_naming.TOKENS))
        self.assertNotIn("SheetSize", ALIASES)
        self.assertNotIn("ElementId", ALIASES)
        model = [n for n, (_, _, scope) in rx_naming.TOKENS.items() if scope == "model"]
        self.assertEqual(set(model) - set(ALIASES), {"SheetSize", "ElementId"})
        self.assertTrue(all(names and all(isinstance(n, str) for n in names)
                            for names in ALIASES.values()))

    def test_unknown_and_missing_ids(self):
        self.standard()
        reader, _ = read(self.res, [S1, "55555555-5555-5555-5555-555555555555-00000002", "", 7])
        self.assertEqual((reader.state, sorted(reader.values)), ("done", [S1]))
        reader, steps = read(self.res, [])
        self.assertEqual((reader.state, reader.values), ("done", {}))
        self.assertEqual(steps[-1][0], steps[-1][1])

    def test_last_element_slice_runs_to_the_end(self):
        self.standard()
        self.assertEqual(read(self.res, [S2])[0].values[S2]["tokens"]["SheetName"], "Roof")

    def test_escapes_commas_and_brackets_across_every_chunk_boundary(self):
        tricky = ['a "quoted", [bracketed] value', "back\\slash\\", 'end \\" mixed',
                  "zażółć ✓ \U0001F600", "", ",", "[", "]", '"', "null", "1,2"]
        attrs = [("Sheet Number", "A101")] + [("P%d" % i, v) for i, v in enumerate(tricky)]
        attrs += [("Float", 1.25), ("Negative", -7), ("Nothing", None), ("Flag", True)]
        build_db(self.res, [element(OTHER, WALL_CAT, [("Q", 'x"y\\z,]')]),
                            element(S1, SHEET_CAT, attrs, name='n"a,m[e]')], level=0,
                 extra_vals=40)
        expected = dict(("P%d" % i, v) for i, v in enumerate(tricky))
        expected.update({"Float": "1.25", "Negative": "-7", "Nothing": "", "Flag": "true"})
        for chunk in (1, 2, 3, 5, 7, 11, 64, 2 ** 20):
            for use_zlib in (True, False):
                reader, steps = read(self.res, [S1], chunk=chunk, use_zlib=use_zlib)
                self.assertEqual(reader.state, "done", (chunk, reader.notes))
                self.assertEqual(reader.values[S1]["params"], expected, (chunk, use_zlib))
                self.assertEqual(reader.values[S1]["tokens"]["SheetNumber"], "A101")
        self.assertGreater(len(steps), 5)

    def test_escaped_json_text_in_the_file(self):
        # ensure_ascii output: \\uXXXX escapes and surrogate pairs instead of raw UTF-8
        build_db(self.res, [element(S1, SHEET_CAT, [("Sheet Name", "Łódź \U0001F600")])])
        path = os.path.join(self.res, "objects_vals.json.gz")
        with gzip.open(path, "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))
        with gzip.GzipFile(path, "wb", mtime=0) as fh:
            fh.write(json.dumps(data, ensure_ascii=True).encode("ascii"))
        for chunk in (1, 3, 2 ** 20):
            reader, _ = read(self.res, [S1], chunk=chunk)
            self.assertEqual(reader.values[S1]["tokens"]["SheetName"], "Łódź \U0001F600")

    def test_zlib_without_gzip_mode_uses_gzipfile_with_a_note(self):
        self.standard()
        real = rx_naming_pdb.zlib.decompressobj

        def no_gzip(wbits=15, *a):
            if wbits > 15:
                raise ValueError("Invalid initialization option")
            return real(wbits, *a)
        with unittest.mock.patch.object(rx_naming_pdb.zlib, "decompressobj", no_gzip):
            reader, _ = read(self.res, [S1, V1])
        self.assertEqual(reader.state, "done")
        self.assertEqual(reader.notes, ["The fast gzip reader is not available here; a slower "
                                        "one was used."])
        self.assertEqual(reader.values, read(self.res, [S1, V1])[0].values)

    def test_too_large_refuses_without_opening(self):
        self.standard()
        opened = []
        real = io.open

        def spy(path, mode="r", *a, **k):
            opened.append(path)
            return real(path, mode, *a, **k)
        with unittest.mock.patch.object(io, "open", spy):
            reader, _ = read(self.res, [S1], max_bytes=100)
        self.assertEqual((reader.state, reader.values, opened), ("failed", {}, []))
        self.assertEqual(reader.notes, ["The export's property data is too large to read here; "
                                        "files keep their names."])

    def test_missing_corrupt_or_cut_files_fail_without_raising(self):
        self.standard()
        os.remove(os.path.join(self.res, "objects_avs.json.gz"))
        reader, _ = read(self.res, [S1])
        self.assertEqual((reader.state, reader.values), ("failed", {}))
        self.assertEqual(reader.notes,
                         ["The export's property data could not be read (FileNotFoundError(2))."])
        self.assertEqual(read(os.path.join(self.root, "nowhere"), [S1])[0].state, "failed")
        self.standard()
        touch(self.res, "objects_vals.json.gz", b"not gzip at all")
        self.assertEqual(read(self.res, [S1])[0].state, "failed")
        self.standard()
        with gzip.GzipFile(os.path.join(self.res, "objects_vals.json.gz"), "wb") as fh:
            fh.write(b'[0,"Model","cut off')
        reader, _ = read(self.res, [S1])
        self.assertEqual(reader.state, "failed")
        self.assertIn("PdbError", reader.notes[0])
        self.standard()
        path = os.path.join(self.res, "objects_avs.json.gz")
        with io.open(path, "rb") as fh:
            data = fh.read()
        with io.open(path, "wb") as fh:   # a gz file cut off in the middle
            fh.write(data[:len(data) // 2])
        reader, _ = read(self.res, [S2])
        self.assertEqual((reader.state, reader.values), ("failed", {}), reader.notes)

    def test_files_opened_rb_only(self):
        self.standard()
        modes = []
        real_io, real_builtin, real_os = io.open, builtins.open, os.open

        def spy(path, mode="r", *a, **k):
            modes.append(mode)
            return real_io(path, mode, *a, **k)

        def spy_os(path, flags, *a, **k):
            modes.append(flags)
            return real_os(path, flags, *a, **k)
        with unittest.mock.patch.object(io, "open", spy), \
                unittest.mock.patch.object(builtins, "open", spy), \
                unittest.mock.patch.object(os, "open", spy_os):
            reader, _ = read(self.res, [S1, V1, S2])
            reader2, _ = read(self.res, [S1], use_zlib=False)
        self.assertEqual((reader.state, reader2.state), ("done", "done"))
        self.assertEqual(set(modes), {"rb"})
        self.assertGreaterEqual(len(modes), 10)

    def test_steps_stop_early_when_closed(self):
        self.standard()
        reader = ExportValues(self.res, [S1], chunk=3)
        steps = reader.steps()
        next(steps)
        next(steps)
        steps.close()
        self.assertEqual(reader.state, "running")


def big_db(folder, n, wanted_every):
    """n elements with about 14 attributes each; every `wanted_every`-th is a sheet. Written as
    JSON text straight away (no per-element dicts) so 200,000 elements take seconds."""
    names = ["Sheet Number", "Sheet Name", "Drawn By", "Mark", "Comments", "Level", "Area",
             "Volume", "Phase Created", "Type Name", "Family", "Width", "Height", "Offset"]
    attrs = [0, ["name", "__name__", 20, None, None, None, 0, 0, None],
             ["Category", "__category__", 20, None, None, None, 1, 0, None],
             ["CategoryId", "__categoryId__", 2, None, None, None, 1, 0, None]]
    attrs += [[nm, "Identity Data", 20, "", None, nm, 0, 0, None] for nm in names]
    vals = [0, "Revit Sheet", -2003100, "Revit Walls", -2000011]
    ids = [0]
    offs = [0]
    avs = []
    wanted = []
    for i in range(1, n + 1):
        ext = "%08d-1111-1111-1111-111111111111-%08x" % (i, i)
        ids.append(ext)
        offs.append(len(avs) // 2)
        sheet = i % wanted_every == 0 or i == n
        if sheet:
            wanted.append(ext)
        base = len(vals)
        vals += ["E%d" % i, "S%d" % i, "Sheet, [%d] \"x\"" % i, "AB", 3.5 + i, i * 7]
        avs += [1, base, 2, 1 if sheet else 3, 3, 2 if sheet else 4]
        for k in range(len(names)):
            avs += [4 + k, base + 1 + (k % 5)]
    os.makedirs(folder, exist_ok=True)
    for name, data in (("attrs", attrs), ("ids", ids), ("offs", offs), ("avs", avs),
                       ("vals", vals)):
        with gzip.GzipFile(os.path.join(folder, "objects_%s.json.gz" % name), "wb",
                           compresslevel=1, mtime=0) as fh:
            fh.write(json.dumps(data, separators=(",", ":")).encode("utf-8"))
    return wanted


class Speed(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="rxpdb-big-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def timed(self, n, every):
        wanted = big_db(self.root, n, every)
        reader = ExportValues(self.root, wanted)
        worst = 0.0
        steps = 0
        start = last = time.perf_counter()
        for _ in reader.steps():
            now = time.perf_counter()
            worst = max(worst, now - last)
            steps += 1
            last = now
        total = time.perf_counter() - start
        self.assertEqual(reader.state, "done", reader.notes)
        self.assertEqual(len(reader.values), len(wanted))
        last_id = wanted[-1]
        record = reader.values[last_id]
        self.assertEqual(record["kind"], "sheet")
        self.assertEqual(record["tokens"]["SheetNumber"], "S%d" % n)
        self.assertEqual(record["tokens"]["SheetName"], 'Sheet, [%d] "x"' % n)
        self.assertEqual(record["tokens"]["DrawnBy"], "AB")
        self.assertEqual(record["params"]["Mark"], "%r" % (3.5 + n))
        self.assertEqual(record["params"]["Comments"], "%d" % (n * 7))
        self.assertEqual(record["id"], "%d" % n)
        mb = reader.total / 2.0 ** 20
        print("\n[rx_naming_pdb] %d elements, %d wanted: %.1f MB compressed, %d steps, %.2f s, "
              "%.1f MB/s, worst step %.1f ms" % (n, len(wanted), mb, steps, total, mb / total,
                                                 worst * 1000))
        self.assertLess(worst, 0.25)   # generous for slow CI; the printed figure is the measure
        return reader

    def test_20000_elements(self):
        self.timed(20000, 50)

    @unittest.skipUnless(os.environ.get("RX_SLOW") == "1", "set RX_SLOW=1 for 200,000 elements")
    def test_200000_elements(self):
        self.timed(200000, 100)


@unittest.skipUnless(os.environ.get("RX_SAMPLE_EXPORT"), "set RX_SAMPLE_EXPORT to an output folder")
class RealSample(unittest.TestCase):
    def test_dynamo_sample(self):
        output = os.environ["RX_SAMPLE_EXPORT"]
        with io.open(os.path.join(output, "bubble.json"), "rb") as fh:
            manifest = json.loads(fh.read().decode("utf-8-sig"))
        ids = [v[0] for v in rx_naming._viewables(manifest)]
        reader, steps = read(os.path.join(output, "Resource"), ids)
        self.assertEqual(reader.state, "done", reader.notes)
        sheets = dict((r["tokens"].get("SheetNumber"), r) for r in reader.values.values()
                      if r["kind"] == "sheet")
        print("\n[rx_naming_pdb] sample: %d viewables, %d found, %d steps, notes %s"
              % (len(ids), len(reader.values), len(steps), reader.notes))
        for vid, r in sorted(reader.values.items(), key=lambda x: x[1]["name"]):
            print("  %s %s id=%s %r tokens=%s params=%d" % (vid, r["kind"], r["id"], r["name"],
                                                           r["tokens"], len(r["params"])))
        self.assertEqual(len(sheets), 5)
        a101 = sheets["A101"]["tokens"]
        for token in ("SheetNumber", "SheetName", "SheetIssueDate", "DrawnBy", "CheckedBy",
                      "DesignedBy", "ApprovedBy", "ElementId"):
            self.assertTrue(a101.get(token), token)
        small, _ = read(os.path.join(output, "Resource"), ids, chunk=97)
        self.assertEqual(small.values, reader.values)


# ---- the NamedRun wiring ----

PDF = "Resource/Sheet/A101 - Ground floor 123/pdf/A101 - Ground floor.pdf"


class Wiring(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="rxpdb-run-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.paths = rx_runner.run_paths_for(self.root)
        self.out = self.paths.output
        manifest = manifest_of(node("folder", "Sheets",
                                    [node("geometry", "A101 - Ground floor", vid=S1)]))
        touch(self.out, "bubble.json", json.dumps(manifest).encode("utf-8"))
        touch(self.out, PDF, b"pdf" * 20)
        build_db(os.path.join(self.out, "Resource"),
                 [element(S1, SHEET_CAT, SHEET_ATTRS, name="Ground floor", revit_id="123")])

    def run_named(self, template, values=None, **kw):
        kw.setdefault("link", copy_link)
        before = snapshot(self.out)
        run = rx_naming.NamedRun(self.paths, {"template": template,
                                              "system": {"ModelName": "Model"},
                                              "values": values}, **kw)
        steps = list(run.steps())
        self.assertEqual(snapshot(self.out), before)
        self.assertTrue(all(d <= t for d, t in steps))
        return run

    def names(self, run):
        return [i["name"] for i in run.items]

    def test_model_token_reads_the_values(self):
        run = self.run_named("{SheetNumber} - {SheetName}")
        self.assertEqual((run.state, self.names(run), run.notes),
                         ("done", ["A101 - Ground floor.pdf"], []))

    def test_param_part_reads_the_values(self):
        run = self.run_named("{param:Zone Code} {OriginalName}")
        self.assertEqual(self.names(run), ["Z1 A101 - Ground floor.pdf"])

    def spy_reader(self, calls):
        def reader(resource, ids, **kw):
            calls.append((resource, ids))
            return ExportValues(resource, ids, **kw)
        return reader

    def test_system_only_template_reads_nothing(self):
        calls = []
        run = self.run_named("{ModelName} {Date} {OriginalName}",
                             values_reader=self.spy_reader(calls),
                             now=datetime.datetime(2026, 1, 2))
        self.assertEqual((calls, self.names(run)),
                         ([], ["Model 2026-01-02 A101 - Ground floor.pdf"]))

    def test_reader_gets_the_resource_folder_and_viewable_ids(self):
        calls = []
        self.run_named("{SheetNumber}", values_reader=self.spy_reader(calls))
        self.assertEqual(calls, [(os.path.join(self.out, "Resource"), [S1])])

    def test_given_values_are_used_as_they_are(self):
        calls = []
        given = {S1: {"kind": "sheet", "id": "123", "name": "X", "tokens": {"SheetNumber": "B7"},
                      "params": {}}}
        run = self.run_named("{SheetNumber}", values=given, values_reader=self.spy_reader(calls))
        self.assertEqual((calls, self.names(run)), ([], ["B7.pdf"]))
        run = self.run_named("{SheetNumber}", values={}, values_reader=self.spy_reader(calls))
        self.assertEqual(calls, [])

    def test_failed_reading_keeps_original_names_and_continues(self):
        os.remove(os.path.join(self.out, "Resource", "objects_vals.json.gz"))
        run = self.run_named("{ModelName} - {SheetNumber}")
        self.assertEqual((run.state, self.names(run)), ("done", ["A101 - Ground floor.pdf"]))
        self.assertEqual(run.notes, [
            "The export's property data could not be read (FileNotFoundError(2)).",
            "Sheet and view values could not be read, so every file keeps its original name."])
        with io.open(os.path.join(self.root, "named.json"), "rb") as fh:
            self.assertIn("could not be read", json.loads(fh.read().decode("ascii"))["notes"][1])
        self.assertIn("Named copies: 1 in named\\", run.result_message())

    def test_a_raising_reader_never_fails_the_run(self):
        def broken(*a, **k):
            raise RuntimeError("boom")
        run = self.run_named("{SheetNumber}", values_reader=broken)
        self.assertEqual((run.state, self.names(run)), ("done", ["A101 - Ground floor.pdf"]))
        self.assertIn("every file keeps its original name", run.notes[-1])

    def test_a_failure_of_the_run_keeps_its_own_note_first(self):
        os.remove(os.path.join(self.out, "Resource", "objects_ids.json.gz"))

        def no_link(src, dst):
            raise OSError(1, "no links")

        def bad_copier(*a, **k):
            raise OSError(5, "no copies")
            yield
        run = self.run_named("{SheetNumber}", link=no_link, copier=bad_copier)
        self.assertEqual(run.state, "failed")
        self.assertEqual(run.notes[0], "No named copy could be made; see named.json.")
        self.assertIn("could not be read", run.notes[1])
        self.assertIn("No named copy could be made", run.result_message())

    def test_polish_note(self):
        os.remove(os.path.join(self.out, "Resource", "objects_ids.json.gz"))
        with unittest.mock.patch.dict(sys.modules, polish()):
            run = self.run_named("{SheetNumber}")
        self.assertIn("każdy plik zachowuje oryginalną nazwę", run.notes[-1])


class SourceGuards(unittest.TestCase):
    SOURCE = (LIB / "rx_naming_pdb.py").read_text(encoding="utf-8")

    def test_no_revit_dotnet_or_clr_imports(self):
        banned = {"pyrevit", "Autodesk", "System", "clr", "rpw"}
        for node_ in ast.walk(ast.parse(self.SOURCE)):
            if isinstance(node_, ast.Import):
                names = [a.name for a in node_.names]
            elif isinstance(node_, ast.ImportFrom):
                names = [node_.module or ""]
            else:
                continue
            for name in names:
                self.assertNotIn(name.split(".")[0], banned, name)

    def test_ironpython_syntax_rules(self):
        import test_export_button
        import test_status
        self.assertEqual(test_status.ironpython_problems(self.SOURCE), [])
        self.assertEqual(test_export_button.extra_ironpython_problems(self.SOURCE), [])
        for banned in ("pathlib", "\t", "json.load(", "ensure_ascii"):
            self.assertNotIn(banned, self.SOURCE)
        self.assertIn("from __future__ import unicode_literals", self.SOURCE)
        self.assertTrue(self.SOURCE.startswith("# -*- coding: utf-8 -*-"))

    def test_only_attrs_is_parsed_whole(self):
        calls = [n for n in ast.walk(ast.parse(self.SOURCE)) if isinstance(n, ast.Call) and
                 getattr(n.func, "attr", "") == "loads"]
        # attrs (whole) and one string token with escapes
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
