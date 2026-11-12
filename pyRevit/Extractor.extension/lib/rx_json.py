# -*- coding: utf-8 -*-
"""JSON text that is pure ASCII without json's ensure_ascii=True.

IronPython 2.7's json encoder raises UnicodeEncodeError ('ascii' codec can't encode ...) from
json.dumps(..., ensure_ascii=True) as soon as the data holds a non-ASCII character, for example a
Polish folder name. ensure_ascii=False does not have that problem, so the escaping is done here.
Use dumps_ascii() wherever JSON text has to be ASCII (the session protocol, the cache file, the
preferences file) and never pass ensure_ascii=True; a test scans the sources for it.
"""
from __future__ import unicode_literals

import json


def dumps_ascii(obj, _json=json, **kwargs):
    """json.dumps(obj, **kwargs) as ASCII text: every non-ASCII character becomes \\uXXXX
    (a surrogate pair above U+FFFF). The result is text (unicode), valid JSON."""
    kwargs["ensure_ascii"] = False
    text = _json.dumps(obj, **kwargs)
    if not isinstance(text, type("")):
        text = text.decode("utf-8")  # IronPython 2.7 may hand back UTF-8 bytes
    pieces = []
    for char in text:
        code = ord(char)
        if code < 128:
            pieces.append(char)
        elif code < 0x10000:
            pieces.append("\\u%04x" % code)
        else:
            code -= 0x10000
            pieces.append("\\u%04x\\u%04x" % (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)))
    return "".join(pieces)
