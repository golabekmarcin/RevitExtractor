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


if __name__ == "__main__":
    unittest.main()
