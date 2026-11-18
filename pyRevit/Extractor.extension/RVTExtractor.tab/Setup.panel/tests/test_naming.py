# -*- coding: utf-8 -*-
"""Tests for lib/rx_naming.py: template parsing, name cleaning, length budgets and clash numbering.
Spec: specs/SPEC-named-copies.md, acceptance criteria 1-3 and 12."""
import ast
import datetime
import sys
import types
import unittest
import unittest.mock
from pathlib import Path

TESTS = Path(__file__).resolve().parent
LIB = TESTS.parents[2] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))

import rx_cloud  # noqa: E402
import rx_naming  # noqa: E402
from rx_naming import (NamingError, Namer, TOKENS, PRESETS, check_naming, clean_name,  # noqa: E402
                       file_budget, fit_name, folder_budget, format_name, parse_template,
                       system_values)


def polish():
    def get_locale_string(string_dict):
        for code in ("pl", "en_us"):
            if code in string_dict:
                return string_dict[code]
        return None
    applocales = types.SimpleNamespace(get_locale_string=get_locale_string)
    coreutils = types.SimpleNamespace(applocales=applocales)
    return {"pyrevit": types.SimpleNamespace(coreutils=coreutils),
            "pyrevit.coreutils": coreutils, "pyrevit.coreutils.applocales": applocales}


def safe(stem, ext=".x"):
    return rx_cloud.safe_file_name(stem + ext)


TOKEN_NAMES = [
    "SheetNumber", "SheetName", "CurrentRevision", "CurrentRevisionDate",
    "CurrentRevisionDescription", "SheetIssueDate", "DrawnBy", "CheckedBy", "DesignedBy",
    "ApprovedBy", "SheetSize", "ViewName", "TitleOnSheet", "Scale", "DetailLevel", "Discipline",
    "Phase", "ViewTemplate", "ViewSheetNumber", "ElementId", "Year", "Year2", "Month", "Day",
    "Hour", "Minute", "Second", "Date", "DateShort", "DateLong", "ModelName", "WindowsUser",
    "RevitUser", "OriginalName"]


class TokenTable(unittest.TestCase):
    def test_all_tokens_in_order(self):
        self.assertEqual(list(TOKENS), TOKEN_NAMES)

    def test_entries_are_bilingual_with_a_scope(self):
        for name, (en, pl, scope) in TOKENS.items():
            self.assertTrue(en and pl, name)
            self.assertIn(scope, ("model", "system", "file"), name)
        self.assertEqual(TOKENS["OriginalName"][2], "file")
        self.assertEqual(TOKENS["Date"][2], "system")
        self.assertEqual(TOKENS["SheetNumber"][2], "model")

    def test_presets_parse(self):
        self.assertEqual(len(PRESETS), 5)
        for preset in PRESETS:
            self.assertTrue(parse_template(preset))


class Parsing(unittest.TestCase):
    def test_every_token_parses_in_any_case(self):
        for name in TOKEN_NAMES:
            for form in (name, name.lower(), name.upper()):
                self.assertEqual(parse_template("{%s}" % form), [("token", name)], form)

    def test_text_tokens_params_and_braces(self):
        self.assertEqual(
            parse_template("A {SheetNumber}-{param: My Par } {{x}}"),
            [("text", "A "), ("token", "SheetNumber"), ("text", "-"), ("param", "My Par"),
             ("text", " {x}")])

    def test_empty_means_off(self):
        for text in ("", "   ", "\t \n"):
            self.assertEqual(parse_template(text), [])

    def test_trimmed(self):
        self.assertEqual(parse_template("  abc  "), [("text", "abc")])

    def test_bad_templates_raise_in_english(self):
        for bad in ("{Nope}", "{SheetNumber", "SheetNumber}", "{param:}", "{param:  }", "{}",
                    "{a{b}}", "x" * 201, None, 5, b"abc"):
            with self.assertRaises(NamingError, msg=repr(bad)) as ctx:
                parse_template(bad)
            self.assertTrue(str(ctx.exception).isascii(), repr(bad))

    def test_200_characters_ok(self):
        self.assertEqual(len(parse_template("x" * 200)[0][1]), 200)

    def test_bad_templates_raise_in_polish(self):
        with unittest.mock.patch.dict(sys.modules, polish()):
            for bad in ("{Nope}", "{SheetNumber", "}", "{param:}", "x" * 201, 5):
                with self.assertRaises(NamingError) as ctx:
                    parse_template(bad)
                self.assertRegex(str(ctx.exception),
                                 "szablon|Szablon|Nieznany|Niesparowany|wymaga", repr(bad))

    def test_naming_error_is_value_error(self):
        self.assertTrue(issubclass(NamingError, ValueError))


class Formatting(unittest.TestCase):
    def test_tokens_params_and_text(self):
        parsed = parse_template("{SheetNumber} - {SheetName} [{param:Phase X}]")
        values = {"SheetNumber": "A101", "SheetName": "Ground floor", "param:Phase X": "New"}
        self.assertEqual(format_name(parsed, values, "orig"), "A101 - Ground floor [New]")

    def test_missing_token_is_empty(self):
        parsed = parse_template("{SheetNumber}_{CurrentRevision}")
        self.assertEqual(format_name(parsed, {"SheetNumber": "A1"}, "orig"), "A1_")

    def test_all_tokens_empty_keeps_original(self):
        parsed = parse_template("{SheetNumber} {param:Foo}")
        self.assertEqual(format_name(parsed, {}, "Orig Name"), "Orig Name")
        self.assertEqual(format_name(parsed, {"SheetNumber": ""}, "Orig Name"), "Orig Name")

    def test_empty_parse_keeps_original(self):
        self.assertEqual(format_name([], {"SheetNumber": "A"}, "Orig"), "Orig")

    def test_empty_after_cleaning_keeps_original(self):
        parsed = parse_template("{SheetNumber}")
        self.assertEqual(format_name(parsed, {"SheetNumber": " . "}, "Orig"), "Orig")

    def test_no_token_template_is_literal(self):
        self.assertEqual(format_name(parse_template("Fixed"), {}, "Orig"), "Fixed")

    def test_original_name_token(self):
        parsed = parse_template("{Date} {OriginalName}")
        self.assertEqual(format_name(parsed, {"Date": "2026-11-18"}, "A101 - Plan"),
                         "2026-11-18 A101 - Plan")

    def test_values_are_cleaned(self):
        parsed = parse_template("{SheetName}")
        self.assertEqual(format_name(parsed, {"SheetName": "a/b:c"}, "o"), "a_b_c")

    def test_forbidden_original_is_cleaned(self):
        self.assertEqual(format_name([], {}, "a:b"), "a_b")

    def test_valid_original_unchanged(self):
        self.assertEqual(format_name([], {}, "Ground floor (1)"), "Ground floor (1)")


class SystemValues(unittest.TestCase):
    def test_fixed_moment(self):
        when = datetime.datetime(2026, 3, 4, 5, 6, 7)
        v = system_values(when, "jan", "Jan K", "Model A", "04.03.2026", "środa, 4 marca 2026")
        self.assertEqual(v, {
            "Year": "2026", "Year2": "26", "Month": "03", "Day": "04", "Hour": "05",
            "Minute": "06", "Second": "07", "Date": "2026-03-04", "DateShort": "04.03.2026",
            "DateLong": "środa, 4 marca 2026", "ModelName": "Model A", "WindowsUser": "jan",
            "RevitUser": "Jan K"})

    def test_covers_every_system_token(self):
        v = system_values(datetime.datetime(2026, 11, 18, 23, 59, 58), "u", "r", "m")
        self.assertEqual(set(v), {n for n, t in TOKENS.items() if t[2] == "system"})
        self.assertEqual(v["DateShort"], "")
        self.assertEqual((v["Month"], v["Hour"], v["Second"]), ("11", "23", "58"))

    def test_year_is_four_digits(self):
        v = system_values(datetime.datetime(905, 1, 1), "u", "r", "m")
        self.assertEqual((v["Year"], v["Year2"]), ("0905", "05"))


class CheckNaming(unittest.TestCase):
    def good(self, **kw):
        d = {"template": "{Date}", "system": {"Date": "2026-11-18"}, "values": None}
        d.update(kw)
        return d

    def test_ok_returns_parse(self):
        self.assertEqual(check_naming(self.good()), [("token", "Date")])
        self.assertEqual(check_naming(self.good(values={"u": {"kind": "sheet"}})),
                         [("token", "Date")])
        self.assertEqual(check_naming(self.good(template="")), [])

    def test_rejects(self):
        bad = [None, [], "x", self.good(template="{Nope}"), self.good(template=3),
               {"template": "x", "values": None}, self.good(system=None),
               self.good(system={"Date": 5}), self.good(system={"Date": None}),
               self.good(values=[]), self.good(values={"u": 5}), self.good(values="x")]
        for item in bad:
            with self.assertRaises(NamingError, msg=repr(item)):
                check_naming(item)

    def test_polish_message(self):
        with unittest.mock.patch.dict(sys.modules, polish()):
            with self.assertRaises(NamingError) as ctx:
                check_naming("x")
            self.assertFalse(str(ctx.exception).isascii())


HOSTILE = [
    "", " ", "   ", ".", "..", "...", " . ", "a.", "a. .", "a ", " a", "a  b", "a\tb", "a\nb",
    "a\r\nb", "a \t\n b", "a<b", "a>b", "a:b", 'a"b', "a/b", "a\\b", "a|b", "a?b", "a*b",
    "<>:\"/\\|?*", "a\x00b", "a\x01b", "a\x1fb", "\x00", "CON", "con", "Prn", "AUX", "nul",
    "COM1", "com9", "LPT1", "lpt9", "CON.foo", "nul.tar.gz", "CON .x", " CON ", "COM0", "COM10",
    "CONSOLE", "..\\..\\x", "../x", "C:\\Windows", "a\u00a0b", "a\u2003 b", "\u3000x\u3000",
    "Zażółć gęślą jaźń", "A101 - Ground floor", "emoji \U0001F600", "x" * 10, "a.b.c.",
    "tail. . .", "-", "_", "{braces}", "50%", "a;b,c", "tab\there",
]


class CleanName(unittest.TestCase):
    def test_hostile_table_is_safe(self):
        self.assertGreaterEqual(len(HOSTILE), 40)
        for raw in HOSTILE:
            result = clean_name(raw)
            self.assertTrue(result == "" or safe(result), (raw, result))
            self.assertTrue(result == "" or safe(result, ".pdf"), (raw, result))

    def test_rules(self):
        cases = {
            "a  b": "a b", "a\tb\n c": "a b c", "a<b>c": "a_b_c", 'a:"b': "a__b",
            "a/b\\c|d?e*f": "a_b_c_d_e_f", "a\x01b": "a_b", "  a  ": "a", "a.. ": "a",
            "...": "", "": "", " ": "", "CON": "_CON", "nul": "_nul", "LPT3": "_LPT3",
            "COM10": "COM10", "CONSOLE": "CONSOLE", "CON.x": "_CON.x", "x.y.": "x.y",
            "Zażółć": "Zażółć",
        }
        for raw, expected in cases.items():
            self.assertEqual(clean_name(raw), expected, repr(raw))

    def test_idempotent(self):
        for raw in HOSTILE:
            once = clean_name(raw)
            self.assertEqual(clean_name(once), once, raw)

    def test_valid_name_unchanged(self):
        self.assertEqual(clean_name("A101 - Ground floor (2)"), "A101 - Ground floor (2)")


class Lengths(unittest.TestCase):
    def test_budgets(self):
        root = "C" * 150
        self.assertEqual(file_budget(root, ".pdf"), 259 - 150 - 1 - 4)
        self.assertEqual(folder_budget(root, 0), min(247 - 150 - 1, 259 - 150 - 2, 255))
        self.assertEqual(folder_budget(root, 30), 259 - 150 - 2 - 30)
        self.assertEqual(file_budget("C:\\x", ".rvt"), 259 - 4 - 1 - 4)
        self.assertEqual(file_budget("", ".rvt"), 255 - 4)
        self.assertEqual(folder_budget("", 0), 246)
    def test_a_nested_folder_must_stay_under_the_folder_limit_too(self):
        root = "C" * 100
        # root + "\\" + name + "\\" + a 14-character nested folder path must stay <= 247
        self.assertEqual(folder_budget(root, 20, 14), 247 - 100 - 2 - 14)
        self.assertLess(folder_budget(root, 20, 14), folder_budget(root, 20, 0))
        self.assertEqual(folder_budget(root, 20, 0), folder_budget(root, 20))

    def test_300_chars_under_150_root_fits(self):
        root = "C" * 150
        stem = "n" * 300
        fitted = fit_name(stem, ".pdf", file_budget(root, ".pdf"))
        self.assertEqual(len(root) + 1 + len(fitted) + 4, 259)
        folder = fit_name(stem, "", folder_budget(root, 0))
        self.assertEqual(len(root) + 1 + len(folder), 247)

    def test_short_name_untouched(self):
        self.assertEqual(fit_name("abc", ".pdf", 50), "abc")

    def test_cut_is_trimmed_again(self):
        self.assertEqual(fit_name("ab  cd", ".x", 3), "ab")
        self.assertEqual(fit_name("ab..cd", ".x", 3), "ab")

    def test_cut_to_reserved_stem_is_prefixed(self):
        result = fit_name("CONSOLE", ".x", 3)
        self.assertTrue(safe(result))

    def test_nothing_fits(self):
        self.assertIsNone(fit_name("abc", ".pdf", 0))
        self.assertIsNone(fit_name("abc", ".pdf", -5))
        self.assertIsNone(fit_name("   ", ".pdf", 10))
        self.assertIsNone(fit_name("", ".pdf", 10))

    def test_component_limit_255(self):
        self.assertEqual(len(fit_name("n" * 400, ".pdf", 400)), 251)

    def test_surrogate_pair_never_split(self):
        pair = "\ud83d\ude00"  # one non-BMP character as two UTF-16 code units
        stem = "ab" + pair + "cd"
        self.assertEqual(fit_name(stem, ".x", 3), "ab")
        self.assertEqual(fit_name(stem, ".x", 4), "ab" + pair)
        self.assertEqual(fit_name(stem, ".x", 5), "ab" + pair + "c")


class Clashes(unittest.TestCase):
    def test_numbering_case_insensitive(self):
        namer = Namer()
        self.assertEqual(namer.unique("f", "Plan", ".pdf", 50), "Plan")
        self.assertEqual(namer.unique("f", "PLAN", ".pdf", 50), "PLAN (2)")
        self.assertEqual(namer.unique("f", "plan", ".pdf", 50), "plan (3)")
        self.assertEqual(namer.unique("f", "plan", ".pdf", 50), "plan (4)")

    def test_extension_and_folder_separate_names(self):
        namer = Namer()
        self.assertEqual(namer.unique("f", "Plan", ".pdf", 50), "Plan")
        self.assertEqual(namer.unique("f", "Plan", ".dwg", 50), "Plan")
        self.assertEqual(namer.unique("g", "Plan", ".pdf", 50), "Plan")

    def test_suffix_stays_in_budget(self):
        namer = Namer()
        self.assertEqual(namer.unique("f", "abcdef", ".pdf", 6), "abcdef")
        self.assertEqual(namer.unique("f", "abcdef", ".pdf", 6), "ab (2)")
        self.assertEqual(namer.unique("f", "abcdef", ".pdf", 6), "ab (3)")

    def test_clash_with_cut_name(self):
        namer = Namer()
        a = namer.unique("f", "x" * 300, ".pdf", 20)
        b = namer.unique("f", "x" * 300, ".pdf", 20)
        self.assertEqual(len(a), 20)
        self.assertEqual(len(b), 20)
        self.assertTrue(b.endswith(" (2)"))
        self.assertNotEqual(a.lower(), b.lower())

    def test_nothing_fits_gives_none(self):
        namer = Namer()
        self.assertIsNone(namer.unique("f", "abc", ".pdf", 0))
        namer.unique("f", "abc", ".pdf", 3)
        # " (2)" needs 4 characters plus one of the name: budget 3 cannot hold it
        self.assertIsNone(namer.unique("f", "abc", ".pdf", 3))


class SourceGuards(unittest.TestCase):
    SOURCE = (LIB / "rx_naming.py").read_text(encoding="utf-8")

    def test_no_revit_dotnet_or_clr_imports(self):
        banned = {"pyrevit", "Autodesk", "System", "clr", "rpw"}
        for node in ast.walk(ast.parse(self.SOURCE)):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                self.assertNotIn(name.split(".")[0], banned, name)

    def test_ironpython_syntax_rules(self):
        import test_export_button
        import test_status
        self.assertEqual(test_status.ironpython_problems(self.SOURCE), [])
        self.assertEqual(test_export_button.extra_ironpython_problems(self.SOURCE), [])
        tree = ast.parse(self.SOURCE)
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)])
        self.assertFalse([n for n in ast.walk(tree)
                          if isinstance(n, ast.AnnAssign)
                          or (isinstance(n, ast.arg) and n.annotation)
                          or (isinstance(n, ast.FunctionDef) and n.returns)])
        for banned in ("pathlib", "\t"):
            self.assertNotIn(banned, self.SOURCE)
        self.assertIn("from __future__ import unicode_literals", self.SOURCE)
        self.assertTrue(self.SOURCE.startswith("# -*- coding: utf-8 -*-"))


# ---- Task 3: discovery and tying (acceptance criterion 4) ----
import builtins  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

G1 = "11111111-1111-1111-1111-111111111111"
G2 = "22222222-2222-2222-2222-222222222222"
G3 = "33333333-3333-3333-3333-333333333333"
G4 = "44444444-4444-4444-4444-444444444444"


def touch(root, rel, data=b"x"):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def discover(root, **kw):
    d = rx_naming.Discovery(root, **kw)
    for _ in d.steps():
        pass
    return d


def rels(d):
    return [(i.kind, i.rel) for i in d.items]


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="rxnm-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_kinds_and_guid_folders(self):
        touch(self.root, "Resource/%s/A101 - Ground floor.pdf" % G1)
        touch(self.root, "Resource/Flat sheet.PDF")
        touch(self.root, "Model.dwg")
        touch(self.root, "Resource/Model.IFC")
        d = discover(self.root)
        self.assertEqual(rels(d), [
            ("dwg", "Model.dwg"), ("ifc", "Resource/Model.IFC"),
            ("pdf", "Resource/%s/A101 - Ground floor.pdf" % G1),
            ("pdf", "Resource/Flat sheet.PDF")])
        self.assertEqual([i.viewable for i in d.items], [None, None, G1, None])
        pdf = d.items[2]
        self.assertEqual(pdf.src, os.path.join(self.root, "Resource", G1, "A101 - Ground floor.pdf"))
        self.assertEqual(d.notes, [])

    def test_view_folders(self):
        touch(self.root, "Resource/3D/%s/0/model.svf" % G1)
        touch(self.root, "Resource/3D/%s/0/mesh.pf" % G1)
        touch(self.root, "Resource/%s/sheet.f2d" % G2)
        touch(self.root, "Resource/Loose view/geo.svf")
        touch(self.root, "Resource/Loose view/thumbnails/t.png")
        d = discover(self.root)
        self.assertEqual(rels(d), [
            ("view", "Resource/%s" % G2), ("view", "Resource/3D/%s" % G1),
            ("view", "Resource/Loose view")])
        self.assertEqual([i.viewable for i in d.items], [G2, G1, None])
        self.assertEqual(d.items[1].src, os.path.join(self.root, "Resource", "3D", G1))

    def test_outermost_guid_folder(self):
        touch(self.root, "Resource/%s/%s/a.svf" % (G1, G2))
        d = discover(self.root)
        self.assertEqual(rels(d), [("view", "Resource/%s" % G1)])

    def test_shared_view_folder_skipped_with_note(self):
        touch(self.root, "Resource/%s/a.svf" % G1)
        touch(self.root, "Resource/%s/sub/b.svf" % G1)
        touch(self.root, "Resource/%s/inside.pdf" % G1)
        touch(self.root, "Resource/Other/c.f2d")
        touch(self.root, "Resource/Other/d.svf")
        d = discover(self.root)
        self.assertEqual(d.items, [])
        self.assertEqual(len(d.notes), 2)
        self.assertTrue(all("several views" in n for n in d.notes))

    def test_polish_note(self):
        touch(self.root, "Resource/%s/a.svf" % G1)
        touch(self.root, "Resource/%s/b.svf" % G1)
        with unittest.mock.patch.dict(sys.modules, polish()):
            d = discover(self.root)
        self.assertEqual(len(d.notes), 1)
        self.assertNotIn("several views", d.notes[0])

    def test_excluded_never_listed(self):
        for rel in ("bubble.json", "Resource/objects_ids.json.gz", "Resource/model.sdb",
                    "Resource/AECModelData.json", "Resource/t.png", "log.txt", "run.log",
                    "Resource/thumbnails/x.png"):
            touch(self.root, rel)
        touch(self.root, "Resource/%s/0/g.svf" % G1)
        touch(self.root, "Resource/%s/0/bubble.json" % G1)
        d = discover(self.root)
        self.assertEqual(rels(d), [("view", "Resource/%s" % G1)])

    def test_symlink_or_junction_skipped(self):
        outside = tempfile.mkdtemp(prefix="rxnm-out-")
        self.addCleanup(shutil.rmtree, outside, True)
        touch(outside, "linked.pdf")
        link = os.path.join(self.root, "lnk")
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            r = subprocess.run(["cmd", "/c", "mklink", "/J", link, outside],
                               capture_output=True) if os.name == "nt" else None
            if r is None or r.returncode != 0:
                self.skipTest("cannot create a link or junction here")
        touch(self.root, "real.pdf")
        d = discover(self.root)
        self.assertEqual(rels(d), [("pdf", "real.pdf")])

    def test_injected_islink_skips_file(self):
        touch(self.root, "a.pdf")
        touch(self.root, "b.pdf")
        d = discover(self.root, islink=lambda p: p.endswith("b.pdf"))
        self.assertEqual(rels(d), [("pdf", "a.pdf")])

    def test_never_opens_a_file(self):
        touch(self.root, "Resource/%s/a.pdf" % G1)
        touch(self.root, "Resource/%s/b.svf" % G2)

        def boom(*a, **k):
            raise AssertionError("open called")
        with unittest.mock.patch.object(builtins, "open", boom), \
                unittest.mock.patch.object(io, "open", boom):
            d = discover(self.root)
        self.assertEqual(len(d.items), 2)

    def test_steps_is_a_generator_one_directory_per_step(self):
        touch(self.root, "a/b/x.pdf")
        d = rx_naming.Discovery(self.root)
        gen = d.steps()
        self.assertTrue(hasattr(gen, "__next__"))
        n = sum(1 for _ in gen)
        self.assertEqual(n, 3)  # root, a, a/b

    def test_order_sorted_and_stable(self):
        for rel in ("z.pdf", "B.pdf", "a.pdf", "m.ifc", "k.dwg"):
            touch(self.root, rel)
        first = rels(discover(self.root))
        self.assertEqual([r for _, r in first], ["k.dwg", "m.ifc", "a.pdf", "B.pdf", "z.pdf"])
        self.assertEqual(first, rels(discover(self.root)))

    def test_fake_listdir(self):
        tree = {"/o": ["a.pdf", "sub"], "/o/sub": ["b.ifc"]}
        d = discover("/o", listdir=lambda p: tree[p.replace("\\", "/")],
                     isdir=lambda p: p.replace("\\", "/") in tree,
                     islink=lambda p: False)
        self.assertEqual(rels(d), [("ifc", "sub/b.ifc"), ("pdf", "a.pdf")])


def node(kind, name, children=None, vid=None, key="viewableID"):
    n = {"type": kind, "name": name}
    if children is not None:
        n["children"] = children
    if vid:
        n[key] = vid
    return n


def manifest_of(*folders):
    return {"type": "folder", "name": "root", "children": list(folders)}


def deliverable(rel, kind="pdf", viewable=None):
    return rx_naming.Deliverable("/abs/" + rel, rel, kind, viewable)


SHEET = {"kind": "sheet", "id": "100", "name": "A101 - Ground floor",
         "tokens": {"SheetNumber": "A101", "SheetName": "Ground floor"}, "params": {}}
VIEW = {"kind": "view", "id": "200", "name": "Level 1", "tokens": {"ViewName": "Level 1"},
        "params": {}}


class TieByElementIdTests(unittest.TestCase):
    """The layout of a real export (observed 2026-11-18): every sheet and view sits in a folder
    "<name> <ElementId in decimal>", and the viewable id ends with the same number in hex."""

    SHEET_ID = "11111111-1111-1111-1111-111111111111-0007af95"      # 0x7af95 = 503701
    VIEW_ID = "22222222-2222-2222-2222-222222222222-000ea86d"       # 0xea86d = 960621
    OTHER_ID = "33333333-3333-3333-3333-333333333333-000ea29f"      # 0xea29f = 959135

    def manifest(self):
        return manifest_of(
            node("folder", "Sheets", [
                node("geometry", "A104 - Elev./Sec./Det.", vid=self.SHEET_ID),
                node("geometry", "A101 - Site Plan", vid=self.OTHER_ID)]),
            node("folder", "3D View", [node("geometry", "{3D}", vid=self.VIEW_ID)]))

    def test_a_pdf_is_tied_through_its_folder_even_when_the_name_was_sanitised(self):
        it = deliverable("Resource/Sheet/A104 - Elev__Sec__Det_ 503701/pdf/A104 - Elev__Sec__Det_.pdf")
        pairs, untied = rx_naming.tie([it], self.manifest(), None)
        self.assertEqual(pairs[0][1]["name"], "A104 - Elev./Sec./Det.")
        self.assertEqual(untied, 0)

    def test_a_view_folder_is_tied_through_its_own_name(self):
        it = deliverable("Resource/3D View/{3D} 960621", kind="view")
        pairs, _ = rx_naming.tie([it], self.manifest(), None)
        self.assertEqual(pairs[0][1]["name"], "{3D}")

    def test_values_are_found_by_the_viewable_id(self):
        values = {self.SHEET_ID: dict(SHEET, tokens={"SheetNumber": "A104", "SheetName": "Details"})}
        it = deliverable("Resource/Sheet/A104 - Elev__Sec__Det_ 503701/pdf/x.pdf")
        pairs, untied = rx_naming.tie([it], self.manifest(), values)
        self.assertEqual(pairs[0][1]["tokens"]["SheetNumber"], "A104")
        self.assertEqual(untied, 0)

    def test_two_viewables_with_the_same_element_number_are_not_guessed(self):
        manifest = manifest_of(node("folder", "Sheets", [
            node("geometry", "One", vid=self.SHEET_ID),
            node("geometry", "Two", vid="44444444-4444-4444-4444-444444444444-0007af95")]))
        it = deliverable("Resource/Sheet/Unrelated name 503701/pdf/other.pdf")
        pairs, untied = rx_naming.tie([it], manifest, None)
        self.assertIsNone(pairs[0][1])
        self.assertEqual(untied, 1)

    def test_a_folder_without_a_number_or_an_unknown_number_ties_nothing(self):
        for rel in ("Resource/Sheet/No number/pdf/x.pdf", "Resource/Sheet/Name 1/pdf/x.pdf"):
            pairs, untied = rx_naming.tie([deliverable(rel)], self.manifest(), None)
            self.assertIsNone(pairs[0][1], rel)
            self.assertEqual(untied, 1)


class TieTests(unittest.TestCase):
    def manifest(self):
        return manifest_of(
            node("folder", "Sheets", [
                node("geometry", "A101 - Ground floor", vid=G1),
                node("geometry", "A102 - First floor", vid=G2, key="guid")]),
            node("folder", "3D", [node("geometry", "Level 1", vid=G3)]))

    def test_by_guid_folder_without_values(self):
        it = deliverable("Resource/%s/x.pdf" % G1, viewable=G1)
        pairs, untied = rx_naming.tie([it], self.manifest(), None)
        self.assertEqual(pairs[0][0], it)
        self.assertEqual(pairs[0][1], {"kind": None, "id": None,
                                       "name": "A101 - Ground floor", "tokens": {}, "params": {}})
        self.assertEqual(untied, 0)

    def test_guid_key_variant(self):
        it = deliverable("Resource/x/y.pdf", viewable=G2)
        pairs, _ = rx_naming.tie([it], self.manifest(), None)
        self.assertEqual(pairs[0][1]["name"], "A102 - First floor")

    def test_by_unique_stem_in_same_top_folder(self):
        it = deliverable("Resource/Sheets/A101 - Ground floor.pdf")
        pairs, untied = rx_naming.tie([it], self.manifest(), None)
        self.assertEqual(pairs[0][1]["name"], "A101 - Ground floor")
        self.assertEqual(untied, 0)

    def test_stem_in_other_top_folder_untied(self):
        it = deliverable("Resource/3D/A101 - Ground floor.pdf")
        pairs, untied = rx_naming.tie([it], self.manifest(), None)
        self.assertIsNone(pairs[0][1])
        self.assertEqual(untied, 1)

    def test_ambiguous_stem_untied(self):
        m = manifest_of(node("folder", "Sheets", [
            node("geometry", "Same", vid=G1), node("geometry", "Same", vid=G2)]))
        it = deliverable("Resource/Sheets/Same.pdf")
        pairs, untied = rx_naming.tie([it], m, None)
        self.assertIsNone(pairs[0][1])
        self.assertEqual(untied, 1)

    def test_view_folder_stem_is_folder_name(self):
        it = deliverable("Resource/3D/Level 1", kind="view")
        pairs, _ = rx_naming.tie([it], self.manifest(), None)
        self.assertEqual(pairs[0][1]["name"], "Level 1")

    def test_by_viewable_id_equal_to_value_key(self):
        values = {G1: dict(SHEET), "other": dict(VIEW)}
        it = deliverable("Resource/%s/x.pdf" % G1, viewable=G1)
        pairs, untied = rx_naming.tie([it], self.manifest(), values)
        self.assertIs(pairs[0][1], values[G1])
        self.assertEqual(untied, 0)

    def test_sheet_by_number_and_name(self):
        values = {"u-sheet": SHEET, "u-view": VIEW}
        it = deliverable("Resource/%s/x.pdf" % G1, viewable=G1)
        pairs, _ = rx_naming.tie([it], self.manifest(), values)
        self.assertIs(pairs[0][1], SHEET)

    def test_view_by_view_name(self):
        values = {"u-sheet": SHEET, "u-view": VIEW}
        it = deliverable("Resource/3D/%s" % G3, kind="view", viewable=G3)
        pairs, _ = rx_naming.tie([it], self.manifest(), values)
        self.assertIs(pairs[0][1], VIEW)

    def test_ambiguous_value_match_is_none(self):
        twin = dict(SHEET, id="101")
        values = {"u1": SHEET, "u2": twin}
        it = deliverable("Resource/%s/x.pdf" % G1, viewable=G1)
        pairs, untied = rx_naming.tie([it], self.manifest(), values)
        self.assertIsNone(pairs[0][1])
        self.assertEqual(untied, 1)

    def test_no_value_match_is_none(self):
        it = deliverable("Resource/%s/x.pdf" % G2, viewable=G2)
        pairs, untied = rx_naming.tie([it], self.manifest(), {"u": SHEET})
        self.assertIsNone(pairs[0][1])
        self.assertEqual(untied, 1)

    def test_no_viewable_no_record_and_order_and_count(self):
        a = deliverable("a.pdf")
        b = deliverable("Resource/%s/b.pdf" % G1, viewable=G1)
        c = deliverable("c.dwg", kind="dwg")
        pairs, untied = rx_naming.tie([a, b, c], self.manifest(), None)
        self.assertEqual([p[0] for p in pairs], [a, b, c])
        self.assertEqual([p[1] is None for p in pairs], [True, False, True])
        self.assertEqual(untied, 2)

    def test_unknown_guid_untied(self):
        it = deliverable("Resource/%s/x.pdf" % G4, viewable=G4)
        pairs, untied = rx_naming.tie([it], self.manifest(), None)
        self.assertIsNone(pairs[0][1])


# ---- Task 4: writer and record (acceptance criteria 5, 6 and 8) ----
import hashlib  # noqa: E402
import json  # noqa: E402

import rx_cloud_stage  # noqa: E402
import rx_runner  # noqa: E402

PDF_REL = "Resource/%s/A101 - Ground floor.pdf" % G1
IFC_REL = "Model.ifc"
VIEW_REL = "Resource/3D/%s" % G3
VIEW_FILES = ["0/mesh.pf", "0/model.svf", "0/sub/t.bin"]
ORIGINALS = {"template": "{SheetNumber}", "system": {}, "values": None}
NAMED_VALUES = {"template": "{SheetNumber}{ViewName}", "system": {},
                "values": {G1: SHEET, G3: VIEW}}


def snapshot(folder):
    """{relative path: "dir" | (size, mtime_ns, sha256)} of everything under `folder`."""
    out = {}
    for dirpath, dirs, files in os.walk(folder):
        for name in dirs + files:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, folder).replace("\\", "/")
            if os.path.isdir(path):
                out[rel] = "dir"
                continue
            st = os.stat(path)
            with io.open(path, "rb") as fh:
                out[rel] = (st.st_size, st.st_mtime_ns, hashlib.sha256(fh.read()).hexdigest())
    return out


def copy_link(src, dst):
    """A stand-in for a hard link that works on any drive: a new file, never an overwrite."""
    with io.open(src, "rb") as s, io.open(dst, "xb") as d:
        d.write(s.read())


def no_link(src, dst):
    raise OSError(1, "no links here")


def _links_supported():
    folder = tempfile.mkdtemp(prefix="rxnm-ln-")
    try:
        touch(folder, "a")
        os.link(os.path.join(folder, "a"), os.path.join(folder, "b"))
        return True
    except (OSError, AttributeError, NotImplementedError):
        return False
    finally:
        shutil.rmtree(folder, True)


class WriterCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="rxnm-run-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.paths = rx_runner.run_paths_for(self.root)
        self.out = self.paths.output
        self.named = os.path.join(self.root, "named")
        self.record = os.path.join(self.root, "named.json")
        manifest = manifest_of(
            node("folder", "Sheets", [node("geometry", "A101 - Ground floor", vid=G1)]),
            node("folder", "3D", [node("geometry", "Level 1", vid=G3)]))
        touch(self.out, "bubble.json", json.dumps(manifest).encode("utf-8"))
        touch(self.out, PDF_REL, b"pdf-1" * 50)
        touch(self.out, IFC_REL, b"ifc-1" * 30)
        for i, rel in enumerate(VIEW_FILES):
            touch(self.out, VIEW_REL + "/" + rel, b"view-%d" % i * (i + 3))
        touch(self.out, "Resource/objects_ids.json.gz", b"excluded")

    def src(self, rel):
        return os.path.join(self.out, *rel.split("/"))

    def dst(self, rel):
        return os.path.join(self.named, *rel.split("/"))

    def run_named(self, naming, exclude=(), **kw):
        """Runs NamedRun to the end and checks criterion 6: output\\ is unchanged (except the
        files a test changes on purpose) and only named\\ and named.json are new."""
        kw.setdefault("link", copy_link)
        before = snapshot(self.out)
        top = set(os.listdir(self.root))
        run = rx_naming.NamedRun(self.paths, dict(naming), **kw)
        steps = list(run.steps())
        after = snapshot(self.out)
        for rel in exclude:
            before.pop(rel, None)
            after.pop(rel, None)
        self.assertEqual(before, after)
        self.assertLessEqual(set(os.listdir(self.root)) - top, {"named", "named.json"})
        self.assertTrue(all(d <= t for d, t in steps))
        return run

    def read_record(self):
        with io.open(self.record, "rb") as fh:
            return fh.read().decode("ascii")

    def assertSameBytes(self, a, b):
        with io.open(a, "rb") as fa, io.open(b, "rb") as fb:
            self.assertEqual(fa.read(), fb.read())


class PlanningSteps(WriterCase):
    def test_every_deliverable_is_one_step_so_the_window_is_never_blocked(self):
        for number in range(40):
            touch(self.out, "Resource/Sheet/S%03d %d/pdf/S%03d.pdf" % (number, 100 + number, number), b"p")
        touch(self.out, "bubble.json", json.dumps(manifest_of()).encode("utf-8"))
        run = rx_naming.NamedRun(self.paths, dict(ORIGINALS, template="{OriginalName}"), link=copy_link)
        gen = run.steps()
        first_write = None
        yields_before_writing = 0
        for step in gen:
            if os.path.isdir(os.path.join(self.root, "named")):
                first_write = step
                break
            yields_before_writing += 1
        gen.close()
        self.assertGreaterEqual(yields_before_writing, 40, "planning yields at least once per file")

    def test_a_deep_view_folder_name_is_cut_for_its_nested_folders(self):
        deep = "d" * 60
        touch(self.out, "Resource/3D View/V 5/%s/%s/m.svf" % (deep, deep), b"s")
        touch(self.out, "bubble.json", json.dumps(manifest_of()).encode("utf-8"))
        long_template = "n" * 200
        run = self.run_named(dict(ORIGINALS, template=long_template))
        self.assertIn(run.state, ("done", "partial"))
        for folder, _dirs, _files in os.walk(os.path.join(self.root, "named")):
            self.assertLessEqual(len(folder), 247, "no nested folder path is over the limit")


class WriterTests(WriterCase):
    LINKS = _links_supported()

    def test_real_hard_links(self):
        if not self.LINKS:
            self.skipTest("the temp drive cannot make hard links (os.link failed)")
        run = self.run_named(ORIGINALS, link=rx_naming.make_hard_link)
        self.assertEqual(run.state, "done")
        self.assertEqual(run.counts["linked"], 3)
        for src, dst in ((PDF_REL, "A101 - Ground floor.pdf"), (IFC_REL, IFC_REL),
                         (VIEW_REL + "/0/model.svf", G3 + "/0/model.svf")):
            s, d = os.stat(self.src(src)), os.stat(self.dst(dst))
            self.assertEqual((s.st_nlink, d.st_nlink), (2, 2))
            self.assertEqual(s.st_ino, d.st_ino)
            self.assertNotEqual(s.st_ino, 0)

    def test_view_subtree_complete_and_names(self):
        run = self.run_named(NAMED_VALUES)
        self.assertEqual(run.state, "done")
        self.assertEqual(sorted(os.listdir(self.named)), ["A101.pdf", "Level 1", "Model.ifc"])
        inside = snapshot(self.dst("Level 1"))
        source = snapshot(self.src(VIEW_REL))
        self.assertEqual({k: v[2] if v != "dir" else v for k, v in inside.items()},
                         {k: v[2] if v != "dir" else v for k, v in source.items()})
        self.assertEqual(run.counts, {"total": 3, "linked": 3, "copied": 0, "failed": 0,
                                      "untied": 1})
        self.assertEqual([(i["source"], i["name"], i["kind"], i["mode"]) for i in run.items], [
            (IFC_REL, "Model.ifc", "file", "linked"),
            (PDF_REL, "A101.pdf", "file", "linked"),
            (VIEW_REL, "Level 1", "dir", "linked")])
        self.assertEqual((run.done, run.total), (5, 5))
        self.assertEqual(run.result_message(),
                         "Named copies: 3 in named\\ (0 copied instead of linked). 1 files "
                         "could not be tied to a sheet or view and kept their name.")

    def test_link_failure_copies_identical_bytes(self):
        run = self.run_named(ORIGINALS, link=no_link)
        self.assertEqual(run.state, "done")
        self.assertEqual((run.counts["copied"], run.counts["linked"]), (3, 0))
        self.assertEqual({i["mode"] for i in run.items}, {"copied"})
        self.assertSameBytes(self.src(PDF_REL), self.dst("A101 - Ground floor.pdf"))
        for rel in VIEW_FILES:
            self.assertSameBytes(self.src(VIEW_REL + "/" + rel), self.dst(G3 + "/" + rel))
        self.assertEqual(os.stat(self.dst(IFC_REL)).st_nlink, 1)
        self.assertIn("(3 copied instead of linked)", run.result_message())

    def test_copier_failure_fails_one_item(self):
        def copier(plan, dest, **kw):
            if plan.items[0].name.endswith(".pdf"):
                raise rx_cloud_stage.StageError("boom")
            return rx_cloud_stage.copy_steps(plan, dest, **kw)
        run = self.run_named(ORIGINALS, link=no_link, copier=copier)
        self.assertEqual(run.state, "partial")
        self.assertEqual([i["mode"] for i in run.items], ["copied", "failed", "copied"])
        self.assertEqual(run.items[1]["error"], "StageError")
        self.assertEqual(run.result_message(),
                         "Named copies: 2 of 3; 1 failed, see named.json. 1 files could not be "
                         "tied to a sheet or view and kept their name.")

    def test_not_enough_space_nothing_made(self):
        asked = []
        run = self.run_named(ORIGINALS, link=no_link,
                             free_space=lambda p: asked.append(p) or 10)
        self.assertEqual(run.state, "failed")
        self.assertEqual(asked, [self.named])
        self.assertEqual([i["error"] for i in run.items], ["not enough space"] * 3)
        self.assertIn("Not enough free disk space", run.notes[0])
        self.assertEqual(os.listdir(self.named), [])
        self.assertTrue(run.result_message().startswith("Named copies were not made: Not enough"))
        self.assertEqual(json.loads(self.read_record())["state"], "failed")

    def test_not_enough_space_after_some_links_is_partial(self):
        def link(src, dst):
            if src.endswith(".pdf"):
                raise OSError(17, "x")
            copy_link(src, dst)
        run = self.run_named(ORIGINALS, link=link, free_space=lambda p: 0)
        self.assertEqual(run.state, "partial")
        self.assertEqual([i["mode"] for i in run.items], ["linked", "failed", "failed"])
        self.assertEqual(sorted(os.listdir(self.named)), [IFC_REL])

    def test_unknown_free_space_goes_on(self):
        def broken(path):
            raise OSError(5, "x")
        run = self.run_named(ORIGINALS, link=no_link, free_space=broken)
        self.assertEqual(run.state, "done")

    def test_existing_named_refused_and_nothing_touched(self):
        touch(self.named, "keep.pdf", b"mine")
        before = snapshot(self.root)
        run = rx_naming.NamedRun(self.paths, dict(ORIGINALS), link=copy_link)
        self.assertEqual(list(run.steps()), [])
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(run.state, "failed")
        self.assertIn("already exists", run.notes[0])
        self.assertIn("already exists", run.result_message())
        self.assertFalse(os.path.exists(self.record))

    def test_invalid_naming_failed_nothing_written(self):
        before = snapshot(self.root)
        run = rx_naming.NamedRun(self.paths, {"template": "{Nope}", "system": {}})
        list(run.steps())
        self.assertEqual(run.state, "failed")
        self.assertIn("Unknown token", run.notes[0])
        self.assertEqual(snapshot(self.root), before)

    def test_vanished_or_changed_source_fails_only_that_item(self):
        changed = VIEW_REL + "/0/sub/t.bin"

        def link(src, dst):
            if src.endswith(".ifc"):    # the first item: now break two later sources
                os.remove(self.src(PDF_REL))
                with io.open(self.src(changed), "ab") as fh:
                    fh.write(b"more")
            copy_link(src, dst)
        run = self.run_named(ORIGINALS, link=link, exclude=(PDF_REL, changed))
        self.assertEqual(run.state, "partial")
        self.assertEqual([i["mode"] for i in run.items], ["linked", "failed", "failed"])
        self.assertTrue(run.items[1]["error"].startswith("FileNotFoundError"))
        self.assertEqual(run.items[2]["error"], "source changed")
        self.assertEqual((run.done, run.total), (5, 5))

    def test_split_layout(self):
        naming = dict(ORIGINALS, split=True)
        run = self.run_named(naming)
        self.assertEqual(run.state, "done")
        self.assertEqual(sorted(os.listdir(self.named)), ["3D", "IFC", "PDF"])
        self.assertEqual([i["name"] for i in run.items],
                         ["IFC/Model.ifc", "PDF/A101 - Ground floor.pdf", "3D/" + G3])
        self.assertTrue(os.path.isfile(self.dst("3D/%s/0/sub/t.bin" % G3)))

    def test_clash_numbering(self):
        touch(self.out, "Resource/%s/Other.pdf" % G2, b"pdf-2")
        run = self.run_named({"template": "Sheet", "system": {}, "values": None})
        self.assertEqual(run.state, "done")
        self.assertEqual([i["name"] for i in run.items],
                         ["Sheet.ifc", "Sheet.pdf", "Sheet (2).pdf", "Sheet"])

    def test_path_too_long_fails_that_item(self):
        length = len(self.named)
        with unittest.mock.patch.object(rx_naming, "_MAX_FILE_PATH", length + 13), \
                unittest.mock.patch.object(rx_naming, "_MAX_DIR_PATH", length + 41):
            run = self.run_named(ORIGINALS)
        self.assertEqual(run.state, "partial")
        self.assertEqual([(i["name"], i["mode"], i["error"]) for i in run.items], [
            ("Model.ifc", "linked", None), ("A101 - G.pdf", "linked", None),
            (None, "failed", "path too long")])
        self.assertFalse(os.path.exists(self.dst(G3)))

    def test_unreadable_bubble_refuses_and_changes_nothing(self):
        touch(self.out, "bubble.json", b"{not json")
        before = sorted(os.listdir(self.paths.root))
        run = self.run_named(NAMED_VALUES)
        self.assertEqual(run.state, "failed")
        self.assertIn("bubble.json could not be read", run.notes[0])
        self.assertIn("bubble.json could not be read", run.result_message())
        self.assertFalse(os.path.exists(self.named))
        self.assertEqual(sorted(os.listdir(self.paths.root)), before, "no named, no named.json")

    def test_record_ascii_relative_and_written_at_start_and_end(self):
        touch(self.out, "Rzut piętra.pdf", b"pl")
        run = rx_naming.NamedRun(self.paths, dict(ORIGINALS, template="{OriginalName} ł"),
                                 link=copy_link)
        first = None
        for _ in run.steps():
            if first is None and os.path.exists(self.record):
                first = self.read_record()
        self.assertEqual(json.loads(first)["state"], "running")
        text = self.read_record()
        record = json.loads(text)
        self.assertEqual(list(record), ["schema", "version", "template", "state", "counts",
                                        "notes", "items"])
        self.assertEqual((record["schema"], record["version"], record["state"]),
                         ("rx-named-copies", 1, "done"))
        self.assertIn("Rzut pi\\u0119tra.pdf", text)
        self.assertIn("Rzut piętra ł.pdf", [i["name"] for i in record["items"]])
        for absolute in (self.root, self.root.replace("\\", "\\\\"),
                         os.path.basename(self.root), tempfile.gettempdir()):
            self.assertNotIn(absolute, text)
        self.assertEqual(record["items"], run.items)
        self.assertFalse(os.path.exists(self.record + ".tmp"))

    def test_failed_record_write_is_one_note(self):
        real = io.open

        def deny(path, *a, **k):
            if str(path).endswith("named.json.tmp"):
                raise OSError(13, "denied")
            return real(path, *a, **k)
        with unittest.mock.patch.object(io, "open", deny):
            # a file-only template: {SheetNumber} would now also try the (fake) property data
            run = self.run_named(dict(ORIGINALS, template="{OriginalName}"))
        self.assertEqual(run.state, "done")
        self.assertEqual(run.notes, ["named.json could not be written."])

    def test_close_early_leaves_complete_items_and_running_record(self):
        touch(self.out, PDF_REL, b"p" * (3 * 2 ** 20))
        before = snapshot(self.out)
        run = rx_naming.NamedRun(self.paths, dict(ORIGINALS), link=no_link)
        gen = run.steps()
        seen = 0
        for done, _ in gen:
            seen += done == 1
            if seen == 2:   # the IFC is copied, the PDF is half way
                break
        self.assertTrue(os.path.exists(self.dst("A101 - Ground floor.pdf")))
        gen.close()
        self.assertEqual(snapshot(self.out), before)
        self.assertEqual(sorted(os.listdir(self.named)), [IFC_REL])
        self.assertSameBytes(self.src(IFC_REL), self.dst(IFC_REL))
        self.assertEqual(json.loads(self.read_record())["state"], "running")
        self.assertEqual(sorted(os.listdir(self.root)), ["named", "named.json", "output"])

    def test_never_raises(self):
        def listdir(path):
            if G3 in path:
                raise RuntimeError("unexpected")
            return os.listdir(path)
        run = self.run_named(ORIGINALS, listdir=listdir)
        self.assertEqual(run.state, "failed")
        self.assertEqual(run.notes, ["Unexpected error: RuntimeError"])
        self.assertEqual(json.loads(self.read_record())["state"], "failed")

    def test_no_source_opened_for_writing(self):
        calls = []
        real_io_open, real_os_open = io.open, os.open
        out = os.path.normcase(os.path.abspath(self.out)) + os.sep

        def under_output(path):
            return os.path.normcase(os.path.abspath(str(path))).startswith(out)

        def spy_open(path, mode="r", *a, **k):
            if under_output(path):
                calls.append(("open", mode))
            return real_io_open(path, mode, *a, **k)

        def spy_os_open(path, flags, *a, **k):
            if under_output(path):
                calls.append(("os.open", flags))
            return real_os_open(path, flags, *a, **k)

        def copier(plan, dest, **kw):   # copy_steps binds io.open as a default at import
            return rx_cloud_stage.copy_steps(plan, dest, open=spy_open, **kw)
        writing = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        with unittest.mock.patch.object(builtins, "open", spy_open), \
                unittest.mock.patch.object(io, "open", spy_open), \
                unittest.mock.patch.object(os, "open", spy_os_open):
            run = rx_naming.NamedRun(self.paths, dict(ORIGINALS), link=no_link, copier=copier)
            list(run.steps())
        self.assertEqual(run.state, "done")
        self.assertGreaterEqual(len(calls), 6)   # bubble.json and five copied sources
        for kind, mode in calls:
            if kind == "open":
                self.assertEqual(mode, "rb")
            else:
                self.assertFalse(mode & writing)

    def test_now_fills_missing_time_tokens(self):
        when = datetime.datetime(2026, 1, 2, 3, 4, 5)
        run = self.run_named({"template": "{Date} {OriginalName}", "system": {},
                              "values": None}, now=when)
        self.assertIn("2026-01-02 Model.ifc", [i["name"] for i in run.items])

    def test_polish_messages(self):
        run = self.run_named(NAMED_VALUES)
        with unittest.mock.patch.dict(sys.modules, polish()):
            self.assertEqual(run.result_message(),
                             "Kopie z nazwami: 3 w named\\ (0 skopiowano zamiast dowiązać). 1 "
                             "plików nie powiązano z arkuszem ani widokiem; zachowały nazwę.")
            run.state = "partial"
            self.assertTrue(run.result_message().startswith("Kopie z nazwami: 3 z 3; 0 "))
            run.state, run.notes = "failed", ["x"]
            self.assertEqual(run.result_message(), "Nie utworzono kopii z nazwami: x")


if __name__ == "__main__":
    unittest.main()
