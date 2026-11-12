# -*- coding: utf-8 -*-
"""rx_json.dumps_ascii and the rule behind it.

IronPython 2.7's json encoder raises UnicodeEncodeError ('ascii' codec ... \\u017c) from
json.dumps(..., ensure_ascii=True) when the data holds a non-ASCII character (seen in Revit with
a Polish folder name). The code must never rely on ensure_ascii=True. These tests run on CPython,
so they cannot reproduce the IronPython failure; the source scan keeps the rule in place.
"""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
import test_status as ts  # noqa: E402
import rx_json  # noqa: E402

PANEL = Path(__file__).resolve().parent.parent


class DumpsAscii(unittest.TestCase):
    def test_result_is_ascii_and_round_trips(self):
        data = {"path": "C:\\RX-test\\Zażółć gęślą & 100%", "n": 3, "list": ["Ł", None, True]}
        text = rx_json.dumps_ascii(data, sort_keys=True)
        text.encode("ascii")
        self.assertIn("\\u017c", text)
        self.assertEqual(json.loads(text), data)

    def test_control_characters_and_quotes_are_escaped(self):
        data = {"a": 'x"y\\z\n\t\x01'}
        text = rx_json.dumps_ascii(data)
        text.encode("ascii")
        self.assertNotIn("\n", text)
        self.assertEqual(json.loads(text), data)

    def test_characters_outside_the_bmp_become_surrogate_pairs(self):
        text = rx_json.dumps_ascii({"k": "a\U0001F600b"})
        text.encode("ascii")
        self.assertIn("\\ud83d\\ude00", text)
        self.assertEqual(json.loads(text), {"k": "a\U0001F600b"})

    def test_keyword_arguments_are_passed_through(self):
        text = rx_json.dumps_ascii({"b": 1, "a": "ą"}, sort_keys=True, indent=2)
        self.assertTrue(text.index('"a"') < text.index('"b"'))
        self.assertIn("\n", text)

    def test_plain_ascii_matches_json_dumps(self):
        data = {"op": "ping", "n": [1, 2]}
        self.assertEqual(rx_json.dumps_ascii(data, sort_keys=True),
                         json.dumps(data, sort_keys=True))

    def test_bytes_from_an_old_json_are_decoded(self):
        class Fake(object):
            @staticmethod
            def dumps(obj, **kwargs):
                return "{\"a\": \"\xc4\x85\"}".encode("latin-1")  # UTF-8 bytes of ą
        text = rx_json.dumps_ascii({"a": "ą"}, _json=Fake)
        self.assertEqual(text, '{"a": "\\u0105"}')


class NoEnsureAsciiTrue(unittest.TestCase):
    """json.dumps(ensure_ascii=True) is the default and the failing call under IronPython."""

    def test_sources_use_dumps_ascii(self):
        lib = Path(ts.LIB)
        files = list(lib.glob("*.py")) + list(PANEL.glob("Export.pushbutton/*.py"))
        self.assertTrue(files)
        bad = []
        for path in files:
            if path.name == "rx_json.py":
                continue
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                if re.search(r"ensure_ascii\s*=\s*True", line):
                    bad.append("%s:%d" % (path.name, number))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
